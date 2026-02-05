@echo off
SET DB_NAME="dmis"
SET DB_USER="postgres"
SET DB_PASSWORD="Excellence!00"
SET DB_HOST="localhost"
SET DB_PORT="5432"
SET DJANGO_DEBUG="1"

python manage.py runserver
