"""The meningitis module: the line list (entry, editing, upload, downloads), the region's sub-districts and
thresholds, and the reports. Everything works for the request's org unit (core.access.unit); the national view
(Ghana) reads every region and changes nothing.
"""
from functools import wraps

from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from core import orgunits
from core.access import api, body_json, error, is_support, ok, page, page_data, unit
from core.branding import letterhead, unit_label

from . import cases, exports, importer, linelist, reports
from .models import Case, SubDistrict, ThresholdConfig

XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
READ_ONLY = "The Ghana view only reads. Pick a region on the start page to add or change cases."
PER_PAGE = 50


def men_call(view):
    """Errors as JSON: a bad request (ValueError), a form to correct (FormErrors), anything else."""
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except cases.FormErrors as e:
            return error(400, "Check the form.", errors=[{"field": f, "msg": m} for f, m in e.errors])
        except ValueError as e:
            return error(400, str(e))
        except Exception as e:
            return error(500, f"Could not read the line list: {e}" if request.method == "GET" else f"Save failed: {e}")
    return wrapped


def writes(view):
    """Only for a region (not the national view)."""
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if orgunits.is_national(unit(request)):
            return error(403, READ_ONLY)
        return view(request, *args, **kwargs)
    return wrapped


def attachment(body, ctype, name):
    resp = HttpResponse(body, content_type=ctype)
    resp["Content-Disposition"] = f'attachment; filename="{name}"'
    return resp


def subdistricts(here):
    qs = SubDistrict.objects.all() if orgunits.is_national(here) else SubDistrict.objects.filter(region=here["name"])
    return [{"id": s.id, "region": s.region, "district": s.district, "name": s.name, "population": s.population} for s in qs]


def snapshot(request):
    here = unit(request)
    today = timezone.localdate().isocalendar()
    years = sorted({y for y in cases.region_cases(here).values_list("epi_year", flat=True).distinct() if y} | {today[0]})
    return {"region": here["name"], "regionLabel": unit_label(here), "national": orgunits.is_national(here),
            "epidRegion": here.get("epid", ""), "districts": here["districts"], "schema": linelist.schema(),
            "subdistricts": subdistricts(here), "cfg": reports.cfg_dict(ThresholdConfig.for_region(here["name"])),
            "canWrite": not orgunits.is_national(here), "support": is_support(request), "user": request.user.username,
            "years": years, "today": {"year": today[0], "week": today[1]}, "reports": reports.KINDS,
            "count": cases.region_cases(here).count()}


# ---------- page and reads ----------
@require_GET
@page
def men_page(request):
    here = unit(request)
    return render(request, "meningitis/meningitis.html", letterhead(here) | {"data": page_data(snapshot(request))})


@require_GET
@api
@men_call
def data(request):
    return ok(snapshot(request))


def listed(request):
    """The line list with the page's filters."""
    here, g = unit(request), request.GET
    qs = cases.search(cases.region_cases(here), g.get("q"))
    if g.get("year"):
        ctx = reports.Context(here, g)
        qs = qs.filter(ctx.period.q)
    area = "region" if orgunits.is_national(here) else "district"
    for param, field in (("district", area), ("classification", "final_classification"), ("outcome", "outcome")):
        if g.get(param):
            qs = qs.filter(**{field: "" if g[param] == "none" else g[param]})
    if g.get("other") in ("0", "1"):
        qs = qs.filter(other_region=g["other"] == "1")
    return qs


@require_GET
@api
@men_call
def case_list(request):
    qs = listed(request).select_related("reporting_subdistrict", "residence_subdistrict")
    pages = Paginator(qs, PER_PAGE)
    p = pages.get_page(request.GET.get("page") or 1)
    return ok({"rows": [linelist.as_row(c) for c in p.object_list], "total": pages.count, "page": p.number,
               "pages": pages.num_pages, "other": cases.region_cases(unit(request)).filter(other_region=True).count()})


@require_GET
@api
@men_call
def case_detail(request):
    try:
        case = cases.region_cases(unit(request)).get(pk=int(request.GET.get("id", "")))
    except (ValueError, Case.DoesNotExist):
        return error(404, "This case is not in the region's line list.")
    return ok({"id": case.id, "epid": case.epid, "fields": linelist.as_form(case), "history": cases.history(case),
               "canDelete": cases.delete_problem(case, request.user) is None,
               "created": case.created_at, "createdBy": case.created_by.username if case.created_by else ""})


@require_GET
@api
@men_call
def next_epid(request):
    here, g = unit(request), request.GET
    parts = [g.get(k, "").strip().upper() for k in ("country", "region", "district", "year")]
    parts[0] = parts[0] or "GHA"
    parts[1] = parts[1] or here.get("epid", "")
    if not all(parts):
        return ok({"sequence": None, "epid": ""})
    seq = linelist.next_sequence(*parts)
    return ok({"sequence": seq, "epid": Case.make_epid(*parts, seq)})


