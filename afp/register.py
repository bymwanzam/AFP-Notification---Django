"""The AFP notification register (an Excel workbook): its columns and checks, new cases, edits, imports and exports."""
import io
import json
import re
import shutil
from copy import copy
from datetime import date, datetime, time, timedelta
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.formatting.formatting import ConditionalFormattingList
from openpyxl.styles import Font
from openpyxl.worksheet.cell_range import MultiCellRange
from openpyxl.utils import column_index_from_string, get_column_letter, range_boundaries

from core.orgunits import ORG_UNITS, district_region

EDIT_HOURS = 24  # a regional account can edit or delete a case it entered for this long


# ---------- who entered which case, and when ----------
# The register has no column for this, so the app keeps it beside the register: EPID # -> entry time, region and
# account. Only cases entered in the app (New case, or added by Update from file) are listed.
def entries_path(xlsx):
    return Path(xlsx).with_name("AFP case entries.json")


def load_entries(xlsx):
    try:
        return json.loads(entries_path(xlsx).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def log_entries(xlsx, items):
    """items: [(epid, region, user)] entered now."""
    data, now = load_entries(xlsx), datetime.now().isoformat(timespec="seconds")
    for epid, region, user in items:
        data[str(epid).strip().upper()] = {"at": now, "region": region, "by": user}
    entries_path(xlsx).write_text(json.dumps(data, indent=1), encoding="utf-8")


def rename_entry(xlsx, old, new):
    """Keep a case's entry time when its EPID # is corrected."""
    data = load_entries(xlsx)
    if old in data and new != old:
        data[new] = data.pop(old)
        entries_path(xlsx).write_text(json.dumps(data, indent=1), encoding="utf-8")


def drop_entry(xlsx, epid):
    data = load_entries(xlsx)
    if data.pop(epid, None) is not None:
        entries_path(xlsx).write_text(json.dumps(data, indent=1), encoding="utf-8")


def edit_until(entry):
    """When the edit window of a logged entry closes."""
    return datetime.fromisoformat(entry["at"]) + timedelta(hours=EDIT_HOURS)


DATE_FORMATS = ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M")
FUP_DAYS = 60


def clean(text):
    return re.sub(r"\s+", " ", str(text)).strip()


def key(header):
    """Loose header match: 'Outcome \\n(select ...)' and 'outcome' both become 'outcome'."""
    return re.sub(r"[^a-z0-9]", "", clean("" if header is None else header).split(" (")[0].lower())


def find_header_row(ws):
    for r in range(1, 11):
        texts = [clean(c.value).lower() for c in ws[r] if c.value]
        if any("epid" in t for t in texts) and len(texts) > 5:
            return r
    return 1


def last_data_row(ws, header_row, ncols):
    last = header_row
    for r in range(header_row + 1, ws.max_row + 1):
        if any(ws.cell(r, c).value not in (None, "") for c in range(1, ncols + 1)):
            last = r
    return last


def dv_list_for(ws, col_letter, row):
    """The column's in-sheet dropdown list, preferring the one covering `row`, else any below the header."""
    col = column_index_from_string(col_letter)
    lists = [dv for dv in ws.data_validations.dataValidation if dv.type == "list" and dv.formula1 and '"' in dv.formula1]
    dv = next((d for d in lists if f"{col_letter}{row}" in d.sqref), None) or next(
        (d for d in lists if any(r.min_col <= col <= r.max_col and r.max_row > 2 for r in d.sqref.ranges)), None)
    if not dv:
        return None
    items = dv.formula1.strip('"').split(",")
    return [i.strip().rstrip(".") for i in items if i.strip().rstrip(".")]


def parse_date(text):
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text.strip(), fmt)
        except ValueError:
            pass
    return None


def blank(v):
    return v is None or (isinstance(v, str) and not v.strip())


def show(v):
    if blank(v):
        return "(blank)"
    if isinstance(v, (datetime, date)):
        return f"{v:%d/%m/%Y}"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return clean(v)


