"""The Weekly IDSR module: data entry, upload, fetch from DHIMS2 and the weekly epidemiological bulletin.

Each region has its own store (store.store_for); Ghana has its own too, whose rows are the regions. A page names
its region on every call (?region=), and it must be the account's own; support and national administrators get the
region they picked on the start page.
"""
from functools import wraps

from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from core import orgunits
from core.access import OtherRegion, api, body_json, error, is_support, ok, page, page_data, sees_all, unit
from core.branding import EMBLEM, RHD, data_uri, letterhead

from . import bulletin, dhims2
from . import store as idsr

XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
LOCKED = "The IDSR data file for this region is open in Excel. Close it and try again."


def region_store(request):
    here = unit(request)
    asked = request.GET.get("region", "")
    if not sees_all(request) and asked and (orgunits.region_of(asked) or {}).get("name") != here["name"]:
        raise OtherRegion()
    return idsr.store_for(here["name"])


def year_week(request):
    try:
        return idsr.check_week(request.GET.get("year", ""), request.GET.get("week", ""))
    except ValueError:
        raise ValueError("Choose a week.")


def store_call(view):
    """Calls on a region's store: `store` is passed in; its errors come back as JSON."""
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        store = region_store(request)  # OtherRegion is answered by @api
        try:
            return view(request, store, *args, **kwargs)
        except PermissionError:
            return error(409, LOCKED)
        except ValueError as e:
            return error(400, str(e))
        except Exception as e:
            return error(500, f"Could not read the IDSR data: {e}" if request.method == "GET" else f"Save failed: {e}")
    return wrapped


def attachment(body, ctype, name):
    resp = HttpResponse(body, content_type=ctype)
    resp["Content-Disposition"] = f'attachment; filename="{name}"'
    return resp


def public(plan):
    return {k: v for k, v in plan.items() if not k.startswith("_")}


def snapshot(store):
    return {"data": bulletin.snapshot(store)}


# ---------- pages and reads ----------
@require_GET
@page
def idsr_page(request):
    try:
        store = region_store(request)
        data = bulletin.snapshot(store)
    except OtherRegion:
        return HttpResponse(f"Your account is for {unit(request)['name']} Region only.", status=403, content_type="text/plain")
    except PermissionError:
        return HttpResponse(LOCKED, status=409, content_type="text/plain")
    return render(request, "idsr/idsr.html", letterhead(unit(request)) | {
        "emblem": data_uri(EMBLEM), "rhd": data_uri(RHD), "data": page_data(data)})


@require_GET
@api
@store_call
def data(request, store):
    return ok(bulletin.snapshot(store))


@require_GET
@api
@store_call
def form_xlsx(request, store):
    y, w = year_week(request)
    return attachment(store.form_xlsx(y, w), XLSX_TYPE, f"IDSR weekly form {store.code} wk{w:03d} {y}.xlsx")


@require_GET
@api
@store_call
def week_csv(request, store):
    y, w = year_week(request)
    return attachment(store.week_csv(y, w), "text/csv; charset=utf-8", f"IDSR week {w:03d} {y} {store.code}.csv")


@require_GET
@api
@store_call
def store_xlsx(request, store):
    if not store.path.exists():
        raise ValueError("No weeks have been saved for this region yet.")
    return attachment(store.path.read_bytes(), XLSX_TYPE, store.path.name)


# ---------- writes ----------
@require_POST
@api
@store_call
def save_week(request, store):
    req = body_json(request)
    store.put_week(req.get("year"), req.get("week"), req.get("meta"), req.get("counts"))
    return ok(snapshot(store))


@require_POST
@api
@store_call
def delete_week(request, store):
    if not is_support(request):
        return error(403, "Only the support account can delete a week.")
    req = body_json(request)
    store.delete_week(req.get("year"), req.get("week"))
    return ok(snapshot(store))


@require_POST
@api
@store_call
def import_file(request, store):
    plan = store.plan_import(*idsr.read_upload(request.GET.get("name", "upload.csv"), request.body))
    out = public(plan)
    if request.GET.get("apply") == "1":
        store.apply_import(plan)
        out["data"] = bulletin.snapshot(store)
    return ok(out)


@require_POST
@api
@store_call
def save_settings(request, store):
    store.set_settings(body_json(request))
    return ok(snapshot(store))


@require_POST
@api
@store_call
def image(request, store):
    bulletin.set_image(request.GET.get("slot", ""), request.body, store.code)
    return ok(snapshot(store))


# ---------- DHIMS2 ----------
@require_GET
@api
@store_call
def dhims2_config(request, store):
    return ok(dhims2.public_config())


@require_GET
@api
@store_call
def dhims2_datasets(request, store):
    return ok({"dataSets": dhims2.data_sets()})


@require_GET
@api
@store_call
def dhims2_elements(request, store):
    return ok(dhims2.elements(request.GET.get("ds", "")))


@require_POST
@api
@store_call
def dhims2_connect(request, store):
    req = body_json(request)
    cfg = dhims2.connect(req.get("url"), req.get("token"), bool(req.get("remember")))
    return ok(cfg | {"dataSets": dhims2.data_sets()})


@require_POST
@api
@store_call
def dhims2_forget(request, store):
    return ok(dhims2.forget())


@require_POST
@api
@store_call
def dhims2_mapping(request, store):
    req = body_json(request)
    return ok({"mapping": dhims2.save_mapping(req.get("ds"), req.get("mapping"))})


@require_POST
@api
@store_call
def dhims2_fetch(request, store):
    """Fetches again on apply, the way an upload is sent again, so what is saved is what DHIMS2 has now."""
    req = body_json(request)
    plan = dhims2.fetch(store, req.get("ds"), req.get("mapping"), req.get("year"), req.get("from"), req.get("to"))
    out = public(plan)
    if req.get("apply"):
        store.apply_import(plan)
        out["data"] = bulletin.snapshot(store)
    return ok(out)
