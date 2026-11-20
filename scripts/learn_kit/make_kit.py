"""SS-73: the playground's starter kit, Green Villa's paperwork (docs/plans/guided-demo-plan.md section 16.2).

The files a real project runs on, made here so they are versioned with the missions that use them, and fixed (no
randomness, no dates that move): run it again and the same files come out. Each file is used by a mission, and the
catch in it is one Mesiri itself shows when the file is brought in (the test reads the files through Mesiri's own
importers: backend/tests/unit/test_learn_kit_ss73.py).

    python scripts/learn_kit/make_kit.py        # writes apps/dashboard/public/learn/kit/

Names and story are the sample company's (backend .../organizations/sample_story.py): Green Villa with its Main block
and Annex, the work its site reports (the estimate's lines use the same names, so that work counts on them), Malabar
Cements Agency, Thrissur Blocks, Joy Tiling Works. No phone numbers or GSTINs: made-up ones could be a real business's.
"""

from __future__ import annotations

import io
import json
import pathlib
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend" / "src"))
from mesiri.application.learn import green_villa  # noqa: E402, I001  (after the path)

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import gv_drawings  # noqa: E402

OUT = ROOT / "apps" / "dashboard" / "public" / "learn" / "kit"

ESTIMATE = "Green Villa - estimate.xlsx"
MATERIALS = "Green Villa - materials and suppliers.xlsx"
CONTRACT = "Green Villa - contract summary.pdf"
PLAN = "Green Villa - ground floor plan A-101.pdf"
QUOTES = ("Quote - Malabar Cements Agency.pdf", "Quote - Kerala Steels.pdf", "Quote - Sri Hardwares.pdf")
CHALLAN = "Malabar - delivery challan.pdf"
BILL = "Malabar - bill MCA-INV-2611.pdf"
MEASURE = "Joy Tiling - measurement sheet.pdf"
SUB_BILL = "Joy Tiling - bill JTW-014.pdf"
# LRN-F5 (project bible section 5): the rest of a real project's paperwork.
DRAWING_SET = "Green Villa - drawing set rev A.pdf"
PERMIT = "Green Villa - building permit.pdf"
RATE_CARD = "Periyar - rate card.pdf"
RETURN_NOTE = "Malabar - return note GV-RN-014.pdf"
HIRE_BILL = "Kerala Earthmovers - hire bill KEE-0118.pdf"
HANDOVER = "Green Villa - handover certificate.pdf"
ZIP = "green-villa-starter-kit.zip"

#: The estimate and its materials per unit: Green Villa's own data (backend .../learn/green_villa.py), the one source
#: the 62-day plan also reads (project bible D2), so the file people bring in and the BOQ the plan puts in agree.
SECTIONS = green_villa.ESTIMATE
NORMS = green_villa.NORMS
#: The work the sample site reports for Green Villa (sample_story.DEMO_WORK, Main block and Annex): each must be a line
#: here with the same unit, or that work can't count on the BOQ. "Plastering" is a catch too: three plastering lines
#: (internal, external, ceiling), so Mesiri suggests none and the person picks (the BOQ page's "Change line").
SITE_WORK = (("Parapet wall", "rmt"), ("Brick work in partitions", "sqm"), ("Plastering", "sqm"), ("Electrical conduits", "nos"),
             ("Site clearance", "sqm"), ("Excavation", "cum"), ("Anti-termite treatment", "sqm"), ("PCC", "cum"),
             ("Footing concreting", "cum"))

