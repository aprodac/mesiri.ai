"""SS-74b: the planned simulation, every role's entries day by day (docs/plans/guided-demo-plan.md section 18).

The sample company's story after its two seeded weeks (``sample_story.seed``), written in advance: from day 0 (the
seed's last day, a Saturday) to Green Villa's handover, what each person enters each day. Ravi (site engineer)
records the sites' days, asks for material and receives it; Anil (project manager) orders, counts work on the BOQ,
closes issues and runs the tiling subcontract; Meera (accounts) books bills, pays suppliers, wages and advances and
records the client's payments; the owner approves wages, sends the running bill and hands the villa over.

The player (SS-74c) plays a day's entries as each role's sandbox user through the real API; the entries of the role
the person plays are their to-do for the day (section 18.4). So the plan is data: who, what kind, which site, the
numbers, and what an entry needs first (``needs``: a delivery needs its order, a bill its delivery, a payment its
bills). Fixed, no randomness: every sample company gets the same plan.

How the plan is made: it starts from exactly what the seed leaves (stock per site, what is still to come on the
seed's orders), worked out by running the seed itself against a recorder (``opening``), never a copy of its rules;
then each site works through its stages (``STAGES``), using material only while it has it (a short site does less
work), asking for more when it will run short within the supplier's lead time and a few days, and so on down the
chain. ``python -m mesiri.application.learn.sample_plan`` writes the readable day-by-day version to
``docs/plans/sample-plan.md``; a test fails when that file is out of date.
"""

from __future__ import annotations

import datetime as dt
import math
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from mesiri.application.learn import green_villa as gv
from mesiri.application.organizations import sample_story as story

# --- Who and where ---------------------------------------------------------------------------------------------------

OWNER, PM, ENGINEER, ACCOUNTS = "ADMIN", "PROJECT_MANAGER", "SITE_ENGINEER", "FINANCE"
#: The person each role is in the sample company (learn/sandbox.py ROLES; the owner is the person themself).
WHO = {OWNER: "Owner", PM: "Anil", ENGINEER: "Ravi", ACCOUNTS: "Meera"}

GREEN_VILLA, LAKE_VIEW = "green_villa", "lake_view"
#: The four sites, in the seed's order (its site index): key, project, name.
SITES: tuple[tuple[str, str, str], ...] = (
    ("main", GREEN_VILLA, story.DEMO_SITES[0]), ("annex", GREEN_VILLA, story.DEMO_SITES[1]),
    ("tower_a", LAKE_VIEW, story.DEMO_SITES_2[0]), ("tower_b", LAKE_VIEW, story.DEMO_SITES_2[1]),
)
SITE_NAME = {key: name for key, _p, name in SITES}
SITE_PROJECT = {key: project for key, project, _n in SITES}
PROJECT_NAME = {GREEN_VILLA: story.DEMO_PROJECT, LAKE_VIEW: story.DEMO_PROJECT_2}

#: How each material is counted, for the words.
UNITS = {"cement": "bags", "m sand": "cum", "p sand": "cum", "aggregate 20mm": "cum", "solid blocks": "nos",
         "steel": "kg", "binding wire": "kg"}
#: One of it, for a rate ("₹410 a bag").
PER = {"cement": "bag", "m sand": "cum", "p sand": "cum", "aggregate 20mm": "cum", "solid blocks": "block", "steel": "kg",
       "binding wire": "kg"}
#: Working days from the order to the lorry on site.
LEAD_DAYS = {"cement": 2, "m sand": 1, "p sand": 1, "aggregate 20mm": 1, "solid blocks": 2, "steel": 3,
             "binding wire": 3}
#: Ask for more when what is there and on its way would not last the lead time and this many days more.
COVER_DAYS = 3
#: A supplier's bill reaches the office this many working days after the delivery.
BILL_AFTER = 2
#: Suppliers are paid on a Saturday for bills at least this many days old.
CREDIT_DAYS = 7
#: The client pays a running bill this many days after it is sent.
CLIENT_PAYS_AFTER = 12

#: LRN-F18 (episode 4, "Cement runs short"): the Main block's first cement request plays the starter kit's paperwork
#: (green_villa.CEMENT_STORY, the one source for the kit's papers and this plan).
CEMENT_STORY: dict[str, Any] = {**gv.CEMENT_STORY,
                                "lines": tuple((m, q) for m, _printed, _u, q in gv.CEMENT_STORY["lines"]),
                                "quotes": tuple((v, ref, rates) for v, _where, ref, rates in gv.CEMENT_STORY["quotes"])}

# --- What each site does next ----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Stage:
    """One piece of work at a site: its quantity a full day, for how many full days, and the material a full day."""

    work: str
    narrative: str
    unit: str
    per_day: float
    days: int
    use: tuple[tuple[str, float], ...] = ()
    #: Helpers from the labour contractor's gang a day (the site's own named workers come every day).
    gang: int = 4
    #: Done by a subcontractor (its work is measured and billed, section 18.3).
    by: str | None = None


#: After the seeded weeks: each site carries on from the stage the seed ends on (``DEMO_WORK``'s last) to its end.
#: Green Villa (Main block, a G+1 villa; the Annex from its plinth) runs to handover; Lake View keeps building.
STAGES: dict[str, tuple[Stage, ...]] = {
    # LRN-F30 (Ilan, 21 Nov: "fix the story to fit the estimate"): each Green Villa stage's crew and material cost a
    # day sit just inside what its BOQ line earns a day (green_villa.ESTIMATE's labour and material rates), so Cost
    # control reads the job near budget and the plastering rework (green_villa.REWORK) is the red line it shows.
    "main": (
        Stage("Electrical conduits", "First floor conduit and box fixing", "nos", 50, 3, (("cement", 2), ("m sand", 0.2)), 1),
        Stage("Ceiling plastering", "First floor ceiling plastering", "sqm", 35, 6, (("cement", 7), ("m sand", 0.65)), 4),
        Stage("Plastering", "First floor internal plastering", "sqm", 40, 8, (("cement", 8), ("m sand", 0.75)), 4),
        Stage("External plastering", "External plastering, all four sides", "sqm", 45, 10, (("cement", 11), ("m sand", 1)), 5),
        # Labour only (Joy's bill); the tiles and adhesive are bought straight for the floor, not drawn from the site
        # store. Our own crew is off this site while Joy's crew lays (one helper for cleaning and curing).
        Stage("Floor tiling", "Vitrified floor tiles, ground and first floor", "sqm", 30, 8, (), 1, by="Joy Tiling Works"),
        Stage("Putty and primer", "Wall putty and primer coat, inside", "sqm", 110, 6, (), 3),
        Stage("Painting", "Two coats of emulsion inside, exterior paint outside", "sqm", 130, 6, (), 3),
        Stage("Snag list", "Snag list, touch-ups and cleaning for handover", "nos", 6, 5, (), 3),  # LRN-F18, LRN-F30: 5 days keeps the handover on day 62 (D1)
    ),
    "annex": (
        Stage("Plinth beam", "Plinth beam shuttering, steel and concrete", "rmt", 24, 3,
              (("cement", 10), ("aggregate 20mm", 1.5), ("m sand", 0.8), ("steel", 120)), 4),
        Stage("Plinth filling", "Plinth filled with excavated earth, rammed in layers", "cum", 30, 3, (), 1),
        Stage("Block work", "Block work, plinth to lintel", "sqm", 18, 8, (("cement", 3), ("solid blocks", 222), ("m sand", 0.4)), 4),
        Stage("Slab shuttering", "Roof slab shuttering", "sqm", 40, 2, (), 4),
        Stage("Slab reinforcement", "Roof slab steel cut, bent and tied", "kg", 500, 2, (("steel", 500), ("binding wire", 8)), 3),
        Stage("Slab concreting", "Roof slab poured, 12 cum", "cum", 12, 1, (("cement", 96), ("aggregate 20mm", 10), ("m sand", 6)), 8),
        Stage("Slab curing", "Roof slab curing, ponding", "sqm", 80, 5, (), 1),
        Stage("Plastering", "Internal and external plastering", "sqm", 35, 8, (("cement", 7), ("m sand", 0.65)), 4),
        Stage("Flooring", "Floor tiles laid by our masons", "sqm", 25, 4, (), 2),
        Stage("Painting", "Putty, primer and two coats", "sqm", 100, 5, (), 3),
    ),
    "tower_a": tuple(s for floor in ("Fourth", "Fifth", "Sixth") for s in (
        Stage("Column casting", f"{floor} floor columns cast", "cum", 4, 3,
              (("cement", 32), ("aggregate 20mm", 3), ("m sand", 1.6), ("steel", 300)), 6),
        Stage("Slab shuttering", f"{floor} floor slab shuttering", "sqm", 60, 4, (), 5),
        Stage("Slab reinforcement", f"{floor} floor slab steel tying", "kg", 900, 4, (("steel", 900), ("binding wire", 9)), 5),
        Stage("Slab concreting", f"{floor} floor slab poured with RMC", "cum", 16, 3, (("cement", 20), ("m sand", 1)), 8),
    )),
    "tower_b": (
        Stage("Retaining wall", "Retaining wall concreting, north side", "sqm", 35, 4,
              (("cement", 24), ("aggregate 20mm", 2.5), ("steel", 400), ("binding wire", 6)), 6),
        *(s for floor in ("Basement", "Ground", "First") for s in (
            Stage("Column casting", f"{floor} columns cast", "cum", 3, 4,
                  (("cement", 24), ("aggregate 20mm", 2.4), ("m sand", 1.2), ("steel", 260)), 6),
            Stage("Slab shuttering", f"{floor} slab shuttering", "sqm", 50, 5, (), 5),
            Stage("Slab reinforcement", f"{floor} slab steel tying", "kg", 1000, 5, (("steel", 1000), ("binding wire", 10)), 5),
            Stage("Slab concreting", f"{floor} slab poured with RMC", "cum", 15, 3, (("cement", 18), ("m sand", 1)), 8),
        )),
    ),
}

