#!/bin/bash
# Set up or update the app on the cPanel server, then check it from outside. Run it in Terminal, inside the app's
# virtualenv (the "source .../activate" command shown in Setup Python App):
#     bash server_setup.sh
# Safe to run again: it never replaces the database, the workbooks or the support account's password.
#
# The app lives in this folder (private). The subdomain's document root (WEB_ROOT, default ~/surveillance_web) holds
# only the .htaccess that hands every visit to the app. The app must never be inside the document root: the web
# server would hand out db.sqlite3, .env and the workbooks to anyone.
set -e
APP="$(cd "$(dirname "$0")" && pwd)"
WEB="${WEB_ROOT:-$HOME/surveillance_web}"
cd "$APP"

fail() { echo; echo "STOPPED: $1"; exit 1; }

[ -n "$VIRTUAL_ENV" ] || fail "run the 'source .../activate' command from Setup Python App first."
python -c 'import sys; sys.exit(sys.version_info < (3, 10))' \
  || fail "Python $(python -V 2>&1) is too old. In Setup Python App choose 3.12, then run the new 'source' command."
[ -f .env ] || fail "no .env in $APP. Upload dist/.env here (turn on Show Hidden Files in File Manager)."
case "$APP/" in "$WEB/"*) fail "the app is inside the document root $WEB. Move it out (e.g. to ~/surveillance).";; esac
case "$WEB/" in "$APP/"*) fail "the document root $WEB is inside the app folder. Point the subdomain at ~/surveillance_web.";; esac
[ -f core/data/ghana-org-units.json ] || fail "core/data/ghana-org-units.json is missing: extract surveillance-app.zip again."

echo "== Packages"
pip install -q --upgrade pip
pip install -q -r requirements.txt

echo "== Database and static files"
python manage.py migrate --noinput
python manage.py collectstatic --noinput

echo "== Accounts"
if [ -f legacy-accounts/users.json ]; then
  python manage.py import_legacy_users --users legacy-accounts/users.json
fi
python manage.py create_support --if-missing
chmod 600 .env db.sqlite3 2>/dev/null || true

echo "== Settings check"
python manage.py check --deploy --fail-level ERROR

echo "== Web server link ($WEB/.htaccess)"
mkdir -p "$WEB" tmp
cat > "$WEB/.htaccess" <<EOF
# DO NOT REMOVE. CLOUDLINUX PASSENGER CONFIGURATION BEGIN
PassengerAppRoot "$APP"
PassengerBaseURI "/"
PassengerPython "$VIRTUAL_ENV/bin/python"
# DO NOT REMOVE. CLOUDLINUX PASSENGER CONFIGURATION END
EOF
touch tmp/restart.txt

HOST="$(sed -n 's/^DJANGO_ALLOWED_HOSTS=//p' .env | cut -d, -f1 | tr -d '\r" ')"
if [ -n "$HOST" ] && command -v curl >/dev/null; then
  echo "== Checking https://$HOST from outside"
  status() { curl -s -o /dev/null -w '%{http_code}' "https://$HOST$1"; }
  login="$(status /login)"
  echo "  /login        $login (want 200)"
  bad=0
  for f in /db.sqlite3 /.env /manage.py /data/ /legacy-accounts/users.json; do
    s="$(status "$f")"
    echo "  $f  $s (want 403 or 404)"
    [ "$s" = "200" ] && bad=1
  done
  [ "$bad" = "0" ] || fail "private files can be downloaded. The subdomain's document root must be $WEB, not $APP."
  [ "$login" = "200" ] || echo "  The login page did not answer 200: see the end of $APP/django-errors.log and $APP/stderr.log."
fi

echo
echo "Done. Open https://${HOST:-your-subdomain}/login"
[ -d legacy-accounts ] && echo "Once the imported accounts can sign in, delete the legacy-accounts folder."
ls ./*.zip >/dev/null 2>&1 && echo "Delete the uploaded .zip files from $APP."
exit 0