def same(a, b):
    if isinstance(a, (datetime, date)) and isinstance(b, (datetime, date)):
        return (a.date() if isinstance(a, datetime) else a) == (b.date() if isinstance(b, datetime) else b)
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return float(a) == float(b)
    return clean("" if a is None else a).lower() == clean("" if b is None else b).lower()


def extend_ranges(ws, src, row):
    for table in ws.tables.values():
        c1, r1, c2, r2 = range_boundaries(table.ref)
        if r2 == src:
            table.ref = f"{get_column_letter(c1)}{r1}:{get_column_letter(c2)}{row}"
            if table.autoFilter:
                table.autoFilter.ref = table.ref
    old = ws.conditional_formatting
    new = ConditionalFormattingList()
    for cf in old:
        ref = " ".join(re.sub(rf"(?<=[A-Z]){src}$", str(row), str(r)) for r in cf.sqref.ranges)
        for rule in cf.rules:
            new.add(ref, rule)
    ws.conditional_formatting = new
    for dv in ws.data_validations.dataValidation:
        dv.sqref = MultiCellRange(" ".join(re.sub(rf"(?<=[A-Z]){src}$", str(row), str(r)) for r in dv.sqref.ranges))


class Field:
    def __init__(self, ws, col, header_row, last_row):
        self.col = col
        self.letter = get_column_letter(col)
        self.label = clean(ws.cell(header_row, col).value).split(" (")[0]
        values = [ws.cell(r, col).value for r in range(header_row + 1, last_row + 1)]
        filled = [v for v in values if v not in (None, "")]
        self.template = None
        self.options, self.strict = [], False
        self.allow_age = "age" in self.label.lower()
        if filled and all(isinstance(v, str) and v.startswith("=") for v in filled):
            self.kind = "formula"
            self.template = filled[-1]
        else:
            options = dv_list_for(ws, self.letter, last_row + 1) or dv_list_for(ws, self.letter, last_row)
            strs = [v for v in filled if isinstance(v, str)]
            if options:
                self.kind, self.options, self.strict = "dropdown", options, True
            elif sum(isinstance(v, datetime) for v in filled) > len(filled) / 2:
                self.kind = "date"
            elif filled and all(isinstance(v, (int, float)) for v in filled):
                self.kind = "number"
            elif strs and len(set(strs)) <= 5 and len(strs) >= 3 and max(map(len, strs)) <= 30:
                opts = sorted({s.strip() for s in strs})
                if opts == ["Yes"]:
                    opts = ["Yes", "No"]
                self.kind, self.options, self.strict = "dropdown", opts, False
            else:
                self.kind = "text"
        self.required = self.kind != "formula" and bool(values) and len(filled) == len(values)
        self.number_format = ws.cell(last_row, col).number_format