#: Rain: (day, sites) -> half a day's work and use, hours lost.
RAIN: dict[int, tuple[tuple[str, ...], float]] = {
    9: (("main", "annex"), 3.0), 10: (("main", "annex", "tower_a", "tower_b"), 4.0), 31: (("tower_a", "tower_b"), 2.5),
}
#: Issues seen on site and closed later: (day, site, type, severity, narrative, day closed, how).
ISSUES = (
    (3, "tower_a", "INSPECTION_WAITING", "HIGH", "Structural engineer to check fourth floor column steel before casting",
     4, "Checked and passed by the structural engineer"),
    (11, "main", "MATERIAL_SHORTAGE", "MEDIUM", "Wall putty brand asked for by the client not in stock at the dealer",
     16, "Client agreed to the alternative brand"),
    (17, "tower_b", "EQUIPMENT_BREAKDOWN", "HIGH", "Vibrator needle broke during retaining wall pour", 18,
     "Spare needle from Sri Hardwares, pour finished"),
    (24, "annex", "DRAWING_PENDING", "MEDIUM", "Electrical points for the annex not marked on the drawing", 27,
     "Architect sent the marked drawing on WhatsApp"),
    (44, "main", "QUALITY", "MEDIUM", "Hollow sound in two floor tiles in the ground floor bedroom", 46,
     "Joy Tiling Works relaid the two tiles"),
    (45, "tower_a", "LABOUR_SHORTAGE", "MEDIUM", "Bar benders short this week, slab steel slow", 48,
     "Two more bar benders from Rahim's crew"),
)
#: Advances to workers: (day, worker, amount).
ADVANCES = ((4, "Suresh", 2000), (13, "Joseph", 1500), (23, "Rajesh", 3000), (30, "Vinod", 1000), (41, "Manoj", 2500))
#: The tiling subcontract with Joy Tiling Works: the agreed rate a square metre, retention (green_villa.TILING, LRN-F28).
TILING_RATE, TILING_RETENTION = gv.TILING["rate"], gv.TILING["retention_pct"]
#: Units counted in whole pieces (work in nos, cement in bags): a day's share is a whole number (LRN-F14).
WHOLE_UNITS = ("nos", "bags")
#: Lake View's running bill to the client, sent by the owner on these days.
RA_BILL_DAYS = (23, 51)
#: Green Villa's running bill (project bible D2): monthly by its contract, so one in the 62 days, and the final bill on
#: the day it is handed over. Its client pays each after ``green_villa.PAYS_AFTER`` days.
GV_RA_BILL_DAYS = (30,)

# --- The plan's entries ----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Kind:
    """A kind of entry: who makes it, and the route(s) the player calls for it (method, path)."""

    role: str
    routes: tuple[tuple[str, str], ...]
    #: What a day of these says in "Days 1 to 2 passed" ("Ravi: work recorded 16"), and in the morning briefing's
    #: short line ("16 work entries"). Required, so a new kind can never reach the person as its code name.
    said: str = field(kw_only=True)
    short: str = field(kw_only=True)
    #: Everyday site records, said in one line per site in the readable plan.
    routine: bool = False


