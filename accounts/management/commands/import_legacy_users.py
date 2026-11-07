r"""Bring the local app's accounts into Django: python manage.py import_legacy_users

Reads %APPDATA%\AFP Watch Out\users.json (regional and national accounts, with their profile pictures in the
photos folder beside it). Passwords carry over: everyone signs in with the password they already have. Accounts
that already exist in Django are left as they are, and none is imported under a reserved name (admin).

The local app's support account is not imported: support here is the "admin" account (manage.py create_support).
"""
import json
import os
import shutil
from pathlib import Path

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from accounts import services
from accounts.models import Profile, reserved_problem

LEGACY_DIR = Path(os.environ.get("APPDATA") or Path.home()) / "AFP Watch Out"
ITERATIONS = 240_000  # the local app's PBKDF2 rounds


def legacy_hash(rec):
    return f"afp_pbkdf2${ITERATIONS}${rec['salt']}${rec['hash']}"


def legacy_photo(photos, name):
    return next((p for ext, _ in services.IMAGE_TYPES.values() if (p := photos / f"{name}{ext}").exists()), None)


class Command(BaseCommand):
    help = "Import the accounts of the local app (users.json) into Django."

    def add_arguments(self, parser):
        parser.add_argument("--users", default=str(LEGACY_DIR / "users.json"), help="users.json to read")

    def handle(self, *args, **opts):
        made = skipped = 0
        photos = Path(opts["users"]).parent / "photos"
        try:
            users = json.loads(Path(opts["users"]).read_text(encoding="utf-8"))
        except FileNotFoundError:
            users = {}
            self.stdout.write(f"No accounts file at {opts['users']}.")
        for name, rec in users.items():
            if reserved_problem(name):
                self.stdout.write(f"Skipped {name}: the name is reserved for the support account.")
                skipped += 1
                continue
            if User.objects.filter(username=name).exists():
                skipped += 1
                continue
            u = User(username=name, password=legacy_hash(rec))
            u.save()
            region = rec.get("region") or ""
            p = Profile.objects.create(user=u, full_name=rec.get("name", ""), cadre=rec.get("cadre", ""),
                                       region=services.NATIONAL if region == "National" else region,
                                       must_change=bool(rec.get("must_change")))
            if (src := legacy_photo(photos, name)) is not None:
                services.photos_dir().mkdir(parents=True, exist_ok=True)
                p.photo = f"{u.pk}-imported{src.suffix}"
                shutil.copy2(src, services.photos_dir() / p.photo)
                p.save(update_fields=["photo"])
            made += 1
        self.stdout.write(self.style.SUCCESS(f"{made} account(s) imported, {skipped} skipped."))
