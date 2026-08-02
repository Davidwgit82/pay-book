from django.urls import path
from . import views

urlpatterns = [
    path('', views.IndexView.as_view(), name="index"),
    path('ping/', views.ping, name="health_check"),
    path('books/', views.BookViewPage.as_view(), name="book-list"),
    path('books/<int:pk>/', views.BookDetailViewPage.as_view(), name="book-detail"),
    
    # Routes de paiement Genius Pay
    path('payment/initiate/<int:instance_id>/', views.initiate_payment, name="initiate-payment"),
    path('payment/webhook/', views.genius_pay_webhook, name="genius-pay-webhook"),
    path('payment/success/', views.TemplateView.as_view(template_name="payment_success.html"), name="payment_success"),
    path('payment/error/', views.TemplateView.as_view(template_name="payment_error.html"), name="payment_error"),
]