KINDS: dict[str, Kind] = {
    "conditions": Kind(ENGINEER, (("PATCH", "/dpr/site-days/{site_id}/conditions"),), routine=True, said="site days written up", short="site notes"),
    "attendance": Kind(ENGINEER, (("POST", "/labour/attendance"),), routine=True, said="attendance", short="attendance"),
    "work": Kind(ENGINEER, (("POST", "/progress/activities"),), routine=True, said="work recorded", short="work entries"),
    "use": Kind(ENGINEER, (("POST", "/materials/outflows"),), routine=True, said="material used", short="material used"),
    "expense": Kind(ENGINEER, (("POST", "/expenses"),), routine=True, said="expenses", short="expenses"),
    "issue": Kind(ENGINEER, (("POST", "/progress/issues"),), said="problems reported", short="problems"),
    "request": Kind(ENGINEER, (("POST", "/procurement/requests"),), said="material asked for", short="requests"),
    "delivery": Kind(ENGINEER, (("POST", "/materials/inflows"),), said="deliveries received", short="deliveries"),
    "order": Kind(PM, (("POST", "/procurement/orders"),), said="orders placed", short="orders"),
    # LRN-F18 (episode 4): the Main block's cement as the kit's paperwork has it.
    "transfer": Kind(PM, (("POST", "/materials/transfers"),), said="material moved between sites", short="moves"),
    "rfq": Kind(PM, (("POST", "/procurement/rfqs"),), said="quotes asked for", short="quote requests"),
    "quote": Kind(PM, (("POST", "/procurement/rfqs/{rfq_id}/quotes"),), said="quotes received", short="quotes"),
    "award": Kind(PM, (("POST", "/procurement/rfqs/{rfq_id}/award"),), said="quotes chosen", short="quotes chosen"),
    "return": Kind(PM, (("POST", "/procurement/returns"),), said="material sent back", short="returns"),
    "return_settle": Kind(PM, (("POST", "/procurement/returns/{return_id}/settle"),), said="returns settled", short="returns settled"),
    "bill_reverse": Kind(ACCOUNTS, (("POST", "/expenses/{expense_id}/reverse"),), said="bills taken back", short="bills taken back"),
    # LRN-F23: the month-end count at the Main block, and the owner's approval of its difference.
    "stock_count": Kind(ENGINEER, (("POST", "/materials/stock-counts"), ("PUT", "/materials/stock-counts/{count_id}/lines")), said="stock counted", short="stock counts"),
    "count_approve": Kind(OWNER, (("POST", "/materials/stock-counts/{count_id}/approve"),), said="stock counts approved", short="counts approved"),
    # LRN-F25 (episode 6): the Annex mixer on hire, its day logs (a breakdown raises the problem), the task that fixes
    # it, and the hire company's bill checked against the logs.
    "machine": Kind(PM, (("POST", "/equipment"),), said="machines brought in", short="machines"),
    "machine_log": Kind(ENGINEER, (("POST", "/equipment/logs"),), routine=True, said="machine hours logged", short="machine logs"),
    "task": Kind(PM, (("POST", "/tasks"),), said="tasks given", short="tasks"),
    "task_status": Kind(PM, (("POST", "/tasks/{task_id}/status"),), said="tasks done", short="tasks done"),
    "hire_bill": Kind(ACCOUNTS, (("POST", "/equipment/hire-bills"),), said="hire bills booked", short="hire bills"),
    "hire_bill_fix": Kind(PM, (("PATCH", "/equipment/hire-bills/{bill_id}"),), said="hire bills corrected", short="hire bills fixed"),
    "boq_count": Kind(PM, (("PUT", "/projects/{project_id}/boq/work/{quantity_id}"),), said="work put on the BOQ", short="BOQ counts"),
    "issue_resolve": Kind(PM, (("POST", "/progress/issues/{issue_id}/resolve"),), said="problems closed", short="fixed"),
    "work_order": Kind(PM, (("POST", "/subcontracts/work-orders"),), said="work orders", short="work orders"),
    "measurement": Kind(PM, (("POST", "/subcontracts/work-orders/{wo_id}/measurements"),), said="measurements", short="measurements"),
    "supplier_bill": Kind(ACCOUNTS, (("POST", "/finance/vendors/{vendor_id}/bills"),), said="supplier bills booked", short="bills booked"),
    "supplier_payment": Kind(ACCOUNTS, (("POST", "/finance/vendors/{vendor_id}/payments"),), said="suppliers paid", short="payments"),
    "sub_bill": Kind(ACCOUNTS, (("POST", "/subcontracts/work-orders/{wo_id}/bills"),), said="subcontract bills", short="subcontract bills"),
    "sub_payment": Kind(ACCOUNTS, (("POST", "/expenses/{expense_id}/payments"),), said="subcontractor paid", short="subcontract paid"),
    # LRN-F28 (episode 7): a subcontractor's bill above the measurement, turned down by the office.
    "sub_bill_reject": Kind(PM, (("POST", "/subcontracts/bills/{bill_id}/reject"),), said="subcontract bills turned down", short="bills turned down"),
    "advance": Kind(ACCOUNTS, (("POST", "/labour/advances"),), said="advances given", short="advances"),
    "wage_pay": Kind(ACCOUNTS, (("POST", "/labour/wage-sheets/{sheet_id}/pay"),), said="wages paid", short="wages paid"),
    "client_receipt": Kind(ACCOUNTS, (("POST", "/billing/receipts"),), said="client payments in", short="client payments"),
    "wage_approve": Kind(OWNER, (("GET", "/labour/wage-sheets/open"), ("POST", "/labour/wage-sheets/{sheet_id}/approve")), said="wage sheets approved", short="wages approved"),
    "ra_bill": Kind(OWNER, (("POST", "/projects/{project_id}/ra-bills"), ("POST", "/billing/ra-bills/{bill_id}/submit")), said="running bills sent", short="running bills"),
    "stage": Kind(OWNER, (("PATCH", "/projects/{project_id}/start"),), said="project stage moved", short="stage moved"),
    # D2: Green Villa's contract and its estimate as the BOQ (the guided project's chapters 2 and 3 do the same; when the
    # person did them, these find them done).
    "contract": Kind(OWNER, (("GET", "/projects/{project_id}/contract"), ("PUT", "/projects/{project_id}/contract")), said="contract set", short="contract"),
    "boq_norms": Kind(PM, (("GET", "/projects/{project_id}/boq"), ("PUT", "/projects/{project_id}/boq/lines/{line_id}/norms")), said="material norms set on the BOQ", short="BOQ norms"),
    "boq_import": Kind(PM, (("GET", "/projects/{project_id}/boq"), ("POST", "/projects/{project_id}/boq/sections"),
                            ("POST", "/projects/{project_id}/boq/sections/{section_id}/lines")), said="estimate brought in as the BOQ", short="BOQ imported"),
}
#: Where each route lives, for the test that every route is real (each is mounted as it is, no extra prefix).
ROUTER_MODULES = (
    "mesiri.domains.dpr.router", "mesiri.domains.workforce.router", "mesiri.domains.workforce.pay_router",
    "mesiri.domains.progress.router", "mesiri.domains.progress.boq_router", "mesiri.domains.materials.router",
    "mesiri.domains.expenses.router", "mesiri.domains.procurement.router", "mesiri.domains.procurement.orders_router",
    "mesiri.domains.subcontracts.router", "mesiri.domains.vendors.router", "mesiri.domains.billing.router",
    "mesiri.domains.schedule.router", "mesiri.domains.procurement.rfqs_router", "mesiri.domains.procurement.returns_router",
    "mesiri.domains.materials.stock_count_router", "mesiri.domains.equipment.router", "mesiri.domains.tasks.router",
)


@dataclass(frozen=True, eq=False)
class Entry:
    """One thing one person enters on one day. ``data`` carries the numbers the player needs (names, never ids: the
    player finds each sample company's own ids); ``needs`` the entries that must be saved before it."""

    id: str
    day: int
    kind: str
    what: str
    site: str | None = None
    project: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    needs: tuple[str, ...] = ()

    @property
    def role(self) -> str:
        return KINDS[self.kind].role


@dataclass
class Plan:
    entries: list[Entry]
    #: Stock per (site, material) when the plan starts: what the seed leaves.
    opening: dict[tuple[str, str], float]
    #: What is still to come on the seed's own orders: (site, material) -> quantity.
    seeded_on_order: dict[tuple[str, str], float]
    #: The day Green Villa is handed over: the plan's last day.
    last_day: int

    def day(self, n: int) -> list[Entry]:
        return [e for e in self.entries if e.day == n]

    def by_id(self) -> dict[str, Entry]:
        return {e.id: e for e in self.entries}


def weekday(day: int) -> int:
    """Monday 0 .. Sunday 6. Day 0 is a Saturday (the seed's last day is made a Saturday, a pay day)."""
    return (5 + day) % 7


def is_sunday(day: int) -> bool:
    return weekday(day) == 6


def _working_after(day: int, n: int) -> int:
    while n > 0:
        day += 1
        if not is_sunday(day):
            n -= 1
    return day


def _fmt(qty: float) -> str:
    return f"{qty:,.0f}" if float(qty).is_integer() or qty >= 100 else f"{qty:,.2f}".rstrip("0").rstrip(".")


def _amount(value: float) -> str:
    return f"₹{value:,.0f}"


def _of(name: str) -> str:
    """Green Villa's, Lake View Apartments'."""
    return f"{name}'" if name.endswith("s") else f"{name}'s"


# --- The opening: what the seed leaves -------------------------------------------------------------------------------


class _Recorder:
    """A stand-in for the API that ``sample_story.seed`` writes through: it answers like the real one and keeps the
    stock per site and what is still to come on each order."""

    def __init__(self) -> None:
        self.n = 0
        self.stock: dict[tuple[str, str], float] = defaultdict(float)
        self.lines: dict[str, list[Any]] = {}  # order line id -> [site id, material id, quantity left]

    def _id(self, kind: str) -> str:
        self.n += 1
        return f"{kind}-{self.n}"

    async def call(self, method: str, path: str, *, json: Any = None, params: dict | None = None,
                   idempotency_key: str | None = None) -> Any:
        body = json or {}
        if method == "GET" and path == "/materials":
            return _Ok({"items": [{"id": f"m:{name}", "name": name, "default_unit_id": f"u:{name}"} for name in UNITS]})
        if method == "GET":
            return _Ok({})
        if path == "/materials/inflows":
            self.stock[(body["site_id"], body["material_id"])] += float(body["quantity"])
            line = body.get("purchase_order_line_id")
            if line:
                self.lines[line][2] -= float(body["quantity"])
        elif path == "/materials/outflows":
            self.stock[(body["site_id"], body["material_id"])] -= float(body["quantity"])
        elif path == "/materials/transfers":
            self.stock[(body["from_site_id"], body["material_id"])] -= float(body["quantity"])
            self.stock[(body["to_site_id"], body["material_id"])] += float(body["quantity"])
        elif path == "/procurement/orders":
            line = body["lines"][0]
            line_id = self._id("line")
            self.lines[line_id] = [body["site_id"], line["material_id"], float(line["quantity"])]
            return _Ok({"id": self._id("order"), "lines": [{"id": line_id}]})
        return _Ok({"id": self._id(path.strip("/").replace("/", "-"))})


