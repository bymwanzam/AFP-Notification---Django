"""Who may open what: the sign-in gate for pages and API calls, and the region a request works for.

Each account belongs to one region and works with it and its districts only. Support (a superuser) and national
administrators see every region: they pick one, or Ghana (all regions), on the start page for that sign-in.
"""
import json
import re
from functools import wraps
from urllib.parse import quote

from django.core.exceptions import RequestDataTooBig
from django.http import JsonResponse
from django.shortcuts import redirect
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie

from accounts import services

from . import orgunits


class OtherRegion(Exception):
    """A call named a region that is not the account's own."""


def error(status, message, **extra):
    return JsonResponse({"error": message, **extra}, status=status, json_dumps_params={"ensure_ascii": False})


def ok(obj):
    return JsonResponse(obj, safe=False, json_dumps_params={"ensure_ascii": False, "default": str})


def safe_next(path):
    """Only a path on this app, never another site ("//host" or "/\\host")."""
    return path if re.fullmatch(r"/(?![/\\])[^\s\\]*", path or "") and not path.startswith(("/login", "/logout")) else "/start"


def page_data(obj):
    """Page data made JSON-safe (dates and the like as text) for the template's json_script."""
    return json.loads(json.dumps(obj, ensure_ascii=False, default=str))


def page(view):
    """A page for signed-in accounts whose password needs no change; everyone else goes to the login page (which
    asks for the new password when that is what is missing). Sets the CSRF cookie the page's API calls send back."""
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated or services.must_change(request.user):
            return redirect("/login?next=" + quote(request.get_full_path()))
        return view(request, *args, **kwargs)
    return never_cache(ensure_csrf_cookie(wrapped))


def api(view=None, *, while_must_change=False):
    """An API call for signed-in accounts. Refused with JSON (not a redirect), so a page whose sign-in ended can say
    so and keep what was typed."""
    def deco(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return error(401, "Your session has ended. Sign in again.")
            if services.must_change(request.user) and not while_must_change:
                return error(403, "Change your password first.")
            try:
                return view(request, *args, **kwargs)
            except RequestDataTooBig:
                return error(413, "That file is over 10 MB.")
            except OtherRegion:
                return error(403, f"Your account is for {unit(request)['name']} Region only.")
        return never_cache(wrapped)
    return deco(view) if view else deco


def body_json(request):
    try:
        d = json.loads(request.body or b"{}")
    except ValueError:
        raise ValueError("The request was not understood.")
    if not isinstance(d, dict):
        raise ValueError("The request was not understood.")
    return d


def sees_all(request):
    return services.sees_all(request.user)


def is_support(request):
    return services.is_support(request.user)


def unit(request):
    """The org unit the request works for: a regional account's own region; for support and national
    administrators the one picked on the start page for this sign-in, else Ghana (national) or the default region."""
    user = request.user
    if not services.sees_all(user):
        return services.user_region(user)
    view = request.session.get("view") or (orgunits.NATIONAL if services.is_national(user) else None)
    return orgunits.national_unit() if view == orgunits.NATIONAL else orgunits.region_of(view) or orgunits.current_region()


def scope(request):
    """The region name a write is limited to, or None in the national view (cases of any region)."""
    u = unit(request)
    return None if orgunits.is_national(u) else u["name"]