#: The materials workbook (the materials import's four sheets). Rows already in the sample company (Cement, Malabar, Joy)
#: are the catch: the preview shows them "already in Mesiri, left as they are", so importing twice is safe.
ITEMS = (
    ("Finishing", "Tiles", "Vitrified tiles 600x600", "sqft", "VT-600", "floor tiles"),
    ("Finishing", "Tiles", "Wall tiles 300x450", "sqft", "WT-345", "bathroom tiles"),
    ("Finishing", "Stone", "Black granite 18mm", "sqft", "GR-18", "granite"),
    ("Plumbing & CP", "Pipes", "CPVC pipe 1 inch", "nos", "CP-25", "cpvc"),
    ("Electrical", "Wires", "FR wire 1.5 sq mm", "rolls", "FR-15", "wire"),
    ("Finishing", "Paint", "Interior emulsion", "litres", "PT-INT", "emulsion"),
    ("Masonry", None, "Cement", "bags", None, "OPC 53, siment"),
)
VENDORS = (
    ("Malabar Cements Agency", None, None, "Palakkad", None, None),
    ("Colour World Paints", None, None, "Round North, Thrissur", 12500, "2026-11-01"),
    ("Kerala Tiles and Sanitary", None, None, "Chalakudy", None, None),
    ("Joy Tiling Works", None, None, "Angamaly", None, None),
)
OPENING = (("Green Villa", "Main block", "Vitrified tiles 600x600", 120, None),
           ("Green Villa", "Annex", "CPVC pipe 1 inch", 24, None))
MINIMUM = (("Green Villa", "Main block", "Cement", 100, 200), ("Green Villa", "Annex", "Cement", 40, 100))

#: The contract summary (the "won" chapter types these in).
CONTRACT_TERMS = (
    ("Client", green_villa.CLIENT["name"]),
    ("Site", green_villa.CLIENT["address"]),
    ("Agreement no.", green_villa.CONTRACT["contract_no"]),
    ("Signed on", "20 October 2026"),
    ("Contract value", f"{{value}}, GST extra at {green_villa.CONTRACT['gst_pct']}% (the estimate's total)"),
    ("Work starts", "2 November 2026"),
    ("Handover", "31 July 2027 (9 months)"),
    ("Mobilisation advance", "{advance} (10% of the contract value), paid on signing"),
    ("Advance recovery", f"{green_villa.CONTRACT['advance_recovery_pct']}% of each RA bill, until the advance is back"),
    ("Retention", f"{green_villa.CONTRACT['retention_pct']}% of each RA bill, released after the defects period"),
    ("Defects period", f"{green_villa.CONTRACT['defect_liability_months']} months from handover"),
    ("Billing", green_villa.CONTRACT["payment_terms"]),
    ("Delay", "Rs 25,000 per week of delay beyond handover, at most 5% of the contract value"),
)

#: The ground floor's rooms (green_villa, drawn by gv_drawings): each room's name, its size in cm under it, and the
#: area the architect printed. Bedroom 2 is drawn 360 x 360 but labelled 163 sq ft, Bedroom 1's area: the catch.
ROOMS = green_villa.GROUND_FLOOR_ROOMS

#: The quotation request: 300 bags of cement and 2,000 kg of steel for Main block. Malabar is cheapest for cement,
#: Kerala Steels cheapest in total; buying each item from its cheapest (cement Malabar, steel Kerala) is cheaper
#: still: the catch Quotations' compare shows (lowest per item, lowest total).
RFQ_ITEMS = (("Cement (OPC 53)", "bags", 300), ("Steel (TMT Fe 500)", "kg", 2000))
QUOTE_RATES = {"Malabar Cements Agency": (400, 72), "Kerala Steels": (412, 66), "Sri Hardwares": (408, 70)}
QUOTE_FROM = {"Malabar Cements Agency": ("Palakkad", "MCA/Q/0412"), "Kerala Steels": ("Industrial Estate, Kalamassery", "KS/Q/2280"),
              "Sri Hardwares": ("MG Road, Thrissur", "SH/Q/117")}
#: The delivery: 190 bags against an order for 200 (the catch: 10 still to come on the order).
ORDERED, DELIVERED = 200, 190
#: The bill: Rs 410 a bag against the order's Rs 400 (the catch: the bill's rate differs from the delivery's).
BILL_RATE, CEMENT_GST = 410, 28
#: Joy Tiling's flooring: measured room by room from the plan (rooms with floor tiles), billed for more.
TILED = ("LIVING", "DINING", "KITCHEN", "BEDROOM-1", "BEDROOM-2", "SIT OUT")
TILING_RATE, TILING_BILLED = 320, 92.0