@dataclass
class _Ok:
    body: Any
    ok: bool = True
    status: int = 200


def _run(coro: Any) -> Any:
    """Run a coroutine that never waits on anything (the recorder answers at once), with no event loop: so the plan
    can be made inside a request as well as in a script."""
    try:
        coro.send(None)
    except StopIteration as done:
        return done.value
    coro.close()
    raise RuntimeError("the seed waited on something real; the plan's recorder must answer everything at once")


#: The seed's day 0: any Saturday gives the same story (its days are counted back from it, Sundays off).
_A_SATURDAY = dt.date(2026, 11, 14)


def opening() -> tuple[dict[tuple[str, str], float], dict[tuple[str, str], float]]:
    """Stock per (site, material) and what is still to come on the seed's orders, as the seed leaves them."""
    recorder = _Recorder()
    info = {"project_id": "project-gv", "site_ids": ["site-main", "site-annex"], "others": []}
    _run(story.seed(recorder, info, today=_A_SATURDAY))
    site_ids = ["site-main", "site-annex"] + sorted(
        {sid for (sid, _m) in recorder.stock if sid not in ("site-main", "site-annex")},
        key=lambda sid: int(sid.rsplit("-", 1)[1]))
    key_of = {sid: SITES[i][0] for i, sid in enumerate(site_ids[: len(SITES)])}
    stock = {(key_of[sid], mid[2:]): round(qty, 2) for (sid, mid), qty in recorder.stock.items() if sid in key_of}
    on_order = {(key_of[sid], mid[2:]): left for sid, mid, left in recorder.lines.values() if left > 0 and sid in key_of}
    return stock, on_order


# --- Making the plan -------------------------------------------------------------------------------------------------


class _Builder:
    def __init__(self) -> None:
        self.entries: list[Entry] = []
        self.counts: dict[str, int] = defaultdict(int)

    def add(self, day: int, kind: str, what: str, *, site: str | None = None, project: str | None = None,
            data: dict | None = None, needs: tuple[str, ...] = ()) -> Entry:
        key = f"d{day:02d}-{kind}-{site or project or 'company'}"
        self.counts[key] += 1
        n = self.counts[key]
        entry = Entry(id=key if n == 1 else f"{key}-{n}", day=day, kind=kind, what=what, site=site,
                      project=project or (SITE_PROJECT[site] if site else None), data=data or {}, needs=needs)
        self.entries.append(entry)
        return entry


