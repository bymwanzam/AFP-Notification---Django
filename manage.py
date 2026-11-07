#!/usr/bin/env python
"""Django's command-line tool: python manage.py runserver | migrate | import_legacy_users | create_support | ..."""
import os
import sys

if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "surveillance.settings")
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)