@require_GET
@api
@men_call
def report(request):
    return ok(reports.build(unit(request), request.GET))


@require_GET
@api
@men_call
def report_xlsx(request):
    rep = reports.build(unit(request), request.GET)
    return attachment(exports.report_xlsx(rep), XLSX_TYPE, f"Meningitis {rep['name']} - {rep['region']}.xlsx")


@require_GET
@api
@men_call
def linelist_xlsx(request):
    here, names = unit(request), request.GET.get("names") == "1"
    title = f"MENINGITIS LINE LIST – {unit_label(here).upper()} – downloaded {timezone.localtime():%d/%m/%Y %H:%M}"
    body = exports.linelist_xlsx(listed(request), title, names=names)
    return attachment(body, XLSX_TYPE, f"Meningitis line list - {here['name']}{'' if names else ' (no names)'}.xlsx")


# ---------- writes ----------
@require_POST
@api
@writes
@men_call
def save_case(request):
    d = body_json(request)
    case, warnings = cases.save(unit(request), request.user, d.get("fields") or {}, d.get("id"))
    return ok({"id": case.id, "epid": case.epid, "warnings": [{"field": f, "msg": m} for f, m in warnings]})


@require_POST
@api
@writes
@men_call
def delete_case(request):
    try:
        case = cases.region_cases(unit(request)).get(pk=int(body_json(request).get("id")))
    except (TypeError, ValueError, Case.DoesNotExist):
        return error(404, "This case is not in the region's line list.")
    problem = cases.delete_problem(case, request.user)
    if problem:
        return error(403, problem)
    cases.delete(case, request.user)
    return ok({"deleted": case.epid})


@require_POST
@api
@writes
@men_call
def import_file(request):
    plan = importer.run(unit(request), request.user, request.GET.get("name", "upload.xlsx"), request.body,
                        save=request.GET.get("apply") == "1")
    return ok(plan)


@require_POST
@api
@writes
@men_call
def save_subdistricts(request):
    """{rows: [{id?, district, name, population}], delete: [id]}: the region's sub-districts and populations."""
    here, d = unit(request), body_json(request)
    reader = linelist.Reader(here)
    mine = {s.id: s for s in SubDistrict.objects.filter(region=here["name"])}
    problems = []
    for i, r in enumerate(d.get("rows") or [], 1):
        name = linelist.clean_text(r.get("name"), 80)
        try:
            district = reader.district(r.get("district"))
            pop = linelist.parse_int(r.get("population"))
        except ValueError as e:
            problems.append(f"Row {i}: {e}")
            continue
        if not name:
            problems.append(f"Row {i}: give the sub-district's name.")
            continue
        s = mine.get(r.get("id")) or SubDistrict(region=here["name"])
        clash = SubDistrict.objects.filter(region=here["name"], district=district, name__iexact=name).exclude(pk=s.pk).exists()
        if clash:
            problems.append(f"Row {i}: {name} is already a sub-district of {district}.")
            continue
        s.district, s.name, s.population = district, name, pop
        s.save()
    for sid in d.get("delete") or []:
        s = mine.get(sid)
        if s and Case.objects.filter(Q(reporting_subdistrict=s) | Q(residence_subdistrict=s)).exists():
            problems.append(f"{s.name} has cases, so it stays. Move its cases to another sub-district first.")
        elif s:
            s.delete()
    return ok({"subdistricts": subdistricts(here), "problems": problems})


@require_POST
@api
@writes
@men_call
def save_thresholds(request):
    here, d = unit(request), body_json(request)
    cfg = ThresholdConfig.for_region(here["name"])
    try:
        alert, epidemic = float(d["alertRate"]), float(d["epidemicRate"])
        cutoff, ac, ec, start = (int(d[k]) for k in ("cutoff", "alertCases", "epidemicCases", "seasonStart"))
    except (KeyError, TypeError, ValueError):
        raise ValueError("Give every threshold as a number.")
    if not (0 < alert < epidemic) or not (0 < ac < ec) or cutoff < 0 or not 1 <= start <= 53:
        raise ValueError("The alert threshold must be above 0 and below the epidemic threshold; the season starts in weeks 1 to 53.")
    cfg.alert_rate, cfg.epidemic_rate, cfg.small_pop_cutoff = alert, epidemic, cutoff
    cfg.small_pop_alert_cases, cfg.small_pop_epidemic_cases, cfg.season_start_week = ac, ec, start
    cfg.save()
    return ok({"cfg": reports.cfg_dict(cfg)})
