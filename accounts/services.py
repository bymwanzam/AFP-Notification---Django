"""Account rules: one region per account (or Ghana for a
national administrator), the support account (a superuser) that sees every region, a 5-try lockout, profiles
with cadre and picture, and passwords someone else set that must be changed at the next sign-in.
"""
import re
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.contrib.sessions.models import Session
from django.db import transaction
from django.utils import timezone

from core import orgunits
from core.branding import IMAGE_TYPES

from .models import RESERVED_USERNAMES, LoginLock, Profile

NATIONAL = orgunits.NATIONAL
SUPPORT_USERNAME = "admin"     # the support account's username: no other account may take it
MIN_PASSWORD = 8
MAX_FAILS, LOCK_MINUTES = 5, 5
CADRES = ["Regional Surveillance Officer", "Deputy Regional Surveillance Officer", "District Surveillance Officer",
          "Disease Control Officer", "Regional Director of Health Services", "Deputy Director of Public Health",
          "Public Health Nurse", "Health Information Officer", "Epidemiologist", "Data Manager", "Other"]
MAX_PHOTO = 3 * 1024 * 1024


def key(username):
    return (username or "").strip().lower()


def profile_of(user):
    p, _ = Profile.objects.get_or_create(user=user)
    return p


# ---------- roles ----------
def is_support(user):
    return bool(user and user.is_authenticated and user.is_superuser)


def is_national(user):
    return bool(user and user.is_authenticated and not user.is_superuser and profile_of(user).region in (NATIONAL, "National"))


def sees_all(user):
    return is_support(user) or is_national(user)


def role(user):
    return "support" if is_support(user) else "national" if is_national(user) else "regional"


def user_region(user):
    """The org unit of a regional account. One with no region yet gets the default region (Upper East)."""
    p = profile_of(user)
    unit = orgunits.region_of(p.region)
    if not unit:
        unit = orgunits.current_region()
        p.region = unit["name"]
        p.save(update_fields=["region"])
    return unit


def has_accounts():
    """Whether anyone but support has an account (the first one is made on the login page)."""
    return User.objects.filter(is_superuser=False).exists()


# ---------- making and checking accounts ----------
def check_new(username, password, confirm=None):
    """The problem with a new username and password, or None."""
    k = key(username)
    if not re.fullmatch(r"[a-z0-9._-]{3,32}", k):
        return "Usernames are 3 to 32 letters, numbers, dots, dashes or underscores."
    if k in RESERVED_USERNAMES:
        return f"The username {k} is reserved. Choose another one."
    if User.objects.filter(username=k).exists():
        return f"There is already an account called {k}."
    if len(password or "") < MIN_PASSWORD:
        return f"Use a password of at least {MIN_PASSWORD} characters."
    if confirm is not None and password != confirm:
        return "The two passwords do not match."
    return None


def region_name(region):
    """The stored name of a chosen region: an org unit region, or Ghana. Raises ValueError otherwise."""
    if (region or "").strip().lower() in (NATIONAL.lower(), "national"):
        return NATIONAL
    unit = orgunits.region_of(region)
    if not unit:
        raise ValueError("Choose your region.")
    return unit["name"]


@transaction.atomic
def create_account(username, password, full_name="", region="", must_change=False):
    problem = check_new(username, password)
    if problem:
        raise ValueError(problem)
    reg = region_name(region)
    user = User.objects.create_user(key(username), password=password)
    Profile.objects.create(user=user, full_name=(full_name or "").strip(), region=reg, must_change=must_change)
    return user


def verify(request, username, password):
    """The account if the password is right; raises ValueError with the message to show otherwise."""
    k, now = key(username), timezone.now()
    lock = LoginLock.objects.filter(username=k).first()
    if lock and lock.locked_until and lock.locked_until > now:
        raise ValueError(f"Too many wrong passwords. Try again in {int((lock.locked_until - now).total_seconds() // 60) + 1} min.")
    user = authenticate(request, username=k, password=password or "")
    if user:
        LoginLock.objects.filter(username=k).delete()
        return user
    lock = lock or LoginLock(username=k)
    if lock.locked_until and lock.locked_until <= now:
        lock.failures, lock.locked_until = 0, None
    lock.failures += 1
    if lock.failures >= MAX_FAILS:
        lock.failures, lock.locked_until = 0, now + timedelta(minutes=LOCK_MINUTES)
    lock.save()
    raise ValueError("The username or password is not right.")


def must_change(user):
    return profile_of(user).must_change


