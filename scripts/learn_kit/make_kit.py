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
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
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
ZIP = "green-villa-starter-kit.zip"

#: The estimate: sections (heading rows) and their lines: item no., work, unit, quantity, client rate, labour rate,
#: material rate. Lines with no labour and no material rate have no budget yet (the catch: "Lines priced" counts
#: them); the staircase is priced below what it costs (the catch: a red margin).
SECTIONS: tuple[tuple[str, tuple[tuple[str, str, str, float, float, float | None, float | None], ...]], ...] = (
    ("A. EARTHWORK", (
        ("1.1", "Site clearance", "sqm", 450, 25, 20, None),
        ("1.2", "Excavation", "cum", 180, 480, 300, None),
        ("1.3", "Backfilling with excavated earth", "cum", 90, 210, 160, None),
        ("1.4", "Anti-termite treatment", "sqm", 300, 45, 10, 28),
    )),
    ("B. CONCRETE", (
        ("2.1", "PCC", "cum", 22, 6200, 900, 4300),
        ("2.2", "Footing concreting", "cum", 48, 8600, 950, 5900),
        ("2.3", "Plinth beam", "rmt", 160, 1450, 420, 780),
        ("2.4", "Column casting", "cum", 26, 9800, 1900, 5600),
        ("2.5", "Lintel concreting", "cum", 14, 8900, 1300, 5800),
        ("2.6", "Roof slab concreting", "cum", 62, 8700, 900, 6100),
        ("2.7", "Slab shuttering", "sqm", 410, 620, 260, 210),
        ("2.8", "Reinforcement steel", "kg", 16500, 92, 12, 70),
        ("2.9", "Staircase waist slab", "cum", 9, 7900, 1400, 6800),
    )),
    ("C. MASONRY", (
        ("3.1", "Block work", "sqm", 620, 1250, 380, 640),
        ("3.2", "Brick work in partitions", "sqm", 140, 980, 360, 520),
        ("3.3", "Parapet wall", "rmt", 95, 1100, 400, 520),
    )),
    ("D. PLASTERING", (
        ("4.1", "Plastering", "sqm", 1450, 420, 210, 120),
        ("4.2", "External plastering", "sqm", 780, 520, 260, 150),
        ("4.3", "Ceiling plastering", "sqm", 380, 460, 240, 130),
    )),
    ("E. FLOORING AND TILING", (
        ("5.1", "Vitrified tile flooring", "sqm", 290, 1650, None, None),
        ("5.2", "Bathroom wall tiling", "sqm", 160, 1450, None, None),
        ("5.3", "Granite kitchen counter", "rmt", 12, 4200, None, None),
        ("5.4", "Skirting", "rmt", 260, 180, 60, 85),
    )),
    ("F. ELECTRICAL", (
        ("6.1", "Electrical conduits", "nos", 320, 260, 90, 110),
        ("6.2", "Wiring per point", "nos", 140, 1450, 450, 700),
        ("6.3", "Distribution board", "nos", 2, 18500, 2500, 13000),
    )),
    ("G. PLUMBING", (
        ("7.1", "CPVC water supply lines", "rmt", 180, 420, 150, 190),
        ("7.2", "Sanitary fittings", "nos", 18, 6500, 900, 4800),
    )),
    ("H. PAINTING", (
        ("8.1", "Interior emulsion", "sqm", 2100, 140, 55, 50),
        ("8.2", "Exterior emulsion", "sqm", 780, 190, 65, 75),
        ("8.3", "Enamel on doors and windows", "sqm", 120, 260, 110, 80),
    )),
    ("I. DOORS AND WINDOWS", (
        ("9.1", "Teak main door", "nos", 1, 68000, 6000, 52000),
        ("9.2", "Flush doors", "nos", 9, 14500, 1800, 10500),
        ("9.3", "UPVC windows", "sqm", 46, 7200, 900, 5600),
    )),
)
#: What one unit of a line uses (the "Materials per unit" sheet), in the material's stock unit. Names as the sample
#: company's catalogue has them (domains/materials/defaults.py).
NORMS = (
    ("2.1", "PCC", "Cement", 4.5, "bags"), ("2.2", "Footing concreting", "Cement", 8, "bags"),
    ("2.5", "Lintel concreting", "Cement", 8, "bags"), ("2.6", "Roof slab concreting", "Cement", 8, "bags"),
    ("3.1", "Block work", "Solid Blocks", 12.5, "nos"), ("3.1", "Block work", "Cement", 0.4, "bags"),
    ("4.1", "Plastering", "Cement", 0.25, "bags"), ("4.1", "Plastering", "P Sand", 0.02, "cum"),
)
#: The work the sample site reports for Green Villa (sample_story.DEMO_WORK, Main block and Annex): each must be a line
#: here with the same unit, or that work can't count on the BOQ. "Plastering" is a catch too: three plastering lines
#: (internal, external, ceiling), so Mesiri suggests none and the person picks (the BOQ page's "Change line").
SITE_WORK = (("Block work", "sqm"), ("Lintel concreting", "cum"), ("Plastering", "sqm"), ("Electrical conduits", "nos"),
             ("Excavation", "cum"), ("PCC", "cum"), ("Footing concreting", "cum"), ("Plinth beam", "rmt"))

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
    ("Client", "Dr. Anand Krishnan"),
    ("Site", "Green Villa, Puthur Road, Thrissur"),
    ("Contract no.", "GV/2026/007"),
    ("Contract value", "{value}, GST extra at 18% (the estimate's total)"),
    ("Start", "1 December 2026"),
    ("Handover", "31 August 2027 (9 months)"),
    ("Mobilisation advance", "10% on signing, recovered from each RA bill in equal parts"),
    ("Retention", "5% of each RA bill, released 12 months after handover"),
    ("Defects period", "12 months from handover"),
    ("Billing", "Monthly RA bills on measured work at the BOQ rates; paid within 15 days"),
    ("Delay", "Rs 25,000 per week of delay beyond handover, at most 5% of the contract value"),
)

