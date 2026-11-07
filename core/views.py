"""Start page: the signed-in account's region, then open a module.

Every page, alert and report works for the account's region and its districts only; the region is set when the
account is made, not here. Support and national administrators pick a region, or Ghana (all regions), for this
sign-in.
"""
from collections import Counter

from django.conf import settings
from django.db.models import Count
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from accounts import services
from afp import cases
from idsr import store as idsr
from meningitis.models import Case as MeningitisCase

from . import orgunits
from .access import api, body_json, error, is_support, ok, page, page_data, sees_all, unit
from .branding import EMBLEM, data_uri


def regions_snapshot():
    """The regions with their districts, AFP cases in the register, IDSR weeks on file and meningitis cases."""
    try:
        afp = Counter((orgunits.district_region(c.get("district"))[0] or {"name": orgunits.DEFAULT_REGION})["name"]
                      for c in cases.load_cases(settings.AFP_REGISTER))
    except Exception:
        afp = Counter()
    weeks = {}
    for name in idsr.regions_on_file():
        try:
            u = orgunits.region_of(name)
            if u:
                weeks[u["name"]] = len(idsr.store_for(u["name"]).weeks)
        except Exception:
            pass
    men = dict(MeningitisCase.objects.values_list("region").annotate(n=Count("id")).order_by())
    return [{"name": r["name"], "code": r["code"], "districts": r["districts"], "afp": afp.get(r["name"], 0),
             "weeks": weeks.get(r["name"], 0), "men": men.get(r["name"], 0)} for r in orgunits.ORG_UNITS]


@require_GET
@page
def start(request):
    """With every region (support and national administrators): Ghana at the top, which adds them all up, and the
    one they are looking at selected. Otherwise only the account's own region, fixed."""
    here, regions = unit(request), regions_snapshot()
    if sees_all(request):
        g = orgunits.national_unit()
        ghana = {"name": g["name"], "code": g["code"], "districts": g["districts"], "national": True,
                 "afp": sum(r["afp"] for r in regions), "weeks": len(idsr.store_for(orgunits.NATIONAL).weeks),
                 "men": sum(r["men"] for r in regions)}
        snap = {"selected": here["name"], "regions": [ghana] + regions}
    else:
        snap = {"selected": here["name"], "regions": [r for r in regions if r["name"] == here["name"]], "locked": True}
    data = snap | {"next": request.GET.get("next", ""), "support": is_support(request), "profile": services.profile(request.user)}
    return render(request, "core/start.html", {"logo": data_uri(EMBLEM), "data": page_data(data)})


@require_POST
@api
def region(request):
    """Support and national administrators: the region to work with for this sign-in. A regional account can only
    confirm its own."""
    try:
        name = str(body_json(request).get("region") or "")
    except ValueError:
        name = ""
    if sees_all(request):
        asked = orgunits.national_unit() if name.strip().lower() == orgunits.NATIONAL.lower() else orgunits.region_of(name)
        if not asked:
            return error(400, "Choose a region.")
        request.session["view"] = asked["name"]
        return ok({"region": asked["name"]})
    asked, mine = orgunits.region_of(name), unit(request)
    if not asked or asked["name"] != mine["name"]:
        return error(403, f"Your account is for {mine['name']} Region only.")
    return ok({"region": asked["name"]})
