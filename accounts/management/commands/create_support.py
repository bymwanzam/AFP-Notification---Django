"""Make the support account, or give it a new password: python manage.py create_support

Prints a new random password once; the first sign-in with it asks for a new one. The support account is a Django
superuser: it sees every region, manages accounts and can open Django's admin at /django-admin/.
"""
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from accounts import services
from accounts.models import Profile


class Command(BaseCommand):
    help = "Create the support account, or set a new random password for it."

    def add_arguments(self, parser):
        parser.add_argument("--username", default=services.SUPPORT_USERNAME)
        parser.add_argument("--if-missing", action="store_true", help="leave an existing support account as it is")

    def handle(self, *args, **opts):
        name = services.key(opts["username"])
        if opts["if_missing"] and User.objects.filter(username=name).exists():
            self.stdout.write(f"Support account {name} already exists; its password is unchanged.")
            return
        pw = "-".join(services.temp_password() for _ in range(2))
        user = User.objects.filter(username=name).first() or User(username=name)
        user.is_superuser = user.is_staff = True
        user.set_password(pw)
        user.save()
        p, _ = Profile.objects.get_or_create(user=user)
        p.region, p.must_change = "", True
        p.save()
        services.end_sessions(user)
        self.stdout.write(f"Support account\n  username: {name}\n  password: {pw}\n"
                          "Keep it with the support team. It is not shown again. The first sign-in asks for a new password.")