#: The ground floor plan, drawn the way Drawing check reads a plan: each room's name, its size in cm under it, and the
#: area the architect printed. Bedroom 2 is drawn 360 x 360 but labelled 163 sq ft, Bedroom 1's area: the catch.
#: (label, x cm, y cm, width cm, depth cm, printed sq ft)
ROOMS = (("LIVING", 0, 0, 520, 430, 241), ("DINING", 520, 0, 400, 360, 155), ("KITCHEN", 920, 0, 330, 300, 107),
         ("BEDROOM-1", 0, 430, 420, 360, 163), ("BEDROOM-2", 420, 430, 360, 360, 163), ("TOILET", 780, 430, 240, 150, 39),
         ("SIT OUT", 1020, 430, 300, 240, 78))

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
)


def estimate_bytes() -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    book = Workbook()
    sheet = book.active
    sheet.title = "BOQ"
    sheet.append(["GREEN VILLA, PUTHUR ROAD, THRISSUR: ESTIMATE (G+1 residence, 3,200 sq ft)"])
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
    value = _rupees(sum(qty * rate for _, lines in SECTIONS for _, _, _, qty, rate, _, _ in lines))
    table = Table([[k, v.format(value=value)] for k, v in CONTRACT_TERMS], colWidths=[140, 330])
    table.setStyle(TableStyle([
        ("FONT", (0, 0), (0, -1), "Helvetica-Bold", 10), ("FONT", (1, 0), (1, -1), "Helvetica", 10),
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#e7e1d6")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7), ("TOPPADDING", (0, 0), (-1, -1), 7),
    ]))
    doc.build([
        Paragraph("Green Villa: contract summary", styles["Title"]),
        Paragraph("Sample paperwork for learning Mesiri. The people and the project are made up.", styles["Italic"]),
        Spacer(1, 16), table, Spacer(1, 18),
        Paragraph("Signed for the contractor and the client on 20 November 2026.", styles["Normal"]),
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
    """A3 sheet, 1:100 in centimetres, with a title block Drawing check reads."""
    from reportlab.lib.pagesizes import A3, landscape
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=landscape(A3), invariant=1)
    pdf.setTitle("Green Villa: ground floor plan A-101")
    width, height = landscape(A3)
    scale, left0, top0 = 0.6, 70, height - 110  # points per cm; the plan hangs from its top-left corner
    pdf.setLineWidth(1.2)
    pdf.rect(30, 30, width - 60, height - 60)  # the sheet's border
    pdf.setLineWidth(2)
    for label, x, y, w, d, sqft in ROOMS:
        left, bottom = left0 + x * scale, top0 - (y + d) * scale
        pdf.rect(left, bottom, w * scale, d * scale)
        cx, cy = left + w * scale / 2, bottom + d * scale / 2
        pdf.setFont("Helvetica-Bold", 9)
        pdf.drawCentredString(cx, cy + 12, label)
        pdf.setFont("Helvetica", 8)
        pdf.drawCentredString(cx, cy, f"{w} x {d}")
        pdf.drawCentredString(cx, cy - 11, f"{sqft} Sq.ft")
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(left0, height - 75, "GROUND FLOOR PLAN")
    # The title block, boxed, bottom right, clear of the plan.
    bx, by, bw, bh = width - 320, 40, 280, 200
    pdf.setLineWidth(1)
    pdf.rect(bx, by, bw, bh)
    pdf.setFont("Helvetica", 9)
    block = (("PROJECT:", "GREEN VILLA, PUTHUR ROAD, THRISSUR"), ("CLIENT:", "DR. ANAND KRISHNAN"),
             ("DWG.TITLE:", "GROUND FLOOR PLAN"), ("DWG.NO:", "A-101"), ("REV:", "B"), ("SCALE:", "1:100"),
             ("DATE:", "09.10.2026"), ("DRAWN BY:", "SK"), ("CHECKED BY:", "AR"))
    for i, (key, value) in enumerate(block):
        pdf.drawString(bx + 12, by + bh - 22 - i * 18, f"{key} {value}")
    pdf.drawString(bx + 12, by + 10, "ALL DIMENSIONS ARE IN CM")
    pdf.drawString(left0, 45, "Sample drawing for learning Mesiri. Not for construction.")
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
             CHALLAN: challan_bytes(), BILL: bill_bytes(), MEASURE: measurement_bytes(), SUB_BILL: sub_bill_bytes()}
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