def build() -> Plan:
    stock0, seeded = opening()
    stock: dict[tuple[str, str], float] = defaultdict(float, stock0)
    seeded_left = dict(seeded)
    b = _Builder()

    stage_at = {key: 0 for key, _p, _n in SITES}          # index into STAGES[site]
    done_days = {key: 0.0 for key, _p, _n in SITES}       # full days of the current stage done
    finished: dict[str, int] = {}                          # site -> day its last stage ended
    coming: dict[tuple[str, str], float] = defaultdict(float)   # asked for or ordered, not yet delivered
    to_order: list[tuple[int, Entry]] = []                 # (order on this day, its request)
    # (day, order or None for the seed's, site, material, qty, extra: rate, vendor, a note, what follows the delivery)
    to_deliver: list[tuple[int, Entry | None, str, str, float, dict]] = []
    story_due: dict[int, list[Any]] = defaultdict(list)    # LRN-F18: the cement story's office work, by day
    story_used = False
    to_bill: list[tuple[int, Entry]] = []                  # (bill on this day, delivery)
    unpaid: dict[str, list[Entry]] = defaultdict(list)     # vendor -> bills
    week_work: dict[str, float] = defaultdict(float)       # tiling laid and not measured yet
    laid: dict[str, float] = defaultdict(float)            # LRN-F28: all the tiling laid so far
    tiling_bills: dict[int, list[tuple[str, Entry]]] = defaultdict(list)  # day -> (which bill, its measurement)
    tiling: dict[str, Entry] = {}                          # the work order, and the last measurement and bill
    to_count: list[tuple[int, Entry]] = []                 # work to count on the BOQ, on this day
    gv_setup: dict[str, Entry] = {}                        # D2: Green Villa's contract and BOQ entries
    issues: dict[int, list[Entry]] = defaultdict(list)     # day to close -> issue
    machine_story: dict[str, Any] = {}                     # LRN-F25: the Annex mixer, its problem and task
    ra_bills: list[tuple[int, Entry]] = []                 # (client pays on this day, the bill)
    workers = {at: [(n, t, w) for n, t, w, home in story.DEMO_WORKERS if home == at] for at in range(len(SITES))}
    worker_site = {n: SITES[home][0] for n, _t, _w, home in story.DEMO_WORKERS}
    boq_lines = {(SITES[at][0], work) for at in range(2, 4) for work, *_ in story.DEMO_WORK[at]}
    spend = 0

    def stage(site: str) -> Stage | None:
        stages = STAGES[site]
        return stages[stage_at[site]] if stage_at[site] < len(stages) else None

    def daily_use(site: str, material: str, ahead: int) -> float:
        """What the site will use of a material over the next ``ahead`` working days, stage by stage."""
        total, at = 0.0, stage_at[site]
        days = ahead
        while days > 0 and at < len(STAGES[site]):
            s = STAGES[site][at]
            left = s.days - (done_days[site] if at == stage_at[site] else 0)
            take = min(days, math.ceil(left))
            total += take * dict(s.use).get(material, 0)
            days -= take
            at += 1
        return total

    def cement_story(day: int, request: Entry) -> None:
        """LRN-F18: the Main block's first cement request, as the kit's paperwork has it (``CEMENT_STORY``)."""
        cs = CEMENT_STORY
        site, other = cs["site"], cs["from_site"]
        move = min(cs["move"], math.floor(stock[(other, "cement")]))
        b.add(day, "transfer", f"Move {move} bags cement from {SITE_NAME[other]} to {SITE_NAME[site]}, so its masons work",
              site=site, data={"material": "cement", "quantity": move, "from_site": other}, needs=(request.id,))
        stock[(other, "cement")] -= move
        stock[(site, "cement")] += move
        names = [v for v, _ref, _rates in cs["quotes"]]
        lines = [{"material": m, "quantity": q} for m, q in cs["lines"]]
        rfq = b.add(day, "rfq", f"Ask {', '.join(names[:-1])} and {names[-1]} for quotes: "
                    + ", ".join(f"{_fmt(q)} {UNITS[m]} {m}" for m, q in cs["lines"]) + f" for {SITE_NAME[site]}",
                    site=site, data={"lines": lines, "vendors": names}, needs=(request.id,))
        for m, q in cs["lines"]:
            coming[(site, m)] += q - (request.data["quantity"] if m == "cement" else 0)

        def quotes_and_award(qday: int) -> None:
            quotes = [b.add(qday, "quote", f"{v}'s quote {ref}: " + ", ".join(f"{m} {_amount(r)}" for m, r in rates.items()),
                            site=site, data={"vendor": v, "their_ref": ref, "rates": rates, "gst_percent": 18,
                                             "delivery_days": 2, "valid_days": 7}, needs=(rfq.id,))
                      for v, ref, rates in cs["quotes"]]
            best = {m: min(cs["quotes"], key=lambda vq, m=m: vq[2][m]) for m, _q in cs["lines"]}
            award = b.add(qday, "award", "Order each line from its cheapest: "
                          + ", ".join(f"{m} from {best[m][0]} at {_amount(best[m][2][m])}" for m, _q in cs["lines"]),
                          site=site, data={"mode": "lowest_per_line", "request": request.id,
                                           "lines": [{"material": m, "quantity": q, "vendor": best[m][0], "rate": best[m][2][m]}
                                                     for m, q in cs["lines"]]},
                          needs=tuple(q.id for q in quotes))
            for m, q in cs["lines"]:
                vendor, rate = best[m][0], best[m][2][m]
                if m == "cement":
                    to_deliver.append((_working_after(qday, LEAD_DAYS[m]), award, site, m, cs["sent"],
                                       {"vendor": vendor, "rate": rate, "after": lorry,
                                        "note": f" on challan {cs['challan']} ({_fmt(q)} ordered, {_fmt(q - cs['sent'])} to follow)"}))
                    to_deliver.append((_working_after(qday, LEAD_DAYS[m] + 3), award, site, m, q - cs["sent"],
                                       {"vendor": vendor, "rate": rate, "note": " (the rest of the order)"}))
                else:
                    to_deliver.append((_working_after(qday, LEAD_DAYS[m]), award, site, m, q, {"vendor": vendor, "rate": rate}))

        def lorry(dday: int, delivery: Entry) -> None:
            torn, rate, vendor = cs["torn"], delivery.data["rate"], delivery.data["vendor"]
            lot = {"material": "cement", "vendor": vendor, "quantity": delivery.data["quantity"]}  # the player finds it
            ret = b.add(dday, "return", f"Send back {torn} torn bags of cement to {vendor}: return note {cs['return_note']}, "
                        f"{_amount(torn * rate)}", site=site,
                        data={"material": "cement", "quantity": torn, "rate": rate, "vendor": vendor, "reason": "damaged",
                              "note": cs["return_note"], "receipt": lot}, needs=(delivery.id,))
            stock[(site, "cement")] -= torn

            def wrong_bill(bday: int) -> None:
                amount = round(delivery.data["quantity"] * cs["bill_rate"], 2)
                wrong = b.add(bday, "supplier_bill", f"Bill from {vendor} {cs['bill']}: {_fmt(delivery.data['quantity'])} bags "
                              f"cement at {_amount(cs['bill_rate'])}, {_amount(amount)}", site=site,
                              data={"vendor": vendor, "amount": amount, "deliveries": [delivery.id], "bill_number": cs["bill"],
                                    "receipt": lot},
                              needs=(delivery.id,))
                taken = b.add(bday, "bill_reverse", f"Take back {_of(vendor)} bill {cs['bill']}: {_amount(cs['bill_rate'] - rate)} "
                              f"a bag above the order, and {torn} bags returned; ask for a corrected bill", site=site,
                              data={"vendor": vendor, "bill_number": cs["bill"]}, needs=(wrong.id,))

                def corrected(cday: int) -> None:
                    kept = delivery.data["quantity"] - torn
                    bill = b.add(cday, "supplier_bill", f"Corrected bill from {vendor} {cs['bill']}-R: {_fmt(kept)} bags cement "
                                 f"at {_amount(rate)}, {_amount(round(kept * rate, 2))}", site=site,
                                 data={"vendor": vendor, "amount": round(kept * rate, 2), "deliveries": [delivery.id],
                                       "bill_number": f"{cs['bill']}-R", "returned": torn, "receipt": lot},
                                 needs=(delivery.id, taken.id))
                    unpaid[vendor].append(bill)
                    b.add(cday, "return_settle", f"Settle return note {cs['return_note']} against {_of(vendor)} corrected bill",
                          site=site, data={"vendor": vendor, "how": "credit", "bill_number": f"{cs['bill']}-R"},
                          needs=(ret.id, bill.id))

                story_due[_working_after(bday, 1)].append(corrected)

            story_due[_working_after(dday, BILL_AFTER)].append(wrong_bill)

        story_due[_working_after(day, 1)].append(quotes_and_award)

    day, last_day = 0, None
    while last_day is None:
        day += 1
        if day > 120:
            raise RuntimeError("the plan never reaches Green Villa's handover")
        if is_sunday(day):
            continue
        saturday = weekday(day) == 5
        if day == 2:
            # D2: Green Villa's contract and its estimate as the BOQ, so its work counts and it can be billed.
            c = gv.CONTRACT
            gv_setup["contract"] = b.add(day, "contract", f"Set {_of(story.DEMO_PROJECT)} contract with {gv.CLIENT['name']}: "
                                         f"{c['contract_no']}, {_amount(c['contract_value'])}, retention {c['retention_pct']}%",
                                         project=GREEN_VILLA, data={"client": dict(gv.CLIENT), **{k: c[k] for k in (
                                             "contract_no", "signed_on", "contract_value", "mobilisation_advance",
                                             "advance_recovery_pct", "retention_pct", "gst_pct", "defect_liability_months",
                                             "payment_terms")}})
            gv_setup["boq"] = b.add(day, "boq_import", f"Put {_of(story.DEMO_PROJECT)} estimate in as its BOQ: "
                                    f"{sum(len(r) for _h, r in gv.ESTIMATE)} lines", project=GREEN_VILLA)
            # LRN-F30: what a unit of each line should use (the kit's "Materials per unit" sheet): Materials vs BOQ.
            b.add(day, "boq_norms", f"Put the materials a unit uses on {_of(story.DEMO_PROJECT)} BOQ: "
                  f"{len({c for c, *_ in gv.NORMS})} lines, {gv.NORM_WASTAGE}% wastage", project=GREEN_VILLA,
                  data={"wastage_pct": gv.NORM_WASTAGE}, needs=(gv_setup["boq"].id,))
            # LRN-F30: the seeded weeks' work counted on the estimate's lines too, so their cost is set against what
            # they earned (Cost control read them as spent and never earned: half a forecast's overrun).
            for at in range(2):
                site = SITES[at][0]
                for work, *_rest in story.DEMO_WORK[at]:
                    line = gv.STAGE_LINE.get(work, work)
                    if gv.line_of(work):
                        b.add(day, "boq_count", f"Count {_of(SITE_NAME[site])} {work.lower()} of the weeks before on the "
                              f"BOQ line {line}", site=site, data={"work": work, "line": line, "estimate": True},
                              needs=(gv_setup["boq"].id,))
            # The seeded weeks' last pay week (to day 0) is still to be approved and paid: the first thing on Monday.
            for project in (GREEN_VILLA, LAKE_VIEW):
                approve = b.add(day, "wage_approve", f"Approve {_of(PROJECT_NAME[project])} wage sheet for last week",
                                project=project, data={"week_from_day": -6, "week_to_day": 0})
                b.add(day, "wage_pay", f"Pay {_of(PROJECT_NAME[project])} wages for last week", project=project,
                      data={"week_from_day": -6, "week_to_day": 0}, needs=(approve.id,))

        # Morning: the lorries that are due.
        for due in [d for d in to_deliver if d[0] == day]:
            to_deliver.remove(due)
            _d, order, site, material, qty, extra = due
            vendor, _size, rate = story.DEMO_SUPPLY[material]
            vendor, rate = extra.get("vendor", vendor), extra.get("rate", rate)
            delivery = b.add(day, "delivery", f"Received {_fmt(qty)} {UNITS[material]} {material} from {vendor} at {SITE_NAME[site]}"
                             + ("" if order else " (on the order placed before)") + extra.get("note", ""), site=site,
                             data={"material": material, "quantity": qty, "vendor": vendor, "rate": rate,
                                   "against": order.id if order else "seeded order"},
                             needs=(order.id,) if order else ())
            stock[(site, material)] += qty
            coming[(site, material)] -= qty
            if extra.get("after"):
                extra["after"](day, delivery)
            else:
                to_bill.append((_working_after(day, BILL_AFTER), delivery))

        # The office: orders for yesterday's requests, bills that came, work to count, issues to close.
        for act in story_due.pop(day, []):
            act(day)
        for due in [t for t in to_order if t[0] == day]:
            to_order.remove(due)
            request = due[1]
            material, qty, site = request.data["material"], request.data["quantity"], request.site
            if not story_used and site == CEMENT_STORY["site"] and material == "cement":
                story_used = True
                cement_story(day, request)
                continue
            vendor, _size, rate = story.DEMO_SUPPLY[material]
            order = b.add(day, "order", f"Order {_fmt(qty)} {UNITS[material]} {material} from {vendor} for {SITE_NAME[site]} "
                          f"at {_amount(rate)} a {PER[material]}",
                          site=site, data={"material": material, "quantity": qty, "vendor": vendor, "rate": rate,
                                           "expected_in_days": LEAD_DAYS[material]}, needs=(request.id,))
            to_deliver.append((_working_after(day, LEAD_DAYS[material]), order, site, material, qty, {}))
        for due in [t for t in to_bill if t[0] == day]:
            to_bill.remove(due)
            delivery = due[1]
            d = delivery.data
            amount = round(d["quantity"] * d["rate"], 2)
            bill = b.add(day, "supplier_bill", f"Bill from {d['vendor']}: {_fmt(d['quantity'])} {UNITS[d['material']]} "
                         f"{d['material']} for {SITE_NAME[delivery.site]} on day {delivery.day}, {_amount(amount)}", site=delivery.site,
                         data={"vendor": d["vendor"], "amount": amount, "deliveries": [delivery.id],
                               "bill_number": f"{d['vendor'][:2].upper()}/{delivery.day:02d}{len(unpaid[d['vendor']]) + 1}"},
                         needs=(delivery.id,))
            unpaid[d["vendor"]].append(bill)
        for due in [t for t in to_count if t[0] == day]:
            to_count.remove(due)
            work = due[1]
            if SITE_PROJECT[work.site] == GREEN_VILLA:  # D2: on the estimate's line (green_villa.STAGE_LINE)
                line = gv.STAGE_LINE.get(work.data["work"], work.data["work"])
                b.add(day, "boq_count", f"Count {_of(SITE_NAME[work.site])} {work.data['work'].lower()} of day {work.day} "
                      f"on the BOQ line {line}", site=work.site, data={"work": work.data["work"], "line": line, "estimate": True},
                      needs=(work.id, gv_setup["boq"].id))
                continue
            b.add(day, "boq_count", f"Count {_of(SITE_NAME[work.site])} {work.data['work'].lower()} of day {work.day} on its BOQ line",
                  site=work.site, data={"work": work.data["work"], "line": f"{work.data['work']} · {SITE_NAME[work.site]}"},
                  needs=(work.id,))
        for issue in [i for close_day in sorted(k for k in issues if k <= day) for i in issues.pop(close_day)]:
            b.add(day, "issue_resolve", f"Close: {issue.data['narrative']}", site=issue.site,
                  data={"narrative": issue.data["narrative"], "resolution_notes": issue.data["close_note"]}, needs=(issue.id,))
        for adv_day, worker, amount in ADVANCES:
            if adv_day == day:
                b.add(day, "advance", f"Advance of {_amount(amount)} to {worker}", site=worker_site[worker],
                      data={"worker": worker, "amount": amount})

        # The sites' day.
        rain_sites, rain_hours = RAIN.get(day, ((), 0.0))
        for at, (site, _project, _name) in enumerate(SITES):
            s = stage(site)
            if s is None:
                continue
            rained = site in rain_sites
            weather = 1.0 if not rained else 0.5
            # Material: the day's use, as far as the stock goes; the work goes as far as the shortest material lets it.
            want = {m: q * weather for m, q in s.use}
            can = min([1.0] + [min(1.0, stock[(site, m)] / q) for m, q in want.items() if q > 0])
            can = math.floor(can * 20) / 20  # in twentieths, so the numbers stay readable
            ratio = weather * can
            for m, q in want.items():
                used = round(q * can, 2)
                if UNITS[m] in WHOLE_UNITS:  # never more than the share: a bag is opened whole or not at all
                    used = math.floor(used)
                if used > 0:
                    stock[(site, m)] = round(stock[(site, m)] - used, 2)
                    b.add(day, "use", f"Used {_fmt(used)} {UNITS[m]} {m} for {s.work.lower()}", site=site,
                          data={"material": m, "quantity": used, "work": s.work})
            # People: the site's own workers (one off now and then) and the gang.
            crew = [{"name": n, "trade": t, "daily_wage": w,
                     "status": "absent" if (day + i) % 9 == 0 else "half_day" if rained else "present"}
                    for i, (n, t, w) in enumerate(workers[at])] if not s.by else []  # LRN-F30: a subcontractor's stage
            gang = max(1, round(s.gang * (0.5 if can < 0.5 else 1)))
            rw = gv.REWORK  # LRN-F30: after the rework is noticed, the rest of the stage with fewer helpers
            if site == rw["site"] and s.work == rw["work"] and rw["noticed"] < day:
                gang = min(gang, rw["gang"])
            present = sum(1 for c in crew if c["status"] != "absent") + gang
            b.add(day, "attendance", f"Attendance: {present} on site", site=site,
                  data={"workers": crew, "gang": {"contractor": "Bengal crew (Rahim)", "trade": "helper", "headcount": gang,
                                                  "daily_wage": 700}})
            if ratio > 0:
                qty = round(s.per_day * ratio, 2)
                redo = site == rw["site"] and s.work == rw["work"] and day in rw["days"]
                if redo:  # LRN-F30: a full day's crew and cement, part of it on walls plastered again
                    qty = round(qty * rw["share"], 2)
                if s.unit in WHOLE_UNITS:  # LRN-F14: points and pieces are counted whole ("12 nos", never 12.1)
                    qty = max(1, round(qty))
                work = b.add(day, "work", f"{s.work}: {_fmt(qty)} {s.unit}" + (f" (by {s.by})" if s.by else "")
                             + (f", the rest of the day {rw['why']}" if redo else ""), site=site,
                             data={"work": s.work, "quantity": qty, "unit": s.unit, "by": s.by,
                                   "narrative": s.narrative + (f"; {rw['why']}" if redo else "")})
                if (site, s.work) in boq_lines or (SITE_PROJECT[site] == GREEN_VILLA and gv.STAGE_LINE.get(s.work)):
                    to_count.append((_working_after(day, 1), work))
                if s.by:
                    week_work[site] += qty
                    laid[site] += qty
            vendor, category, amount, what = story.DEMO_SPENDS[spend % len(story.DEMO_SPENDS)]
            spend += 1
            b.add(day, "expense", f"{what}, {_amount(amount)} at {vendor}", site=site,
                  data={"vendor": vendor, "category": category, "amount": amount, "description": what})
            done_days[site] += ratio
            if done_days[site] >= s.days - 1e-9:
                stage_at[site] += 1
                done_days[site] = 0.0
                if stage(site) is None:
                    finished[site] = day
            nxt = stage(site)
            short = [m for m, q in want.items() if q > 0 and stock[(site, m)] < q]
            b.add(day, "conditions", ("Rain, " + _fmt(rain_hours) + " hours lost" if rained else "Clear")
                  + (f"; short of {', '.join(short)}" if can < 1 else ""), site=site,
                  data={"weather": "rainy" if rained else "sunny", "hours_lost": rain_hours if rained else None,
                        "tomorrow_plan": nxt.narrative if nxt else "Handover"})
            # Ask for what will run short before a lorry could come.
            for m in sorted({m for st in STAGES[site][stage_at[site]: stage_at[site] + 2] for m, _q in st.use}):
                need = daily_use(site, m, LEAD_DAYS[m] + COVER_DAYS)
                have = stock[(site, m)] + coming[(site, m)]
                if need <= 0 or have >= need:
                    continue
                _vendor, size, _rate = story.DEMO_SUPPLY[m]
                if seeded_left.get((site, m), 0) > 0:
                    qty = min(seeded_left[(site, m)], size * max(1, math.ceil((need - have) / size)))
                    seeded_left[(site, m)] -= qty
                    coming[(site, m)] += qty
                    to_deliver.append((_working_after(day, 1), None, site, m, qty, {}))
                    continue
                qty = size * max(1, math.ceil((need - have) / size))
                request = b.add(day, "request", f"Ask for {_fmt(qty)} {UNITS[m]} {m} for {SITE_NAME[site]}", site=site,
                                data={"material": m, "quantity": qty,
                                      "needed_by_days": LEAD_DAYS[m] + 1, "purpose": nxt.work if nxt else s.work})
                coming[(site, m)] += qty
                to_order.append((_working_after(day, 1), request))

        # LRN-F23: the month's end at the Main block: the store counted after the day's use, the difference approved.
        if story_used and day == CEMENT_STORY["count_day"]:
            cs, site = CEMENT_STORY, CEMENT_STORY["site"]
            book = stock[(site, "cement")]
            counted = b.add(day, "stock_count", f"Count {_of(SITE_NAME[site])} store: cement {_fmt(book - cs['count_short'])} bags "
                            f"against {_fmt(book)} in the book, {cs['count_short']} short ({cs['count_reason']})", site=site,
                            data={"material": "cement", "short": cs["count_short"], "reason": cs["count_reason"], "book": book})
            b.add(day, "count_approve", f"Approve {_of(SITE_NAME[site])} stock count: {cs['count_short']} bags cement written off "
                  f"({cs['count_reason']})", site=site, data={"material": "cement"}, needs=(counted.id,))
            stock[(site, "cement")] -= cs["count_short"]

        # LRN-F30 (episode 9): the plastering line red, noticed; Ravi to mark the conduits before the next room.
        if day == gv.REWORK["noticed"]:
            rw = gv.REWORK
            b.add(day, "task", f"Task for {WHO[ENGINEER]}: {rw['task']} (plastering red on Green / red: {rw['why']})",
                  site=rw["site"], data={"title": rw["task"], "for": ENGINEER, "due_days": rw["task_due_days"]})

        # LRN-F25 (episode 6): the Annex mixer (green_villa.HIRE).
        hire, mixer_site = gv.HIRE, "annex"
        if day == hire["on_day"]:
            machine_story["machine"] = b.add(
                day, "machine", f"Put the {hire['short_name'].lower()} from {hire['vendor']} on hire at {SITE_NAME[mixer_site]}, "
                f"{_amount(hire['rate_per_hour'])} an hour", site=mixer_site,
                data={"machine": hire["short_name"], "type": hire["machine"], "vendor": hire["vendor"],
                      "rate": hire["rate_per_hour"]})
        if day in hire["log"] and "machine" in machine_story:
            worked, broke = hire["log"][day]
            said = f"{hire['short_name']} {_fmt(worked)} hr{'' if worked == 1 else 's'}" + (f", broke down {_fmt(broke)} hrs: {hire['breakdown_reason']}" if broke else "")
            log = b.add(day, "machine_log", said, site=mixer_site,
                        data={"machine": hire["short_name"], "worked": worked, "breakdown": broke,
                              "reason": hire["breakdown_reason"] if broke else None},
                        needs=(machine_story["machine"].id,))
            if broke:
                # The log raises the problem itself (equipment's breakdown rule), in these words.
                narrative = f"{hire['short_name']} breakdown, {_fmt(broke)} hrs: {hire['breakdown_reason']}"
                machine_story["problem"] = log
                machine_story["narrative"] = narrative
                machine_story["task"] = b.add(
                    day, "task", f"Task for {WHO[ENGINEER]}: {hire['task']}, due tomorrow", site=mixer_site,
                    data={"title": hire["task"], "for": ENGINEER, "due_days": hire["task_due_days"],
                          "narrative": narrative}, needs=(log.id,))
            elif "task" in machine_story and "fixed" not in machine_story:
                fixed = b.add(day, "task_status", f"Done: {hire['task']} ({hire['fixed']})", site=mixer_site,
                              data={"title": hire["task"], "status": "done", "note": hire["fixed"]},
                              needs=(machine_story["task"].id,))
                machine_story["fixed"] = fixed
                b.add(day, "issue_resolve", f"Close: {machine_story['narrative']}", site=mixer_site,
                      data={"narrative": machine_story["narrative"], "resolution_notes": hire["fixed"]},
                      needs=(machine_story["problem"].id, fixed.id))
        if day == hire["bill_day"] and "machine" in machine_story:
            days = sorted(hire["log"])
            billed = hire["billed_hours"] * hire["rate_per_hour"]
            bill = b.add(day, "hire_bill", f"Bill {hire['bill']} from {hire['vendor']}: {hire['short_name'].lower()}, "
                         f"days {days[0]} to {days[-1]}, {hire['billed_hours']} hours, {_amount(billed)}", site=mixer_site,
                         data={"machine": hire["short_name"], "bill_ref": hire["bill"], "from_day": days[0], "to_day": days[-1],
                               "hours": hire["billed_hours"], "amount": billed},
                         needs=tuple(e.id for e in b.entries if e.kind == "machine_log" and e.site == mixer_site))
            agreed = hire["logged_hours"] * hire["rate_per_hour"]
            b.add(day, "hire_bill_fix", f"Correct bill {hire['bill']} to the {hire['logged_hours']} hours logged, "
                  f"{_amount(agreed)}: {hire['agreed']}", site=mixer_site,
                  data={"bill_ref": hire["bill"], "hours": hire["logged_hours"], "amount": agreed, "note": hire["agreed"]},
                  needs=(bill.id,))

        # Issues seen today (closed on their day).
        for issue_day, site, kind, severity, narrative, close_day, note in ISSUES:
            if issue_day == day:
                issue = b.add(day, "issue", narrative, site=site,
                              data={"issue_type": kind, "severity": severity, "narrative": narrative, "close_note": note})
                issues[close_day].append(issue)

        # The tiling subcontract: the work order two working days before Joy's crew starts, measured on Saturdays,
        # billed on the Monday after, paid the Saturday after that.
        for site in ("main",):
            upcoming = [st for st in STAGES[site][stage_at[site]:] if st.by]
            if upcoming and "work_order" not in tiling:
                st = upcoming[0]
                ahead = sum(x.days for x in STAGES[site][stage_at[site]: STAGES[site].index(st)]) - done_days[site]
                if ahead <= 2:
                    quantity = st.per_day * st.days
                    tiling["work_order"] = b.add(day, "work_order", f"Work order to {st.by}: {st.work.lower()}, "
                                                 f"{_fmt(quantity)} {st.unit} at {_amount(TILING_RATE)}", site=site,
                                                 data={"vendor": st.by, "work": st.work, "unit": st.unit, "quantity": quantity,
                                                       "rate": TILING_RATE, "retention_pct": TILING_RETENTION})
            # LRN-F28 (episode 7): measured when the ground floor is finished (the kit's measurement sheet) and when
            # the tiling is done; billed the next working day. The ground floor's bill asks for more than was measured
            # (green_villa.TILING), is turned down the same day, and Joy's corrected bill comes the day after.
            if "work_order" in tiling and week_work[site] > 0:
                ground = gv.ground_floor_tiled()
                tiling_now = stage(site) is not None and stage(site).by  # still laying
                part = ("ground" if "ground" not in tiling and laid[site] >= ground
                        else "rest" if "ground" in tiling and "rest" not in tiling and not tiling_now else None)
                if part:
                    qty = ground if part == "ground" else round(week_work[site], 2)
                    week_work[site] = round(week_work[site] - qty, 2)
                    words = "the finished ground floor, room by room" if part == "ground" else "the first floor, the rest of the order"
                    m = b.add(day, "measurement", f"Measure the tiling {st_by(site)} laid: {words}, {qty:g} sqm",
                              site=site, data={"work": "Floor tiling", "quantity": qty}, needs=(tiling["work_order"].id,))
                    tiling[part] = m
                    tiling_bills[_working_after(day, 1)].append((part, m))
            for part, measured in tiling_bills.pop(day, []):
                t, qty = gv.TILING, measured.data["quantity"]
                if part == "ground":
                    asked = t["billed"]
                    flagged = b.add(day, "sub_bill", f"Bill {t['bill']} from {st_by(site)}: {_fmt(asked)} sqm of tiling, "
                                    f"{_amount(asked * TILING_RATE)} (measured {_fmt(qty)})", site=site,
                                    data={"vendor": t["vendor"], "work": "Floor tiling", "quantity": asked, "rate": TILING_RATE,
                                          "amount": round(asked * TILING_RATE, 2), "their_bill_no": t["bill"], "flagged": True},
                                    needs=(measured.id,))
                    b.add(day, "sub_bill_reject", f"Turn down bill {t['bill']}: {t['reject']}", site=site,
                          data={"bill": t["bill"], "reason": t["reject"]}, needs=(flagged.id,))
                    tiling_bills[_working_after(day, 1)].append(("corrected", measured))
                    continue
                ref = t["corrected"] if part == "corrected" else t["last_bill"]
                amount = round(qty * TILING_RATE, 2)
                tiling[f"b{day}"] = b.add(day, "sub_bill", f"Bill {ref} from {st_by(site)}: {qty:g} sqm of tiling, {_amount(amount)}",
                                          site=site, data={"vendor": t["vendor"], "work": "Floor tiling", "quantity": qty,
                                                           "rate": TILING_RATE, "amount": amount, "their_bill_no": ref},
                                          needs=(measured.id,))

        # Saturday: suppliers paid for bills a week old, the subcontractor's bills paid, wages approved and paid.
        if saturday:
            for vendor in sorted(unpaid):
                due = [bill for bill in unpaid[vendor] if day - bill.day >= CREDIT_DAYS]
                if not due:
                    continue
                unpaid[vendor] = [bill for bill in unpaid[vendor] if bill not in due]
                total = round(sum(bill.data["amount"] for bill in due), 2)
                b.add(day, "supplier_payment", f"Pay {vendor} {_amount(total)} for {len(due)} bill{'s' if len(due) > 1 else ''}",
                      data={"vendor": vendor, "amount": total, "bills": [bill.id for bill in due]},
                      needs=tuple(bill.id for bill in due))
            for key in [k for k in tiling if k.startswith("b") and day - int(k[1:]) >= 5]:
                bill = tiling.pop(key)
                b.add(day, "sub_payment", f"Pay Joy Tiling Works for their bill of day {bill.day}", site="main",
                      data={"vendor": "Joy Tiling Works", "bill": bill.id}, needs=(bill.id,))
            week = (day - 6, day)
            for project in (GREEN_VILLA, LAKE_VIEW):
                if not any(e.kind == "attendance" and e.project == project and week[0] <= e.day <= day for e in b.entries):
                    continue
                approve = b.add(day, "wage_approve", f"Approve {_of(PROJECT_NAME[project])} wage sheet for the week", project=project,
                                data={"week_from_day": week[0], "week_to_day": day})
                b.add(day, "wage_pay", f"Pay {_of(PROJECT_NAME[project])} wages for the week", project=project,
                      data={"week_from_day": week[0], "week_to_day": day}, needs=(approve.id,))

        # Lake View's running bill, and the client paying it.
        if day in RA_BILL_DAYS:
            bill = b.add(day, "ra_bill", f"Send {_of(PROJECT_NAME[LAKE_VIEW])} running bill to the client, work up to today",
                         project=LAKE_VIEW, data={"period_to_day": day})
            ra_bills.append((day + CLIENT_PAYS_AFTER, bill))
        # D2: Green Villa's running bill, by its contract (needs the contract and the BOQ in).
        if day in GV_RA_BILL_DAYS:
            bill = b.add(day, "ra_bill", f"Send {_of(story.DEMO_PROJECT)} running bill to {gv.CLIENT['name']}, work up to today",
                         project=GREEN_VILLA, data={"period_to_day": day},
                         needs=(gv_setup["contract"].id, gv_setup["boq"].id))
            ra_bills.append((day + gv.PAYS_AFTER, bill))
        for due in [t for t in ra_bills if t[0] <= day]:
            ra_bills.remove(due)
            client = gv.CLIENT["name"] if due[1].project == GREEN_VILLA else story.DEMO_CLIENT["name"]
            b.add(day, "client_receipt", f"{client} paid the running bill of day {due[1].day}",
                  project=due[1].project, data={"bill": due[1].id, "client": client}, needs=(due[1].id,))

        # Green Villa done: its final bill, then the owner hands it over.
        if all(site in finished for site, project, _n in SITES if project == GREEN_VILLA):
            b.add(day, "ra_bill", f"Send {_of(story.DEMO_PROJECT)} final bill to {gv.CLIENT['name']}: all the work, measured",
                  project=GREEN_VILLA, data={"period_to_day": day, "final": True},
                  needs=(gv_setup["contract"].id, gv_setup["boq"].id))
            b.add(day, "stage", f"{story.DEMO_PROJECT} handed over to the client", project=GREEN_VILLA,
                  data={"stage": "handover"})
            last_day = day

    return Plan(entries=b.entries, opening=dict(stock0), seeded_on_order=dict(seeded), last_day=last_day)