class Register:
    """The AFP follow-up workbook: its column schema, validation and writes."""

    def __init__(self, path):
        self.path = Path(path)
        self.reload()

    def reload(self):
        wb = load_workbook(self.path)
        ws = wb.active
        self.header_row = find_header_row(ws)
        ncols = max(c for c in range(1, ws.max_column + 1) if ws.cell(self.header_row, c).value)
        self.last_row = last_data_row(ws, self.header_row, ncols)
        self.fields = [Field(ws, c, self.header_row, self.last_row) for c in range(1, ncols + 1)]
        self.existing = [[ws.cell(r, c).value for c in range(1, ncols + 1)]
                         for r in range(self.header_row + 1, self.last_row + 1)]
        self.code_map = {}
        district, code = self.field_like("district or"), self.field_like("epid. code")
        if district and code and district.kind == code.kind == "dropdown" and len(district.options) == len(code.options):
            self.code_map = dict(zip(district.options, code.options))
        self.home, self.regions = None, []
        if self.code_map:
            self._add_org_units(district, code)

    def _add_org_units(self, district, code):
        """Let the district column take a district from any region, picked region first.

        The register's own region keeps the sheet's spellings; its in-sheet dropdown still lists only those.
        """
        own = {c: n for n, c in self.code_map.items()}
        self.home = next((r for n in self.code_map if (r := district_region(n)[0])), None)
        ids = [str(r[self.fields.index(self.field_like("epid #"))]) for r in self.existing] if self.field_like("epid #") else []
        # The register's own EPID region code, from its latest case of one of its own districts (not a case
        # entered for another region, e.g. GHA-UPW-...).
        home_epid = next((m.group(1) for i in reversed(ids) if (m := re.match(r"GHA-([A-Z]+)-([A-Z]+)-", i)) and m.group(2) in own), None)
        for r in ORG_UNITS:
            mine = r is self.home
            districts = [[c, own.get(c, n) if mine else n] for c, n in r["districts"]]
            if mine:
                districts += [[c, n] for c, n in own.items() if c not in {d[0] for d in districts}]
            self.regions.append({"name": r["name"], "epid": (home_epid if mine and home_epid else r["epid"]),
                                 "districts": districts})
            for c, n in districts:
                if n not in self.code_map:
                    self.code_map[n] = c
                    district.options.append(n)
                if c not in code.options:
                    code.options.append(c)

    def in_region(self, district, region):
        """Whether a reporting district is in `region`; a district the register can't place counts as its own region's."""
        if not region:
            return True
        r = district_region(district)[0]
        return (r["name"] if r else self.home["name"] if self.home else None) == region

    def district_error(self, values, region):
        """(col, message) when a new case's reporting district is outside `region`, else None."""
        f = self.field_like("district or")
        if f and values.get(f.col) and not self.in_region(values[f.col], region):
            return f.col, f"{values[f.col]} is not in {region} Region. Choose one of its districts."
        return None

    def field_like(self, text):
        return next((f for f in self.fields if text in f.label.lower()), None)

    def sn_field(self):
        return self.fields[0] if self.fields and self.fields[0].kind == "number" else None

    def next_sn(self):
        nums = [row[0] for row in self.existing if isinstance(row[0], (int, float))]
        return int(max(nums, default=0)) + 1

    def epids(self):
        idx = self.fields.index(self.field_like("epid #"))
        return {str(r[idx]).strip().upper(): r for r in self.existing if r[idx]}

    def next_epid(self, code, region=None):
        """Next EPID # for a district code: GHA-<region>-<code>-<yy>-<nnn>. Without a region, the register's own."""
        code = code.strip()
        epid = self.field_like("epid #")
        idx = self.fields.index(epid)
        ids = [str(r[idx]) for r in self.existing if r[idx]]
        prefix = ids[-1].rsplit("-", 3)[0] if ids else "GHA"
        unit = next((r for r in self.regions if r["name"].lower() == clean(region or "").lower()), None)
        if unit:
            prefix = f"GHA-{unit['epid']}"
        yy = f"{date.today():%y}"
        nums = [int(m.group(1)) for i in ids if (m := re.search(rf"^{re.escape(prefix)}-{code}-{yy}-(\d+)$", i))]
        return f"{prefix}-{code}-{yy}-{max(nums, default=0) + 1:03d}"

    def schema(self):
        col = lambda f: f.col if f else None
        return {
            "fields": [{"col": f.col, "label": f.label, "kind": f.kind, "options": f.options, "strict": f.strict,
                        "required": f.required, "allowAge": f.allow_age} for f in self.fields],
            "nextSn": self.next_sn(), "nextRow": self.last_row + 1, "codeMap": self.code_map,
            "snCol": col(self.sn_field()), "epidCol": col(self.field_like("epid #")),
            "nameCol": col(self.field_like("patient name")), "districtCol": col(self.field_like("district or")),
            "codeCol": col(self.field_like("epid. code")), "onsetCol": col(self.field_like("onset")),
            "outcomeCol": col(self.field_like("outcome")), "reportCol": col(self.field_like("report availability")),
            "fupDays": FUP_DAYS, "regions": self.regions, "homeRegion": self.home["name"] if self.home else None,
        }

    def convert(self, f, raw):
        """Turn one typed or uploaded value into what the cell should hold. Returns (value, error)."""
        if blank(raw):
            return None, None
        if isinstance(raw, float) and raw.is_integer():
            raw = int(raw)
        if f.kind == "date":
            if isinstance(raw, datetime):
                return raw, None
            if isinstance(raw, date):
                return datetime.combine(raw, time()), None
            if f.allow_age and isinstance(raw, (int, float)):
                return raw, None
            text = clean(raw)
            d = parse_date(text)
            if d:
                return d, None
            if f.allow_age and re.fullmatch(r"\d+(\.\d+)?", text):
                return (float(text) if "." in text else int(text)), None
            return None, "enter a date as dd/mm/yyyy."
        if f.kind == "number" or (f.kind == "dropdown" and f.options and all(o.isdigit() for o in f.options)):
            if isinstance(raw, (int, float)):
                return raw, None
            text = clean(raw)
            try:
                return (int(text) if re.fullmatch(r"-?\d+", text) else float(text)), None
            except ValueError:
                return None, "must be a number."
        text = clean(raw)
        if f.kind == "dropdown" and f.strict:
            match = next((o for o in f.options if o.lower() == text.lower()), None)
            return (match, None) if match else (None, "choose from the list.")
        return text, None

    def validate(self, raw, own_epid=None):
        """raw: {col: value}. Returns ({col: value}, [(col, message)]). own_epid: the case being edited."""
        values, errors = {}, []
        for f in self.fields:
            if f.kind == "formula":
                continue
            v, err = self.convert(f, raw.get(f.col))
            if err:
                errors.append((f.col, f"{f.label}: {err}"))
                continue
            if v is None and f.required:
                errors.append((f.col, f"{f.label} is required."))
            values[f.col] = v
        epid = self.field_like("epid #")
        new_id = str(values.get(epid.col) or "").strip().upper() if epid else ""
        if new_id and new_id in self.epids() and new_id != own_epid:
            errors.append((epid.col, f"{epid.label} {values[epid.col]} already exists."))
        onset = self.field_like("onset")
        if onset and isinstance(values.get(onset.col), datetime) and values[onset.col].date() > date.today():
            errors.append((onset.col, "Date of onset cannot be in the future."))
        return values, errors

    def prepare_new(self, raw):
        """Fill the SN and district code when left blank, then validate a new case."""
        raw = dict(raw)
        sn = self.sn_field()
        if sn and blank(raw.get(sn.col)):
            raw[sn.col] = self.next_sn()
        district, code = self.field_like("district or"), self.field_like("epid. code")
        if self.code_map and district and code and blank(raw.get(code.col)):
            match = next((d for d in self.code_map if d.lower() == clean(raw.get(district.col) or "").lower()), None)
            if match:
                raw[code.col] = self.code_map[match]
        return self.validate(raw)

    def case_values(self, epid):
        """The entry columns of one case, as the form shows them (dates as yyyy-mm-dd)."""
        row = self.epids().get(epid)
        if row is None:
            raise ValueError(f"There is no case {epid}.")
        out = {}
        for f in self.fields:
            v = row[f.col - 1]
            if f.kind == "formula" or v is None:
                continue
            out[f.col] = (v.date().isoformat() if isinstance(v, datetime) else v.isoformat() if isinstance(v, date)
                          else str(int(v)) if isinstance(v, float) and v.is_integer() else str(v))
        return out

    def prepare_edit(self, epid, raw):
        """Validate the edited values of a case. Its SN stays as it is; its EPID # can be corrected, but not
        left blank or set to another case's."""
        old = self.epids().get(epid)
        if old is None:
            raise ValueError(f"There is no case {epid}.")
        raw = dict(raw)
        ef = self.field_like("epid #")
        if blank(raw.get(ef.col)):
            return {}, [(ef.col, f"{ef.label} is required.")]
        sn = self.sn_field()
        if sn:
            raw[sn.col] = old[sn.col - 1]
        district, code = self.field_like("district or"), self.field_like("epid. code")
        if self.code_map and district and code:
            match = next((d for d in self.code_map if d.lower() == clean(raw.get(district.col) or "").lower()), None)
            if match:
                raw[code.col] = self.code_map[match]
        return self.validate(raw, own_epid=epid)

    def update_case(self, epid, values):
        return self.write(lambda ws: self._set_cells(ws, epid, values))

    def delete_case(self, epid):
        """Remove a case's row. Rows below move up, and their formulas are written again for their new rows."""
        ecol = self.field_like("epid #").col
        formulas = [f for f in self.fields if f.kind == "formula" and f.template]

        def edit(ws):
            last = last_data_row(ws, self.header_row, len(self.fields))
            row = next((r for r in range(self.header_row + 1, last + 1)
                        if str(ws.cell(r, ecol).value or "").strip().upper() == epid), None)
            if row is None:
                raise ValueError(f"There is no case {epid}.")
            ws.delete_rows(row)
            for r in range(row, last):
                for f in formulas:
                    ws.cell(r, f.col).value = re.sub(rf"(?<=[A-Z]){self.last_row}(?!\d)", str(r), f.template)
            return row
        return self.write(edit)

    def write(self, edit):
        shutil.copy2(self.path, self.path.with_suffix(".bak.xlsx"))
        wb = load_workbook(self.path)
        ws = wb.active
        result = edit(ws)
        wb.save(self.path)
        self.reload()
        return result

    def append(self, values):
        return self.write(lambda ws: self._append_row(ws, values))

    def _append_row(self, ws, values):
        src = last_data_row(ws, self.header_row, len(self.fields))
        row = src + 1
        for f in self.fields:
            cell, prev = ws.cell(row, f.col), ws.cell(src, f.col)
            if prev.has_style:
                cell.font, cell.border, cell.fill = copy(prev.font), copy(prev.border), copy(prev.fill)
                cell.alignment, cell.protection = copy(prev.alignment), copy(prev.protection)
            cell.number_format = prev.number_format
            if f.kind == "formula":
                cell.value = re.sub(rf"(?<=[A-Z]){src}(?!\d)", str(row), f.template)
            else:
                cell.value = values.get(f.col)
                if f.kind == "date" and isinstance(cell.value, (int, float)):
                    cell.number_format = "General"
        extend_ranges(ws, src, row)
        return row

    def _set_cells(self, ws, epid, changes):
        ecol = self.field_like("epid #").col
        for r in range(self.header_row + 1, ws.max_row + 1):
            if str(ws.cell(r, ecol).value or "").strip().upper() == epid:
                for col, v in changes.items():
                    f, cell = self.fields[col - 1], ws.cell(r, col)
                    cell.value = v
                    if f.kind == "date" and isinstance(v, (int, float)):
                        cell.number_format = "General"
                    elif isinstance(v, datetime) and not cell.is_date:
                        cell.number_format = f.number_format
                return r
        return None

    def plan_import(self, header, rows, add_new=False, region=None):
        """Compare an uploaded table with the register, matching rows by EPID #. Nothing is written.

        With a region, only that region's cases are updated or added; other rows are listed as problems.
        """
        district_f = self.field_like("district or")
        by_key = {key(f.label): f for f in self.fields}
        cols, unknown, ignored = {}, [], []
        for i, h in enumerate(header):
            if blank(h):
                continue
            f = by_key.get(key(h))
            if not f:
                unknown.append(clean(h))
            elif f.kind == "formula":
                ignored.append(f.label)
            elif f not in cols.values():
                cols[i] = f
        epid_f, sn_f, name_f = self.field_like("epid #"), self.sn_field(), self.field_like("patient name")
        if epid_f not in cols.values():
            raise ValueError("The file needs an EPID # column so rows can be matched to cases.")
        epid_i = next(i for i, f in cols.items() if f is epid_f)
        current = self.epids()
        plan = {"rows": 0, "matched": 0, "changes": [], "adds": [], "unmatched": [], "errors": [],
                "ignored": ignored, "unknown": unknown, "_updates": {}, "_adds": []}
        seen, next_sn = set(), self.next_sn()
        for row in rows:
            row = list(row) + [None] * (len(header) - len(row))
            if all(blank(v) for v in row):
                continue
            plan["rows"] += 1
            epid = clean(row[epid_i]).upper() if not blank(row[epid_i]) else ""
            if not epid:
                plan["errors"].append({"epid": "—", "field": epid_f.label, "msg": "Row has no EPID #, so it was skipped."})
                continue
            if epid in seen:
                plan["errors"].append({"epid": epid, "field": epid_f.label, "msg": "Appears more than once in the file. Only the first row is used."})
                continue
            seen.add(epid)
            old = current.get(epid)
            if old is not None and district_f and not self.in_region(old[district_f.col - 1], region):
                plan["errors"].append({"epid": epid, "field": district_f.label,
                                       "msg": f"A case from {old[district_f.col - 1]}, outside {region} Region, so it was skipped."})
            elif old is not None:
                plan["matched"] += 1
                cells, upd = [], {}
                for i, f in cols.items():
                    if f in (epid_f, sn_f):
                        continue
                    v, err = self.convert(f, row[i])
                    if err:
                        plan["errors"].append({"epid": epid, "field": f.label, "msg": err[0].upper() + err[1:]})
                    elif v is not None and not same(old[f.col - 1], v):
                        upd[f.col] = v
                        cells.append({"field": f.label, "old": show(old[f.col - 1]), "new": show(v)})
                if upd:
                    plan["_updates"][epid] = upd
                    plan["changes"].append({"epid": epid, "name": show(old[name_f.col - 1]) if name_f else "", "cells": cells})
            elif add_new:
                raw = {f.col: row[i] for i, f in cols.items()}
                if sn_f and blank(raw.get(sn_f.col)):
                    raw[sn_f.col] = next_sn
                values, errs = self.prepare_new(raw)
                errs += [e for e in [self.district_error(values, region)] if e]
                if errs:
                    plan["errors"] += [{"epid": epid, "field": "New case", "msg": m} for _, m in errs]
                else:
                    plan["_adds"].append(values)
                    plan["adds"].append({"epid": epid, "name": show(values.get(name_f.col)) if name_f else ""})
                    next_sn += 1
            else:
                plan["unmatched"].append(epid)
        plan["cellCount"] = sum(len(c["cells"]) for c in plan["changes"])
        return plan

    def apply_import(self, plan):
        def edit(ws):
            for epid, upd in plan["_updates"].items():
                self._set_cells(ws, epid, upd)
            return [self._append_row(ws, v) for v in plan["_adds"]]
        if plan["_updates"] or plan["_adds"]:
            return self.write(edit)
        return []

    def export_xlsx(self, region=None):
        """Current cases (entry columns only; with a region, its cases only) as a workbook people can edit and upload again."""
        fields = [f for f in self.fields if f.kind != "formula"]
        district_f = self.field_like("district or")
        wb = Workbook()
        ws = wb.active
        ws.title = "Cases"
        ws.append([f.label for f in fields])
        for cell in ws[1]:
            cell.font = Font(bold=True)
        for r in self.existing:
            if not district_f or self.in_region(r[district_f.col - 1], region):
                ws.append([r[f.col - 1] for f in fields])
        for i, f in enumerate(fields, 1):
            ws.column_dimensions[get_column_letter(i)].width = max(10, min(40, len(f.label) + 4))
            if f.kind == "date":
                for (cell,) in ws.iter_rows(min_row=2, min_col=i, max_col=i):
                    if isinstance(cell.value, datetime):
                        cell.number_format = "dd/mm/yyyy"
        ws.freeze_panes = "C2"
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()


def read_table(name, data):
    """Header row and data rows from an uploaded .xlsx or .csv file."""
    import csv
    suffix = Path(name).suffix.lower()
    if suffix in (".xlsx", ".xlsm"):
        try:
            wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        except Exception:
            raise ValueError("That file could not be opened as an Excel workbook.")
        rows = [list(r) for r in wb.active.iter_rows(values_only=True)]
        wb.close()
    elif suffix == ".csv":
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("cp1252")
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        rows = list(csv.reader(io.StringIO(text), dialect))
    elif suffix == ".xls":
        raise ValueError("Old .xls files are not supported. Save it as .xlsx or .csv in Excel first.")
    else:
        raise ValueError("Upload an .xlsx or .csv file.")
    hdr = next((i for i, r in enumerate(rows[:10]) if any(key(c) == "epid" for c in r)), None)
    if hdr is None:
        raise ValueError("No header row with an EPID # column was found in the first 10 rows.")
    return rows[hdr], rows[hdr + 1:]
