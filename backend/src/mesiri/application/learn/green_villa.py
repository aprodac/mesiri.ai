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
#: Levels in cm above ground. The elevation and the section agree, except the roof: +660 on the elevation, +655 on the
#: section (the catch: Drawing check asks which is right before the slab is cast).
ELEVATION_LEVELS = (0, 45, 345, 660, 765)
SECTION_LEVELS = (0, 45, 345, 655, 765)
#: What each level is: ground, plinth (ground floor), first floor, roof slab, top of parapet. The terrace over
#: BEDROOM-1 is the first floor's slab; its parapet is 100 high.
LEVEL_NAMES = ("GROUND", "PLINTH, GROUND FLOOR", "FIRST FLOOR", "ROOF", "TOP OF PARAPET")
#: The ground floor (A-101), Main block, drawn at 1:50. Walls: 23 cm outside, 10 cm partitions. Three bays across
#: (clear 520, 360, 420), 740 deep inside. Rooms: (label, x, y, width, depth in cm, printed sq ft), x from the inside
#: face of the left wall, y from the inside face of the front wall (the road side), the sizes clear inside. The catch:
#: BEDROOM-2 is drawn 360 x 360 but printed 163 sq ft, BEDROOM-1's area (Drawing check: "the label looks copied").
WALL_EXT, WALL_INT = 23, 10
BAYS_X = (520, 360, 420)
CLEAR_W, CLEAR_D = sum(BAYS_X) + 2 * WALL_INT, 740
GROUND_FLOOR_ROOMS: tuple[tuple[str, int, int, int, int, int], ...] = (
    ("LIVING", 0, 0, 520, 430, 241), ("DINING", 0, 440, 520, 300, 168),
    ("BEDROOM-2", 530, 0, 360, 360, 163), ("PASSAGE", 530, 370, 360, 120, 46), ("KITCHEN", 530, 500, 360, 240, 93),
    ("BEDROOM-1", 900, 0, 420, 360, 163), ("STAIR", 900, 370, 420, 210, 95), ("STORE", 900, 590, 170, 150, 27),
    ("TOILET", 1080, 590, 240, 150, 39), ("SIT OUT", 110, -263, 300, 240, 78),
)
#: Openings with no door (x, y, width, depth, inside coordinates): the arch between living and dining, living to the
#: passage, the passage to the stair lobby.
GROUND_OPENINGS = ((40, 430, 440, 10), (520, 380, 10, 100), (890, 380, 10, 100))
#: Doors: ("h" in a wall across the sheet | "v" up it, from, to, the wall's two faces, opens +1 up/right | -1, hinge
#: "l"/"r" or "b"/"t", mark).
GROUND_DOORS = (
    ("h", 200, 320, (-23, 0), 1, "l", "D1"),
    ("h", 790, 880, (360, 370), -1, "r", "D2"),
    ("h", 905, 995, (360, 370), -1, "r", "D2"),
    ("h", 540, 630, (490, 500), 1, "l", "D2"),
    ("h", 1100, 1175, (580, 590), 1, "l", "D3"),
    ("h", 985, 1060, (580, 590), 1, "r", "D3"),
    ("h", 640, 730, (740, 763), -1, "l", "D4"),
)
#: Windows: (direction, from, to, the wall's faces, mark, which side the mark is written).
GROUND_WINDOWS = (
    ("v", 120, 270, (-23, 0), "W1", -1), ("v", 500, 650, (-23, 0), "W1", -1),
    ("h", 420, 510, (-23, 0), "W3", -1), ("h", 635, 785, (-23, 0), "W1", -1), ("h", 1030, 1180, (-23, 0), "W1", -1),
    ("v", 110, 260, (1320, 1343), "W1", -1), ("v", 400, 520, (1320, 1343), "W2", -1),
    ("h", 200, 320, (740, 763), "W2", 1), ("h", 760, 880, (740, 763), "W2", 1),
    ("h", 960, 1020, (740, 763), "V1", 1), ("h", 1200, 1260, (740, 763), "V1", 1),
)
#: Door and window types: mark, type, width, height (cm). Each plan's list counts its own marks.
OPENING_TYPES = (
    ("D1", "TEAK, PANELLED", 120, 210), ("D2", "FLUSH, TEAK FRAME", 90, 210), ("D3", "PVC, FOR WET AREAS", 75, 210),
    ("D4", "FLUSH, STEEL GRILL", 90, 210), ("D5", "UPVC, GLAZED, 2 LEAVES", 120, 210),
    ("W1", "UPVC, 3 SHUTTERS", 150, 135), ("W2", "UPVC, 2 SHUTTERS", 120, 120), ("W3", "UPVC, 2 SHUTTERS", 90, 135),
    ("V1", "UPVC LOUVRE", 60, 60),
)
#: Window sill and lintel above the floor (cm); the lintel band runs at 210.
SILL, LINTEL = 75, 210

