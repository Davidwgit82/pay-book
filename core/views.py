from django.views.generic import ListView, DetailView, TemplateView
import hashlib
import hmac
import requests
from django.conf import settings
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST, require_http_methods
import json
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from .models import BookInstance, Payment, Book
from django.urls import reverse
from django.contrib import messages


def ping(request):
    return HttpResponse("pong")


""" base views """
class IndexView(TemplateView):
    template_name = "index.html"


class BookViewPage(ListView):
    model = Book
    template_name = "book_list.html"
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


@require_http_methods(["GET", "POST"])
def checkout_info(request, instance_id):
    book_instance = get_object_or_404(BookInstance, id=instance_id)

    if book_instance.status != BookInstance.Status.DISPONIBLE:
        messages.error(request, "Cet exemplaire n'est plus disponible.")
        return redirect('book-detail', pk=book_instance.book.id)

    if request.user.is_authenticated:
        # Déjà connecté, pas besoin du formulaire invité
        return redirect('initiate-payment', instance_id=instance_id)

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        email = request.POST.get('email', '').strip()
        phone = request.POST.get('phone', '').strip()

        if not name or not email or not phone:
            messages.error(request, "Merci de renseigner tous les champs.")
            return render(request, 'checkout_info.html', {'book_instance': book_instance})

        # On stocke temporairement les infos invité en session
        request.session['guest_name'] = name
        request.session['guest_email'] = email
        request.session['guest_phone'] = phone
        return redirect('initiate-payment', instance_id=instance_id)

    return render(request, 'checkout_info.html', {'book_instance': book_instance})

@require_POST
def initiate_payment(request, instance_id):
    book_instance = get_object_or_404(BookInstance, id=instance_id)

    # 1. Vérification de la disponibilité
    if book_instance.status != BookInstance.Status.DISPONIBLE:
        messages.error(request, "Cet exemplaire n'est plus disponible.")
        return redirect('book-detail', pk=book_instance.book.id)

    # 2. Détermination des infos client : connecté ou invité
    if request.user.is_authenticated:
        user = request.user
        customer_name = request.user.email
        customer_email = request.user.email
        customer_phone = getattr(request.user, 'phone', '')
    else:
        user = None
        customer_name = request.session.get('guest_name', '')
        customer_email = request.session.get('guest_email', '')
        customer_phone = request.session.get('guest_phone', '')

        if not customer_email:
            messages.error(request, "Veuillez renseigner vos informations avant de payer.")
            return redirect('checkout-info', instance_id=instance_id)

    # 3. Création du paiement en local (statut pending) dans une transaction atomique
    with transaction.atomic():
        payment = Payment.objects.create(
            user=user,
            book_instance=book_instance,
            amount=book_instance.book.prix,
            currency='XOF',
            status=Payment.Status.PENDING,
            guest_name=customer_name if user is None else '',
            guest_email=customer_email if user is None else '',
            guest_phone=customer_phone if user is None else '',
        )

    # 4. Préparation des données pour l'API Genius Pay
    success_url = request.build_absolute_uri(reverse('payment_success'))
    error_url = request.build_absolute_uri(reverse('payment_error'))

    payload = {
        "amount": int(payment.amount),
        "currency": "XOF",
        "description": f"Achat du livre : {book_instance.book.title}",
        "customer": {
            "name": customer_name,
            "email": customer_email,
            "phone": customer_phone,
        },
        "success_url": success_url,
        "error_url": error_url,
        "metadata": {
            "payment_id": str(payment.id),
            "book_instance_id": str(book_instance.id)
        }
    }

    headers = {
        "X-API-Key": settings.GENIUS_PAY_API_KEY,
        "X-API-Secret": settings.GENIUS_PAY_API_SECRET,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "GeniusPay-Django-Client/1.0"
    }

    # --- DEBUG TEMPORAIRE : à retirer une fois le bug identifié ---
    print("=== DEBUG PAYMENT ===")
    print("amount:", payment.amount, type(payment.amount))
    print("success_url:", success_url)
    print("error_url:", error_url)
    print("payload:", payload)
    # ----------------------------------------------------------------

    try:
        response = requests.post(settings.GENIUS_PAY_API_URL, json=payload, headers=headers, timeout=10)

        # --- DEBUG TEMPORAIRE ---
        print("STATUS CODE:", response.status_code)
        print("RESPONSE BODY:", response.text)
        # ------------------------

        data = response.json()

        if response.status_code in [200, 201] and data.get("success"):
            payment_data = data.get("data", {})

            # Sauvegarde de la référence et de l'ID de transaction renvoyés par l'API
            payment.transaction_id = str(payment_data.get("id"))
            payment.reference = payment_data.get("reference")
            payment.save()

            # Redirection vers la page de checkout Genius Pay
            payment_url = payment_data.get("checkout_url")
            if payment_url:
                return redirect(payment_url)
        else:
            # Si l'API refuse la requête, on récupère le message d'erreur si possible
            error_message = data.get("message", "Erreur lors de l'initialisation du paiement.")
            print("ERREUR GENIUSPAY (data complet):", data)  # --- DEBUG TEMPORAIRE ---
            messages.error(request, error_message)

    except requests.RequestException as e:
        print("ERREUR REQUETE:", repr(e))  # --- DEBUG TEMPORAIRE ---
        messages.error(request, "Erreur de communication avec le service de paiement.")

    # En cas d'échec, on redirige vers le détail du livre
    return redirect('book-detail', pk=book_instance.book.id)

