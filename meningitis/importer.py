"""Bring cases in from a workbook: the regional meningitis line list (its "Outbreak linelist" and "Outbreak
linelist-other region" sheets, Table14 headers LastName ... FinalClassification) or this module's own download.

Rows are matched by EPID number: a new EPID is added, a known one updated. Blank cells never erase anything. Codes
written in other ways ("9 unknown", "Missing", "2 GND") are read back to the list's codes and reported. Rows with
no EPID number (the workbook's Filter = 0) are skipped, as the workbook's analyses skipped them.

The plan is worked out by doing the whole import inside a transaction that is then rolled back, so what you
review is exactly what Apply will do.
"""
import csv
import io
import re
from collections import Counter

from django.db import IntegrityError, transaction
from openpyxl import load_workbook

from . import choices as ch
from .cases import apply, diff, region_cases, snapshot_of
from .linelist import BY_HEADER, BY_NAME, Reader, clean_text, parse_int
from .models import Case, CaseEdit

EPID_RE = re.compile(r"^([A-Z]{2,3})-([A-Z0-9]{1,3})-([A-Z0-9]{1,3})-(\d{2})-(\d{1,5})$")
SHOWN = 200  # rows listed per group in the review


class Rollback(Exception):
    pass


def header_row(rows):
    """(index, {column: field name or epid/epiweek}) of the row holding the line list's headers, or None."""
    for i, r in enumerate(rows[:15]):
        cols = {}
        for j, h in enumerate(r):
            k = ch.key(h)
            if k in BY_HEADER:
                cols[j] = BY_HEADER[k].name
            elif k in ("epid", "epiweek"):
                cols[j] = k
        names = set(cols.values())
        if "epid" in names and len(names) >= 8 and ({"sequence_no", "last_name", "district"} & names):
            return i, cols
    return None


def read_tables(name, body):
    """[(sheet, first row number, header columns, rows)] for every sheet that is a line list."""
    if name.lower().endswith(".csv"):
        text = next((body.decode(enc) for enc in ("utf-8-sig", "cp1252") if _decodes(body, enc)), None)
        sheets = [("CSV", list(csv.reader(io.StringIO(text or ""))))]
    else:
        try:
            wb = load_workbook(io.BytesIO(body), read_only=True, data_only=True)
        except Exception:
            raise ValueError("This file could not be opened as an Excel workbook (.xlsx) or a CSV table.")
        sheets = [(ws.title, [list(r) for r in ws.iter_rows(values_only=True)]) for ws in wb.worksheets]
        wb.close()
    out = []
    for title, rows in sheets:
        found = header_row(rows)
        if found:
            i, cols = found
            out.append((title, i + 2, cols, rows[i + 1:]))
    if not out:
        raise ValueError("No line list found: the file needs a header row with EPID, NNNNN (or LastName), District "
                         "and the other columns of the meningitis line list.")
    return out


def _decodes(body, enc):
    try:
        body.decode(enc)
        return True
    except UnicodeDecodeError:
        return False


def epid_parts(raw, epid_text):
    """Fill CCC, RRR, DDD, YY and NNNNN from the EPID column when the parts are blank. Returns the EPID or None."""
    parts = ("country_code", "region_code", "district_code", "year_code", "sequence_no")
    if not all(clean_text(raw.get(p)) for p in parts):
        m = EPID_RE.match(clean_text(epid_text).upper().replace(" ", ""))
        if not m:
            return None
        for p, v in zip(parts, m.groups()):
            if not clean_text(raw.get(p)):
                raw[p] = v
    try:
        seq = parse_int(raw["sequence_no"])
    except ValueError:
        return None
    if not seq:
        return None
    yy = clean_text(raw["year_code"])
    yy = f"{int(float(yy)):02d}" if re.fullmatch(r"\d+(\.0+)?", yy) else yy
    raw["year_code"] = yy
    return Case.make_epid(clean_text(raw["country_code"]), clean_text(raw["region_code"]), clean_text(raw["district_code"]), yy, seq)


