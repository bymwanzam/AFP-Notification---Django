"""ASGI entry point, for an ASGI server such as uvicorn or daphne."""
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "surveillance.settings")
application = get_asgi_application()