#: What the Learn page shows for each file: what it is, where it goes, what to look for.
MANIFEST = (
    {"file": ESTIMATE, "title": "The estimate", "kind": "excel", "page": "/boq",
     "what": "Every piece of work with its quantity, the client's rate and your labour and material cost.",
     "goes": "BOQ and budget: Import from Excel",
     "catch": "Three lines have no cost yet, one is priced below what it costs, and the site's plastering could be any of three lines: Mesiri shows all three, and asks you which plastering."},
    {"file": MATERIALS, "title": "Materials and suppliers", "kind": "excel", "page": "/bring-data",
     "what": "New items, the shops you buy from, what you owe one of them, opening stock and minimums.",
     "goes": "Bring your data: Materials, vendors and opening stock",
     "catch": "Cement, Malabar and Joy Tiling are already in Mesiri: the preview says so and leaves them as they are."},
    {"file": CONTRACT, "title": "Contract summary", "kind": "pdf", "page": "/planning/setup",
     "what": "The client, the dates, the advance, retention and the defects period.",
     "goes": "Project start: the contract step",
     "catch": "The handover date you type sets the schedule's finish."},
    {"file": PLAN, "title": "Ground floor plan (A-101)", "kind": "pdf", "page": "/planning/drawing-check",
     "what": "The architect's plan: every room with its size and the area printed on it.",
     "goes": "Drawing check",
     "catch": "One bedroom is labelled bigger than it is drawn: Mesiri works out the real area and says the label was copied."},
    {"file": QUOTES[0], "title": "Three quotations: cement and steel", "kind": "pdf", "page": "/procurement/quotations",
     "also": list(QUOTES[1:]),
     "what": "Malabar, Kerala Steels and Sri Hardwares quote for 300 bags of cement and 2,000 kg of steel.",
     "goes": "Quotations: a request to the three, then their rates",
     "catch": "The cheapest for cement is not the cheapest in total, and splitting the order beats both. The compare shows each."},
    {"file": CHALLAN, "title": "Delivery challan", "kind": "pdf", "page": "/procurement/orders",
     "what": "What came on Malabar's lorry for your cement order.",
     "goes": "Orders: Material came",
     "catch": "The lorry brought 190 bags against an order for 200: the order keeps 10 still to come."},
    {"file": BILL, "title": "Malabar's bill", "kind": "pdf", "page": "/finance/vendors",
     "what": "The supplier's bill for the cement that came.",
     "goes": "Suppliers: Malabar, match the bill to the delivery",
     "catch": "The bill's rate is Rs 10 a bag more than the order: Mesiri shows the difference before you pay."},
    {"file": MEASURE, "title": "Joy Tiling: measurement and bill", "kind": "pdf", "page": "/subcontract/bills",
     "also": [SUB_BILL],
     "what": "The flooring measured room by room, and the subcontractor's bill for it.",
     "goes": "Subcontract: measurement, then the bill",
     "catch": "The bill asks for more square metres than were measured: Mesiri says how many more."},
    {"file": DRAWING_SET, "title": "The drawing set (8 sheets)", "kind": "pdf", "page": "/planning/drawing-check",
     "what": "The architect's and consultants' set: both floor plans, the elevation, a section, the footings, the columns, electrical and plumbing.",
     "goes": "Drawing check, then Documents (each sheet kept, its rooms and footings tracked as places)",
     "catch": "The first-floor toilet is drawn smaller than the one below it, and the roof is +660 on the elevation but +655 on the section: Mesiri asks which is right before the slab is cast."},
    {"file": PERMIT, "title": "Building permit", "kind": "pdf", "page": "/planning/documents",
     "what": "The municipality's permit: the plot, the built-up area, the floors allowed.",
     "goes": "Documents: Approvals",
     "catch": "None: it is kept where everyone on the project can find the latest one."},
    {"file": RATE_CARD, "title": "Periyar's rate card", "kind": "pdf", "page": "/procurement/rates",
     "what": "The rates agreed with the sand and aggregate supplier for the year.",
     "goes": "Rates (and the rate on each order)",
     "catch": "M sand is agreed at Rs 1,650 a cum, but the later loads come at Rs 1,750: Rates shows the rise."},
    {"file": RETURN_NOTE, "title": "Return note", "kind": "pdf", "page": "/procurement/returns",
     "what": "Six torn bags from Malabar's load sent back.",
     "goes": "Returns: from the delivery",
     "catch": "The debit note takes Rs 2,400 off what you owe Malabar at once, before their next bill."},
    {"file": HIRE_BILL, "title": "A hire bill", "kind": "pdf", "page": "/equipment/hire",
     "what": "The concrete mixer hired for the Annex, billed by the hour.",
     "goes": "Equipment: Hire check",
     "catch": "42 hours billed, 36 logged on site: Mesiri shows the 6 hours (Rs 2,700) to question."},
    {"file": HANDOVER, "title": "Handover certificate", "kind": "pdf", "page": "/planning/documents",
     "what": "Green Villa handed over to Dr. Anand Krishnan, the defects period starting.",
     "goes": "Documents: Handover",
     "catch": "None: it starts the 12-month defects period, after which the retention is released."},
)