#: The first floor (A-102), on the same walls and grid: the main block over the left and middle bays, the stair hall,
#: a utility and a toilet over the right bay's back, an open terrace over BEDROOM-1, a balcony over the sit out. The
#: catch: this TOILET is drawn 210 x 150 over the ground floor's 240 x 150, though toilets stack (Drawing check asks
#: "intended?"). Printed area 0: the terrace is not carpet area, none is printed.
FIRST_FLOOR_ROOMS: tuple[tuple[str, int, int, int, int, int], ...] = (
    ("FAMILY LIVING", 0, 0, 520, 430, 241), ("BEDROOM-3", 0, 440, 520, 300, 168),
    ("BEDROOM-4", 530, 0, 360, 360, 140), ("PASSAGE", 530, 370, 360, 120, 46), ("STUDY", 530, 500, 360, 240, 93),
    ("STAIR", 900, 370, 420, 210, 95), ("UTILITY", 900, 590, 200, 150, 32), ("TOILET", 1110, 590, 210, 150, 34),
    ("TERRACE", 900, 0, 420, 360, 0), ("BALCONY", 110, -173, 330, 150, 53),
)
FIRST_OPENINGS = ((520, 380, 10, 100), (890, 380, 10, 100))
FIRST_DOORS = (
    ("h", 200, 320, (-23, 0), 1, "l", "D5"),
    ("h", 400, 490, (430, 440), 1, "r", "D2"),
    ("h", 790, 880, (360, 370), -1, "r", "D2"),
    ("h", 540, 630, (490, 500), 1, "l", "D2"),
    ("h", 905, 995, (360, 370), -1, "r", "D4"),
    ("h", 985, 1060, (580, 590), 1, "r", "D3"),
    ("h", 1130, 1205, (580, 590), 1, "l", "D3"),
)
FIRST_WINDOWS = (
    ("v", 120, 270, (-23, 0), "W1", -1), ("v", 500, 650, (-23, 0), "W1", -1), ("h", 420, 510, (-23, 0), "W3", -1),
    ("h", 635, 785, (-23, 0), "W1", -1), ("h", 200, 320, (740, 763), "W2", 1), ("h", 650, 770, (740, 763), "W2", 1),
    ("v", 400, 520, (1320, 1343), "W2", -1), ("h", 960, 1020, (740, 763), "V1", 1),
    ("h", 1200, 1260, (740, 763), "V1", 1),
)
#: Columns that stop at the first floor: the terrace's front corner and the sit out's two (their roof is the balcony).
STOP_AT_FIRST = ("C4", "C13", "C14")

#: The column grid, on the walls' centre lines, from the building's outside front-left corner (cm).
GRID_X = (("A", 11.5), ("B", 548), ("C", 918), ("D", CLEAR_W + 2 * WALL_EXT - 11.5))
GRID_Y = (("1", 11.5), ("2", 388), ("3", CLEAR_D + 2 * WALL_EXT - 11.5))
#: Every column where it stands: (mark, x, y, size across, size up the sheet), numbered from the front left, row by
#: row; C13 and C14 carry the sit out's roof.
COLUMN_SPOTS: tuple[tuple[str, float, float, int, int], ...] = (
    *((f"C{1 + r * 4 + c}", x, y, 23, 30 if (r, c) in ((1, 1), (1, 2)) else 23)
      for r, (_ny, y) in enumerate(GRID_Y) for c, (_nx, x) in enumerate(GRID_X)),
    ("C13", 144.5, -228.5, 23, 23), ("C14", 421.5, -228.5, 23, 23),
)
#: Plinth beams: on every grid line between its end columns, and from the sit out's columns to the front wall.
PLINTH_BEAMS = (
    *(((x, GRID_Y[0][1]), (x, GRID_Y[-1][1])) for _n, x in GRID_X),
    *(((GRID_X[0][1], y), (GRID_X[-1][1], y)) for _n, y in GRID_Y),
    ((144.5, -228.5), (144.5, 11.5)), ((421.5, -228.5), (421.5, 11.5)), ((144.5, -228.5), (421.5, -228.5)),
)
#: The footings (S-101): (type, A, B, depth D at the column, edge thickness C, the columns on it, bars each way, bar
#: dia). Corners light, edges heavier, the two inside columns heaviest, the sit out's smallest.
FOOTINGS: tuple[tuple[str, int, int, int, int, tuple[str, ...], int, int], ...] = (
    ("F1", 150, 150, 45, 20, ("C1", "C4", "C9", "C12"), 8, 12),
    ("F2", 180, 180, 50, 20, ("C2", "C3", "C5", "C8", "C10", "C11"), 10, 12),
    ("F3", 200, 200, 55, 25, ("C6", "C7"), 12, 12),
    ("F4", 100, 100, 30, 15, ("C13", "C14"), 6, 10),
)
#: The columns (S-102): mark, size in cm, main bars, ties.
COLUMNS: tuple[tuple[str, int, int, str, str], ...] = tuple(
    (m, a, b, "6-T16" if b > 23 else ("4-T12" if m in ("C13", "C14") else "4-T16"), "T8 @ 15 CM")
    for m, _x, _y, a, b in COLUMN_SPOTS)
