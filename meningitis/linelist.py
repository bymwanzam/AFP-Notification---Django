"""The line list's columns: what each is called in the workbook (Table14 headers), in the form and in downloads, and
how a typed or uploaded value becomes a Case field. One list, so the form, the API, the import and the downloads
always agree.
"""
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from django.db.models import Max

from core import orgunits

from . import choices as ch
from .models import Case, SubDistrict


@dataclass(frozen=True)
class Field:
    name: str          # Case field
    header: str        # the workbook's column (Table14), also used in downloads
    label: str         # the form's label (the workbook's heading)
    group: str
    kind: str          # text, long, int, date, choice, district, subdistrict, epid
    list: str = ""     # choices list for kind "choice"
    pii: bool = False
    help: str = ""


FIELDS = [
    Field("last_name", "LastName", "Surname", "Patient", "text", pii=True),
    Field("first_name", "FirstName", "Other names", "Patient", "text", pii=True),
    Field("country_code", "CCC", "Country", "EPID number", "epid"),
    Field("region_code", "RRR", "Region", "EPID number", "epid"),
    Field("district_code", "DDD", "District", "EPID number", "epid"),
    Field("year_code", "YY", "Year", "EPID number", "epid"),
    Field("sequence_no", "NNNNN", "Number", "EPID number", "int", help="Next free number for the district and year."),
    Field("health_facility", "HealthFacility", "Reporting health facility", "Place", "text"),
    Field("reporting_subdistrict", "Subdistrict", "Reporting sub-district", "Place", "subdistrict"),
    Field("residence_subdistrict", "Subdistrict2", "Residential sub-district", "Place", "subdistrict",
          help="Used for the sub-district thresholds. Leave blank if the patient lives in another region."),
    Field("district", "District", "Reporting district", "Place", "district"),
    Field("residence_district", "DistrictOrigin", "District of residence", "Place", "anydistrict"),
    Field("community", "Village", "Community of residence", "Place", "text"),
    Field("age_months", "AgeMonths", "Age in months (under 1 year)", "Person", "int"),
    Field("age_years", "AgeYears", "Age in years (1 year and over)", "Person", "int"),
    Field("sex", "Sex", "Sex", "Person", "choice", "sex"),
    Field("date_seen", "DateConsultation", "Date seen at health facility", "Time", "date",
          help="Sets the epi week."),
    Field("date_onset", "Onset", "Date of onset", "Time", "date"),
    Field("fever", "Fever", "Fever", "Signs and symptoms", "choice", "yesno"),
    Field("neck_stiffness", "NeckStiff", "Neck stiffness", "Signs and symptoms", "choice", "yesno"),
    Field("headache", "Headache", "Headache", "Signs and symptoms", "choice", "yesno"),
    Field("other_symptoms", "Other", "Other signs (specify)", "Signs and symptoms", "text"),
    Field("outcome", "Outcome", "Outcome", "Signs and symptoms", "choice", "outcome"),
    Field("vaccinated", "Immu", "Vaccinated?", "Vaccination", "choice", "yesno"),
    Field("vaccine_1", "Vaccine1", "If yes, which vaccine 1", "Vaccination", "choice", "vaccine"),
    Field("vaccine_2", "Vaccine2", "If yes, which vaccine 2", "Vaccination", "choice", "vaccine"),
    Field("pcv", "PCV", "Pneumococcal vaccine (PCV)", "Vaccination", "choice", "pcv"),
    Field("other_vaccine", "VaccineOther", "Other vaccine (specify)", "Vaccination", "text"),
    Field("specimen_collected", "SpecimenCollected", "Specimen collected", "Laboratory", "choice", "yesno"),
    Field("date_specimen", "DateSpecimenCollected", "Date specimen collected", "Laboratory", "date"),
    Field("gram", "Gram", "Gram stain", "Laboratory", "choice", "gram"),
    Field("rapid_test", "TDR", "Rapid test (TDR)", "Laboratory", "choice", "rapid"),
    Field("latex", "Latex", "Latex", "Laboratory", "choice", "latex"),
    Field("culture", "Culture", "Culture", "Laboratory", "choice", "pathogen"),
    Field("pcr", "PCR", "PCR", "Laboratory", "choice", "pathogen"),
    Field("final_result", "FinalResult", "Final lab result", "Laboratory", "choice", "pathogen"),
    Field("final_classification", "FinalClassification", "Final classification", "Classification", "choice",
          "classification"),
    Field("observations", "Observations", "Observations", "Classification", "long",
          help='When you change a case, note "Updated [date]" and why.'),
]
BY_NAME = {f.name: f for f in FIELDS}
BY_HEADER = {ch.key(f.header): f for f in FIELDS}
EXTRA_HEADERS = {"epid": "EPID", "epiweek": "Epi Week"}  # read on import, written in downloads


def schema():
    """The form's fields and code lists, for the page."""
    return {"fields": [f.__dict__ for f in FIELDS], "lists": {n: ch.as_options(n) for n in ch.LISTS}}


# ---------- reading a value ----------
def parse_date(v):
    if v in (None, ""):
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, (int, float)) and 20000 < v < 80000:  # an Excel serial date
        return date(1899, 12, 30) + timedelta(days=int(v))
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"“{s}” is not a date (use dd/mm/yyyy)")


def parse_int(v):
    if v in (None, ""):
        return None
    if isinstance(v, float):
        if not v.is_integer():
            raise ValueError(f"“{v}” is not a whole number")
        return int(v)
    s = str(v).strip()
    if not re.fullmatch(r"\d+(\.0+)?", s):
        raise ValueError(f"“{s}” is not a whole number")
    return int(float(s))


