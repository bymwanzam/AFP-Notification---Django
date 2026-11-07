"""Ghana's org units (regions and their districts) for picking a region in the Weekly IDSR module.

They come from the DHIS2 org unit exports in `core/data/ghana-org-units.json`. To refresh it from new exports:
    python manage.py orgunits --import ghana_regions_final.json ghana_districts_final.json

District codes for North East and Upper East are the ones already used in the bulletins and the AFP register.
The others are made from the district names (first letters of the words, then the rest of the first word),
unique within the region; they can be changed in the app.
"""
import json
import re
from pathlib import Path

SOURCE = Path(__file__).resolve().parent / "data" / "ghana-org-units.json"
DEFAULT_REGION = "Upper East"  # the AFP register's own region
NATIONAL = "Ghana"             # the national view: every region, added up

REGION_CODES = {
    "Ahafo": "AHR", "Ashanti": "ASR", "Bono": "BR", "Bono East": "BER", "Central": "CR", "Eastern": "ER",
    "Greater Accra": "GAR", "North East": "NER", "Northern": "NR", "Oti": "OR", "Savannah": "SR",
    "Upper East": "UER", "Upper West": "UWR", "Volta": "VR", "Western": "WR", "Western North": "WNR",
}
# Codes already in use, by district name; other spellings seen on forms and in DHIS2 are listed too.
FIXED_CODES = {
    "Bunkpurugu Nakpayili": "BND", "Bunkpurugu-Nyankpanduri": "BND", "Bunkpurugu Nankpanduri": "BND",
    "Chereponi": "CHD", "Cheriponi": "CHD", "East Mamprusi": "EMM", "Mamprugu Moagduri": "MMD",
    "West Mamprusi": "WMM", "Yunyoo Nasuan": "YND",
    "Bawku Municipal": "BAW", "Bawku Muncipal": "BAW", "Bawku West": "BKW", "Binduri": "BID", "Bolgatanga East": "BOE",
    "Bolgatanga Municipal": "BOG", "Bongo": "BON", "Builsa North": "BUI", "Builsa South": "BUS", "Garu": "GAR",
    "Kassena Nankana East": "KND", "Kassena-Nankana Municipal": "KND", "Kassena Nankana West": "KNW",
    "Nabdam": "NAB", "Pusiga": "PUS", "Talensi": "TAL", "Tempane": "TEP",
}
# Corrections to the DHIS2 export, applied every time it is loaded (so a fresh --import keeps them):
# districts missing from the export, old names and duplicates of current districts, and misspellings.
CORRECTIONS = {
    "Ashanti": {"add": ["Adansi Asokwa", "Adansi North", "Adansi South", "Kwadaso Municipal", "Oforikrom Municipal",
                        "Old Tafo Municipal", "Suame Municipal"],
                "rename": {"Atwima Nwabiagya South": "Atwima Nwabiagya Municipal"}},
    "Bono": {"rename": {"Suinyani Municipal": "Sunyani Municipal", "Suinyani East": "Sunyani West Municipal"}},
    "Central": {"remove": ["Hemang Lower Denkyira"]},
    "Eastern": {"add": ["Asuogyaman"], "remove": ["Afram Plains North", "Afram Plains South"]},
    "North East": {"rename": {"Bunkpurugu Nakpayili": "Bunkpurugu-Nyankpanduri"}},
    "Northern": {"add": ["Tatale Sanguli"]},
    "Upper East": {"rename": {"Kassena Nankana East": "Kassena-Nankana Municipal"}},
    "Volta": {"add": ["Adaklu"]},
    "Western": {"remove": ["Amenfi East"]},
    "Western North": {"add": ["Aowin Municipal", "Bibiani Anhwiaso Bekwai Municipal"]},
}
# The region part of AFP EPID numbers (GHA-UPE-BAW-26-001). UPE is the one in the register; check the others.
EPID_REGION = {
    "Ahafo": "AHA", "Ashanti": "ASH", "Bono": "BON", "Bono East": "BOE", "Central": "CEN", "Eastern": "EAS",
    "Greater Accra": "GAR", "North East": "NOE", "Northern": "NOR", "Oti": "OTI", "Savannah": "SAV",
    "Upper East": "UPE", "Upper West": "UPW", "Volta": "VOL", "Western": "WES", "Western North": "WEN",
}
SUFFIX = re.compile(r"(municipal(ity)?|metropolitan|metro|district)(assembly)?$")


def bare(name):
    """Name without spaces, punctuation or a Municipal / Metropolitan ending, for matching spellings."""
    n = re.sub(r"[^a-z0-9]", "", str(name or "").lower())
    return SUFFIX.sub("", n) or n


