@echo off
set DB_NAME=dmis
set DB_USER=postgres
set DB_PASSWORD=Excellence!00
set DB_HOST=localhost
set DB_PORT=5432
set DJANGO_DEBUG=1

python manage.py runserver
