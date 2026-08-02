import os
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

class Command(BaseCommand):
    help = 'Crée un superutilisateur par défaut si aucun n\'existe'

    def handle(self, *args, **options):
        User = get_user_model()
        
        # Récupération depuis l'environnement ou utilisation de tes valeurs par défaut
        email = os.environ.get('DJANGO_SUPERUSER_EMAIL', 'david@py.py')
        phone = os.environ.get('DJANGO_SUPERUSER_PHONE', '0102030405')
        password = os.environ.get('DJANGO_SUPERUSER_PASSWORD', 'Miky2003')

        if not User.objects.filter(email=email).exists():
            self.stdout.write(self.style.WARNING(f'Création du superutilisateur : {email}...'))
            User.objects.create_superuser(
                email=email,
                phone=phone,
                password=password
            )
            self.stdout.write(self.style.SUCCESS('Superutilisateur créé avec succès !'))
        else:
            self.stdout.write(self.style.SUCCESS('Le superutilisateur existe déjà.'))