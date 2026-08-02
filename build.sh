#!/usr/bin/env bash
# Exit on error
set -o errexit

# Installer les dépendances
pip install -r requirements.txt

# Collecter les fichiers statiques de Django
python manage.py collectstatic --no-input

# Appliquer les migrations de la base de données
python manage.py migrate