"""Weekly IDSR: the regional weekly summary of priority diseases by district.

Every week is kept in `IDSR weekly data.xlsx` (settings.IDSR_STORE), one row per district per week, so weeks add up into the
year-to-date tables of the bulletin. Filled-in official weekly forms (IDSR Summary Regional Weekly
Reporting Form) or plain .xlsx/.csv tables can be imported, and any week can be written back out as
the official form.
"""
import csv
import difflib
import io
import re
import shutil
from copy import copy
from datetime import date, datetime, timedelta
from pathlib import Path

from django.conf import settings
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from afp.register import parse_date
from core.orgunits import KNOWN_CODES, NATIONAL, ORG_UNITS, bare, make_code, national_unit, region_of

FORM_TEMPLATE = Path(__file__).resolve().parent / "data" / "idsr-weekly-form-template.xlsx"

# The four tables of the official form, left to right from column C. Each disease is
# (key, name, short name used in column headers, measures, pattern its heading on the form matches).
BLOCKS = [
    [("afp", "Acute flaccid paralysis (polio)", "AFP", "CS D LC", r"flaccid"),
     ("ahf", "Acute haemorrhagic fever", "AHF", "CS D LC", r"haemorrhagic"),
     ("aefi", "Adverse events following immunisation", "AEFI", "CS D", r"aefi"),
     ("anthrax", "Anthrax", "Anthrax", "CS D LC", r"anthrax"),
     ("cholera", "Cholera", "Cholera", "CS D LC", r"cholera"),
     ("dengue", "Dengue fever", "Dengue", "CS D LC", r"dengue")],
    [("shigella", "Diarrhoea with blood (shigellosis)", "Shigellosis", "CS D LC", r"blood"),
     ("guinea", "Dracunculiasis (guinea worm)", "Guinea worm", "Rumour CS D LC", r"dracuncul"),
     ("ili", "Influenza-like illness", "ILI", "CS D LC", r"influenza"),
     ("matdeath", "Maternal deaths", "Maternal deaths", "D", r"maternal"),
     ("measles", "Measles", "Measles", "CS D LC", r"measles"),
     ("mening", "Meningitis", "CSM", "CS D LC", r"meningitis")],
    [("nnt", "Neonatal tetanus", "NNT", "CS D", r"tetanus"),
     ("plague", "Plague", "Plague", "CS D LC", r"plague"),
     ("rabies", "Rabies (human) / dog bite", "Dog bite", "CS D LC", r"rabies"),
     ("sari", "Severe acute respiratory infection", "SARI", "CS D LC", r"sari"),
     ("mpox", "Mpox (smallpox)", "Mpox", "CS D LC", r"mpox"),
     ("yf", "Yellow fever", "YF", "CS D LC", r"yellow")],
    [("awd_u5", "Acute watery diarrhoea under 5 years", "AWD U5", "CS D", r"<\s*5"),
     ("awd_o5", "Acute watery diarrhoea 5 years and over", "AWD 5+", "CS D LC", r">\s*5"),
     ("bu", "Buruli ulcer", "BU", "CS D LC", r"buruli"),
     ("covid", "COVID-19", "COVID-19", "CS D LC", r"covid"),
     ("zika", "Zika virus disease", "Zika", "CS D LC", r"zika"),
     ("pheic", "Public health event of international or national concern", "PHEIC", "CS D LC", r"concern")],
]
MEASURES = {"CS": "Suspected cases", "D": "Deaths", "LC": "Lab confirmed", "Rumour": "Rumours"}
DISEASES = [{"key": k, "name": n, "short": s, "measures": m.split(), "block": i}
            for i, block in enumerate(BLOCKS) for k, n, s, m, _ in block]
COLS = [f"{d['key']}.{m}" for d in DISEASES for m in d["measures"]]
HEAD = {f"{d['key']}.{m}": f"{d['short']} {m}" for d in DISEASES for m in d["measures"]}

WEEK_FIELDS = [  # (key, column header in the store, kind)
    ("start", "Week beginning", "date"), ("end", "Week ending", "date"),
    ("expected", "Reports expected", "int"), ("received", "Reports received", "int"), ("ontime", "Reports on time", "int"),
    ("epi", "Epidemiological summary", "text"), ("comments", "Comments", "text"),
    ("decisions", "Decisions and actions taken", "text"), ("recommendations", "Recommendations", "text"),
    ("highlights", "Extra bulletin highlights", "text"),
    ("reporter", "Reported by", "text"), ("phone", "Telephone", "text"),
    ("filled", "Date form filled", "date"), ("submitted", "Date submitted", "date"),
    ("published", "Bulletin publication date", "date"),
]
WEEK_LABEL = {k: h for k, h, _ in WEEK_FIELDS}
WEEK_KIND = {k: kind for k, _, kind in WEEK_FIELDS}



def norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s if s is not None else "").lower())


def text(v):
    return re.sub(r"\s+", " ", str(v)).strip() if v is not None else ""


def to_int(v, what="value"):
    """Whole number >= 0, or None for a blank cell."""
    if v is None or (isinstance(v, str) and v.strip() in ("", "-", "–")):
        return None
    if isinstance(v, bool):
        raise ValueError(f"{what}: {v!r} is not a number")
    if isinstance(v, (int, float)) and float(v).is_integer() and v >= 0:
        return int(v)
    if isinstance(v, str) and re.fullmatch(r"\s*\d+(\.0+)?\s*", v):
        return int(float(v))
    raise ValueError(f"{what}: “{v}” is not a whole number")


def safe_int(v):
    try:
        return to_int(v)
    except ValueError:
        return None


def iso(v):
    """A date from a cell or text, as YYYY-MM-DD, or '' when there is none."""
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    d = parse_date(text(v)) if text(v) else None
    return d.date().isoformat() if d else ""


def dmy(s):
    return date.fromisoformat(s).strftime("%d-%m-%Y") if s else ""


def week_dates(year, week):
    start = date.fromisocalendar(year, week, 1)
    return start.isoformat(), (start + timedelta(days=6)).isoformat()


def check_week(year, week):
    y, w = to_int(year, "Year"), to_int(week, "Week")
    if not y or not 2000 <= y <= 2100:
        raise ValueError("Enter the year, for example 2026.")
    if not w or not 1 <= w <= date(y, 12, 28).isocalendar()[1]:
        raise ValueError(f"Week must be between 1 and {date(y, 12, 28).isocalendar()[1]} for {y}.")
    return y, w


def clean_meta(raw):
    """Week details from a form or the entry page, checked and in stored form. Unknown keys are ignored."""
    meta, errors = {}, []
    for k, v in raw.items():
        kind = WEEK_KIND.get(k)
        if kind is None:
            continue
        if kind == "int":
            try:
                meta[k] = to_int(v, WEEK_LABEL[k])
            except ValueError as e:
                errors.append(str(e))
        elif kind == "date":
            meta[k] = iso(v)
            if text(v) and not meta[k]:
                errors.append(f"{WEEK_LABEL[k]}: “{v}” is not a date (use dd/mm/yyyy)")
        else:
            meta[k] = str(v).strip()[:4000] if v is not None else ""
    if errors:
        raise ValueError("; ".join(errors))
    return meta


def check_reports(meta):
    e, r, t = meta.get("expected"), meta.get("received"), meta.get("ontime")
    if e is not None and r is not None and r > e:
        raise ValueError("Reports received can't be more than reports expected.")
    if r is not None and t is not None and t > r:
        raise ValueError("Reports on time can't be more than reports received.")


