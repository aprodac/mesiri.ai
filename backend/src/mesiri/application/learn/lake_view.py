"""Lake View Apartments' paperwork as data: its full estimate (the BOQ, both towers) and its contract with Lake View
Builders. The one source for the sample company's seed (``organizations/sample_story.py`` puts the estimate in as the
BOQ and sets the contract) and the 62-day plan (the work counted on these lines, the running bills on days 23 and 51).
Project bible section 8 item 3 (docs/learning/film/PROJECT_BIBLE.md): "Lake View's full estimate and terms".

What the contract is: Green Villa Builders build the **civil works** of two residential towers for a developer,
Lake View Builders: the basement and the frame, the block work and the plastering, and the waterproofing. Flooring,
doors, windows, electrical and plumbing are the developer's other contractors (the film says so: a contract's scope is
written in its BOQ). Each tower: a basement, a ground floor and six upper floors, about 330 m2 a floor.

No imports from the rest of Mesiri, like ``green_villa``.
"""

from __future__ import annotations

#: The towers, as the seed names their sites.
TOWERS = ("Tower A", "Tower B")
#: One tower's estimate: sections and their lines (work, unit, quantity, client rate, labour rate, material rate).
#: Section names carry the tower ("Structure · Tower A"): the plan counts each site's work on its own tower's line.
#: The work names are the ones the site records (the seed's DEMO_WORK and the plan's stages) so work lands on them.
_TOWER: tuple[tuple[str, tuple[tuple[str, str, float, float, float, float], ...]], ...] = (
    ("Substructure", (
        ("Excavation", "cum", 1150, 480, 300, 0),
        ("PCC", "cum", 40, 6200, 900, 4300),
        ("Raft reinforcement", "kg", 26000, 90, 11, 70),
        ("Raft concreting", "cum", 300, 8700, 850, 6000),
        ("Retaining wall", "sqm", 380, 4600, 1300, 2900),
        ("Basement waterproofing", "sqm", 720, 650, 180, 380),
    )),
    ("Structure", (
        ("Column reinforcement", "kg", 15000, 92, 12, 70),
        ("Column casting", "cum", 110, 9800, 1900, 5600),
        ("Slab shuttering", "sqm", 2700, 620, 260, 210),
        ("Slab reinforcement", "kg", 40000, 92, 12, 70),
        ("Slab concreting", "cum", 520, 8900, 900, 6100),
        ("Staircase concreting", "cum", 22, 9500, 1500, 6600),
        ("Lintel concreting", "cum", 26, 8900, 1300, 5800),
    )),
    ("Masonry and plaster", (
        ("Block work", "sqm", 1650, 1250, 380, 640),
        ("Plastering", "sqm", 3300, 420, 210, 120),
        ("External plastering", "sqm", 1300, 520, 260, 150),
        ("Ceiling plastering", "sqm", 2300, 460, 240, 130),
        ("Terrace waterproofing", "sqm", 330, 950, 250, 520),
    )),
)
#: Work for the whole project, on no tower: (work, unit, quantity, client rate, labour rate, material rate).
_COMMON: tuple[tuple[str, str, float, float, float, float], ...] = (
    ("Site clearance and setting out", "sqm", 2400, 25, 20, 0),
    ("Dewatering during the basement", "month", 4, 65000, 15000, 40000),
    ("Scaffolding for both towers", "sqm", 2600, 180, 90, 60),
)

#: The estimate as the seed puts it in: (section name, tower or None, lines).
ESTIMATE: tuple[tuple[str, str | None, tuple[tuple[str, str, float, float, float, float], ...]], ...] = (
    ("Site works · Lake View", None, _COMMON),
    *((f"{section} · {tower}", tower, lines) for tower in TOWERS for section, lines in _TOWER),
)

#: The contract value: the estimate's total, GST extra (rule 1 of the project bible: one number, one source).
CONTRACT_VALUE: float = sum(q * r for _s, _t, lines in ESTIMATE for _w, _u, q, r, *_ in lines)

CLIENT = {"name": "Lake View Builders", "contact_person": "Mr. Varghese", "address": "Kakkanad, Kochi"}
#: The contract's terms. No mobilisation advance (the developer pays each month instead: Green Villa's client paid
#: 10% on signing, the film sets the two side by side). Lake View Builders is a company, so it deducts TDS (2% on a
#: works contract) from each payment, which Green Villa's client, a person, does not.
CONTRACT = {
    "contract_no": "LVB/2026/014",
    "contract_value": CONTRACT_VALUE,
    "retention_pct": 5,
    "gst_pct": 18,
    "tds_pct": 2,
    "defect_liability_months": 12,
    "payment_terms": "Monthly RA bills on measured work at the BOQ rates; paid within 15 days, less TDS",
    "notes": "Civil works only: substructure, frame, block work, plastering, waterproofing. Delay: Rs 50,000 a week "
             "beyond the agreed date, at most 5% of the contract value.",
}
#: When it was signed, in days before the seed's today (the towers are mid-frame when the story starts).
SIGNED_DAYS_AGO = 150


def lines_of(tower: str) -> list[tuple[str, str, float, float, float, float]]:
    """Every line of one tower, in estimate order."""
    return [line for _s, t, lines in ESTIMATE if t == tower for line in lines]
