"""Downloads: the line list (with or without patient names) and every report, as Excel workbooks.

The line list download has the workbook's own columns (Table14), so it can be filled in, sent back and uploaded.
Reports follow the regional style: an upper-case title, the period and filters, compact tables with C and D
columns, a bold total row, alert cells amber and epidemic cells red.
"""
import io

from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .linelist import FIELDS, display

THIN = Side(style="thin", color="000000")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
BOLD = Font(bold=True)
HEAD = PatternFill("solid", fgColor="D9E1F2")
FILL = {"alert": PatternFill("solid", fgColor="FFC000"), "epidemic": PatternFill("solid", fgColor="FF0000")}
CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)


def to_bytes(wb):
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------- the line list ----------
def linelist_xlsx(qs, title, names=True):
    wb = Workbook()
    ws = wb.active
    ws.title = "Outbreak linelist"
    cols = [f for f in FIELDS if names or not f.pii]
    headers = [f.header for f in cols]
    at = headers.index("NNNNN") + 1
    headers[at:at] = ["EPID", "Epi Week"]
    ws["A1"], ws["A2"] = title, ("Patient names removed. " if not names else "") + f"{qs.count()} cases."
    ws["A1"].font = Font(bold=True, size=13)
    ws.append([])
    ws.append(headers)
    for c in ws[4]:
        c.font, c.fill, c.border = BOLD, HEAD, BOX
    for case in qs.select_related("reporting_subdistrict", "residence_subdistrict").iterator():
        row = [display(case, f) for f in cols]
        row[at:at] = [case.epid, case.epi_week]
        ws.append(row)
    ws.freeze_panes = ws.cell(row=5, column=at + 2)
    ws.auto_filter.ref = f"A4:{get_column_letter(len(headers))}{max(ws.max_row, 4)}"
    for i, h in enumerate(headers, 1):
        ws.column_dimensions[get_column_letter(i)].width = max(8, min(28, len(h) + 4))
    return to_bytes(wb)


# ---------- reports ----------
def heading(ws, rep, width):
    ws["A1"] = rep["title"]
    ws["A1"].font = Font(bold=True, size=13)
    ws["A2"] = f"{rep['period']} · {rep['cases']} cases with a valid EPID · data as of {rep['asOf']}"
    if rep.get("otherRegion"):
        ws["A3"] = f"{rep['otherRegion']} cases living in other regions are not included."
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=max(width, 6))
    return 5


def cell(ws, r, c, v, bold=False, fill=None, center=False):
    x = ws.cell(row=r, column=c, value=v)
    x.border = BOX
    if bold:
        x.font = BOLD
    if fill:
        x.fill = fill
    if center:
        x.alignment = CENTER
    return x


def table(ws, r, title, headers, rows, total=None):
    """A titled table; rows are lists. Returns the next free row."""
    if title:
        ws.cell(row=r, column=1, value=title).font = Font(bold=True, size=11)
        r += 1
    for j, h in enumerate(headers, 1):
        cell(ws, r, j, h, bold=True, fill=HEAD, center=True)
    for row in rows:
        r += 1
        for j, v in enumerate(row, 1):
            cell(ws, r, j, v, center=j > 1)
    if total:
        r += 1
        for j, v in enumerate(total, 1):
            cell(ws, r, j, v, bold=True, center=j > 1)
    return r + 2


def week_head(rep):
    return [str(w["w"]) for w in rep["weeks"]]


def cfr(v):
    return "—" if v is None else v


def weekly_sheet(ws, rep):
    weeks, r = week_head(rep), heading(ws, rep, 8)
    head = [rep["areaLabel"], "Sub-district", "Population", "Alert", "Epidemic", "", *weeks, "Total"]
    for j, h in enumerate(head, 1):
        cell(ws, r, j, h, bold=True, fill=HEAD, center=True)
    for g in rep["groups"]:
        for s in g["rows"]:
            for k, key in enumerate(("c", "d")):
                r += 1
                lead = [g["area"], s["label"], s["population"], s["alert"], s["epidemic"]] if k == 0 else ["", "", "", "", ""]
                for j, v in enumerate(lead + [key.upper()] + s[key] + [s["cases" if key == "c" else "deaths"]], 1):
                    st = s["status"][j - 7] if key == "c" and 7 <= j < 7 + len(weeks) else ""
                    cell(ws, r, j, v, fill=FILL.get(st), center=j > 2)
        for k, key in enumerate(("c", "d")):
            r += 1
            vals = [f"{g['area']} total" if k == 0 else "", "", "", "", "", key.upper()] + g["total"][key] + [g["total"]["cases" if key == "c" else "deaths"]]
            for j, v in enumerate(vals, 1):
                cell(ws, r, j, v, bold=True, center=j > 2)
    for k, key in enumerate(("c", "d")):
        r += 1
        vals = [rep["region"] if k == 0 else "", "", "", "", "", key.upper()] + rep["total"][key] + [rep["total"]["cases" if key == "c" else "deaths"]]
        for j, v in enumerate(vals, 1):
            cell(ws, r, j, v, bold=True, center=j > 2)
    ws.freeze_panes = "G6"
    legend(ws, r + 2)


