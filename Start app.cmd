@echo off
cd /d "%~dp0"
python manage.py migrate --noinput
python manage.py collectstatic --noinput -v 0
start "" http://127.0.0.1:8765/login
python manage.py runserver 127.0.0.1:8765