def estimate_bytes() -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    book = Workbook()
    sheet = book.active
    sheet.title = "BOQ"
    sheet.append([f"GREEN VILLA, PUTHUR ROAD, THRISSUR: ESTIMATE (G+1 residence and annex, "
                  f"{sum(green_villa.BUILT_UP.values()):,} sq ft built-up)"])
    sheet.append(["Client: Dr. Anand Krishnan. Rates in rupees per unit. Labour and material rates are our cost."])
    sheet.append([])
    header = ["Item no.", "Description", "Unit", "Qty", "Rate", "Labour rate", "Material rate", "Amount"]
    sheet.append(header)
    bold = Font(bold=True)
    for cell in sheet[4]:
        cell.font = bold
        cell.fill = PatternFill("solid", fgColor="F2EEE6")
    sheet["A1"].font = Font(bold=True, size=13)
    total = 0.0
    for heading, lines in SECTIONS:
        sheet.append([None, heading])
        sheet.cell(sheet.max_row, 2).font = bold
        for code, work, unit, qty, rate, labour, material in lines:
            amount = qty * rate
            total += amount
            sheet.append([code, work, unit, qty, rate, labour, material, amount])
    sheet.append([])
    sheet.append([None, "TOTAL", None, None, None, None, None, total])
    sheet.cell(sheet.max_row, 2).font = bold
    sheet.cell(sheet.max_row, 8).font = bold
    for col, width in zip("ABCDEFGH", (9, 36, 7, 10, 10, 12, 13, 14), strict=True):
        sheet.column_dimensions[col].width = width
    for row in sheet.iter_rows(min_row=5, min_col=4, max_col=8):
        for cell in row:
            cell.number_format = "#,##0.##"
            cell.alignment = Alignment(horizontal="right")

    norms = book.create_sheet("Materials per unit")
    norms.append(["Item no.", "Work", "Material", "Quantity per unit", "Material unit"])
    for cell in norms[1]:
        cell.font = bold
    for row in NORMS:
        norms.append(list(row))
    norms.column_dimensions["B"].width = 24
    norms.column_dimensions["C"].width = 16
    norms.column_dimensions["D"].width = 18
    return _save(book)


