from django.db import models
from django.contrib.auth.models import (
    AbstractBaseUser,
    PermissionsMixin,
)
from django.utils import timezone
from .managers import UserManager
from django.urls import reverse

from django.conf import settings


class User(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(
        unique=True,
        max_length=255,
    )

    phone = models.CharField(
        max_length=20,
        unique=True,
        null=True,
        blank=True,
    )

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    date_joined = models.DateTimeField(
        default=timezone.now
    )

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["phone"]

    def __str__(self):
        return self.email


""" core """
class Category(models.Model):
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name


class Book(models.Model):
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="books")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="books"
    )

    title = models.CharField(max_length=200)
    description = models.TextField()
    prix = models.DecimalField(max_digits=5, decimal_places=0)

    def __str__(self):
        cat = self.category.name if self.category else "Book Category"
        author = self.author.email if self.author else "Author"

        return f"Book {self.title} of {cat} - {author}"

    def get_absolute_url(self):
        return reverse('book-detail', kwargs={'pk': self.pk})


class BookInstance(models.Model):
    class Status(models.TextChoices):
        DISPONIBLE = 'disponible', 'Disponible'
        EMPRUNTE = 'emprunte', 'Emprunté'
        MAINTENANCE = 'maintenance', 'En maintenance'
        VENDU = 'vendu', 'Vendu'

    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="instances")
    status = models.CharField(
        max_length=20, 
        choices=Status.choices, 
        default=Status.DISPONIBLE
    )
    due_back = models.DateTimeField(null=True, blank=True) 


""" payment """
class Payment(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'En attente'
        SUCCESS = 'success', 'Succès'
        FAILED = 'failed', 'Échoué'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="payments"
    )

    book_instance = models.ForeignKey(
        'BookInstance',
        on_delete=models.SET_NULL,
        null=True,
        related_name="payments"
    )
    
    # Données de la transaction Genius Pay
    transaction_id = models.CharField(max_length=100, unique=True, null=True, blank=True)
    reference = models.CharField(max_length=100, unique=True, null=True, blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=0)
    currency = models.CharField(max_length=3, default='XOF')
    status = models.CharField(
        max_length=20, 
        choices=Status.choices, 
        default=Status.PENDING
    )
    
    # Traçabilité temporelle
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Paiement {self.reference or self.id} - {self.status} ({self.amount} {self.currency})"