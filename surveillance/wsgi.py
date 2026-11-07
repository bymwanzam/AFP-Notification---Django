"""WSGI entry point (used by passenger_wsgi.py on cPanel, or any WSGI server)."""
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "surveillance.settings")
application = get_wsgi_application()
