"""The AFP district/region report as a print-ready Excel workbook."""
import re

from core.branding import logo_for


def report_xlsx(rep, unit):
    """The district report as a print-ready workbook: title, bordered table, SUM totals, source note."""
    from io import BytesIO
    from openpyxl import Workbook
    from openpyxl.drawing.image import Image as XLImage
    from openpyxl.drawing.spreadsheet_drawing import AnchorMarker, OneCellAnchor
    from openpyxl.drawing.xdr import XDRPositiveSize2D
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils.units import pixels_to_EMU

    wb = Workbook()
    ws = wb.active
    ws.title = "Report"
    thin = Side(style="thin", color="000000")
    box = Border(left=thin, right=thin, top=thin, bottom=thin)
    tnr = lambda **k: Font(name="Times New Roman", size=12, **k)
    widths = (6, 38, 24, 28)
    for col, width in zip("ABCD", widths):
        ws.column_dimensions[col].width = width
    t = 1
    logo = logo_for(unit)
    if logo.exists():
        # Letterhead: logo centred over the table in its own row.
        img = XLImage(str(logo))
        img.width, img.height = round(84 * img.width / img.height), 84
        table_px = sum(w * 7 + 5 for w in widths)
        left = (table_px - img.width) // 2 - (widths[0] * 7 + 5)
        img.anchor = OneCellAnchor(_from=AnchorMarker(col=1, colOff=pixels_to_EMU(max(left, 0)), row=0, rowOff=pixels_to_EMU(6)),
                                   ext=XDRPositiveSize2D(pixels_to_EMU(img.width), pixels_to_EMU(img.height)))
        ws.add_image(img)
        ws.row_dimensions[1].height = 72
        t = 2
    ws.merge_cells(start_row=t, start_column=1, end_row=t, end_column=4)
    title = ws.cell(t, 1, rep["title"])
    title.font = Font(name="Times New Roman", size=14, bold=True)
    title.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[t].height = 40
    for c, h in enumerate(rep["header"], 1):
        cell = ws.cell(t + 1, c, h)
        cell.font, cell.border = tnr(bold=True), box
        cell.alignment = Alignment(horizontal="center" if c > 2 else "left", vertical="bottom", wrap_text=True)
    ws.row_dimensions[t + 1].height = 34
    first = r = t + 2
    for row in rep["rows"]:
        for c, v in enumerate(row, 1):
            cell = ws.cell(r, c, v if v != "" else None)
            cell.font, cell.border = tnr(bold=c <= 2), box
            cell.alignment = Alignment(horizontal="center" if c > 2 else "left", vertical="bottom")
        ws.row_dimensions[r].height = 22
        r += 1
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=2)
    ws.cell(r, 1, str(rep.get("totalLabel") or "REGIONAL TOTAL"))
    ws.cell(r, 3, f"=SUM(C{first}:C{r - 1})")
    ws.cell(r, 4, f"=SUM(D{first}:D{r - 1})")
    for c in range(1, 5):
        cell = ws.cell(r, c)
        cell.font, cell.border = tnr(bold=True), box
        cell.alignment = Alignment(horizontal="center" if c > 2 else "left", vertical="bottom")
    for k, (text, height, italic) in enumerate(((rep.get("foot", ""), 48, True), (rep.get("rights", ""), 18, False)), 2):
        ws.merge_cells(start_row=r + k, start_column=1, end_row=r + k, end_column=4)
        note = ws.cell(r + k, 1, text)
        note.font = Font(name="Times New Roman", size=10, italic=italic, color="333333" if italic else "555555")
        note.alignment = Alignment(wrap_text=True, vertical="top")
        ws.row_dimensions[r + k].height = height
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.orientation = "portrait"
    ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_area = f"A1:D{r + 3}"
    # Background colour picked on the report page; white leaves the cells unfilled.
    paper = str(rep.get("paper") or "")
    if re.fullmatch(r"#[0-9a-fA-F]{6}", paper) and paper.lower() != "#ffffff":
        fill = PatternFill("solid", fgColor=paper[1:].upper())
        for row in ws.iter_rows(min_row=1, max_row=r + 3, min_col=1, max_col=4):
            for cell in row:
                cell.fill = fill
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
