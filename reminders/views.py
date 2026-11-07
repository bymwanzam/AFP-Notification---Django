"""The SMS reminders page: the district officers who get the AFP follow-up reminders, today's reminders and the log.

- Regional accounts add and change their own region's district officers, and see its reminders and log.
- The support account (the super admin) also holds the Fish Africa settings, and is the only one who sends from the
  page (Send now, test SMS); it works in any region it picks.
- National administrators read every region (the Ghana view) and change nothing.
The daily job (manage.py send_reminders) sends every region's reminders whoever is signed in."""
from functools import wraps

from django.conf import settings
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from core import orgunits
from core.access import api, body_json, error, is_support, ok, page, page_data, unit
from core.branding import letterhead, unit_label

from . import letsfish, service
from .models import DistrictContact

SUPPORT_ONLY = "Only the support account can change the SMS settings or send from this page. The daily job sends the reminders."
READ_ONLY = "The Ghana view only reads. District officers are added for one region."


def region_name(request):
    here = unit(request)
    return None if orgunits.is_national(here) else here["name"]


def handled(view):
    """A request's mistakes (ValueError) and Fish Africa's refusals (SmsError) as JSON."""
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except ValueError as e:
            return error(400, str(e))
        except letsfish.SmsError as e:
            return error(502, str(e))
    return wrapped


def support_only(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not is_support(request):
            return error(403, SUPPORT_ONLY)
        return view(request, *args, **kwargs)
    return wrapped


def in_region(view):
    """For one region: a regional account's own, or the one support picked (never the Ghana view)."""
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if region_name(request) is None:
            return error(403, READ_ONLY)
        return view(request, *args, **kwargs)
    return wrapped


def snapshot(request):
    here, region = unit(request), region_name(request)
    preview = service.run(region=region, dry_run=True)
    support = is_support(request)
    return {"region": here["name"], "regionLabel": unit_label(here), "national": region is None, "support": support,
            "regions": [r["name"] for r in orgunits.ORG_UNITS] if support else [],
            "districts": here["districts"] if region else [], "contacts": service.contacts_for(region),
            "sms": letsfish.status() if support else {"configured": letsfish.configured()}, "preview": preview, "due": len(service.due_cases(region=region)),
            "log": service.log_for(region), "today": timezone.localdate(),
            "rules": {"soon": settings.REMINDER_SOON_DAYS, "repeat": settings.REMINDER_REPEAT_DAYS}}


@require_GET
@page
def reminders_page(request):
    here = unit(request)
    # the Fish Africa settings panel is only in the page at all for the support account
    return render(request, "reminders/reminders.html",
                  letterhead(here) | {"data": page_data(snapshot(request)), "support": is_support(request)})


@require_GET
@api
def data(request):
    return ok(page_data(snapshot(request)))


@require_POST
@api
@support_only
@handled
def save_settings(request):
    """{appId, appSecret (blank keeps the saved one), senderId} or {clear: true}. The secret never comes back."""
    d = body_json(request)
    if d.get("clear"):
        letsfish.clear_settings()
    else:
        letsfish.save_settings(d.get("appId"), d.get("appSecret"), d.get("senderId"))
    return ok(page_data(snapshot(request)))


@require_POST
@api
@in_region
@handled
def save_contacts(request):
    """{rows: [{id?, district, name, phone, active}], delete: [id]} for the region."""
    region, d = region_name(request), body_json(request)
    here = unit(request)
    districts = {orgunits.bare(n): n for _, n in here["districts"]}
    mine = {c.id: c for c in DistrictContact.objects.filter(region=region)}
    problems = []
    for i, r in enumerate(d.get("rows") or [], 1):
        name = " ".join(str(r.get("name") or "").split())[:80]
        raw = str(r.get("district") or "")
        district = districts.get(orgunits.bare(raw)) if raw else ""
        try:
            number = letsfish.phone(r.get("phone"))
        except ValueError as e:
            problems.append(f"Row {i}: {e}")
            continue
        if not name:
            problems.append(f"Row {i}: give the officer's name.")
            continue
        if district is None:
            problems.append(f"Row {i}: {raw} is not a district of {region} Region.")
            continue
        c = mine.get(r.get("id")) or DistrictContact(region=region)
        if DistrictContact.objects.filter(region=region, district=district, phone=number).exclude(pk=c.pk).exists():
            problems.append(f"Row {i}: {number} is already a contact for {district or 'the whole region'}.")
            continue
        c.district, c.name, c.phone, c.active = district, name, number, bool(r.get("active", True))
        c.save()
    for cid in d.get("delete") or []:
        if cid in mine:
            mine[cid].delete()
    return ok(page_data(snapshot(request)) | {"problems": problems})


@require_POST
@api
@support_only
@in_region
@handled
def send_now(request):
    results = service.run(region=region_name(request), user=request.user)
    return ok(page_data(snapshot(request)) | {"results": page_data(results)})


@require_POST
@api
@support_only
@in_region
@handled
def send_test(request):
    number = letsfish.phone(body_json(request).get("phone"))
    letsfish.send([number], f"Test from the GHS surveillance app ({unit(request)['name']} Region): SMS reminders are working.")
    return ok({"sent": number})