def clean_text(v, limit=200):
    return re.sub(r"\s+", " ", str(v if v is not None else "")).strip()[:limit]


class Reader:
    """Turns raw values (from the form or a workbook) into Case values for one region."""

    def __init__(self, unit):
        self.unit = unit
        self.districts = {orgunits.bare(n): n for _, n in unit["districts"]}
        self.subs = {(s.district, s.name.lower()): s for s in SubDistrict.objects.filter(region=unit["name"])}
        self.sub_ids = {s.id: s for s in self.subs.values()}

    def district(self, v):
        """The region's district called v (any spelling), or raise."""
        name = self.districts.get(orgunits.bare(v))
        if not name:
            raise ValueError(f"“{clean_text(v)}” is not a district of {self.unit['name']} Region")
        return name

    def subdistrict(self, v, district=None, create=False):
        """A sub-district by id (form) or by name (workbook); a new name is added when `create`."""
        if v in (None, ""):
            return None
        if isinstance(v, int) or str(v).isdigit():
            s = self.sub_ids.get(int(v))
            if not s:
                raise ValueError("Choose a sub-district from the list")
            return s
        name = clean_text(v, 80)
        if district:
            s = self.subs.get((district, name.lower()))
        else:
            found = [s for (d, n), s in self.subs.items() if n == name.lower()]
            s = found[0] if len(found) == 1 else None
        if s or not create or not district:
            if not s:
                raise ValueError(f"“{name}” is not a sub-district on file" + ("" if district else " (give its district)"))
            return s
        s = SubDistrict.objects.create(region=self.unit["name"], district=district, name=name)
        self.subs[(district, name.lower())] = s
        self.sub_ids[s.id] = s
        return s

    def value(self, f, raw, row=None, create=False):
        """(value, warning). Raises ValueError when raw can't be read."""
        if f.kind == "choice":
            code, problem = ch.normalise(f.list, raw)
            if problem:
                raise ValueError(problem)
            shown = ch.label(f.list, code)
            changed = code and ch.key(shown) != ch.key(raw) and ch.key(raw) != ch.key(code)
            return code or "", f"“{clean_text(raw)}” read as {shown}" if changed else None
        if f.kind == "date":
            return parse_date(raw), None
        if f.kind == "int":
            return parse_int(raw), None
        if f.kind == "epid":
            s = clean_text(raw, 3).upper()
            if s and not re.fullmatch(r"[A-Z0-9]{1,3}", s):
                raise ValueError(f"“{s}” must be letters or digits")
            return s, None
        if f.kind == "district":
            return (self.district(raw) if clean_text(raw) else ""), None
        if f.kind == "anydistrict":
            s = clean_text(raw, 80)
            if not s:
                return "", None
            r, d = orgunits.district_region(s)
            return (d[1] if d else s), None if d else f"District of residence “{s}” is not in the org unit list"
        if f.kind == "subdistrict":
            row = row or {}
            district = row.get("district") if f.name == "reporting_subdistrict" else row.get("residence_district") or row.get("district")
            if district not in self.districts.values():
                district, create = None, False  # a residence outside the region: only sub-districts already on file
            return self.subdistrict(raw, district, create), None
        return clean_text(raw, 2000 if f.kind == "long" else 200), None


def lives_elsewhere(case):
    """Whether the district of residence is in another region."""
    r, _ = orgunits.district_region(case.residence_district) if case.residence_district else (None, None)
    return bool(r and r["name"] != case.region)


def next_sequence(country, region_code, district_code, year_code):
    top = Case.objects.filter(country_code=country, region_code=region_code, district_code=district_code,
                              year_code=year_code).aggregate(m=Max("sequence_no"))["m"]
    return (top or 0) + 1


def district_code(unit, name):
    return next((c for c, n in unit["districts"] if n == name), "")


# ---------- a case as the page and the downloads see it ----------
def display(case, f):
    """A field's value as text, as the workbook shows it."""
    v = getattr(case, f.name)
    if f.kind == "choice":
        return ch.label(f.list, v)
    if f.kind == "subdistrict":
        return v.name if v else ""
    if f.kind == "date":
        return v.strftime("%d/%m/%Y") if v else ""
    return "" if v is None else v


def as_form(case):
    """{field: value} for the form: codes, ids and ISO dates."""
    out = {}
    for f in FIELDS:
        v = getattr(case, f.name + "_id" if f.kind == "subdistrict" else f.name)
        out[f.name] = v.isoformat() if isinstance(v, date) else ("" if v is None else v)
    return out


def as_row(case):
    """The line list's columns for one case (the list on the page)."""
    sub = case.residence_subdistrict or case.reporting_subdistrict
    return {"id": case.id, "epid": case.epid, "name": " ".join(x for x in (case.last_name, case.first_name) if x),
            "week": case.epi_week, "year": case.epi_year, "district": case.district, "subdistrict": sub.name if sub else "",
            "facility": case.health_facility, "community": case.community,
            "age": f"{case.age_months} mth" if case.age_months is not None else (f"{case.age_years} yr" if case.age_years is not None else ""),
            "sex": case.sex, "seen": case.date_seen, "onset": case.date_onset,
            "outcome": ch.label("outcome", case.outcome), "result": ch.label("pathogen", case.final_result),
            "classification": case.final_classification, "otherRegion": case.other_region,
            "updated": case.updated_at}