def materials_bytes() -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    book = Workbook()
    book.remove(book.active)
    for title, columns, rows in (
        ("Items", ("Main category", "Sub-category", "Item", "Unit", "Item code", "Other names"), ITEMS),
        ("Vendors", ("Vendor", "Phone", "GSTIN", "Address", "Opening balance", "Balance date"), VENDORS),
        ("Opening stock", ("Project", "Site", "Item", "Quantity", "Date"), OPENING),
        ("Minimum stock", ("Project", "Site", "Item", "Minimum", "Reorder qty"), MINIMUM),
    ):
        sheet = book.create_sheet(title)
        sheet.append(list(columns))
        for cell in sheet[1]:
            cell.font = Font(bold=True)
        for row in rows:
            sheet.append(list(row))
        for col in "ABCDEF":
            sheet.column_dimensions[col].width = 24
    return _save(book)


def contract_bytes() -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buffer = io.BytesIO()
    # invariant=1: no creation date or random id in the file, so the same input gives the same bytes.
    doc = SimpleDocTemplate(buffer, pagesize=A4, title="Green Villa: contract summary", author="Mesiri sample",
                            leftMargin=56, rightMargin=56, topMargin=56, bottomMargin=56, invariant=1)
    styles = getSampleStyleSheet()
    total = sum(qty * rate for _, lines in SECTIONS for _, _, _, qty, rate, _, _ in lines)
    value, advance = _rupees(total), _rupees(round(total / 10))
    table = Table([[k, v.format(value=value, advance=advance)] for k, v in CONTRACT_TERMS], colWidths=[140, 330])
    table.setStyle(TableStyle([
        ("FONT", (0, 0), (0, -1), "Helvetica-Bold", 10), ("FONT", (1, 0), (1, -1), "Helvetica", 10),
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#e7e1d6")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7), ("TOPPADDING", (0, 0), (-1, -1), 7),
    ]))
    doc.build([
        Paragraph("Green Villa: contract summary", styles["Title"]),
        Paragraph("Sample paperwork for learning Mesiri. The people and the project are made up.", styles["Italic"]),
        Spacer(1, 16), table, Spacer(1, 18),
        Paragraph("Signed for the contractor and the client on 20 October 2026.", styles["Normal"]),
    ])
    return buffer.getvalue()


def _styles():
    from reportlab.lib.styles import getSampleStyleSheet

    return getSampleStyleSheet()


def _doc(title: str, head: list[tuple[str, str]], table: list[list[str]], foot: list[str], *, note: str | None = None,
         widths: tuple[float, ...] = (230, 60, 70, 70, 80)) -> bytes:
    """A one-page business document: a title, the who/what lines, a table, the closing lines. Fixed bytes."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, title=title, author="Mesiri sample", leftMargin=50, rightMargin=50,
                            topMargin=50, bottomMargin=50, invariant=1)
    styles = _styles()
    info = Table([[k, v] for k, v in head], colWidths=[110, 400])
    info.setStyle(TableStyle([("FONT", (0, 0), (0, -1), "Helvetica-Bold", 9), ("FONT", (1, 0), (1, -1), "Helvetica", 9),
                              ("BOTTOMPADDING", (0, 0), (-1, -1), 3), ("TOPPADDING", (0, 0), (-1, -1), 3)]))
    body = Table(table, colWidths=list(widths), repeatRows=1)
    body.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9), ("FONT", (0, 1), (-1, -1), "Helvetica", 9),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f2eee6")), ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d9d1c3")), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    parts = [Paragraph(title, styles["Title"])]
    if note:
        parts.append(Paragraph(note, styles["Italic"]))
    parts += [Spacer(1, 10), info, Spacer(1, 14), body, Spacer(1, 12)]
    parts += [Paragraph(line, styles["Normal"]) for line in foot]
    parts += [Spacer(1, 16), Paragraph("Sample paperwork for learning Mesiri. The people and businesses are made up.",
                                       styles["Italic"])]
    doc.build(parts)
    return buffer.getvalue()


def plan_bytes() -> bytes:
    """A-101 issued alone (rev B), A3 at 1:50, the same drawing as the set's first sheet."""
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=gv_drawings.landscape(gv_drawings.A3), invariant=1)
    pdf.setTitle("Green Villa: ground floor plan A-101")
    gv_drawings.ground_floor(pdf, rev="B")
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def quote_bytes(vendor: str) -> bytes:
    place, ref = QUOTE_FROM[vendor]
    rates = QUOTE_RATES[vendor]
    rows = [["Item", "Unit", "Qty", "Rate (Rs)", "Amount (Rs)"]]
    total = 0
    for (item, unit, qty), rate in zip(RFQ_ITEMS, rates, strict=True):
        rows.append([item, unit, f"{qty:,}", f"{rate:,}", _rupees(qty * rate)[3:]])
        total += qty * rate
    rows.append(["Total, before GST", "", "", "", _rupees(total)[3:]])
    return _doc(f"Quotation: {vendor}", [("From", f"{vendor}, {place}"), ("Quotation no.", ref), ("To", "Green Villa Builders"),
                                        ("For", "Green Villa, Main block, Puthur Road, Thrissur"), ("Date", "18 November 2026")],
                rows, ["Rates include unloading at site. GST extra: cement 28%, steel 18%.", "Valid for 7 days. Delivery in 2 days from the order."])


