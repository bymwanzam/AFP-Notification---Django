"""The AFP register's cases as the AFP page sees them: read from the workbook, limited to a region (or every region
for the national view), with each case's edit window when the signed-in account may still change it."""
import re
from datetime import date, datetime
from pathlib import Path

from django.conf import settings
from openpyxl import load_workbook

from core import orgunits
from core.branding import org_for, unit_label

# Upper East report rows, in the order of the regional summary sheet, keyed by the register's district code column.
# Other regions use their org unit districts.
REPORT_DISTRICTS = [
    ("BAW", "Bawku Municipal"), ("BKW", "Bawku West"), ("BID", "Binduri"), ("BOE", "Bolgatanga East"),
    ("BOG", "Bolgatanga Municipal"), ("BON", "Bongo Municipal"), ("BUI", "Builsa North Municipal"),
    ("BUS", "Builsa South"), ("GAR", "Garu"), ("KND", "Kassena-Nankana Municipal"), ("KNW", "Kassena-Nankana West"),
    ("NAB", "Nabdam"), ("PUS", "Pusiga"), ("TAL", "Talensi"), ("TEP", "Tempane"),
]

FIELDS = {
    "sn": "sn", "epid": "epid #", "name": "patient name", "sex": "patient sex",
    "dob": "date of birth", "district": "reporting district", "week": "epid. week",
    "onset": "onset", "outcome": "outcome", "report": "report availability",
    "reportDate": "date report received", "lab": "laboratory feedback", "remarks": "remarks", "code": "epid. code",
}


def clean(text):
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def plain(v):
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, str):
        return re.sub(r"\s+", " ", v).strip() or None
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def load_cases(xlsx):
    wb = load_workbook(xlsx, read_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    hdr_idx = next(i for i, r in enumerate(rows[:10]) if any("epid #" in clean(c) for c in r))
    headers = [clean(h) for h in rows[hdr_idx]]
    idx = {k: next((i for i, h in enumerate(headers) if t in h), None) for k, t in FIELDS.items()}
    cases = []
    for r in rows[hdr_idx + 1:]:
        if idx["epid"] is not None and r[idx["epid"]]:
            cases.append({k: plain(r[i]) if i is not None and i < len(r) else None for k, i in idx.items()})
    return cases


# ---------- one region at a time: the signed-in account's ----------
def report_districts(unit):
    return REPORT_DISTRICTS if unit["name"] == orgunits.DEFAULT_REGION else [tuple(d) for d in unit["districts"]]


def in_region(case, unit):
    """Whether a case's reporting district is in the region; cases with no known district stay with Upper East."""
    return orgunits.is_national(unit) or orgunits.case_region(case.get("district"))["name"] == unit["name"]


def region_cases(xlsx, unit):
    """The unit's cases. In the national view every case, with its code set to its region's code, so the
    report counts cases by region the way a region's report counts them by district."""
    cases = [c for c in load_cases(xlsx) if in_region(c, unit)]
    if orgunits.is_national(unit):
        for c in cases:
            r = orgunits.case_region(c.get("district"))
            c["code"], c["region"] = r["code"], r["name"]
    return cases


def snapshot(xlsx=None, live=True, unit=None, editable=None):
    """editable: {EPID: until} for the cases the signed-in account may still edit or delete (in the app)."""
    xlsx, unit = Path(xlsx or settings.AFP_REGISTER), unit or orgunits.current_region()
    cases = region_cases(xlsx, unit)
    for c in cases:
        until = (editable or {}).get(str(c.get("epid") or "").strip().upper())
        if until:
            c["editUntil"] = until
    return {"generated": datetime.now().isoformat(timespec="seconds"), "source": xlsx.name,
            "live": live, "appUrl": "/", "region": unit_label(unit), "regionName": unit["name"],
            "national": orgunits.is_national(unit),
            "org": org_for(unit), "districts": report_districts(unit), "cases": cases}
