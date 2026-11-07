"""Django settings for the surveillance web app (AFP 60-day follow-up and Weekly IDSR).

Everything that differs between this computer and the hosting server comes from environment variables, so the
same files run in both places. On cPanel, set them under Setup Python App > Environment variables:

    DJANGO_SECRET_KEY     a long random string (without it, one is made and kept in .secret_key)
    DJANGO_DEBUG          1 only while testing; leave unset on the server
    DJANGO_ALLOWED_HOSTS  the site's domain(s), comma separated, e.g. surveillance.rhduer.online
    DJANGO_HTTPS          1 once the site has an SSL certificate (secure cookies)
    DJANGO_CSRF_TRUSTED_ORIGINS  e.g. https://surveillance.rhduer.online, if the site sits behind a proxy on another host
    DB_ENGINE             mysql to use MySQL; unset uses SQLite (db.sqlite3 here)
    DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT   for MySQL (DB_NAME alone: another SQLite file)
    DATA_DIR              folder of the workbooks (default: data/ here): the AFP register, the IDSR stores, pictures
    AFP_REGISTER          path of the AFP register workbook (default: DATA_DIR/AFP nofitication.xlsx)
    PRIVATE_DIR           folder never served directly (default: private_media/ here): profile pictures, DHIMS2 token

The same variables can be written in a .env file beside manage.py (see .env.example). cPanel's variables reach only
the web app, not the Terminal, so on Namecheap keep them in .env and manage.py commands see the same settings.

The workbooks and private_media hold patient and account details: keep them out of git and out of public_html.
"""
import os
import secrets
import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_env(f):
    """NAME=value lines of .env; variables already set (cPanel's own) win."""
    if not f.exists():
        return
    for line in f.read_text(encoding="utf-8").splitlines():
        name, sep, value = line.strip().partition("=")
        if sep and not name.startswith("#"):
            os.environ.setdefault(name.strip(), value.strip().strip("\"'"))


_load_env(BASE_DIR / ".env")


def _secret_key():
    if os.environ.get("DJANGO_SECRET_KEY"):
        return os.environ["DJANGO_SECRET_KEY"]
    f = BASE_DIR / ".secret_key"
    if not f.exists():
        f.write_text(secrets.token_urlsafe(50), encoding="utf-8")
    return f.read_text(encoding="utf-8").strip()


SECRET_KEY = _secret_key()
DEBUG = os.environ.get("DJANGO_DEBUG") == "1"
ALLOWED_HOSTS = [h.strip() for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",") if h.strip()]
HTTPS = os.environ.get("DJANGO_HTTPS") == "1"
CSRF_TRUSTED_ORIGINS = [o.strip() for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "core",
    "afp",
    "idsr",
    "meningitis",
    "reminders",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",  # serves /static/ on cPanel, where nothing else does
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.locks.WriteLockMiddleware",  # one save at a time, across all the app's processes
]

ROOT_URLCONF = "surveillance.urls"
WSGI_APPLICATION = "surveillance.wsgi.application"

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
        "core.context_processors.branding",
    ]},
}]

if os.environ.get("DB_ENGINE") == "mysql":
    try:
        import MySQLdb  # noqa: F401  mysqlclient, when the server could build it
    except ImportError:  # shared hosting often cannot: PyMySQL (pure Python) stands in for it
        import pymysql
        pymysql.version_info = (2, 2, 1, "final", 0)  # the mysqlclient version Django asks for
        pymysql.install_as_MySQLdb()
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": os.environ.get("DB_NAME", ""),
        "USER": os.environ.get("DB_USER", ""),
        "PASSWORD": os.environ.get("DB_PASSWORD", ""),
        "HOST": os.environ.get("DB_HOST", "localhost"),
        "PORT": os.environ.get("DB_PORT", "3306"),
        "OPTIONS": {"charset": "utf8mb4"},
    }}
else:
    if sqlite3.sqlite_version_info < (3, 31):  # Django needs SQLite 3.31; Namecheap's servers have an older one
        try:
            import pysqlite3  # pysqlite3-binary brings its own, newer SQLite
            sys.modules["sqlite3"] = pysqlite3
        except ImportError:
            pass
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3","NAME": os.environ.get("DB_NAME") or BASE_DIR / "db.sqlite3"}}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Passwords: Django's own hashing; accounts brought over from the local app keep working (accounts.hashers) and
# are moved to Django's hashing the first time they sign in.
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "accounts.hashers.LegacyAFPHasher",
]

# Sign-ins last 12 hours; the cookie is never readable by page scripts or sent by other sites.
SESSION_COOKIE_NAME = "afp_session"
SESSION_COOKIE_AGE = 12 * 3600
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Strict"
SESSION_COOKIE_SECURE = HTTPS
CSRF_COOKIE_SECURE = HTTPS
if HTTPS:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")  # cPanel/Passenger sits behind a proxy
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 3600
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

LOGIN_URL = "/login"
APPEND_SLASH = False                          # the pages call /api/... without trailing slashes
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # uploads (forms, tables, pictures) up to 10 MB

LANGUAGE_CODE = "en-gb"
TIME_ZONE = "Africa/Accra"
USE_I18N = False
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# The workbooks the modules read and write. Each save keeps the previous version beside it as .bak.xlsx.
DATA_DIR = Path(os.environ.get("DATA_DIR") or BASE_DIR / "data")
AFP_REGISTER = Path(os.environ.get("AFP_REGISTER") or DATA_DIR / "AFP nofitication.xlsx")
IDSR_STORE = DATA_DIR / "IDSR weekly data.xlsx"  # the main region's; the others are in DATA_DIR/IDSR regions/
IDSR_IMAGES = DATA_DIR / "idsr-images"           # each region's map and SORMAS pictures for the bulletin

# Files that must never be served directly (profile pictures, the remembered DHIMS2 token): read by views that
# check the sign-in, or by the server only.
PRIVATE_MEDIA = Path(os.environ.get("PRIVATE_DIR") or BASE_DIR / "private_media")

# SMS reminders to district officers (AFP 60-day follow-up), through Fish Africa (https://docs.letsfish.africa).
# App ID and App Secret: Fish Africa dashboard > Settings > Applications > Default App. The sender ID (at most 11
# characters) must be approved by Fish Africa. Run `python manage.py send_reminders` once a day.
LETSFISH_APP_ID = os.environ.get("LETSFISH_APP_ID", "")
LETSFISH_APP_SECRET = os.environ.get("LETSFISH_APP_SECRET", "")
LETSFISH_SENDER_ID = os.environ.get("LETSFISH_SENDER_ID", "")
REMINDER_SOON_DAYS = int(os.environ.get("REMINDER_SOON_DAYS") or 7)      # remind once when this many days are left
REMINDER_REPEAT_DAYS = int(os.environ.get("REMINDER_REPEAT_DAYS") or 7)  # then every this many days while overdue

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"stamped": {"format": "%(asctime)s %(name)s %(levelname)s %(message)s"}},
    "handlers": {"file": {"class": "logging.FileHandler", "filename": BASE_DIR / "django-errors.log", "level": "ERROR",
                          "formatter": "stamped"}},
    "loggers": {"django": {"handlers": ["file"], "level": "ERROR"},
                "idsr.dhims2": {"handlers": ["file"], "level": "ERROR", "propagate": False}},
}
if "test" in sys.argv[1:2]:  # the test suite's made-up failures stay out of the real error log
    LOGGING["handlers"]["file"] = {"class": "logging.NullHandler"}