def challan_bytes() -> bytes:
    rows = [["Item", "Unit", "Ordered", "Sent", ""], ["Cement (OPC 53)", "bags", f"{ORDERED}", f"{DELIVERED}", ""]]
    return _doc("Delivery challan", [("From", "Malabar Cements Agency, Palakkad"), ("Challan no.", "MCA/DC/2611"),
                                     ("To", "Green Villa, Main block, Puthur Road, Thrissur"), ("Against", "Your order for cement"),
                                     ("Date", "20 November 2026"), ("Vehicle", "Lorry (sample)")],
                rows, [f"{ORDERED - DELIVERED} bags to follow with the next load.", "Received by: ____________   Site seal: ____________"],
                note="What came on the lorry, signed at the gate.")


def bill_bytes() -> bytes:
    amount = DELIVERED * BILL_RATE
    gst = amount * CEMENT_GST // 100
    rows = [["Item", "Unit", "Qty", "Rate (Rs)", "Amount (Rs)"],
            ["Cement (OPC 53)", "bags", f"{DELIVERED}", f"{BILL_RATE}", _rupees(amount)[3:]],
            [f"GST {CEMENT_GST}%", "", "", "", _rupees(gst)[3:]], ["Total", "", "", "", _rupees(amount + gst)[3:]]]
    return _doc("Tax invoice", [("From", "Malabar Cements Agency, Palakkad"), ("Invoice no.", "MCA/INV/2611"),
                                ("To", "Green Villa Builders"), ("Delivery", "Challan MCA/DC/2611, 20 November 2026"),
                                ("Date", "22 November 2026")],
                rows, ["Payment within 15 days. Bank details on request."])


def _tiled_rows() -> tuple[list[list[str]], float]:
    rows = [["Room", "Length (m)", "Width (m)", "Area (sqm)", ""]]
    total = 0.0
    for label, _x, _y, w, d, _sqft in ROOMS:
        if label in TILED:
            area = round(w * d / 10000, 2)
            total += area
            rows.append([label.title(), f"{w / 100:.2f}", f"{d / 100:.2f}", f"{area:.2f}", ""])
    total = round(total, 2)
    rows.append(["Total measured", "", "", f"{total:.2f}", ""])
    return rows, total


def measurement_bytes() -> bytes:
    rows, _total = _tiled_rows()
    return _doc("Measurement sheet: vitrified tile flooring", [("Work", "Vitrified tile flooring, ground floor"),
                                                               ("Subcontractor", "Joy Tiling Works, Angamaly"),
                                                               ("Site", "Green Villa, Main block"), ("Measured", "28 November 2026, by Ravi (site engineer) with Joy")],
                rows, ["Measured on the finished floor, wall to wall, from drawing A-101 rev B."])


