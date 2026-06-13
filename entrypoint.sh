#!/bin/sh
set -e

echo "==> Corriendo migraciones..."
python manage.py migrate --noinput

echo "==> Creando superusuario si no existe..."
python manage.py shell -c "
from django.contrib.auth.models import User
import os
username = os.environ.get('DJANGO_SUPERUSER_USERNAME', 'admin')
email = os.environ.get('DJANGO_SUPERUSER_EMAIL', 'admin@acuagro.com')
password = os.environ.get('DJANGO_SUPERUSER_PASSWORD', 'admin1234')
if not User.objects.filter(username=username).exists():
    u = User.objects.create_superuser(username=username, email=email, password=password)
    u.first_name = 'Administrador'
    u.save()
    print(f'Superusuario creado: {username}')
else:
    print(f'Superusuario ya existe: {username}')
"

echo "==> Iniciando servidor..."
exec "$@"