def legend(ws, r):
    ws.cell(row=r, column=1, value="Alert").fill = FILL["alert"]
    ws.cell(row=r, column=2, value="Epidemic").fill = FILL["epidemic"]


def district_sheet(ws, rep):
    weeks, r = week_head(rep), heading(ws, rep, 8)
    cell(ws, r, 1, rep["areaLabel"], bold=True, fill=HEAD)
    for i, w in enumerate(weeks + ["Total"]):
        ws.merge_cells(start_row=r, start_column=2 + 2 * i, end_row=r, end_column=3 + 2 * i)
        cell(ws, r, 2 + 2 * i, w, bold=True, fill=HEAD, center=True)
        cell(ws, r + 1, 2 + 2 * i, "C", bold=True, fill=HEAD, center=True)
        cell(ws, r + 1, 3 + 2 * i, "D", bold=True, fill=HEAD, center=True)
    cell(ws, r + 1, 1, "", fill=HEAD)
    r += 1
    for row in rep["rows"] + [{"label": rep["region"] + " total", **rep["total"], "status": [""] * len(weeks)}]:
        r += 1
        bold = row is not None and row["label"].endswith(" total")
        cell(ws, r, 1, row["label"], bold=bold)
        for i in range(len(weeks)):
            cell(ws, r, 2 + 2 * i, row["c"][i], bold=bold, fill=FILL.get(row["status"][i]), center=True)
            cell(ws, r, 3 + 2 * i, row["d"][i], bold=bold, center=True)
        cell(ws, r, 2 + 2 * len(weeks), row["cases"], bold=True, center=True)
        cell(ws, r, 3 + 2 * len(weeks), row["deaths"], bold=True, center=True)
    ws.freeze_panes = "B7"
    legend(ws, r + 2)


def regional_sheet(ws, rep):
    r = heading(ws, rep, 4)
    t = rep["total"]
    r = table(ws, r, f"Cases and deaths by {rep['areaLabel'].lower()}", [rep["areaLabel"], "Cases", "Deaths", "CFR %"],
              [[a["label"], a["cases"], a["deaths"], cfr(a["cfr"])] for a in rep["areas"]], ["Total", t["cases"], t["deaths"], cfr(t["cfr"])])
    r = table(ws, r, "Cases and deaths by age group (years)", ["Age group", "Cases", "Deaths", "CFR %"],
              [[a["label"], a["cases"], a["deaths"], cfr(a["cfr"])] for a in rep["ages"]], ["Total", t["cases"], t["deaths"], cfr(t["cfr"])])
    r = table(ws, r, "Cases and deaths by sex", ["Sex", "Cases", "Deaths"],
              [[a["label"], a["cases"], a["deaths"]] for a in rep["sexes"]], ["Total", t["cases"], t["deaths"]])
    r = table(ws, r, "Cases and deaths by final lab result", ["Final lab result", "Cases", "Deaths"],
              [[a["label"], a["cases"], a["deaths"]] for a in rep["pathogens"]], ["Total", t["cases"], t["deaths"]])
    table(ws, r, "Cases and deaths by sub-district", [rep["areaLabel"], "Sub-district", "Cases", "Deaths", "CFR %"],
          [[a["area"], a["label"], a["cases"], a["deaths"], cfr(a["cfr"])] for a in rep["subdistricts"]],
          ["Total", "", t["cases"], t["deaths"], cfr(t["cfr"])])


def epicurve_sheet(ws, rep):
    r = heading(ws, rep, 6)
    weeks = week_head(rep)
    top = r
    r = table(ws, r, None, ["Epi week", *[s["label"] for s in rep["series"]], "Total"],
              [[w, *[s["values"][i] for s in rep["series"]], sum(s["values"][i] for s in rep["series"])] for i, w in enumerate(weeks)],
              ["Total", *[s["total"] for s in rep["series"]], rep["cases"]])
    chart = BarChart()
    chart.type, chart.grouping, chart.overlap = "col", "stacked", 100
    chart.title, chart.y_axis.title, chart.x_axis.title = "Cases by epi week", "Cases", "Epi week"
    n = len(weeks)
    chart.add_data(Reference(ws, min_col=2, max_col=1 + len(rep["series"]), min_row=top, max_row=top + n), titles_from_data=True)
    chart.set_categories(Reference(ws, min_col=1, min_row=top + 1, max_row=top + n))
    for s, color in zip(chart.series, ("8B1A1A", "E07B00", "8C8C8C", "C9C9C9")):
        s.graphicalProperties.solidFill = color
    chart.width, chart.height = 26, 10
    ws.add_chart(chart, f"{get_column_letter(len(rep['series']) + 4)}{top}")