def sub_bill_bytes() -> bytes:
    amount = round(TILING_BILLED * TILING_RATE)
    rows = [["Work", "Unit", "Qty", "Rate (Rs)", "Amount (Rs)"],
            ["Vitrified tile flooring, laying", "sqm", f"{TILING_BILLED:.2f}", f"{TILING_RATE}", _rupees(amount)[3:]]]
    return _doc("Bill: Joy Tiling Works", [("From", "Joy Tiling Works, Angamaly"), ("Bill no.", "JTW-014"),
                                          ("To", "Green Villa Builders"), ("Work", "Ground floor flooring, Green Villa"),
                                          ("Date", "29 November 2026")],
                rows, ["Labour only; tiles and adhesive supplied by the contractor."])


def drawing_set_bytes() -> bytes:
    """The whole set, eight A3 sheets (green_villa.DRAWINGS), drawn by gv_drawings."""
    from reportlab.pdfgen import canvas

    sheets = {"A-101": gv_drawings.ground_floor, "A-102": gv_drawings.first_floor, "A-201": gv_drawings.front_elevation,
              "A-301": gv_drawings.section_aa, "S-101": gv_drawings.footing_layout, "S-102": gv_drawings.column_schedule,
              "E-101": gv_drawings.electrical, "P-101": gv_drawings.plumbing}
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=gv_drawings.landscape(gv_drawings.A3), invariant=1)
    pdf.setTitle("Green Villa: drawing set rev A")
    for number, _title, _kind in green_villa.DRAWINGS:
        sheets[number](pdf)
        pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def permit_bytes() -> bytes:
    p = green_villa.PERMIT
    rows = [["Particular", "", "", "", "Allowed"], ["Plot", "", "", "", p["plot"]], ["Floors", "", "", "", p["floors"]],
            ["Built-up area", "", "", "", f"{p['built_up_sqft']:,} sq ft"], ["Validity", "", "", "", p["valid"]]]
    return _doc("Building permit", [("Issued by", p["authority"]), ("Permit no.", p["number"]), ("Date", p["date"]),
                                    ("Owner", green_villa.CLIENT["name"]), ("Site", green_villa.CLIENT["address"])],
                rows, ["Construction to follow the approved drawings (Rev A). Keep this permit on site."],
                widths=(110, 10, 10, 10, 370))


def rate_card_bytes() -> bytes:
    r = green_villa.RATE_CARD
    rows = [["Material", "Unit", "", "", "Rate (Rs)"]] + [[m.title(), u, "", "", f"{rate:,}"] for m, u, rate in r["rates"]]
    return _doc("Rate card", [("From", f"{r['vendor']}, Aluva"), ("Ref", r["ref"]), ("To", "Green Villa Builders"),
                              ("Valid from", r["from"]), ("Delivery", "At site, Thrissur, by tipper lorry")],
                rows, ["Rates before GST (5%). Any change will be told in writing a week before."])


def return_note_bytes() -> bytes:
    r = green_villa.RETURN
    value = r["quantity"] * r["rate"]
    rows = [["Item", "Unit", "Qty", "Rate (Rs)", "Value (Rs)"], [r["material"], r["unit"], f"{r['quantity']}", f"{r['rate']}",
                                                                 _rupees(value)[3:]]]
    return _doc("Return note", [("From", "Green Villa Builders, Green Villa site"), ("Note no.", r["note"]),
                                ("To", f"{r['vendor']}, Palakkad"), ("Against", f"Challan {r['against']}"),
                                ("Reason", r["reason"])],
                rows, ["Please send a credit note or replace with the next load.", "Sent by: ____________"])