def run(unit, user, name, body, save=False):
    """The import plan; with save, the import itself."""
    tables = read_tables(name, body)
    plan = {"sheets": [t[0] for t in tables], "rows": 0, "added": [], "updated": [], "unchanged": 0, "skipped": 0,
            "errors": [], "warnings": [], "newSubdistricts": [], "counts": {}}
    warn_counts = Counter()
    try:
        with transaction.atomic():
            reader = Reader(unit)
            known_subs = set(reader.sub_ids)
            mine = region_cases(unit)
            for sheet, first, cols, rows in tables:
                for k, r in enumerate(rows):
                    raw = {f: r[j] for j, f in cols.items() if j < len(r)}
                    if not any(clean_text(v) for v in raw.values()):
                        continue
                    plan["rows"] += 1
                    where = {"sheet": sheet, "row": first + k}
                    epid = epid_parts(raw, raw.pop("epid", ""))
                    week = raw.pop("epiweek", None)
                    if not epid:
                        plan["skipped"] += 1
                        continue
                    case = Case.objects.filter(epid=epid).first()
                    if case and case.region != unit["name"]:
                        plan["errors"].append({**where, "epid": epid, "msgs": [f"{epid} is in {case.region} Region's line list."]})
                        continue
                    before = snapshot_of(case) if case else {}
                    case = case or Case()
                    try:
                        w = parse_int(week)
                        if w and 1 <= w <= 53 and not (clean_text(raw.get("date_seen")) or clean_text(raw.get("date_onset"))) \
                                and case.date_seen is None and case.date_onset is None:
                            case.epi_week, case.epi_year = w, 2000 + int(raw["year_code"])
                    except (ValueError, TypeError):
                        pass
                    errors, warnings = apply(reader, case, {f: v for f, v in raw.items() if f in BY_NAME},
                                             create_subs=True, partial=bool(before))
                    if errors:
                        plan["errors"].append({**where, "epid": epid, "msgs": [f"{BY_NAME[f].header if f in BY_NAME else f}: {m}" for f, m in errors]})
                        continue
                    for f, m in warnings:
                        warn_counts[f"{BY_NAME[f].header}: {m}"] += 1
                    is_new = case.pk is None
                    case.updated_by = user
                    if is_new:
                        case.created_by = user
                    try:
                        with transaction.atomic():  # a clash fails this row only
                            case.save()
                    except IntegrityError:
                        plan["errors"].append({**where, "epid": epid, "msgs": [f"{case.epid} clashes with a case already in the line list."]})
                        continue
                    changes = diff(before, snapshot_of(case))
                    if is_new:
                        CaseEdit.objects.create(case=case, epid=case.epid, region=case.region, user=user, action="import", changes=changes)
                        plan["added"].append({**where, "epid": case.epid, "id": case.pk})
                    elif changes:
                        CaseEdit.objects.create(case=case, epid=case.epid, region=case.region, user=user, action="import", changes=changes)
                        plan["updated"].append({**where, "epid": case.epid, "id": case.pk,
                                                "changes": [[BY_NAME[f].header, *v] for f, v in changes.items()]})
                    else:
                        plan["unchanged"] += 1
            plan["newSubdistricts"] = sorted(f"{s.name} ({s.district})" for i, s in reader.sub_ids.items() if i not in known_subs)
            plan["counts"] = {"added": len(plan["added"]), "updated": len(plan["updated"]), "errors": len(plan["errors"]),
                              "inRegion": mine.count()}
            if not save:
                raise Rollback()
    except Rollback:
        pass
    plan["warnings"] = [{"text": t, "n": n} for t, n in warn_counts.most_common(60)]
    for k in ("added", "updated", "errors"):
        plan[k] = plan[k][:SHOWN]
    plan["saved"] = save
    return plan
