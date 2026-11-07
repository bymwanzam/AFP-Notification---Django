"""The AFP 60-day follow-up module: alerts and case list, new-case entry, editing a case within 24 hours, update
from file, downloads and the district/region report. Everything works for the request's region (core.access.unit)."""
import json
from datetime import datetime
from functools import wraps

from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from core import orgunits
from core.access import api, body_json, error, is_support, ok, page, page_data, scope, sees_all, unit
from core.branding import letterhead

from . import cases, register
from .register import Register, read_table
from .report import report_xlsx

XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def xlsx_path():
    return settings.AFP_REGISTER


def register_call(view):
    """The register's errors as JSON: open in Excel (PermissionError), a bad request (ValueError), anything else."""
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except PermissionError:
            return error(409, f"{xlsx_path().name} is open in Excel. Close it and try again.")
        except ValueError as e:
            return error(400, str(e))
        except Exception as e:
            return error(500, f"Could not read the register: {e}" if request.method == "GET" else f"Save failed: {e}")
    return wrapped


def attachment(body, ctype, name):
    resp = HttpResponse(body, content_type=ctype)
    resp["Content-Disposition"] = f'attachment; filename="{name}"'
    return resp


def form_errors(errors):
    return error(400, "Check the form.", errors=[{"col": c, "msg": m} for c, m in errors])


# ---------- editing a case within 24 hours of entry: regional accounts only ----------
def editable(request, here):
    """{EPID: when its edit window closes} for the cases this account may still edit or delete; "always" for every
    case when signed in as support."""
    if is_support(request):
        return {str(c.get("epid")).strip().upper(): "always" for c in cases.region_cases(xlsx_path(), here) if c.get("epid")}
    if sees_all(request) or orgunits.is_national(here):
        return {}
    now = datetime.now()
    return {epid: until.isoformat(timespec="minutes") for epid, e in register.load_entries(xlsx_path()).items()
            if e.get("region") == here["name"] and (until := register.edit_until(e)) > now}


def edit_problem(request, epid, here):
    """Why this account may not edit or delete the case, or None."""
    if is_support(request):
        return None if epid in Register(xlsx_path()).epids() else f"There is no case {epid}."
    if sees_all(request):
        return "Only regional accounts can edit or delete a case, within 24 hours of entering it."
    e = register.load_entries(xlsx_path()).get(epid)
    if not e:
        return "This case was not entered in this app, so it can't be edited or deleted here. Use Update from file to change it."
    if e.get("region") != here["name"]:
        return f"{epid} was entered for {e.get('region')} Region."
    if register.edit_until(e) <= datetime.now():
        return f"{epid} was entered more than 24 hours ago, so it can no longer be edited or deleted here. Use Update from file to change it."
    return None


def log_added(request, reg, rows):
    """Note who entered new cases and when, for the 24-hour edit window."""
    ef, df = reg.field_like("epid #"), reg.field_like("district or")
    if not ef:
        return
    register.log_entries(xlsx_path(), [(v[ef.col], orgunits.case_region(v.get(df.col) if df else None)["name"], request.user.username)
                                       for v in rows if v.get(ef.col)])


def public(plan):
    return {k: v for k, v in plan.items() if not k.startswith("_")}


# ---------- pages and reads ----------
@require_GET
@page
def dashboard(request):
    here = unit(request)
    try:
        data = cases.snapshot(xlsx_path(), unit=here, editable=editable(request, here))
    except PermissionError:
        return HttpResponse(f"{xlsx_path().name} is open in Excel. Close it and reload this page.", status=409, content_type="text/plain")
    return render(request, "afp/dashboard.html", letterhead(here) | {"data": page_data(data)})


@require_GET
@api
@register_call
def data(request):
    here = unit(request)
    return ok(cases.snapshot(xlsx_path(), unit=here, editable=editable(request, here)))