def change_password(user, current, new, confirm):
    if not user.check_password(current or ""):
        raise ValueError("Your current password is not right.")
    if len(new or "") < MIN_PASSWORD:
        raise ValueError(f"Use a password of at least {MIN_PASSWORD} characters.")
    if new != confirm:
        raise ValueError("The two new passwords do not match.")
    if new == current:
        raise ValueError("Choose a password different from the current one.")
    user.set_password(new)
    user.save()
    p = profile_of(user)
    p.must_change = False
    p.save(update_fields=["must_change"])


def temp_password():
    return "-".join(secrets.token_urlsafe(4) for _ in range(3))


def end_sessions(user):
    """Sign an account out everywhere (after its region, password or the account itself changes)."""
    for s in Session.objects.filter(expire_date__gt=timezone.now()):
        if s.get_decoded().get("_auth_user_id") == str(user.pk):
            s.delete()


# ---------- support: managing accounts ----------
def list_users():
    out = []
    for u in User.objects.filter(is_superuser=False).order_by("username"):
        p = profile_of(u)
        out.append({"username": u.username, "name": p.full_name, "region": p.region, "cadre": p.cadre,
                    "mustChange": p.must_change, "photo": photo_path(u) is not None})
    return out


def account(username):
    u = User.objects.filter(username=key(username), is_superuser=False).first()
    if not u:
        raise ValueError(f"There is no account called {key(username)}.")
    return u


def manage(action, username, data):
    """One action from the Accounts page. Returns extra results (a password to hand over)."""
    if action == "add":
        pw = str(data.get("password") or "") or temp_password()
        create_account(username, pw, str(data.get("name") or ""), str(data.get("region") or ""), must_change=True)
        return {"password": pw}
    u = account(username)
    p = profile_of(u)
    if action == "reset":
        pw = str(data.get("password") or "") or temp_password()
        if len(pw) < MIN_PASSWORD:
            raise ValueError(f"Use a password of at least {MIN_PASSWORD} characters.")
        u.set_password(pw)
        u.save()
        p.must_change = True
        p.save(update_fields=["must_change"])
        end_sessions(u)
        LoginLock.objects.filter(username=u.username).delete()
        return {"password": pw}
    if action == "region":
        p.region = region_name(str(data.get("region") or ""))
        p.save(update_fields=["region"])
        end_sessions(u)
    elif action == "rename":
        name = str(data.get("name") or "").strip()
        if not name:
            raise ValueError("Enter the full name.")
        p.full_name = name[:80]
        p.save(update_fields=["full_name"])
    elif action == "unlock":
        LoginLock.objects.filter(username=u.username).delete()
    elif action == "remove":
        end_sessions(u)
        if (f := photo_path(u)) is not None:
            f.unlink()
        u.delete()
    else:
        raise ValueError("Unknown action.")
    return {}


# ---------- profile: full name, cadre and picture ----------
def profile(user):
    p = profile_of(user)
    r = role(user)
    return {"username": user.username, "name": p.full_name, "cadre": p.cadre, "region": "" if r == "support" else p.region,
            "role": r, "photo": photo_path(user) is not None, "cadres": CADRES}


def set_profile(user, name, cadre):
    name, cadre = (name or "").strip(), (cadre or "").strip()
    if not name:
        raise ValueError("Enter your full name.")
    if len(name) > 80:
        raise ValueError("Keep the full name under 80 characters.")
    if cadre and cadre not in CADRES:
        raise ValueError("Choose a cadre from the list.")
    p = profile_of(user)
    p.full_name, p.cadre = name, cadre
    p.save(update_fields=["full_name", "cadre"])


def photos_dir():
    return settings.PRIVATE_MEDIA / "photos"


def photo_path(user):
    name = profile_of(user).photo
    f = photos_dir() / name if name else None
    return f if f and f.exists() else None


def set_photo(user, body):
    """Store the account's picture (PNG or JPEG, under 3 MB); an empty body removes it."""
    ext = next((e for magic, (e, _) in IMAGE_TYPES.items() if body.startswith(magic)), None)
    if body and not ext:
        raise ValueError("Choose a PNG or JPEG picture.")
    if len(body) > MAX_PHOTO:
        raise ValueError("Choose a picture under 3 MB.")
    p = profile_of(user)
    if (old := photo_path(user)) is not None:
        old.unlink()
    p.photo = ""
    if body:
        photos_dir().mkdir(parents=True, exist_ok=True)
        p.photo = f"{user.pk}-{secrets.token_hex(4)}{ext}"
        (photos_dir() / p.photo).write_bytes(body)
    p.save(update_fields=["photo"])


def photo_type(path):
    return next((m for e, m in IMAGE_TYPES.values() if path.suffix == e), "image/png")