def hire_bill_bytes() -> bytes:
    h = green_villa.HIRE
    amount = h["billed_hours"] * h["rate_per_hour"]
    gst = amount * 18 // 100
    rows = [["Machine", "Unit", "Hours", "Rate (Rs)", "Amount (Rs)"],
            [h["machine"], "hour", f"{h['billed_hours']}", f"{h['rate_per_hour']}", _rupees(amount)[3:]],
            ["GST 18%", "", "", "", _rupees(gst)[3:]], ["Total", "", "", "", _rupees(amount + gst)[3:]]]
    return _doc("Hire bill", [("From", h["vendor"]), ("Bill no.", h["bill"]), ("To", "Green Villa Builders"),
                              ("Site", f"Green Villa, {h['site']}"), ("For", h["for"])],
                rows, ["Hours as per our operator's log. Payment within 15 days."])


def handover_bytes() -> bytes:
    h = green_villa.HANDOVER
    rows = [["Handed over", "", "", "", "Count"], ["Keys (main door, back door, Annex)", "", "", "", f"{h['keys']}"],
            ["Drawings as built (Rev A)", "", "", "", "1 set"], ["Warranty papers (pump, fittings)", "", "", "", "1 file"]]
    return _doc("Handover certificate", [("Project", "Green Villa, Puthur Road, Thrissur"), ("Client", green_villa.CLIENT["name"]),
                                         ("Agreement", green_villa.CONTRACT["contract_no"]), ("Handed over on", h["date"]),
                                         ("Defects period until", h["defects_until"])],
                rows, [h["note"], "For the contractor: ____________     For the client: ____________"],
                widths=(320, 10, 10, 10, 160))


def _rupees(amount: float) -> str:
    """Rs 82,06,050: Indian grouping."""
    whole = str(round(amount))
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    return "Rs " + ",".join([g for g in [head, *groups] if g] + [tail])


def _save(book) -> bytes:  # noqa: ANN001
    buffer = io.BytesIO()
    book.save(buffer)
    return _fixed_zip(buffer.getvalue())


def _fixed_zip(data: bytes) -> bytes:
    """An xlsx is a zip whose entries carry the time they were written; rewrite them with one fixed time, so the
    same input always gives the same file (and a run that changes nothing shows no change in git)."""
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as src, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            body = src.read(info.filename)
            if info.filename == "docProps/core.xml":
                import re

                body = re.sub(rb"<dcterms:(created|modified)[^>]*>[^<]*</dcterms:\1>", b"", body)
            fixed = zipfile.ZipInfo(info.filename, date_time=(2026, 11, 17, 0, 0, 0))
            fixed.compress_type = zipfile.ZIP_DEFLATED
            dst.writestr(fixed, body)
    return out.getvalue()


def build() -> dict[str, bytes]:
    files = {ESTIMATE: estimate_bytes(), MATERIALS: materials_bytes(), CONTRACT: contract_bytes(), PLAN: plan_bytes(),
             CHALLAN: challan_bytes(), BILL: bill_bytes(), MEASURE: measurement_bytes(), SUB_BILL: sub_bill_bytes(),
             DRAWING_SET: drawing_set_bytes(), PERMIT: permit_bytes(), RATE_CARD: rate_card_bytes(),
             RETURN_NOTE: return_note_bytes(), HIRE_BILL: hire_bill_bytes(), HANDOVER: handover_bytes()}
    files.update({name: quote_bytes(vendor) for name, vendor in zip(QUOTES, QUOTE_RATES, strict=True)})
    manifest = {"name": "Green Villa starter kit", "zip": ZIP, "files": list(MANIFEST)}
    files["kit.json"] = (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode()
    bundle = io.BytesIO()
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as z:
        for name in [f for f in files if f != "kit.json"]:
            entry = zipfile.ZipInfo(f"Green Villa starter kit/{name}", date_time=(2026, 11, 17, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(entry, files[name])
    files[ZIP] = bundle.getvalue()
    return files


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, data in build().items():
        (OUT / name).write_bytes(data)
        print(f"{len(data):>8}  {OUT.relative_to(ROOT) / name}")


if __name__ == "__main__":
    main()
