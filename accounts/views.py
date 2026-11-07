"""Sign-in, passwords, profiles and the support account's Accounts page.

The login page has four modes: "login"; "setup", while there are no accounts yet, which makes the first account
and the region it works for; "change", for a signed-in account that must set its own password before going on;
and "password" (at /password), where any signed-in account changes its password when it wants to.
"""
from urllib.parse import quote

from django.contrib.auth import login as sign_in, logout as sign_out, update_session_auth_hash
from django.contrib.auth.models import User
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from core import orgunits
from core.access import api, body_json, error, ok, page, page_data, safe_next
from core.branding import EMBLEM, LOGO, data_uri

from . import services


def _login_page(request, mode, nxt):
    regions = [r["name"] for r in orgunits.ORG_UNITS] if mode == "setup" else []
    return render(request, "accounts/login.html", {
        "logo": data_uri(LOGO), "icon": data_uri(EMBLEM),
        "data": {"mode": mode, "next": nxt, "regions": regions}})


@require_GET
@never_cache
@ensure_csrf_cookie
def login_page(request):
    nxt = safe_next(request.GET.get("next", ""))
    user = request.user
    if user.is_authenticated and not services.must_change(user):
        return redirect(nxt)
    mode = "change" if user.is_authenticated else "login" if services.has_accounts() else "setup"
    return _login_page(request, mode, nxt)


@require_GET
def logout_view(request):
    sign_out(request)
    return redirect("/login")


@require_GET
@page
def password_page(request):
    return _login_page(request, "password", safe_next(request.GET.get("next", "")))


@require_POST
@never_cache
def login_api(request):
    """/api/login, and /api/setup: the first account, only while there are no accounts (the rest are added by
    support on the Accounts page, or with manage.py)."""
    try:
        d = body_json(request)
        username, pw = str(d.get("username") or ""), str(d.get("password") or "")
        if request.path == "/api/setup":
            if services.has_accounts():
                return error(409, "An account already exists. Reload the page to sign in.")
            problem = services.check_new(username, pw, str(d.get("confirm") or ""))
            if problem:
                return error(400, problem)
            try:
                services.create_account(username, pw, str(d.get("name") or ""), str(d.get("region") or ""))
            except ValueError as e:
                return error(400, str(e))
        user = services.verify(request, username, pw)
    except ValueError as e:
        return error(401, str(e))
    sign_in(request, user)
    go = safe_next(str(d.get("next") or ""))
    # An account that must set its own password goes to the change-password form first.
    return ok({"go": "/login?next=" + quote(go) if services.must_change(user) else go})


@require_POST
@api(while_must_change=True)
def password_api(request):
    try:
        d = body_json(request)
        services.change_password(request.user, str(d.get("current") or ""), str(d.get("password") or ""),
                                 str(d.get("confirm") or ""))
    except ValueError as e:
        return error(400, str(e))
    update_session_auth_hash(request, request.user)  # stays signed in here; other sign-ins end
    return ok({"go": safe_next(str(d.get("next") or ""))})


@require_GET
@api
def me(request):
    return ok({"user": request.user.username, "role": services.role(request.user)})


# ---------- profile: full name, cadre and picture ----------
@require_GET
@page
def profile_page(request):
    data = services.profile(request.user) | {"next": safe_next(request.GET.get("next", ""))}
    return render(request, "accounts/profile.html", {"logo": data_uri(EMBLEM), "data": page_data(data)})


@api
def profile_api(request):
    if request.method == "GET":
        return ok(services.profile(request.user))
    if request.method != "POST":
        return error(405, "Method not allowed.")
    try:
        d = body_json(request)
        services.set_profile(request.user, str(d.get("name") or ""), str(d.get("cadre") or ""))
    except ValueError as e:
        return error(400, str(e))
    return ok(services.profile(request.user))


@api
def photo_api(request):
    """GET: your own picture; support may see anyone's (?u=, on the Accounts page). POST: set or remove yours."""
    if request.method == "POST":
        try:
            services.set_photo(request.user, request.body)
        except ValueError as e:
            return error(400, str(e))
        return ok(services.profile(request.user))
    who = request.user
    if services.is_support(request.user) and request.GET.get("u"):
        who = User.objects.filter(username=services.key(request.GET["u"])).first()
    f = services.photo_path(who) if who else None
    if f is None:
        return error(404, "No picture.")
    return HttpResponse(f.read_bytes(), content_type=services.photo_type(f))


# ---------- the support account's Accounts page ----------
@require_GET
@page
def accounts_page(request):
    if not services.is_support(request.user):
        return redirect("/start")
    data = {"regions": [r["name"] for r in orgunits.ORG_UNITS], "national": orgunits.NATIONAL}
    return render(request, "accounts/accounts.html", {"logo": data_uri(EMBLEM), "data": data})


@api
def users_api(request):
    """Support: list accounts; add one, reset its password, move it to another region, rename, unlock or remove it."""
    if not services.is_support(request.user):
        return error(403, "Only the support account manages accounts.")
    if request.method == "GET":
        return ok({"users": services.list_users()})
    if request.method != "POST":
        return error(405, "Method not allowed.")
    try:
        d = body_json(request)
        out = services.manage(str(d.get("action") or ""), str(d.get("username") or ""), d)
    except ValueError as e:
        return error(400, str(e))
    return ok(out | {"users": services.list_users()})