@csrf_exempt
@require_POST
def genius_pay_webhook(request):
    # 1. Récupération des en-têtes spécifiques à Genius Pay
    signature = request.headers.get("X-Webhook-Signature") or request.headers.get("HTTP_X_WEBHOOK_SIGNATURE")
    timestamp = request.headers.get("X-Webhook-Timestamp") or request.headers.get("HTTP_X_WEBHOOK_TIMESTAMP")

    if not signature or not timestamp:
        return JsonResponse({"error": "Missing signature or timestamp headers"}, status=401)

    # 2. Récupération du corps brut (payload)
    payload_body = request.body  # C'est déjà des bytes en Django

    # 3. Reconstruction de la chaîne signée : timestamp + "." + payload
    secret = getattr(settings, "GENIUS_PAY_WEBHOOK_SECRET", "").encode("utf-8")

    signed_payload = timestamp.encode("utf-8") + b"." + payload_body

    computed_signature = hmac.new(
        secret,
        msg=signed_payload,
        digestmod=hashlib.sha256
    ).hexdigest()

    # 4. Comparaison sécurisée anti-timing attack
    if not hmac.compare_digest(computed_signature, signature):
        return JsonResponse({"error": "Invalid signature"}, status=403)

    # 5. Traitement du payload
    try:
        payload = json.loads(payload_body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    event_type = payload.get("event") or payload.get("type")
    data = payload.get("data", {})

    metadata = data.get("metadata", {})
    payment_id = metadata.get("payment_id")

    if not payment_id:
        return JsonResponse({"status": "ignored", "reason": "No payment_id in metadata"}, status=200)

    try:
        payment = Payment.objects.get(id=payment_id)
    except Payment.DoesNotExist:
        return JsonResponse({"error": "Payment not found"}, status=404)

    with transaction.atomic():
        if payload.get("status") == "success" or event_type == "payment.success":
            if payment.status != Payment.Status.SUCCESS:
                payment.status = Payment.Status.SUCCESS
                payment.transaction_id = str(data.get("id", payment.transaction_id))
                payment.reference = data.get("reference", payment.reference)
                payment.save()

                book_instance = payment.book_instance
                book_instance.status = BookInstance.Status.VENDU
                book_instance.save()

        elif payload.get("status") == "failed" or event_type == "payment.failed":
            if payment.status != Payment.Status.FAILED:
                payment.status = Payment.Status.FAILED
                payment.save()

                book_instance = payment.book_instance
                if book_instance.status != BookInstance.Status.DISPONIBLE:
                    book_instance.status = BookInstance.Status.DISPONIBLE
                    book_instance.save()

    return JsonResponse({"status": "success"}, status=200)