class Store:
    def __init__(self, path=None):
        self.path = Path(path or settings.IDSR_STORE)
        self.region, self.code = "", ""
        self.districts = []   # [code, name], in report order
        self.board = []       # [name, role]
        self.actions = []     # standard public health actions
        self.weeks = {}       # (year, week) -> details
        self.counts = {}      # (year, week) -> {district code: {column: number}}
        if self.path.exists():
            self._load()

    # ---------- reading and writing the store ----------
    def _load(self):
        wb = load_workbook(self.path, read_only=True, data_only=True)
        try:
            rows = lambda name: [list(r) for r in wb[name].iter_rows(values_only=True)] if name in wb.sheetnames else []
            settings = {norm(r[0]): r[1] for r in rows("Settings")[1:] if len(r) > 1 and r[0]}
            self.region, self.code = text(settings.get("region")), text(settings.get("regioncode")).upper()
            self.districts = [[text(r[0]).upper(), text(r[1])] for r in rows("Districts")[1:] if len(r) > 1 and r[0] and r[1]]
            self.board = [[text(r[0]), text(r[1]) if len(r) > 1 else ""] for r in rows("Editorial board")[1:] if r and r[0]]
            self.actions = [text(r[0]) for r in rows("Standard actions")[1:] if r and r[0]]
            weeks = rows("Weeks")
            if weeks:
                idx = {norm(h): i for i, h in enumerate(weeks[0])}
                get = lambda r, h: r[idx[norm(h)]] if norm(h) in idx and idx[norm(h)] < len(r) else None
                for r in weeks[1:]:
                    y, w = safe_int(get(r, "Year")), safe_int(get(r, "Week"))
                    if y and w:
                        self.weeks[(y, w)] = {k: (iso(get(r, h)) if kind == "date" else safe_int(get(r, h)) if kind == "int"
                                                  else ("" if get(r, h) is None else str(get(r, h)).strip()))
                                              for k, h, kind in WEEK_FIELDS}
            data = rows("Weekly data")
            if data:
                idx = {norm(h): i for i, h in enumerate(data[0])}
                cols = [(c, idx[norm(HEAD[c])]) for c in COLS if norm(HEAD[c]) in idx]
                iy, iw, ic = idx.get("year"), idx.get("week"), idx.get("districtcode")
                for r in data[1:]:
                    if None in (iy, iw, ic) or max(iy, iw, ic) >= len(r):
                        continue
                    y, w, code = safe_int(r[iy]), safe_int(r[iw]), text(r[ic]).upper()
                    if y and w and code:
                        self.counts.setdefault((y, w), {})[code] = {c: v for c, i in cols if i < len(r) and (v := safe_int(r[i])) is not None}
                        self.weeks.setdefault((y, w), {})
        finally:
            wb.close()

    def save(self):
        wb = Workbook()
        head_font, head_fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="1F3864")

        def sheet(title, header, rows, widths, freeze="A2"):
            ws = wb.create_sheet(title)
            ws.append(header)
            for c in ws[1]:
                c.font, c.fill = head_font, head_fill
                c.alignment = Alignment(wrap_text=True, vertical="center")
            for r in rows:
                ws.append(r)
            for i, width in enumerate(widths, 1):
                ws.column_dimensions[get_column_letter(i)].width = width
            ws.freeze_panes = freeze
            return ws

        order = {c: i for i, (c, _) in enumerate(self.districts)}
        names = dict(self.districts)
        keys = sorted(self.weeks)
        sheet("Weekly data", ["Year", "Week", "District code", "District"] + [HEAD[c] for c in COLS],
              [[y, w, code, names.get(code, code)] + [vals.get(c) for c in COLS]
               for y, w in keys for code, vals in sorted(self.counts.get((y, w), {}).items(), key=lambda kv: order.get(kv[0], 999))],
              [7, 7, 9, 26] + [10] * len(COLS), freeze="E2")
        as_cell = lambda v, kind: date.fromisoformat(v) if kind == "date" and v else v
        ws = sheet("Weeks", ["Year", "Week"] + [h for _, h, _ in WEEK_FIELDS],
                   [[y, w] + [as_cell(self.weeks[(y, w)].get(k), kind) for k, _, kind in WEEK_FIELDS] for y, w in keys],
                   [7, 7] + [14 if kind != "text" else 40 for _, _, kind in WEEK_FIELDS], freeze="C2")
        for i, (_, _, kind) in enumerate(WEEK_FIELDS, 3):
            if kind == "date":
                for (c,) in ws.iter_rows(min_row=2, min_col=i, max_col=i):
                    c.number_format = "dd/mm/yyyy"
        sheet("Districts", ["Code", "District"], self.districts, [10, 32])
        sheet("Settings", ["Setting", "Value"], [["Region", self.region], ["Region code", self.code]], [16, 40])
        sheet("Editorial board", ["Name", "Role"], self.board, [40, 20])
        sheet("Standard actions", ["Public health action"], [[a] for a in self.actions], [120])
        del wb["Sheet"]
        buf = io.BytesIO()
        wb.save(buf)
        if self.path.exists():
            shutil.copy2(self.path, self.path.with_suffix(".bak.xlsx"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(buf.getvalue())

    # ---------- districts ----------
    def district_code(self, label, add=False):
        """Code of the district named or coded `label`; close spellings match too. With add, unknown names are added."""
        if getattr(self, "national", False):  # Ghana's rows are regions: "Upper East Region" is Upper East
            label = re.sub(r"(?i)\s*region$", "", text(label))
        n, b = norm(label), bare(label)
        if not n:
            return None
        for c, name in self.districts:
            if n == norm(c) or b == bare(name):
                return c
        # Spelling variants (Cheriponi / Chereponi) only: same start and end, so East and West Mamprusi stay apart.
        close = [c for c, name in self.districts if b[:4] == bare(name)[:4] and b[-3:] == bare(name)[-3:]
                 and difflib.SequenceMatcher(None, b, bare(name)).ratio() >= 0.85]
        if len(close) == 1:
            return close[0]
        # Another known name of a district already set up (Bunkpurugu Nankpanduri / Nakpayili).
        used, code = {c for c, _ in self.districts}, KNOWN_CODES.get(b)
        if code in used:
            return code
        if not add:
            return None
        if not code:
            code = make_code(label, used)
        name = text(label)
        self.districts.append([code, name.title() if name.isupper() else name])
        return code

    # ---------- weeks ----------
    def week_meta(self, y, w):
        meta = {k: None if kind == "int" else "" for k, _, kind in WEEK_FIELDS} | self.weeks.get((y, w), {})
        # The dates follow the epi week (Monday to Sunday; bulletin on the Thursday after), whatever was typed or uploaded.
        start, end = week_dates(y, w)
        meta["start"], meta["end"] = start, end
        meta["published"] = (date.fromisoformat(end) + timedelta(days=4)).isoformat()
        return meta

    def put_week(self, year, week, meta, counts):
        """Save one week from the entry page: its details and the full count grid (blank counts are 0)."""
        y, w = check_week(year, week)
        meta = clean_meta(meta or {})
        check_reports(meta)
        known = {c for c, _ in self.districts}
        grid, errors = {}, []
        for code, vals in (counts or {}).items():
            if code not in known:
                raise ValueError(f"Unknown district code {code}.")
            row = {}
            for c in COLS:
                try:
                    row[c] = to_int(vals.get(c), f"{dict(self.districts)[code]}, {HEAD[c]}") or 0
                except ValueError as e:
                    errors.append(str(e))
            grid[code] = row
        if errors:
            raise ValueError("; ".join(errors[:5]))
        self.weeks[(y, w)] = self.weeks.get((y, w), {}) | meta
        self.counts.setdefault((y, w), {}).update(grid)
        self.save()
        return y, w

    def delete_week(self, year, week):
        """Remove one week (its details and every district's counts). The previous file is kept as .bak.xlsx."""
        y, w = check_week(year, week)
        if (y, w) not in self.weeks and (y, w) not in self.counts:
            raise ValueError(f"Week {w:03d} of {y} is not on file.")
        self.weeks.pop((y, w), None)
        self.counts.pop((y, w), None)
        self.save()
        return y, w

    def set_settings(self, raw):
        region, code = text(raw.get("region")), text(raw.get("code")).upper()
        if not region:
            raise ValueError("Enter the region name.")
        districts, seen = [], set()
        for line in raw.get("districts", []):
            c, name = text(line[0]).upper(), text(line[1])
            if not c or not name:
                continue
            if c in seen:
                raise ValueError(f"District code {c} is used twice.")
            seen.add(c)
            districts.append([c, name])
        if not districts:
            raise ValueError("List at least one district.")
        in_use = {c for grid in self.counts.values() for c in grid} - seen
        if in_use and self.region and norm(region) != norm(self.region):
            raise ValueError(f"The weeks on file are for {self.region}, so the region can't be changed to {region}. "
                             f"Keep a separate copy of {self.path.name} for each region.")
        if in_use:
            raise ValueError(f"{', '.join(sorted(in_use))} already {'has' if len(in_use) == 1 else 'have'} weekly data, "
                             f"so {'it' if len(in_use) == 1 else 'they'} can't be removed. Rename instead.")
        self.region, self.code, self.districts = region, code, districts
        self.board = [[text(n), text(r)] for n, r in raw.get("board", []) if text(n)]
        self.actions = [text(a) for a in raw.get("actions", []) if text(a)]
        self.save()

    # ---------- import ----------
    def plan_import(self, forms, table):
        """Compare an upload with the store. Nothing is written; apply_import(plan) does that."""
        problems, notes, incoming = [], [], {}
        before = {c for c, _ in self.districts}

        def target(y, w):
            return incoming.setdefault((y, w), {"meta": {}, "counts": {}})

        for f in forms:
            problems += f["problems"]
            if not (f["year"] and f["week"]):
                problems.append(f"Sheet “{f['sheet']}”: the week or year could not be read from the form.")
                continue
            try:
                y, w = check_week(f["year"], f["week"])
            except ValueError as e:
                problems.append(f"Sheet “{f['sheet']}”: {e}")
                continue
            if f["region"] and not self.region:
                self.region, self.code = f["region"], f["code"] or self.code
                notes.append(f"Region set to {self.region}" + (f" ({self.code})" if self.code else "") + " from the form.")
            elif f["region"] and norm(f["region"]) != norm(self.region):
                problems.append(f"Sheet “{f['sheet']}” is a {f['region']} form, but this store is for {self.region}. Check it is the right file.")
            t = target(y, w)
            t["meta"].update({k: v for k, v in f["meta"].items() if v not in (None, "")})
            for label, vals in f["rows"]:
                code = self.district_code(label, add=True)
                t["counts"].setdefault(code, {}).update(vals)
        if table:
            self._plan_table(table, target, problems, notes)
        return self.plan_incoming(incoming, problems, notes, before)

    def plan_incoming(self, incoming, problems=(), notes=(), before=None):
        """Compare {(year, week): {"meta", "counts"}} with the store, as a plan for apply_import."""
        problems, notes = list(problems), list(notes)
        before = {c for c, _ in self.districts} if before is None else before
        weeks, cells = [], 0
        names = dict(self.districts)
        for y, w in sorted(incoming):
            inc, old = incoming[(y, w)], self.counts.get((y, w), {})
            changes = [{"district": names.get(code, code), "field": HEAD[c], "old": old.get(code, {}).get(c), "new": v}
                       for code, vals in inc["counts"].items() for c in COLS
                       if (v := vals.get(c)) is not None and v != old.get(code, {}).get(c)]
            cur = self.weeks.get((y, w), {})
            meta = [{"field": WEEK_LABEL[k], "old": cur.get(k), "new": v} for k, v in inc["meta"].items()
                    if v not in (None, "") and v != cur.get(k)]
            cells += len(changes)
            weeks.append({"year": y, "week": w, "new": (y, w) not in self.weeks, "districts": len(inc["counts"]),
                          "cases": sum(vals.get(f"{d['key']}.CS") or 0 for vals in inc["counts"].values() for d in DISEASES),
                          "changeCount": len(changes), "changes": changes[:300], "meta": meta})
        added = [[c, n] for c, n in self.districts if c not in before]
        return {"weeks": weeks, "newDistricts": added, "problems": problems, "notes": notes,
                "summary": {"weeks": len(weeks), "newWeeks": sum(w["new"] for w in weeks), "cells": cells,
                            "meta": sum(len(w["meta"]) for w in weeks)},
                "_incoming": incoming}

    def _plan_table(self, rows, target, problems, notes):
        hdr = next((i for i, r in enumerate(rows[:10]) if {"year", "week"} <= {norm(c) for c in r}
                    and any("district" in norm(c) for c in r)), None)
        if hdr is None:
            problems.append("No IDSR weekly form and no header row with Year, Week and District columns was found.")
            return
        head = [norm(c) for c in rows[hdr]]
        col = lambda *names: next((i for n in names for i, h in enumerate(head) if h == n), None)
        iy, iw = col("year"), col("week")
        idist = col("districtcode", "code", "district", "districtname", "nameofdistrict", "mdistrict", "md")
        alias = {}
        for d in DISEASES:
            for m in d["measures"]:
                for a in (d["short"], d["name"], d["key"]):
                    for mm in (m, MEASURES[m]):
                        alias.setdefault(norm(f"{a} {mm}"), f"{d['key']}.{m}")
        meta_alias = {norm(h): k for k, h, _ in WEEK_FIELDS if k not in ("start", "end")}
        long = col("disease"), col("measure"), col("value")
        if None not in long:
            dis = {norm(a): d for d in DISEASES for a in (d["short"], d["name"], d["key"])}
            meas = {norm(a): m for m, label in MEASURES.items() for a in (m, label)}
        mapped = {i: alias[h] for i, h in enumerate(head) if h in alias}
        metas = {i: meta_alias[h] for i, h in enumerate(head) if h in meta_alias}
        ignored = [text(rows[hdr][i]) for i, h in enumerate(head) if h and i not in mapped and i not in metas
                   and i not in (iy, iw, idist, *long) and h not in ("district", "districtname")]
        if ignored:
            notes.append("Columns not used: " + ", ".join(ignored[:12]) + (" …" if len(ignored) > 12 else ""))
        if None in long and not mapped:
            problems.append("The table has no disease columns such as “AFP CS” or “Measles D”.")
            return
        for n, r in enumerate(rows[hdr + 1:], hdr + 2):
            cell = lambda i: r[i] if i is not None and i < len(r) else None
            if not any(v not in (None, "") for v in r):
                continue
            try:
                y, w = check_week(cell(iy), cell(iw))
            except ValueError as e:
                problems.append(f"Row {n}: {e}")
                continue
            if not norm(cell(idist)):
                problems.append(f"Row {n}: no district.")
                continue
            try:
                if None not in long:
                    d, m = dis.get(norm(cell(long[0]))), meas.get(norm(cell(long[1])))
                    if not d or m not in d["measures"]:
                        raise ValueError(f"unknown disease or measure “{text(cell(long[0]))} {text(cell(long[1]))}”")
                    vals, meta = {f"{d['key']}.{m}": to_int(cell(long[2]), "Value")}, {}
                else:
                    vals = {c: v for i, c in mapped.items() if (v := to_int(cell(i), HEAD[c])) is not None}
                    meta = {k: v for k, v in clean_meta({k: cell(i) for i, k in metas.items()}).items() if v not in (None, "")}
            except ValueError as e:
                problems.append(f"Row {n}: {e}")
                continue
            t = target(y, w)
            t["counts"].setdefault(self.district_code(cell(idist), add=True), {}).update(vals)
            t["meta"].update(meta)

    def apply_import(self, plan):
        for (y, w), inc in plan["_incoming"].items():
            self.weeks[(y, w)] = self.weeks.get((y, w), {}) | inc["meta"]
            grid = self.counts.setdefault((y, w), {})
            for code, vals in inc["counts"].items():
                grid.setdefault(code, {}).update({c: v for c, v in vals.items() if v is not None})
        self.save()
        return len(plan["_incoming"])

    # ---------- exports ----------
    def week_csv(self, y, w):
        grid = self.counts.get((y, w), {})
        out = io.StringIO()
        wr = csv.writer(out)
        wr.writerow(["Year", "Week", "District code", "District"] + [HEAD[c] for c in COLS])
        for code, name in self.districts:
            wr.writerow([y, w, code, name] + [grid.get(code, {}).get(c, "") for c in COLS])
        return ("﻿" + out.getvalue()).encode("utf-8")

    def form_xlsx(self, y, w):
        """The week written into the official weekly reporting form."""
        if not FORM_TEMPLATE.exists():
            raise ValueError(f"The form template is missing: idsr/data/{FORM_TEMPLATE.name}")
        wb = load_workbook(FORM_TEMPLATE)
        ws = wb.worksheets[0]
        meta, grid = self.week_meta(y, w), self.counts.get((y, w), {})
        num = lambda v: "" if v is None else v

        def put(pattern, value):
            for row in ws.iter_rows():
                for c in row:
                    if isinstance(c.value, str) and re.search(pattern, c.value, re.I):
                        c.value = value
                        return c

        put(r"^\s*IDSR Summary", f"IDSR Summary Regional Weekly _{w:03d}_ {y}  Reporting Form_{self.code}")
        put(r"Reporting Region", f"Reporting Region:   {self.region.upper()}")
        put(r"Region Code", f"Region Code: {self.code}")
        put(r"^\s*Week\s*:", f"Week: {w:03d}")
        put(r"^\s*Year\s*:", f"Year: {y}")
        put(r"Week Beginning", f"Week Beginning Monday: {dmy(meta['start'])}")
        put(r"Week Ending", f"Week Ending Sunday: {dmy(meta['end'])}")
        put(r"Expected Number of Reports", f"Officially Expected Number of Reports:  {num(meta['expected'])}")
        put(r"Reports received\s*:", f"Number of Reports received:  {num(meta['received'])}")
        put(r"received on time", f"Number of Reports received on time: {num(meta['ontime'])}")
        put(r"Name of Person reporting", f"Name of Person reporting:     {meta['reporter']}")
        put(r"^\s*Telephone", f"Telephone No.:      {meta['phone']}")
        put(r"Date Reporting Form Filled", f"Date Reporting Form Filled: {dmy(meta['filled'])}   Date Reporting Form Submitted "
                                           f"to next level: {dmy(meta['submitted'])}   Date Received at next level:      /     /   /")
        epi = meta["epi"] + (("\n\nComments: " + meta["comments"]) if meta["comments"] else "")
        for pattern, value in ((r"^\s*Epidemiological", epi), (r"^\s*Decisions", meta["decisions"]), (r"^\s*Recommendations", meta["recommendations"])):
            label = next((c for (c,) in ws.iter_rows(min_col=2, max_col=2) if isinstance(c.value, str) and re.search(pattern, c.value, re.I)), None)
            if label:
                ws.cell(label.row, 3).value = value
        for i, (head_row, rows) in enumerate(grow_blocks(ws, len(self.districts))):
            for k, r in enumerate(rows):
                code, name = self.districts[k] if k < len(self.districts) else (None, None)
                ws.cell(r, 2).value = name.upper() if name else None
                vals = grid.get(code)
                c = 3
                for d in BLOCKS[i]:
                    for m in d[3].split():
                        ws.cell(r, c).value = None if vals is None else vals.get(f"{d[0]}.{m}", 0)
                        c += 1
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def snapshot(self):
        return {"region": self.region, "code": self.code, "districts": self.districts, "board": self.board,
                "actions": self.actions, "orgUnits": ORG_UNITS, "diseases": DISEASES, "measures": MEASURES, "heads": HEAD,
                "weeks": [{"year": y, "week": w, **self.week_meta(y, w)} for y, w in sorted(self.weeks)],
                "counts": {f"{y}-{w}": grid for (y, w), grid in self.counts.items()}}


# ---------- one store per region ----------
def region_dir():
    return Path(settings.IDSR_STORE).parent / "IDSR regions"


def store_for(region=None):
    """The store of `region` (one of the org unit regions); without one, the main store.

    The main store, IDSR weekly data.xlsx, keeps the region it was first set up for. Other regions are kept
    in IDSR regions/IDSR weekly data - <Region>.xlsx. A region with no file yet starts with its org unit
    districts and the main store's standard actions, and is saved with its first week.
    """
    main = Store()
    if not text(region):
        return main
    if bare(region) == bare(NATIONAL):
        # Ghana: its own file, whose rows are the regions, entered like a region's districts (form, upload or
        # DHIMS2 fetched by region). It is not added up from the regions' files.
        store = Store(region_dir() / f"IDSR weekly data - {NATIONAL}.xlsx")
        store.national = True
        if not store.region:
            unit = national_unit()
            store.region, store.code = unit["name"], unit["code"]
            store.districts = [list(d) for d in unit["districts"]]
            store.actions = list(main.actions)
        return store
    unit = region_of(region)
    if not unit:
        raise ValueError(f"Unknown region {region}.")
    home = region_of(main.region)
    if not main.region or (home and home["name"] == unit["name"]):
        store = main
    else:
        store = Store(region_dir() / f"IDSR weekly data - {unit['name']}.xlsx")
    if not store.region:
        store.region, store.code = unit["name"], unit["code"]
        store.districts = [list(d) for d in unit["districts"]]
        store.actions = list(main.actions)
    return store


def regions_on_file():
    """Names of the regions that have a store, the main one first."""
    main = Store()
    out = [main.region] if main.region else []
    for p in sorted(region_dir().glob("IDSR weekly data - *.xlsx")):
        if not p.stem.endswith(".bak"):
            out.append(p.stem.split(" - ", 1)[1])
    return out


# ---------- the official weekly form ----------
def form_blocks(ws):
    """(header row, district rows) for each disease table: the rows under 'Name of District' down to 'Total'."""
    out = []
    for (c,) in ws.iter_rows(min_col=2, max_col=2):
        if norm(c.value) == "nameofdistrict":
            rows, r = [], c.row + 1
            while r <= ws.max_row and norm(ws.cell(r, 2).value) not in ("total", ""):
                rows.append(r)
                r += 1
            out.append((c.row, rows))
    return out


def insert_rows_styled(ws, at, n, like):
    """Insert n rows before row `at`, styled like row `like`, moving merged cells and row heights down too."""
    moved = []
    for m in list(ws.merged_cells.ranges):
        if m.max_row >= at:
            ws.unmerge_cells(str(m))
            moved.append((m.min_col, m.min_row + (n if m.min_row >= at else 0), m.max_col, m.max_row + n))
    heights = {r: ws.row_dimensions[r].height for r in range(at, ws.max_row + 1)}
    ws.insert_rows(at, n)
    for r, h in sorted(heights.items(), reverse=True):
        ws.row_dimensions[r + n].height = h
    for r in range(at, at + n):
        ws.row_dimensions[r].height = ws.row_dimensions[like].height
        for c in range(1, ws.max_column + 1):
            src = ws.cell(like, c)
            if src.has_style:
                ws.cell(r, c)._style = copy(src._style)
    for c1, r1, c2, r2 in moved:
        ws.merge_cells(start_row=r1, start_column=c1, end_row=r2, end_column=c2)


def grow_blocks(ws, n):
    """The form's disease tables with at least n district rows each; the Total rows add up the new rows too."""
    out, offset = [], 0
    for head, rows in form_blocks(ws):
        head, rows = head + offset, [r + offset for r in rows]
        if rows and n > len(rows):
            k = n - len(rows)
            insert_rows_styled(ws, rows[-1] + 1, k, rows[-1])
            rows += list(range(rows[-1] + 1, rows[-1] + 1 + k))
            offset += k
        out.append((head, rows))
    for _, rows in out:  # insert_rows doesn't update formulas, so every table's totals are rewritten
        for c in range(3, ws.max_column + 1):
            cell = ws.cell(rows[-1] + 1, c)
            if isinstance(cell.value, str) and cell.value.upper().startswith("=SUM("):
                col = get_column_letter(c)
                cell.value = f"=SUM({col}{rows[0]}:{col}{rows[-1]})"
    return out


def is_form(ws):
    return len(form_blocks(ws)) == len(BLOCKS)


def parse_form(ws):
    """One filled-in weekly form: week, region, details and counts by district name."""
    cells = [(c.row, c.column, text(c.value)) for row in ws.iter_rows() for c in row if isinstance(c.value, str) and c.value.strip()]

    def find(pattern, only_row=None):
        for r, _, t in cells:
            if only_row in (None, r) and (m := re.search(pattern, t, re.I)):
                return m.group(1).strip()
        return ""

    def beside(pattern):
        label = next((r for r, col, t in cells if col == 2 and re.search(pattern, t, re.I)), None)
        v = ws.cell(label, 3).value if label else None
        return str(v).strip() if v is not None else ""

    title = next((m for _, _, t in cells if (m := re.search(r"_(\d{1,3})_\s*(\d{4})", t))), None)
    year = safe_int(find(r"\byear\s*:\s*(\d{4})")) or (safe_int(title.group(2)) if title else None)
    week = safe_int(find(r"^week\s*:\s*0*(\d{1,2})\b")) or (safe_int(title.group(1)) if title else None)
    reporter_row = next((r for r, _, t in cells if re.search(r"name of person reporting", t, re.I)), None)
    meta, problems = {}, []
    raw = {
        "start": find(r"week beginning[^:]*:\s*([\d/.\-]+)"), "end": find(r"week ending[^:]*:\s*([\d/.\-]+)"),
        "expected": find(r"expected number of reports\s*:\s*(\d+)"), "received": find(r"reports received\s*:\s*(\d+)"),
        "ontime": find(r"received on time\s*:\s*(\d+)"),
        "epi": beside(r"^epidemiological"), "decisions": beside(r"^decisions"), "recommendations": beside(r"^recommendations"),
        "reporter": find(r"name of person reporting\s*:\s*(.*)$"),
        "phone": find(r"telephone no\.?\s*:\s*([\d +]*)", reporter_row) if reporter_row else "",
        "filled": find(r"form filled\s*:\s*([\d/.\-]+)"), "submitted": find(r"form submitted[^:]*:\s*([\d/.\-]+)"),
    }
    try:
        meta = clean_meta(raw)
    except ValueError as e:
        problems.append(f"Sheet “{ws.title}”: {e}")
        meta = {k: v for k, v in raw.items() if WEEK_KIND[k] == "text"}
    rows = []
    for i, (head_row, drows) in enumerate(form_blocks(ws)):
        heading = " ".join(t.lower() for r, col, t in cells if head_row - 2 <= r < head_row and col >= 3)
        missing = [d[1] for d in BLOCKS[i] if not re.search(d[4], heading)]
        if missing:
            raise ValueError(f"Sheet “{ws.title}” does not match the standard IDSR weekly form: table {i + 1} has no "
                             f"{', '.join(missing)} column. Upload it as a table with Year, Week and District columns instead.")
        for r in drows:
            name = text(ws.cell(r, 2).value)
            vals, c = {}, 3
            for d in BLOCKS[i]:
                for m in d[3].split():
                    try:
                        vals[f"{d[0]}.{m}"] = to_int(ws.cell(r, c).value, f"{name}, {d[2]} {m}")
                    except ValueError as e:
                        problems.append(f"Sheet “{ws.title}”, {ws.cell(r, c).coordinate}: {e}")
                    c += 1
            rows.append((name, vals))
    return {"sheet": ws.title, "year": year, "week": week, "meta": meta, "rows": rows, "problems": problems,
            "region": text(find(r"reporting region\s*:\s*(.*)$")).title(), "code": find(r"region code\s*:\s*(\w+)").upper()}


def read_upload(name, data):
    """(forms, table) from an uploaded file: every sheet that is an official weekly form, otherwise the rows of a table."""
    suffix = Path(name).suffix.lower()
    if suffix in (".xlsx", ".xlsm"):
        try:
            wb = load_workbook(io.BytesIO(data), data_only=True)
        except Exception:
            raise ValueError("That file could not be opened as an Excel workbook.")
        forms = [parse_form(ws) for ws in wb.worksheets if is_form(ws)]
        return (forms, None) if forms else ([], [list(r) for r in wb.worksheets[0].iter_rows(values_only=True)])
    if suffix == ".csv":
        try:
            body = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            body = data.decode("cp1252")
        try:
            dialect = csv.Sniffer().sniff(body[:4096], delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        return [], list(csv.reader(io.StringIO(body), dialect))
    if suffix == ".xls":
        raise ValueError("Old .xls files are not supported. Save it as .xlsx or .csv in Excel first.")
    raise ValueError("Upload an .xlsx or .csv file.")