def counts_sheet(ws, rep):
    r = heading(ws, rep, 4)
    if rep["kind"] == "vaccination":
        r = table(ws, r, "Indicators", ["Indicator", "Number", "Of", "%", ""],
                  [[i["label"], i["n"], i["of"], cfr(i["pct"]), i["note"]] for i in rep["indicators"]])
    for t in rep["tables"]:
        r = table(ws, r, t["title"], [t["title"], "Cases", "%"], [[x["label"], x["n"], cfr(x["pct"])] for x in t["rows"]],
                  ["Total", t["total"], 100.0 if t["total"] else "—"])
    if rep["kind"] == "vaccination":
        table(ws, r, "Data completeness", ["Field", "Missing", "% complete"],
              [[c["label"], c["missing"], cfr(c["pct"])] for c in rep["completeness"]])
    else:
        table(ws, r, "Pathogens found (final lab result)", ["Pathogen", "Cases"], [[p["label"], p["n"]] for p in rep["pathogens"]])


def thresholds_sheet(ws, rep):
    r = heading(ws, rep, 8)
    weeks = week_head(rep)
    for ch_ in rep["charts"]:
        ws.cell(row=r, column=1, value=ch_["title"]).font = BOLD
        top = r + 1
        r = table(ws, top, None, ["Epi week", "Cases", "Deaths", "Alert", "Epidemic"],
                  [[w, ch_["c"][i], ch_["d"][i], ch_["alert"], ch_["epidemic"]] for i, w in enumerate(weeks)])
        chart = LineChart()
        chart.title, chart.y_axis.title, chart.x_axis.title = ch_["label"], "No. of cases & deaths", "Epi week"
        chart.add_data(Reference(ws, min_col=2, max_col=5, min_row=top, max_row=top + len(weeks)), titles_from_data=True)
        chart.set_categories(Reference(ws, min_col=1, min_row=top + 1, max_row=top + len(weeks)))
        for s, color, dash in zip(chart.series, ("1F3864", "C00000", "FFC000", "FF0000"), (None, None, "dash", "dash")):
            s.graphicalProperties.line.solidFill = color
            if dash:
                s.graphicalProperties.line.dashStyle = dash
        chart.width, chart.height = 22, 8
        ws.add_chart(chart, f"G{top}")
        r = max(r, top + 18)


def dashboard_sheet(ws, rep):
    r = heading(ws, rep, 6)
    t = rep["total"]
    r = table(ws, r, "Headline figures", ["Measure", "Value"],
              [["Cases", t["cases"]], ["Deaths", t["deaths"]], ["CFR %", cfr(t["cfr"])], ["Confirmed %", cfr(rep["confirmedPct"])],
               [f"Cases in epi week {rep['week']['w']} of {rep['week']['y']}", rep["weekCases"]],
               ["Sub-districts in alert this week", len(rep["alert"])], ["Sub-districts in epidemic this week", len(rep["epidemic"])]])
    table(ws, r, f"By {rep['areaLabel'].lower()}", [rep["areaLabel"], "Cases", "Deaths", "CFR %", f"Week {rep['week']['w']}", "Status"],
          [[a["label"], a["cases"], a["deaths"], cfr(a["cfr"]), a["week"], a["status"].title()] for a in rep["areas"]],
          ["Total", t["cases"], t["deaths"], cfr(t["cfr"]), rep["weekCases"], ""])


SHEETS = {"weekly": weekly_sheet, "district": district_sheet, "regional": regional_sheet, "epicurve": epicurve_sheet,
          "vaccination": counts_sheet, "laboratory": counts_sheet, "thresholds": thresholds_sheet, "dashboard": dashboard_sheet}


def report_xlsx(rep):
    wb = Workbook()
    ws = wb.active
    ws.title = rep["name"][:31]
    SHEETS[rep["kind"]](ws, rep)
    ws.column_dimensions["A"].width = 26
    if rep["kind"] in ("weekly", "regional"):
        ws.column_dimensions["B"].width = 22
    ws.sheet_view.showGridLines = False
    return to_bytes(wb)
