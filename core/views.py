from django.views.generic import ListView, DetailView, TemplateView

import requests
from django.conf import settings
# from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST
import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from .models import BookInstance, Payment, Book

from django.contrib import messages

""" base views """
class IndexView(TemplateView):
    template_name = "index.html"

class BookViewPage(ListView):
    model = Book
    template_name = "books.html"
    context_object_name = "books"

    def get_queryset(self):
        return Book.objects.select_related('category')


class BookDetailViewPage(DetailView):
    model = Book
    context_object_name = "book"
    template_name = "book_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context['book_instance'] = BookInstance.objects.select_related(
            "book"
        ).filter(
            book=self.object
        )

        return context

# checkout page
# @login_required
@require_POST
def initiate_payment(request, instance_id):
    if request.method != "POST":
        return redirect('book-detail', pk=instance_id)

    book_instance = get_object_or_404(BookInstance, id=instance_id)

    # 1. Vérification de la disponibilité
    if book_instance.status != BookInstance.Status.DISPONIBLE: # Adapte selon ton choix de status (ex: 'disponible')
        messages.error(request, "Cet exemplaire n'est plus disponible.")
        return redirect('book-detail', pk=book_instance.book.id)

    # Utilisation d'une transaction atomique pour sécuriser la création
    with transaction.atomic():
        # 2. Création du paiement en local (statut pending)
        payment = Payment.objects.create(
            user=request.user,
            book_instance=book_instance,
            amount=book_instance.book.prix,  # Assure-toi que book_instance pointe bien vers Book
            currency='XOF',
            status=Payment.Status.PENDING
        )

    # 3. Préparation des données pour l'API Genius Pay
    payload = {
        "amount": int(payment.amount),
        "description": f"Achat du livre : {book_instance.book.title}",
        "customer": {
            "name": request.user.email,  # Ou nom/prénom si tu en as
            "email": request.user.email,
            "phone": getattr(request.user, 'phone', ''),
        },
        "success_url": request.build_absolute_uri('/payment/success/'),
        "error_url": request.build_absolute_uri('/payment/error/'),
        "metadata": {
            "payment_id": str(payment.id),
            "book_instance_id": str(book_instance.id)
        }
    }

    headers = {
        "Authorization": f"Bearer {settings.GENIUS_PAY_API_KEY}",
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(settings.GENIUS_PAY_API_URL, json=payload, headers=headers, timeout=10)
        data = response.json()

        if response.status_code == 201 and data.get("success"):
            payment_data = data.get("data", {})
            
            # Sauvegarde de la référence/transaction_id renvoyée par l'API
            payment.transaction_id = str(payment_data.get("id"))
            payment.reference = payment_data.get("reference")
            payment.save()

            # Redirection vers la page de checkout Genius Pay
            payment_url = payment_data.get("payment_url")
            if payment_url:
                return redirect(payment_url)
                
    except requests.RequestException as e:
        # Gérer l'erreur réseau (logger l'erreur)
        pass

    return redirect('book-list')


@csrf_exempt
@require_POST
def genius_pay_webhook(request):
    # 1. Vérification de l'en-tête d'environnement pour s'assurer de la cohérence
    env_header = request.headers.get("X-Webhook-Environment")
    
    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    event_type = payload.get("event") or payload.get("type") # Selon la structure exacte de l'événement
    data = payload.get("data", {})
    
    # On récupère le payment_id passé dans les metadata lors de l'initiation
    metadata = data.get("metadata", {})
    payment_id = metadata.get("payment_id")

    if not payment_id:
        return JsonResponse({"status": "ignored", "reason": "No payment_id in metadata"}, status=200)

    try:
        payment = Payment.objects.get(id=payment_id)
    except Payment.DoesNotExist:
        return JsonResponse({"error": "Payment not found"}, status=404)

    # 2. Traitement sécurisé avec une transaction atomique
    with transaction.atomic():
        # Vérification des événements de paiement
        if payload.get("status") == "success" or event_type == "payment.success":
            if payment.status != Payment.Status.SUCCESS:
                payment.status = Payment.Status.SUCCESS
                payment.transaction_id = str(data.get("id", payment.transaction_id))
                payment.reference = data.get("reference", payment.reference)
                payment.save()

                # Mise à jour de l'instance du livre en "vendu"
                book_instance = payment.book_instance
                book_instance.status = BookInstance.Status.VENDU  # Assure-toi que ce statut existe dans tes Choices
                book_instance.save()

        elif payload.get("status") == "failed" or event_type == "payment.failed":
            if payment.status != Payment.Status.FAILED:
                payment.status = Payment.Status.FAILED
                payment.save()
                
                # Optionnel : Remettre l'instance du livre en disponible si le paiement échoue
                book_instance = payment.book_instance
                if book_instance.status != BookInstance.Status.DISPONIBLE:
                    book_instance.status = BookInstance.Status.DISPONIBLE
                    book_instance.save()

    return JsonResponse({"status": "success"}, status=200)