FIXED = {bare(n): c for n, c in FIXED_CODES.items()}


def make_code(name, used):
    """A 3-letter code for a district, not in `used`."""
    words = re.findall(r"[A-Za-z]+", re.sub(r"\b(Municipal|Metropolitan)\b", "", str(name))) or ["X"]
    base = ("".join(w[0] for w in words) + words[0][1:]).upper()
    tries = [base[:3]] + [base[0] + base[i] + base[j] for i in range(1, len(base)) for j in range(i + 1, len(base))]
    return next(c for c in tries + [f"{base[:2]}{k}" for k in range(1, 100)] if len(c) == 3 and c not in used)


def from_dhis2(regions_file, districts_file):
    """Regions and districts from DHIS2 organisationUnits exports, joined by the districts' parent id."""
    load = lambda f: json.loads(Path(f).read_text(encoding="utf-8"))["organisationUnits"]
    regions = {r["id"]: {"id": r["id"], "name": r["name"], "districts": []} for r in load(regions_file)}
    for d in load(districts_file):
        parent = (d.get("parent") or {}).get("id")
        if parent not in regions:
            raise ValueError(f"District {d['name']} has parent {parent}, which is not in {regions_file}.")
        regions[parent]["districts"].append({"id": d["id"], "name": d["name"], "shortName": d.get("shortName", d["name"])})
    out = sorted(regions.values(), key=lambda r: r["name"])
    for r in out:
        r["districts"].sort(key=lambda d: d["name"])
    return out


def org_units(source=SOURCE):
    """[{code, name, id, epid, districts: [[code, name]], ids: {code: DHIS2 id}}] for every region, corrected."""
    out = []
    for r in json.loads(Path(source).read_text(encoding="utf-8")):
        fix = CORRECTIONS.get(r["name"], {})
        rename, remove = fix.get("rename", {}), set(fix.get("remove", []))
        items = [{**d, "name": rename.get(d["name"], d["name"])} for d in r["districts"] if d["name"] not in remove]
        items += [{"id": None, "name": n} for n in fix.get("add", []) if bare(n) not in {bare(d["name"]) for d in items}]
        r["districts"] = sorted(items, key=lambda d: d["name"])
        fixed = [FIXED.get(bare(d["name"])) for d in r["districts"]]
        used, districts, ids = {c for c in fixed if c}, [], {}
        for d, c in zip(r["districts"], fixed):
            if not c:
                c = make_code(d["name"], used)
                used.add(c)
            districts.append([c, d["name"]])
            ids[c] = d["id"]
        out.append({"code": REGION_CODES.get(r["name"], make_code(r["name"], set())), "name": r["name"], "id": r["id"],
                    "epid": EPID_REGION.get(r["name"], r["name"][:3].upper()), "districts": districts, "ids": ids})
    return out


def region_of(name):
    """The org unit region called `name` ('Upper East' or 'Upper East Region'), or None."""
    b = bare(re.sub(r"(?i)\s*region$", "", str(name or "")))
    return next((r for r in ORG_UNITS if bare(r["name"]) == b), None)


def current_region():
    """The region used when no account says otherwise: the AFP register's own region (Upper East)."""
    return region_of(DEFAULT_REGION)


def national_unit():
    """Ghana as one org unit whose "districts" are the regions, so the pages show regional figures the way a
    region's pages show district figures. Only national and support accounts see it."""
    return {"name": NATIONAL, "code": "GHA", "id": None, "epid": "GHA", "national": True,
            "ids": {r["code"]: r["id"] for r in ORG_UNITS if r.get("id")},
            "districts": [[r["code"], r["name"]] for r in ORG_UNITS]}


def is_national(unit):
    return bool(unit and unit.get("national"))


def case_region(district):
    """The region of a case's reporting district; a district that can't be placed stays with Upper East."""
    return district_region(district)[0] or region_of(DEFAULT_REGION)


def district_region(name):
    """(region, [code, name]) of the district called `name`, matching spellings loosely, or (None, None)."""
    b = bare(name)
    for r in ORG_UNITS:
        for d in r["districts"]:
            if bare(d[1]) == b or FIXED.get(b) == d[0] and r["name"] in ("North East", "Upper East"):
                return r, d
    return None, None


ORG_UNITS = org_units() if SOURCE.exists() else []
# Bare district name -> code, for districts first seen on an uploaded form.
KNOWN_CODES = {**FIXED, **{bare(n): c for r in ORG_UNITS for c, n in r["districts"]}}

