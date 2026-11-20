"""Green Villa's paperwork as data: its estimate (the BOQ), its contract, and which BOQ line each site stage is counted
on. The one source for the starter kit's files (``scripts/learn_kit/make_kit.py`` writes the estimate and the contract
summary from it) and for the 62-day plan (``sample_plan.py``: the contract set, the estimate put in as the BOQ, the
work counted on its lines, the running bills). Project bible D2 (docs/learning/film/PROJECT_BIBLE.md, agreed 20 Nov
2026): Green Villa is billed to its client like a real project, by its contract.

No imports from the rest of Mesiri: the kit script reads it outside the app.
"""

from __future__ import annotations

#: The estimate: sections (heading rows) and their lines: item no., work, unit, quantity, client rate, labour rate,
#: material rate. Lines with no labour and no material rate have no budget yet (the kit's catch: "Lines priced"
#: counts them); the staircase is priced below what it costs (the catch: a red margin).
ESTIMATE: tuple[tuple[str, tuple[tuple[str, str, str, float, float, float | None, float | None], ...]], ...] = (
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
NORMS: tuple[tuple[str, str, str, float, str], ...] = (
    ("2.1", "PCC", "Cement", 4.5, "bags"), ("2.2", "Footing concreting", "Cement", 8, "bags"),
    ("2.5", "Lintel concreting", "Cement", 8, "bags"), ("2.6", "Roof slab concreting", "Cement", 8, "bags"),
    ("3.1", "Block work", "Solid Blocks", 12.5, "nos"), ("3.1", "Block work", "Cement", 0.4, "bags"),
    ("4.1", "Plastering", "Cement", 0.25, "bags"), ("4.1", "Plastering", "P Sand", 0.02, "cum"),
)

#: The contract value: the estimate's total, GST extra.
CONTRACT_VALUE: float = sum(q * r for _h, rows in ESTIMATE for _c, _w, _u, q, r, *_ in rows)

#: The contract, as the summary prints it and Project start (and the plan) types it in.
CLIENT = {"name": "Dr. Anand Krishnan", "address": "Green Villa, Puthur Road, Thrissur"}
CONTRACT = {
    "contract_no": "GV/2026/007",
    "signed_on": "2026-10-20",
    "starts_on": "2026-11-02",
    "handover_on": "2027-07-31",
    "contract_value": CONTRACT_VALUE,
    "mobilisation_advance": round(CONTRACT_VALUE / 10),
    "advance_recovery_pct": 10,
    "retention_pct": 5,
    "gst_pct": 18,
    "defect_liability_months": 12,
    "payment_terms": "Monthly RA bills on measured work at the BOQ rates; paid within 15 days",
    "delay_per_week": 25000,
}
#: Days the client takes to pay a running bill (the contract's "paid within 15 days").
PAYS_AFTER = 15

#: The BOQ line each site stage of the 62-day plan (sample_plan.STAGES) is counted on, by the line's work name. A stage
#: with no line (None) is done but not billable: the estimate has no line for it (a catch the film points at).
STAGE_LINE: dict[str, str | None] = {
    "Electrical conduits": "Electrical conduits",
    "Ceiling plastering": "Ceiling plastering",
    "Plastering": "Plastering",
    "External plastering": "External plastering",
    "Floor tiling": "Vitrified tile flooring",
    "Flooring": "Vitrified tile flooring",
    "Putty and primer": None,
    "Painting": "Interior emulsion",
    "Snag list": None,
    "Plinth beam": "Plinth beam",
    "Plinth filling": "Backfilling with excavated earth",
    "Block work": "Block work",
    "Slab shuttering": "Slab shuttering",
    "Slab concreting": "Roof slab concreting",
    "Slab curing": None,
}


def line_of(work: str) -> tuple[str, str, str, float, float, float | None, float | None] | None:
    """The estimate line a work name is counted on (``STAGE_LINE``), or None."""
    name = STAGE_LINE.get(work, work)
    return next((line for _h, rows in ESTIMATE for line in rows if line[1] == name), None)


# --- The paperwork before and around the 62 days (project bible section 5, LRN-F5) ----------------------------------

#: The architect's and consultants' drawing set, one PDF the way an office issues it: (number, title, kind). Drawing
#: check reads it whole; Documents keeps each sheet; "Track" turns its rooms and footings into places.
DRAWINGS: tuple[tuple[str, str, str], ...] = (
    ("A-101", "GROUND FLOOR PLAN", "plan"), ("A-102", "FIRST FLOOR PLAN", "plan"),
    ("A-201", "FRONT ELEVATION", "elevation"), ("A-301", "SECTION A-A", "section"),
    ("S-101", "FOOTING LAYOUT AND SCHEDULE", "structure"), ("S-102", "COLUMN SCHEDULE", "schedule"),
    ("E-101", "ELECTRICAL LAYOUT GROUND FLOOR", "services"), ("P-101", "PLUMBING LAYOUT GROUND FLOOR", "services"),
)
#: The first floor (A-102): (label, x, y, width, depth in cm, printed sq ft). The catch: the TOILET is drawn 210 deep
#: here and 240 on the ground floor (A-101), though the floors are meant to stack: Drawing check asks "intended?".
FIRST_FLOOR_ROOMS: tuple[tuple[str, int, int, int, int, int], ...] = (
    ("FAMILY LIVING", 0, 0, 520, 430, 241), ("BEDROOM-3", 520, 0, 400, 360, 155), ("BALCONY", 920, 0, 330, 150, 53),
    ("MASTER BEDROOM", 0, 430, 420, 400, 181), ("DRESS", 420, 430, 200, 180, 39), ("TOILET", 780, 430, 210, 150, 34),
)
#: Levels in cm above ground. The elevation and the section agree, except the roof: +660 on the elevation, +655 on the
#: section (the catch: Drawing check asks which is right before the slab is cast).
ELEVATION_LEVELS = (0, 45, 345, 660, 765)
SECTION_LEVELS = (0, 45, 345, 655, 765)
#: The footings (S-101): type, size in cm, depth, the columns on them (C-marks) and the bars each way.
FOOTINGS: tuple[tuple[str, int, int, int, int, tuple[str, ...], int, int], ...] = (
    # (type, A, B, depth, PCC, columns, bars each way, bar dia)
    ("F1", 150, 150, 45, 10, ("C1", "C2", "C3", "C4"), 8, 12),
    ("F2", 180, 180, 50, 10, ("C5", "C6"), 10, 12),
)
#: The columns (S-102): mark, size in cm, main bars, ties.
COLUMNS: tuple[tuple[str, int, int, str, str], ...] = (
    ("C1", 23, 45, "6-T16", "T8 @ 15 CM"), ("C2", 23, 45, "6-T16", "T8 @ 15 CM"), ("C3", 23, 45, "6-T16", "T8 @ 15 CM"),
    ("C4", 23, 45, "6-T16", "T8 @ 15 CM"), ("C5", 23, 60, "8-T16", "T8 @ 15 CM"), ("C6", 23, 60, "8-T16", "T8 @ 15 CM"),
)
ARCHITECT = "Sreekumar Architects, Thrissur"
CONSULTANT = "R. Anand, Structural Consultant"

#: The building permit (Documents, approvals).
PERMIT = {"authority": "Thrissur Municipal Corporation", "number": "TMC/BP/2026/1187", "date": "30 September 2026",
          "valid": "3 years from the date of issue", "plot": "Survey no. 412/3, Puthur village, 6.2 cents",
          "built_up_sqft": 2150, "floors": "Ground + 1 (Main block); Ground (Annex)"}

#: Periyar Sand & Aggregates' rate card (Rates): the agreed rate per material. The catch: M sand comes later at Rs 1,750
#: (sample_story.DEMO_RATE_NOW), Rs 100 a cum above this card; Rates shows the rise.
RATE_CARD = {"vendor": "Periyar Sand & Aggregates", "ref": "PSA/RC/2026-27", "from": "1 October 2026",
             "rates": (("m sand", "cum", 1650), ("p sand", "cum", 1900), ("aggregate 20mm", "cum", 1450))}

#: A return to the supplier (Returns): bags torn in Malabar's load (the kit's challan, 190 bags). The debit note lowers
#: what Green Villa Builders owes Malabar at once, at the order's rate.
RETURN = {"vendor": "Malabar Cements Agency", "note": "GV/RN/014", "against": "MCA/DC/2611", "material": "Cement (OPC 53)",
          "unit": "bags", "quantity": 6, "rate": 400, "reason": "Bags torn and set hard; refused at the gate"}

#: A hired machine (Equipment, Hire check): the bill against the hours logged on site. The catch: billed 42 hours,
#: 36 logged (two half days the mixer stood idle with the motor fault are billed as working).
HIRE = {"vendor": "Kerala Earthmovers & Equipments", "bill": "KEE/2027/0118", "machine": "Concrete mixer with hopper (10/7)",
        "site": "Annex", "for": "Annex roof slab and plinth", "rate_per_hour": 450, "billed_hours": 42, "logged_hours": 36}

#: The handover certificate (Documents, handover), signed on handover day.
HANDOVER = {"date": "31 July 2027", "defects_until": "31 July 2028", "keys": 3,
            "note": "Handed over complete, with the snag list closed; retention to be released after the defects period."}