def st_by(site: str) -> str:
    return next((s.by for s in STAGES[site] if s.by), "")


@lru_cache(maxsize=1)
def plan() -> Plan:
    """The plan, made once per process (it is fixed)."""
    return build()


# --- The readable plan -----------------------------------------------------------------------------------------------

_DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def render(p: Plan | None = None) -> str:
    """The plan as a page people read: each day, each person's entries; the everyday site records in one line a site."""
    p = p or plan()
    out = [
        "# The sample company's plan, day by day",
        "",
        "> Generated by `backend/src/mesiri/application/learn/sample_plan.py` (SS-74b, "
        "[guided-demo-plan.md section 18](guided-demo-plan.md)); do not edit by hand. Rewrite with "
        "`python -m mesiri.application.learn.sample_plan` from `backend/` (with `src` on the path); a test fails when "
        "this page is out of date.",
        "",
        f"Day 0 is the last of the two seeded weeks (a Saturday). The plan runs to day {p.last_day}, when "
        f"{story.DEMO_PROJECT} is handed over: {len(p.entries):,} entries. When the person plays a role, that role's "
        "entries are their to-do for the day; everyone else's are played for them.",
        "",
        "Who: **Ravi** (site engineer), **Anil** (project manager), **Meera** (accounts), **Owner**.",
        "",
        "## Where it starts (what the two seeded weeks leave)",
        "",
        "| Site | Stock |",
        "|---|---|",
    ]
    for site, _project, name in SITES:
        held = [f"{m} {_fmt(q)} {UNITS[m]}" for (s, m), q in sorted(p.opening.items()) if s == site and q > 0]
        out.append(f"| {name} | {', '.join(held) or 'nothing'} |")
    if p.seeded_on_order:
        coming = "; ".join(f"{SITE_NAME[s]}: {_fmt(q)} {UNITS[m]} {m}" for (s, m), q in sorted(p.seeded_on_order.items()))
        out += ["", f"Still to come on the seeded orders: {coming}."]
    out += ["", "## Each site's work", ""]
    for site, _project, name in SITES:
        out.append(f"- **{name}**: " + " → ".join(f"{s.work} ({s.days} d)" for s in STAGES[site]))
    out += ["", "## The days", ""]
    for day in range(1, p.last_day + 1):
        entries = p.day(day)
        out.append(f"### Day {day} · {_DAY_NAMES[weekday(day)]}")
        out.append("")
        if not entries:
            out += ["Sunday: nobody works.", ""]
            continue
        for role in (ENGINEER, PM, ACCOUNTS, OWNER):
            mine = [e for e in entries if e.role == role]
            if not mine:
                continue
            lines: list[str] = []
            for site, _project, name in SITES:
                routine = [e for e in mine if e.site == site and KINDS[e.kind].routine]
                if routine:
                    lines.append(f"{name}: {_site_day(routine)}")
            lines += [e.what for e in mine if not KINDS[e.kind].routine]
            out.append(f"**{WHO[role]}**")
            out += [f"- {line}" for line in lines]
            out.append("")
    return "\n".join(out).rstrip() + "\n"


def _site_day(routine: list[Entry]) -> str:
    """A site's everyday records in one line: the work, who came, what was used and spent, the weather."""
    def of(kind: str) -> list[Entry]:
        return [e for e in routine if e.kind == kind]

    parts = [e.what for e in of("work")] or ["no work done"]
    parts += [e.what.replace("Attendance: ", "") for e in of("attendance")]
    used = [f"{e.data['material']} {_fmt(e.data['quantity'])} {UNITS[e.data['material']]}" for e in of("use")]
    if used:
        parts.append("used " + ", ".join(used))
    parts += [f"spent {_amount(e.data['amount'])} ({e.data['description'].lower()})" for e in of("expense")]
    parts += [e.what.lower() for e in of("machine_log")]  # LRN-F25: the mixer's hours
    parts += [e.what.lower() for e in of("conditions")]
    return "; ".join(parts)


DOC = Path(__file__).resolve().parents[5] / "docs" / "plans" / "sample-plan.md"


def main(argv: list[str]) -> int:
    DOC.write_text(render(), encoding="utf-8")
    print(f"wrote {DOC} ({len(plan().entries)} entries, last day {plan().last_day})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
