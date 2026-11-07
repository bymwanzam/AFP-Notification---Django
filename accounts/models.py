from django.conf import settings
from django.contrib.auth.models import User
from django.db import models
from django.db.models.signals import pre_save
from django.dispatch import receiver

RESERVED_USERNAMES = {"admin"}  # the support account's (accounts.services.SUPPORT_USERNAME); no one else may take them


class Profile(models.Model):
    """What the app needs about an account beyond Django's user: its region, cadre and picture.

    The support account is a Django superuser (region left blank). A national administrator has region "Ghana".
    """
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    full_name = models.CharField(max_length=80, blank=True)
    region = models.CharField(max_length=40, blank=True, help_text='An org unit region, or "Ghana" for a national administrator.')
    cadre = models.CharField(max_length=60, blank=True)
    photo = models.CharField(max_length=120, blank=True, help_text="File name in private_media/photos.")
    must_change = models.BooleanField(default=False, help_text="Sets its own password at the next sign-in.")

    def __str__(self):
        return f"{self.user.username} ({self.region or 'support'})"


class LoginLock(models.Model):
    """Wrong passwords in a row for a username; after 5 it is locked for 5 minutes."""
    username = models.CharField(max_length=150, unique=True)
    failures = models.PositiveIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)


def reserved_problem(username, pk=None, superuser=False):
    """Why an account may not be called `username`, or None. A reserved name belongs to the support account only:
    one superuser, whatever the letter case."""
    name = (username or "").strip().lower()
    if name in RESERVED_USERNAMES and (not superuser or User.objects.filter(username__iexact=name).exclude(pk=pk).exists()):
        return f"The username {name} is reserved for the support account."
    return None


@receiver(pre_save, sender=User)
def keep_reserved_usernames(sender, instance, **kwargs):
    """However an account is made or renamed (the app's forms, the Accounts page, Django's admin, an import or the
    shell), only the support account may be called admin."""
    problem = reserved_problem(instance.username, instance.pk, instance.is_superuser)
    if problem:
        raise ValueError(problem)
