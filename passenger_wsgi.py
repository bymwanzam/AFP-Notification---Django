"""cPanel "Setup Python App" entry point: point the app's startup file here (application = application)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "surveillance.settings")

from surveillance.wsgi import application  # noqa: E402,F401