ARCHITECT = "Sreekumar Architects, Thrissur"
CONSULTANT = "R. Anand, Structural Consultant"

#: Built-up area, sq ft, outside faces (LRN-F12): the Main block's two floors as the drawing set draws them
#: (ground 1366 x 786, first floor over the left and middle bays and the stair hall), and the single-storey Annex.
BUILT_UP = {"Main block": 2150, "Annex": 450}
#: The building permit (Documents, approvals).
PERMIT = {"authority": "Thrissur Municipal Corporation", "number": "TMC/BP/2026/1187", "date": "30 September 2026",
          "valid": "3 years from the date of issue", "plot": "Survey no. 412/3, Puthur village, 6.2 cents",
          "built_up_sqft": sum(BUILT_UP.values()),
          "floors": f"Main block, ground + 1: {BUILT_UP['Main block']:,} sq ft; Annex, ground: {BUILT_UP['Annex']:,} sq ft"}

#: Periyar Sand & Aggregates' rate card (Rates): the agreed rate per material. The catch: M sand comes later at Rs 1,750
#: (sample_story.DEMO_RATE_NOW), Rs 100 a cum above this card; Rates shows the rise.
RATE_CARD = {"vendor": "Periyar Sand & Aggregates", "ref": "PSA/RC/2026-27", "from": "1 October 2026",
             "rates": (("m sand", "cum", 1650), ("p sand", "cum", 1900), ("aggregate 20mm", "cum", 1450))}

#: LRN-F18 (episode 4, "Cement runs short"): the Main block's first cement request, as the kit's paperwork has it and the
#: 62-day plan plays it (sample_plan.py). Anil moves bags from the Annex so the masons work, asks three suppliers for
#: cement and the staircase's steel, and orders each line from its cheapest; the lorry brings 190 of 200 (challan), 6
#: torn go back (RETURN below); Malabar bills 190 at Rs 410 against the order's Rs 400. The one source for the quotes,
#: the challan, the bill (scripts/learn_kit/make_kit.py) and the plan.
CEMENT_STORY = {
    "site": "main", "from_site": "annex", "move": 40,
    #: The request for quotes: (material as the sample company names it, as the papers print it, unit, quantity).
    "lines": (("cement", "Cement (OPC 53)", "bags", 200), ("steel", "Steel (TMT Fe 500)", "kg", 1000)),
    #: (supplier, where, quotation no., {material: rate}). Malabar is cheapest for cement, Kerala Steels in total;
    #: each line from its cheapest is cheaper still (Rs 1,46,000 against Rs 1,48,400).
    "quotes": (("Malabar Cements Agency", "Palakkad", "MCA/Q/0412", {"cement": 400, "steel": 72}),
               ("Kerala Steels", "Industrial Estate, Kalamassery", "KS/Q/2280", {"cement": 412, "steel": 66}),
               ("Sri Hardwares", "MG Road, Thrissur", "SH/Q/117", {"cement": 408, "steel": 70})),
    "challan": "MCA/DC/2611", "ordered": 200, "sent": 190, "torn": 6, "return_note": "GV/RN/014",
    "bill": "MCA/INV/2611", "bill_rate": 410,
}

#: A return to the supplier (Returns): bags torn in Malabar's load (the kit's challan, 190 bags). The debit note lowers
#: what Green Villa Builders owes Malabar at once, at the order's rate.
RETURN = {"vendor": "Malabar Cements Agency", "note": CEMENT_STORY["return_note"], "against": CEMENT_STORY["challan"],
          "material": "Cement (OPC 53)", "unit": "bags", "quantity": CEMENT_STORY["torn"], "rate": 400,
          "reason": "Bags torn and set hard; refused at the gate"}

#: A hired machine (Equipment, Hire check): the bill against the hours logged on site. The catch: billed 42 hours,
#: 36 logged (two half days the mixer stood idle with the motor fault are billed as working).
HIRE = {"vendor": "Kerala Earthmovers & Equipments", "bill": "KEE/2027/0118", "machine": "Concrete mixer with hopper (10/7)",
        "site": "Annex", "for": "Annex roof slab and plinth", "rate_per_hour": 450, "billed_hours": 42, "logged_hours": 36}

#: The handover certificate (Documents, handover), signed on handover day.
HANDOVER = {"date": "31 July 2027", "defects_until": "31 July 2028", "keys": 3,
            "note": "Handed over complete, with the snag list closed; retention to be released after the defects period."}
