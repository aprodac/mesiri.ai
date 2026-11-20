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