@require_GET
@api
@register_call
def schema(request):
    """The New case form offers only this region and its districts (in the Ghana view, every region)."""
    here, sc = unit(request), Register(xlsx_path()).schema()
    if not orgunits.is_national(here):
        sc["regions"] = [r for r in sc["regions"] if r["name"] == here["name"]]
        sc["homeRegion"] = here["name"]
    return ok(sc)


@require_GET
@api
@register_call
def next_epid(request):
    here = unit(request)
    region = request.GET.get("region", "") if orgunits.is_national(here) else here["name"]
    return ok({"epid": Register(xlsx_path()).next_epid(request.GET.get("code", ""), region)})


@require_GET
@api
@register_call
def case(request):
    here, epid = unit(request), request.GET.get("epid", "").strip().upper()
    problem = edit_problem(request, epid, here)
    if problem:
        return error(403, problem)
    reg, entry = Register(xlsx_path()), register.load_entries(xlsx_path()).get(epid)
    fields, df = reg.case_values(epid), reg.field_like("district or")
    return ok({"epid": epid, "fields": fields,
               "region": orgunits.case_region(fields.get(df.col) if df else None)["name"],
               "until": None if is_support(request) or not entry else register.edit_until(entry).isoformat(timespec="minutes")})


@require_GET
@api
@register_call
def register_xlsx(request):
    here = unit(request)
    return attachment(Register(xlsx_path()).export_xlsx(scope(request)), XLSX_TYPE, f"AFP cases for update - {here['name']}.xlsx")


# ---------- writes ----------
@require_POST
@api
@register_call
def new_case(request):
    raw = {int(k): v for k, v in body_json(request)["fields"].items()}
    reg = Register(xlsx_path())
    values, errors = reg.prepare_new(raw)
    errors += [e for e in [reg.district_error(values, scope(request))] if e]
    if errors:
        return form_errors(errors)
    row = reg.append(values)
    epid, name = reg.field_like("epid #"), reg.field_like("patient name")
    log_added(request, reg, [values])
    return ok({"row": row, "epid": values.get(epid.col) if epid else None, "name": values.get(name.col) if name else None})


@require_POST
@api
@register_call
def import_file(request):
    header, rows = read_table(request.GET.get("name", "upload.csv"), request.body)
    reg = Register(xlsx_path())
    plan = reg.plan_import(header, rows, add_new=request.GET.get("add") == "1", region=scope(request))
    if request.GET.get("apply") == "1":
        plan["addedRows"] = reg.apply_import(plan)
        log_added(request, reg, plan["_adds"])
    return ok(public(plan))


@require_POST
@api
@register_call
def update_case(request):
    here, d = unit(request), body_json(request)
    epid = str(d.get("epid") or "").strip().upper()
    problem = edit_problem(request, epid, here)
    if problem:
        return error(403, problem)
    reg = Register(xlsx_path())
    raw = {int(k): v for k, v in d["fields"].items()}
    values, errors = reg.prepare_edit(epid, raw)
    errors += [e for e in [reg.district_error(values, scope(request))] if e]
    if errors:
        return form_errors(errors)
    reg.update_case(epid, values)
    new_id = str(values.get(reg.field_like("epid #").col) or epid).strip().upper()
    register.rename_entry(xlsx_path(), epid, new_id)  # a corrected EPID # keeps its 24-hour window
    return ok({"epid": new_id})


@require_POST
@api
@register_call
def delete_case(request):
    here, epid = unit(request), str(body_json(request).get("epid") or "").strip().upper()
    problem = edit_problem(request, epid, here)
    if problem:
        return error(403, problem)
    Register(xlsx_path()).delete_case(epid)
    register.drop_entry(xlsx_path(), epid)
    return ok({"deleted": epid})


@require_POST
@api
@register_call
def report(request):
    rep = json.loads(request.body)
    return attachment(report_xlsx(rep, unit(request)), XLSX_TYPE, "AFP cases by district.xlsx")
