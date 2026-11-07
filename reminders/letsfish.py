"""Sending SMS through Fish Africa (LetsFish): https://docs.letsfish.africa (OpenAPI at https://api.letsfish.africa/api/docs).

    POST https://api.letsfish.africa/v1/sms
    Authorization: Bearer <app_id>.<app_secret>
    {"sender_id": "<= 11 characters", "message": "...", "recipients": ["233XXXXXXXXX", ...]}
    202 {"success": true, "data": [{"recipient", "reference", "status"}]}
    error {"success": false, "error": {"status", "title", "detail"}}  (401 credentials, 402 balance, 403 not allowed)

Credentials: set by the support account on the SMS reminders page (kept in PRIVATE_MEDIA/sms.json, never served,
the secret never sent back to a page), or else from the settings (.env: LETSFISH_APP_ID, LETSFISH_APP_SECRET,
LETSFISH_SENDER_ID). The page's values win when both are set.
"""
import json
import re
import urllib.error
import urllib.request

from django.conf import settings

URL = "https://api.letsfish.africa/v1/sms"
TIMEOUT = 30
# The API sits behind Cloudflare, which refuses Python's default User-Agent ("Python-urllib", error 1010).
USER_AGENT = "GHS-Surveillance/1.0"
KEYS = {"app_id": "LETSFISH_APP_ID", "app_secret": "LETSFISH_APP_SECRET", "sender_id": "LETSFISH_SENDER_ID"}


class SmsError(Exception):
    pass


def config_file():
    return settings.PRIVATE_MEDIA / "sms.json"


def saved():
    try:
        return json.loads(config_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def creds():
    """{app_id, app_secret, sender_id}: the page's saved values, else the settings (.env)."""
    s = saved()
    return {k: str(s.get(k) or getattr(settings, name, "") or "").strip() for k, name in KEYS.items()}


def save_settings(app_id, app_secret, sender_id):
    """Save the page's values. A blank App ID or secret keeps the saved one."""
    app_id, app_secret, sender_id = (str(v or "").strip() for v in (app_id, app_secret, sender_id))
    if sender_id and not re.fullmatch(r"[A-Za-z0-9 ._-]{1,11}", sender_id):
        raise ValueError("The sender ID is 1 to 11 letters, digits, spaces, dots, dashes or underscores.")
    if app_id and not re.fullmatch(r"[\w-]{4,100}", app_id):
        raise ValueError("That App ID does not look right: copy it again from the Fish Africa dashboard.")
    if app_secret and (len(app_secret) < 8 or len(app_secret) > 200 or re.search(r"\s", app_secret)):
        raise ValueError("That App Secret does not look right: copy it again from the Fish Africa dashboard.")
    cfg = saved()
    cfg["sender_id"] = sender_id
    if app_id:
        cfg["app_id"] = app_id
    if app_secret:
        cfg["app_secret"] = app_secret
    config_file().parent.mkdir(parents=True, exist_ok=True)
    config_file().write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def clear_settings():
    try:
        config_file().unlink()
    except FileNotFoundError:
        pass


def configured():
    return all(creds().values())


def status():
    """What the page may show: whether sending is set up, where from, the sender ID and the App ID's end. Never the
    secret."""
    c, s = creds(), saved()
    missing = [KEYS[k] for k, v in c.items() if not v]
    return {"configured": not missing, "missing": missing, "sender": c["sender_id"],
            "appIdEnd": c["app_id"][-4:] if c["app_id"] else "", "hasSecret": bool(c["app_secret"]),
            "source": "page" if any(s.get(k) for k in KEYS) else "env" if any(getattr(settings, n, "") for n in KEYS.values()) else ""}


def phone(number):
    """A Ghana mobile number as the API wants it (233XXXXXXXXX), from 024..., +233 24..., 233-24-..., or raise."""
    digits = re.sub(r"\D", "", str(number or ""))
    if digits.startswith("00"):
        digits = digits[2:]
    if len(digits) == 10 and digits.startswith("0"):
        digits = "233" + digits[1:]
    elif len(digits) == 9:
        digits = "233" + digits
    if not re.fullmatch(r"233[2-5]\d{8}", digits):
        raise ValueError(f"“{number}” is not a Ghana mobile number (e.g. 0244123456).")
    return digits


def send(recipients, message):
    """Send one message to one or more numbers. Returns [{recipient, reference, status}]; raises SmsError."""
    c = creds()
    if not all(c.values()):
        raise SmsError("SMS is not set up: the support account enters the Fish Africa App ID, App Secret and sender ID on the SMS reminders page.")
    if len(c["sender_id"]) > 11:
        raise SmsError("The sender ID must be at most 11 characters.")
    body = json.dumps({"sender_id": c["sender_id"], "message": message, "recipients": list(recipients)}).encode()
    req = urllib.request.Request(URL, data=body, method="POST", headers={
        "Authorization": f"Bearer {c['app_id']}.{c['app_secret']}",
        "Content-Type": "application/json", "Accept": "application/json", "User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            answer = json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            err = json.loads(raw).get("error") or {}
        except ValueError:
            err = {}
        detail = err.get("detail") or err.get("title") or raw[:120].decode(errors="replace").strip()
        raise SmsError({
            401: "Fish Africa did not accept the App ID and App Secret. Check them in the SMS settings.",
            402: "The Fish Africa account has too little balance. Top it up, then send again.",
            403: f"Fish Africa refused the request: {detail}",
        }.get(e.code) or f"Fish Africa answered with error {e.code}: {detail}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise SmsError(f"Could not reach Fish Africa ({getattr(e, 'reason', e)}). Check the internet connection.") from None
    except ValueError:
        raise SmsError("Fish Africa sent back something that is not JSON.") from None
    if not answer.get("success"):
        err = answer.get("error") or {}
        raise SmsError(f"Fish Africa did not accept the message: {err.get('detail') or err.get('title') or answer}")
    return answer.get("data") or []
