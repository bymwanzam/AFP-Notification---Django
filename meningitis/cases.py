"""Adding, changing and deleting cases, with the checks the workbook's notes asked for, and a log of every change.

Every write is for one region (the request's org unit); the national view (Ghana) only reads.
"""
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from accounts import services as accounts

from . import linelist
from .linelist import BY_NAME, FIELDS, Reader
from .models import Case, CaseEdit

DELETE_WINDOW = timedelta(hours=24)


class FormErrors(Exception):
    def __init__(self, errors):
        super().__init__("Check the form.")
        self.errors = errors


def region_cases(unit, include_other=True):
    """The unit's cases (every region's in the national view). Cases living in another region are listed apart and
    left out of the region's reports, as the workbook kept them on their own sheet."""
    qs = Case.objects.all() if unit.get("national") else Case.objects.filter(region=unit["name"])
    return qs if include_other else qs.filter(other_region=False)


def search(qs, text):
    for word in (text or "").split():
        qs = qs.filter(Q(epid__icontains=word) | Q(last_name__icontains=word) | Q(first_name__icontains=word)
                       | Q(health_facility__icontains=word) | Q(community__icontains=word))
    return qs


def snapshot_of(case):
    return {f.name: linelist.display(case, f) for f in FIELDS}


def diff(before, after):
    return {k: [before.get(k, ""), v] for k, v in after.items() if str(before.get(k, "")) != str(v)}


def apply(reader, case, raw, *, create_subs=False, partial=False):
    """Set the case's fields from raw values ({field: value}). Returns (errors, warnings) as [(field, message)].
    partial: blank values leave the field as it is (imports never erase)."""
    errors, warnings, parsed = [], [], {}
    order = [f for f in FIELDS if f.kind != "subdistrict"] + [f for f in FIELDS if f.kind == "subdistrict"]
    for f in order:
        if f.name not in raw:
            continue
        v = raw[f.name]
        if partial and (v is None or str(v).strip() == ""):
            continue
        try:
            value, warn = reader.value(f, v, {**{k: getattr(case, k) for k in ("district", "residence_district")}, **parsed},
                                       create=create_subs)
        except ValueError as e:
            errors.append((f.name, str(e)))
            continue
        if warn:
            warnings.append((f.name, warn))
        parsed[f.name] = value
        setattr(case, f.name, value)
    unit = reader.unit
    case.region = unit["name"]
    case.country_code = case.country_code or "GHA"
    case.region_code = case.region_code or unit.get("epid", "")
    if case.district and not case.district_code:
        case.district_code = linelist.district_code(unit, case.district)
    if not case.year_code and (case.date_seen or case.date_onset):
        case.year_code = f"{(case.date_seen or case.date_onset).year % 100:02d}"
    for f in ("country_code", "region_code", "district_code", "year_code"):
        if not getattr(case, f):
            errors.append((f, "Give this part of the EPID number."))
    if not case.district:
        errors.append(("district", "Choose the reporting district."))
    if case.sequence_no is None and not any(e[0] in ("country_code", "region_code", "district_code", "year_code") for e in errors):
        case.sequence_no = linelist.next_sequence(case.country_code, case.region_code, case.district_code, case.year_code)
    if case.sequence_no in (None, 0):
        errors.append(("sequence_no", "Give the case number."))
    case.other_region = linelist.lives_elsewhere(case)
    if case.other_region and case.residence_subdistrict:
        warnings.append(("residence_subdistrict", "The patient lives in another region, so the residential sub-district is left out."))
        case.residence_subdistrict = None
    if not errors:
        e, w = case.problems()
        errors += e
        warnings += w
    if case.sequence_no and not errors:
        epid = Case.make_epid(case.country_code, case.region_code, case.district_code, case.year_code, case.sequence_no)
        if Case.objects.filter(epid=epid).exclude(pk=case.pk).exists():
            errors.append(("sequence_no", f"{epid} is already in the line list."))
    return errors, warnings


def save(unit, user, raw, case_id=None):
    """Add a case (case_id None) or change one. Returns (case, warnings); raises FormErrors."""
    if case_id:
        case = region_cases(unit).filter(pk=case_id).first()
        if not case:
            raise FormErrors([("", "This case is not in the region's line list.")])
        before = snapshot_of(case)
    else:
        case, before = Case(), {}
    errors, warnings = apply(Reader(unit), case, raw)
    if errors:
        raise FormErrors(errors)
    case.updated_by = user
    if not case_id:
        case.created_by = user
    try:
        with transaction.atomic():
            case.save()
            log(case, user, "edit" if case_id else "add", diff(before, snapshot_of(case)))
    except IntegrityError:
        raise FormErrors([("sequence_no", f"{case.epid} is already in the line list.")])
    return case, warnings


def log(case, user, action, changes):
    CaseEdit.objects.create(case=case, epid=case.epid, region=case.region, user=user, action=action, changes=changes)


def delete_problem(case, user):
    """Why this account may not delete the case, or None: support always; otherwise whoever entered it, within 24 hours."""
    if accounts.is_support(user):
        return None
    if case.created_by_id != user.id or timezone.now() - case.created_at > DELETE_WINDOW:
        return "Only the person who entered a case can delete it, within 24 hours. Mark it in Observations instead, or ask support."
    return None


def delete(case, user):
    with transaction.atomic():
        CaseEdit.objects.create(case=None, epid=case.epid, region=case.region, user=user, action="delete",
                                changes={k: [v, ""] for k, v in snapshot_of(case).items() if v not in ("", None)})
        case.delete()


def history(case):
    return [{"at": e.at, "user": e.user.username if e.user else "", "action": e.get_action_display(),
             "changes": [[BY_NAME[k].label if k in BY_NAME else k, *v] for k, v in e.changes.items()]}
            for e in case.edits.select_related("user")[:30]]
