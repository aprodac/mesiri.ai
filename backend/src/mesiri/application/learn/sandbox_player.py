"""SS-74c: the player: days pass in a learning sample company (docs/plans/guided-demo-plan.md section 18).

``next_day`` plays the planned simulation (``sample_plan.plan()``) forward one or more days. Each entry is made as its
role's sandbox user (Anil, Ravi, Meera, the owner), with that user's token dated to the game's day, through the same
routes the dashboard calls, in process. The entries of the role the person plays are left for them on the day they
land on ("for you", section 18.4); on days skipped over, theirs are made for them too (D-GC3).

**Following what happened, not a script of ids.** An entry finds what it needs in the sample company as it is: a
delivery comes against an open order line for that site and material, a bill takes that supplier's unbilled
deliveries, a payment that supplier's unpaid bills, a client receipt the bill that was sent. So whatever the person
did (ordered more, from someone else, or nothing) is what the day follows; when what an entry needs is not there, it
waits and is tried again the next day (cement nobody ordered: no lorry, and the site's use and work that need it
wait too, as the plan made them only from what was on site).

``clock`` says where the sample is and what is waiting for the person; a "for you" entry is ticked when a record of
its kind was saved by the person's user since that day began (``_DONE``). Nothing here moves a real company: every
step refuses a company that is not a sample (``sandbox_of``), and the date only lives in the sample's token.
"""

from __future__ import annotations

import asyncio
import contextvars
import datetime as dt
import logging
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import sqlalchemy as sa

from mesiri.application.learn import green_villa as gv
from mesiri.application.learn import sample_plan as sp
from mesiri.application.learn import sandbox_days as sd
from mesiri.application.learn.sandbox import (
    OWNER,
    PLAYABLE_ROLES,
    RealPerson,
    SandboxError,
    _InProcessApi,
    find,
    sandbox_token,
)
from mesiri.domains.shared import clock as app_clock

_log = logging.getLogger(__name__)

#: Most days at once (D-GC5).
MAX_DAYS = 7
#: The company's bank account in the sample, opened the first time days pass, with enough in it for the project.
BANK_ACCOUNT, _BANK_NAME, OPENING_BALANCE = sp.story.DEMO_BANK  # the seed opens it (D5); here only if it is missing

# --- Where the sample is -----------------------------------------------------------------------------------------


@dataclass
class ForYou:
    id: str
    day: int
    what: str
    kind: str
    page: str
    done: bool


@dataclass
class Clock:
    day: int
    date: dt.date
    last_day: int
    for_you: list[ForYou] = field(default_factory=list)
    #: The save points the person can go back to (SS-74d), oldest first: [{"day", "date"}].
    can_go_back_to: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Moved:
    day: int
    date: dt.date
    token: str
    expires_at: dt.datetime
    summary: list[dict[str, Any]] = field(default_factory=list)
    for_you: list[ForYou] = field(default_factory=list)
    waiting: list[dict[str, Any]] = field(default_factory=list)
    failed: list[dict[str, Any]] = field(default_factory=list)
    #: UX-71: the days' notable moments, for the dashboard's "a day passes" scene: {day, who, kind, what}, in order.
    highlights: list[dict[str, Any]] = field(default_factory=list)
    #: UX-71: on the last day (handover), the whole run's totals for the end credits: {days, entries, by_kind}.
    finale: dict[str, Any] | None = None


#: UX-71: the kinds worth a line in the "a day passes" scene (not the routine attendance, use and site notes).
NOTABLE = ("issue", "request", "order", "delivery", "supplier_payment", "client_receipt", "ra_bill", "stage",
           "issue_resolve", "work_order", "wage_pay", "advance", "sub_payment")
#: At most this many moments a day, and in all.
HIGHLIGHTS_A_DAY = 4
HIGHLIGHTS_MAX = 24


def pick_highlights(played: list[Any]) -> list[dict[str, Any]]:
    """UX-71: the moments worth showing from what the cast played, in plan order: per day, the first work done and the
    notable kinds, at most HIGHLIGHTS_A_DAY a day and HIGHLIGHTS_MAX in all."""
    out: list[dict[str, Any]] = []
    per_day: dict[int, int] = {}
    work_shown: set[int] = set()
    for e in played:
        worth = e.kind in NOTABLE or (e.kind == "work" and e.day not in work_shown)
        if not worth or per_day.get(e.day, 0) >= HIGHLIGHTS_A_DAY:
            continue
        if e.kind == "work":
            work_shown.add(e.day)
        per_day[e.day] = per_day.get(e.day, 0) + 1
        out.append({"day": e.day, "who": sp.WHO[e.role], "kind": e.kind, "what": e.what})
    return out[:HIGHLIGHTS_MAX]


#: Where each kind of entry is done on the dashboard (a "for you" item opens it).
PAGE = {
    "conditions": "/today", "attendance": "/labour", "work": "/today", "use": "/materials?view=movements",
    "expense": "/finance/expenses", "issue": "/issues", "request": "/materials/requests", "delivery": "/procurement/grn",
    "order": "/procurement/orders", "boq_count": "/boq", "issue_resolve": "/issues", "work_order": "/subcontract/work-orders",
    "measurement": "/subcontract/work-orders", "supplier_bill": "/finance/vendors", "supplier_payment": "/finance/vendors",
    "sub_bill": "/subcontract/bills", "sub_payment": "/subcontract/bills", "advance": "/labour/advances",
    "wage_pay": "/labour/wages", "client_receipt": "/accounts/receivables", "wage_approve": "/labour/wages",
    "ra_bill": "/billing/ra-bills", "stage": "/planning/setup", "contract": "/planning/setup", "boq_import": "/boq",
    # LRN-F18: the Main block's cement, as the kit's paperwork has it.
    "transfer": "/materials", "rfq": "/procurement/quotations", "quote": "/procurement/quotations",
    "award": "/procurement/quotations", "return": "/procurement/returns", "return_settle": "/procurement/returns",
    "bill_reverse": "/finance/vendors", "stock_count": "/materials/counts", "count_approve": "/materials/counts",
    # LRN-F25: the Annex mixer.
    "machine": "/equipment", "machine_log": "/equipment/log", "task": "/tasks?view=all", "task_status": "/tasks?view=all",
    "hire_bill": "/equipment/hire", "hire_bill_fix": "/equipment/hire",
}

#: How a "for you" entry is known to be done: records of its kind saved by the person's user since that day began, at
#: the entry's place (its site, project or supplier). (table, who saved it, when, what one counts as, where.) Entries of
#: one kind at one place on one day are ticked in plan order, one per record counted.
_DONE: dict[str, tuple[str, str, str, str, tuple[str, str] | None]] = {
    "attendance": ("labour_attendance_reports", "created_by", "created_at", "count(*)", ("site", "site_id")),
    "work": ("activities", "reported_by_user_id", "created_at", "count(*)", ("site", "site_id")),
    "use": ("material_usage", "created_by", "created_at", "count(*)", ("site", "site_id")),
    "expense": ("expenses", "created_by", "created_at", "count(*)", ("site", "site_id")),
    "issue": ("site_issues", "reported_by_user_id", "created_at", "count(*)", ("site", "site_id")),
    "request": ("material_requests", "requested_by", "created_at", "count(*)", ("site", "site_id")),
    "delivery": ("material_receipts", "created_by", "created_at", "count(*)", ("site", "site_id")),
    "order": ("purchase_orders", "created_by", "created_at", "count(*)", ("site", "site_id")),
    "work_order": ("work_orders", "created_by", "created_at", "count(*)", ("vendor", "vendor_id")),
    "measurement": ("work_order_measurements", "recorded_by", "created_at", "count(*)", None),
    "supplier_bill": ("expenses", "created_by", "created_at", "count(*)", ("vendor", "vendor_id")),
    "sub_bill": ("expenses", "created_by", "created_at", "count(*)", ("vendor", "vendor_id")),
    "supplier_payment": ("expense_payments", "created_by", "created_at", "count(DISTINCT vendor_id)", ("vendor", "vendor_id")),
    "sub_payment": ("expense_payments", "created_by", "created_at", "count(DISTINCT expense_id)", ("vendor", "vendor_id")),
    "advance": ("labour_advances", "created_by", "created_at", "count(*)", ("site", "site_id")),
    "wage_pay": ("wage_payments", "created_by", "created_at", "count(DISTINCT sheet_id)",
                 ("project", "(SELECT ws.project_id FROM wage_sheets ws WHERE ws.id = sheet_id)")),
    "client_receipt": ("client_receipts", "created_by", "created_at", "count(*)", ("project", "project_id")),
    "wage_approve": ("wage_sheets", "approved_by", "approved_at", "count(*)", ("project", "project_id")),
    "ra_bill": ("ra_bills", "submitted_by", "submitted_at", "count(*)", ("project", "project_id")),
    "transfer": ("material_movements", "recorded_by_user_id", "created_at", "count(DISTINCT source_id)", ("site", "site_id")),
    "rfq": ("rfqs", "created_by", "created_at", "count(*)", ("site", "site_id")),
    "quote": ("rfq_vendors", "quoted_by", "quoted_at", "count(*)", None),
    "award": ("rfqs", "status_by", "status_at", "count(*)", ("site", "site_id")),
    "return": ("material_returns", "created_by", "created_at", "count(*)", ("site", "site_id")),
    "return_settle": ("material_returns", "status_by", "settled_on", "count(*)", ("site", "site_id")),
    # LRN-F23: the month-end count, and its approval.
    "stock_count": ("stock_counts", "created_by", "created_at", "count(*)", ("site", "site_id")),
    "count_approve": ("stock_counts", "approved_by", "approved_at", "count(*)", ("site", "site_id")),
}


async def _outcome_done(conn: Any, org: uuid.UUID, e: sp.Entry, ids: dict[str, dict[str, str]], date: dt.date) -> bool:
    """The kinds known by what they leave behind rather than by who saved a record."""
    async def scalar(sql: str, **params: Any) -> Any:
        return (await conn.execute(sa.text(sql), {"o": org, **params})).scalar()

    if e.kind == "stage":
        return await scalar("SELECT stage FROM projects WHERE organization_id = :o AND id = :p",
                            p=ids["project"].get(e.project or "")) == e.data["stage"]
    if e.kind == "issue_resolve":
        return bool(await scalar("SELECT count(*) FROM site_issues WHERE organization_id = :o AND narrative = :n "
                                 "AND status = 'RESOLVED'", n=e.data["narrative"]))
    if e.kind == "conditions":
        return bool(await scalar("SELECT count(*) FROM daily_reports WHERE organization_id = :o AND site_id = :s "
                                 "AND report_date = :d AND (weather IS NOT NULL OR tomorrow_plan IS NOT NULL)",
                                 s=ids["site"].get(e.site or ""), d=date))
    if e.kind == "contract":  # D2: the project has its contract (here, or in the guided project's chapter 2)
        return bool(await scalar("SELECT count(*) FROM project_contracts WHERE organization_id = :o AND project_id = :p",
                                 p=ids["project"].get(e.project or "")))
    if e.kind == "boq_import":  # D2: the project has a BOQ (here, or imported in the guided project's chapter 3)
        return bool(await scalar("SELECT count(*) FROM work_package_planned_items i JOIN work_packages w ON w.id = i.work_package_id "
                                 "WHERE w.organization_id = :o AND w.project_id = :p", p=ids["project"].get(e.project or "")))
    if e.kind == "bill_reverse":  # LRN-F18: the supplier's bill of that number was taken back
        return bool(await scalar("SELECT count(*) FROM material_invoices i JOIN expenses x ON x.id = i.expense_id "
                                 "WHERE i.organization_id = :o AND i.invoice_number = :n AND x.workflow_status <> 'confirmed'",
                                 n=e.data["bill_number"]))
    # LRN-F25: the Annex mixer's story, known by what it leaves (whoever saved it, here or on WhatsApp).
    if e.kind == "machine":
        return bool(await scalar("SELECT count(*) FROM equipment WHERE organization_id = :o AND name = :n", n=e.data["machine"]))
    if e.kind == "machine_log":
        return bool(await scalar("SELECT count(*) FROM equipment_events ev JOIN equipment m ON m.id = ev.equipment_id "
                                 "WHERE ev.organization_id = :o AND m.name = :n AND ev.event_type = 'day_log' "
                                 "AND ev.occurred_date = :d", n=e.data["machine"], d=date))
    if e.kind in ("task", "task_status"):
        status = "('done', 'cancelled')" if e.kind == "task_status" else "('open', 'doing', 'blocked', 'done', 'cancelled')"
        return bool(await scalar(f"SELECT count(*) FROM tasks WHERE organization_id = :o AND title = :t AND status IN {status}",  # noqa: S608
                                 t=e.data["title"]))
    if e.kind in ("hire_bill", "hire_bill_fix"):
        sql = "SELECT count(*) FROM equipment_hire_bills WHERE organization_id = :o AND bill_ref = :r"
        if e.kind == "hire_bill_fix":
            sql += " AND billed_hours <= :h"
        return bool(await scalar(sql, r=e.data["bill_ref"], **({"h": e.data["hours"]} if e.kind == "hire_bill_fix" else {})))
    if e.kind == "boq_count":  # nothing of that work left off its BOQ line
        return not await scalar(
            "SELECT count(*) FROM activities a JOIN activity_quantities q ON q.activity_id = a.id "
            "WHERE a.organization_id = :o AND a.site_id = :s AND a.work_type = :w AND a.activity_date <= :d "
            "AND a.deleted_at IS NULL AND q.planned_item_id IS NULL", s=ids["site"].get(e.site or ""), w=e.data["work"], d=date)
    return False


# --- The sample as it is -----------------------------------------------------------------------------------------


class _World:
    """The sample company's ids, read once per play: sites, materials, suppliers, workers, the money account, and a
    client per role. Writes go through the API (``call``); reads of what is there come straight from the database,
    always for this sample company only."""

    def __init__(self, engine: Any, app: Any, org: uuid.UUID, real_org: uuid.UUID) -> None:
        self.engine, self.app, self.org, self.real_org = engine, app, org, real_org
        self.sites: dict[str, tuple[str, str]] = {}      # site key -> (project id, site id)
        self.projects: dict[str, str] = {}               # project key -> id
        self.materials: dict[str, tuple[str, str]] = {}  # name -> (material id, unit id)
        self.vendors: dict[str, str] = {}
        self.workers: dict[str, str] = {}
        self.users: dict[str, tuple[uuid.UUID, str]] = {}  # role -> (user id, name)
        self.account: str | None = None
        self.day: int = 0
        self.date: dt.date = app_clock.today()  # set by at() before any call
        self._clients: dict[str, _InProcessApi] = {}

    async def load(self) -> None:
        async with self.engine.connect() as conn:
            async def rows(sql: str) -> list[Any]:
                return list((await conn.execute(sa.text(sql), {"o": self.org})).mappings())

            names = {story_name: key for key, _p, story_name in sp.SITES}
            for r in await rows("SELECT s.id, s.project_id, s.name, p.name AS project FROM sites s "
                                "JOIN projects p ON p.id = s.project_id WHERE s.organization_id = :o"):
                if r["name"] in names:
                    self.sites[names[r["name"]]] = (str(r["project_id"]), str(r["id"]))
            for key, name in sp.PROJECT_NAME.items():
                hit = await rows(f"SELECT id FROM projects WHERE organization_id = :o AND name = '{name}'")  # noqa: S608
                if hit:
                    self.projects[key] = str(hit[0]["id"])
            for r in await rows("SELECT id, name FROM vendors WHERE organization_id = :o"):
                self.vendors[r["name"]] = str(r["id"])
            for r in await rows("SELECT id, name FROM workforce_workers WHERE organization_id = :o"):
                self.workers[r["name"]] = str(r["id"])
            for r in await rows("SELECT id, full_name, upper(role) AS role FROM users WHERE organization_id = :o "
                                "ORDER BY created_at"):
                self.users.setdefault(r["role"], (r["id"], r["full_name"]))
            acc = await rows("SELECT id FROM money_accounts WHERE organization_id = :o AND status = 'active' "
                             "ORDER BY (account_type = 'bank') DESC, created_at LIMIT 1")
            self.account = str(acc[0]["id"]) if acc else None
        if self.account is None:
            # The company's bank account, the first time days pass: suppliers, wages and the client go through it.
            made = await self.call(OWNER, "POST", "/finance/accounts", json={
                "name": BANK_ACCOUNT, "account_type": "bank", "bank_name": _BANK_NAME,
                "opening_balance": OPENING_BALANCE})
            if made.ok and isinstance(made.body, dict) and made.body.get("id"):
                self.account = str(made.body["id"])
            else:
                _log.warning("learn_sandbox.no_account org=%s %s", self.org, str(made.body)[:200])
        listed = await self.call(OWNER, "GET", "/materials", params={"limit": 200, "is_active": True})
        for m in (listed.body or {}).get("items") or [] if listed.ok else []:
            if m.get("default_unit_id"):
                self.materials[str(m.get("name") or "").lower()] = (str(m["id"]), str(m["default_unit_id"]))

    async def at(self, day: int, day0: dt.date) -> None:
        """Every call from here is made on that game day (a new token per role, carrying its date)."""
        self.day, self.date = day, day0 + dt.timedelta(days=day)
        await self.close()

    def client(self, role: str) -> _InProcessApi:
        if role not in self._clients:
            user_id, name = self.users[role]
            token, _ = sandbox_token(user_id=user_id, org_id=self.org, role=role, name=name, real_org=self.real_org,
                                     now=dt.datetime.now(dt.UTC), today=self.date)
            self._clients[role] = _InProcessApi(self.app, token)
        return self._clients[role]

    async def call(self, role: str, method: str, path: str, *, json: Any = None, params: dict | None = None) -> Any:
        return await self.client(role).call(method, path, json=json, params=params,
                                            idempotency_key=f"plan-{uuid.uuid4()}")

    async def one(self, sql: str, **params: Any) -> Any:
        async with self.engine.connect() as conn:
            row = (await conn.execute(sa.text(sql), {"o": self.org, **params})).mappings().first()
        return dict(row) if row else None

    async def all(self, sql: str, **params: Any) -> list[dict[str, Any]]:
        async with self.engine.connect() as conn:
            return [dict(r) for r in (await conn.execute(sa.text(sql), {"o": self.org, **params})).mappings()]

    async def close(self) -> None:
        for client in self._clients.values():
            await client.close()
        self._clients = {}


class _Wait(Exception):
    """What this entry needs is not in the sample company yet: it waits for a later day."""


class _Failed(Exception):
    pass


def _ok(res: Any, what: str) -> dict[str, Any]:
    if not res.ok:
        raise _Failed(f"{what}: HTTP {res.status} {str(res.body)[:200]}")
    return res.body if isinstance(res.body, dict) else {}


# --- Making each kind of entry -----------------------------------------------------------------------------------


async def _story_receipt(w: _World, e: sp.Entry, want: dict[str, Any]) -> Any:
    """LRN-F18: the delivery a story entry is about: the supplier's latest delivery of that material at the site (the
    lorry of the given quantity, when said). Not saved yet (the person plays Ravi and has not recorded it): the entry waits,
    as every entry whose record is not there yet does, instead of failing the whole day."""
    mid, _uid = w.materials[want["material"]]
    got = await w.one("SELECT id FROM material_receipts WHERE organization_id = :o AND site_id = :s AND vendor_id = :v "
                       "AND material_id = :m AND reverses_movement_id IS NULL AND quantity > 0 "
                       + ("AND quantity = :q " if want.get("quantity") else "") + "ORDER BY occurred_date DESC, created_at DESC LIMIT 1",
                       s=w.sites[e.site][1], v=w.vendors[want["vendor"]], m=mid,
                       **({"q": want["quantity"]} if want.get("quantity") else {}))
    if not got:
        raise _Wait(f"no delivery of {want['material']} from {want['vendor']} yet")
    return got


async def _play(w: _World, e: sp.Entry) -> dict[str, Any]:  # noqa: C901, PLR0912, PLR0915 -- one branch per kind
    d, iso, role = e.data, w.date.isoformat(), e.role
    project, site = w.sites.get(e.site or "", (w.projects.get(e.project or "", ""), None))
    if e.project and not e.site:
        project = w.projects.get(e.project, "")

    def material(name: str) -> tuple[str, str]:
        found = w.materials.get(name)
        if not found:
            raise _Failed(f"no material {name}")
        return found

    if e.kind == "conditions":
        body = {"weather": d["weather"], "tomorrow_plan": d["tomorrow_plan"]}
        if d.get("hours_lost"):
            body["hours_lost"] = d["hours_lost"]
        return _ok(await w.call(role, "PATCH", f"/dpr/site-days/{site}/conditions", json=body, params={"date": iso}), e.kind)
    if e.kind == "attendance":
        lines = [{"worker_name": c["name"], "trade": c["trade"], "headcount": 1, "daily_wage": c["daily_wage"],
                  "attendance_status": c["status"], **({"worker_id": w.workers[c["name"]]} if c["name"] in w.workers else {})}
                 for c in d["workers"]]
        g = d["gang"]
        lines.append({"trade": g["trade"], "headcount": g["headcount"], "contractor": g["contractor"], "daily_wage": g["daily_wage"]})
        return _ok(await w.call(role, "POST", "/labour/attendance", json={
            "project_id": project, "site_id": site, "occurred_date": iso, "recorded_via": "whatsapp_text", "lines": lines}), e.kind)
    if e.kind == "work":
        return _ok(await w.call(role, "POST", "/progress/activities", json={
            "project_id": project, "site_id": site, "activity_date": iso, "source": "whatsapp_text", "work_type": d["work"],
            "narrative": d["narrative"] + (f" ({d['by']})" if d.get("by") else ""),
            "quantities": [{"quantity": d["quantity"], "unit": d["unit"], "work_type": d["work"]}]}), e.kind)
    if e.kind == "use":
        mid, uid = material(d["material"])
        have = await w.one("SELECT COALESCE(SUM(CASE WHEN movement_type IN ('RECEIPT', 'TRANSFER_IN', 'ADJUSTMENT_IN') "
                           "THEN quantity ELSE -quantity END), 0) AS q FROM material_movements "
                           "WHERE organization_id = :o AND site_id = :s AND material_id = :m", s=site, m=mid)
        if have is not None and float(have["q"] or 0) < float(d["quantity"]) - 1e-6:
            raise _Wait(f"not enough {d['material']} on site")
        return _ok(await w.call(role, "POST", "/materials/outflows", json={
            "project_id": project, "site_id": site, "material_id": mid, "unit_id": uid, "quantity": d["quantity"],
            "occurred_date": iso, "work_item": d["work"]}), e.kind)
    if e.kind == "expense":
        return _ok(await w.call(role, "POST", "/expenses", json={
            "project_id": project, "site_id": site, "amount": d["amount"], "occurred_date": iso, "vendor_text": d["vendor"],
            "category_text": d["category"], "description": d["description"], "source": "whatsapp"}), e.kind)
    if e.kind == "issue":
        return _ok(await w.call(role, "POST", "/progress/issues", json={
            "project_id": project, "site_id": site, "issue_type": d["issue_type"], "severity": d["severity"],
            "narrative": d["narrative"]}), e.kind)
    if e.kind == "issue_resolve":
        hit = await w.one("SELECT id FROM site_issues WHERE organization_id = :o AND narrative = :n "
                          "AND status IN ('OPEN', 'ACKNOWLEDGED') ORDER BY created_at LIMIT 1",
                          n=d["narrative"])
        if not hit:
            raise _Wait("the issue is not reported yet")
        return _ok(await w.call(role, "POST", f"/progress/issues/{hit['id']}/resolve",
                                json={"resolution_notes": d["resolution_notes"]}), e.kind)
    if e.kind == "request":
        mid, uid = material(d["material"])
        return _ok(await w.call(role, "POST", "/procurement/requests", json={
            "project_id": project, "site_id": site, "material_id": mid, "unit_id": uid, "quantity": d["quantity"],
            "needed_by": (w.date + dt.timedelta(days=d["needed_by_days"])).isoformat(), "purpose": d["purpose"],
            "source": "whatsapp", "confirm_duplicate": True}), e.kind)
    if e.kind == "order":
        mid, uid = material(d["material"])
        req = await w.one("SELECT r.id FROM material_requests r JOIN material_request_lines l ON l.request_id = r.id "
                          "WHERE r.organization_id = :o AND r.site_id = :s AND l.material_id = :m "
                          "AND NOT EXISTS (SELECT 1 FROM purchase_order_lines pl WHERE pl.request_line_id = l.id) "
                          "AND r.status = 'waiting' ORDER BY r.created_at LIMIT 1",
                          s=site, m=mid)
        if not req:
            raise _Wait("no request to order")
        body = {"project_id": project, "site_id": site, "vendor_id": w.vendors.get(d["vendor"]), "supplier": d["vendor"],
                "confirm_duplicate": True,  # the office has looked: a second order for the same material is meant
                "request_id": str(req["id"]), "expected_date": (w.date + dt.timedelta(days=d["expected_in_days"])).isoformat(),
                # The item comes from the request; the plan's quantity is ordered (a site keeps a little in hand),
                # not only what the request still has to buy over today's stock.
                "quantity": d["quantity"], "rate": d["rate"]}
        return _ok(await w.call(role, "POST", "/procurement/orders", json=body), e.kind)
    if e.kind == "delivery":
        mid, uid = material(d["material"])
        line = await w.one(
            "SELECT pl.id, pl.quantity - COALESCE((SELECT SUM(r.quantity) FROM material_receipts r "
            "WHERE r.purchase_order_line_id = pl.id AND r.reverses_movement_id IS NULL), 0) AS left "
            "FROM purchase_order_lines pl JOIN purchase_orders po ON po.id = pl.purchase_order_id "
            "WHERE pl.organization_id = :o AND po.site_id = :s AND pl.material_id = :m "
            "AND po.status = 'open' "
            "AND pl.quantity > COALESCE((SELECT SUM(r.quantity) FROM material_receipts r "
            "WHERE r.purchase_order_line_id = pl.id AND r.reverses_movement_id IS NULL), 0) "
            "ORDER BY po.created_at LIMIT 1", s=site, m=mid)
        if not line:
            raise _Wait(f"no {d['material']} on order for {sp.SITE_NAME[e.site]}")
        qty = min(float(d["quantity"]), float(line["left"]))
        return _ok(await w.call(role, "POST", "/materials/inflows", json={
            "project_id": project, "site_id": site, "material_id": mid, "unit_id": uid, "quantity": qty,
            "occurred_date": iso, "supplier": d["vendor"], "vendor_id": w.vendors.get(d["vendor"]),
            "unit_cost": d["rate"], "total_cost": round(qty * d["rate"], 2), "purchase_order_line_id": str(line["id"])}), e.kind)
    if e.kind == "supplier_bill":
        vid = w.vendors.get(d["vendor"])
        if d.get("receipt"):  # LRN-F18: the bill is for one delivery (the lorry of a given day), whatever came before
            mine = [await _story_receipt(w, e, d["receipt"])]
        else:
            mine = await w.all("SELECT id, total_cost FROM material_receipts WHERE organization_id = :o AND vendor_id = :v "
                               "AND site_id = :s AND invoice_id IS NULL AND reverses_movement_id IS NULL AND quantity > 0 "
                               "ORDER BY occurred_date, created_at LIMIT 1", v=vid, s=site)
        if not mine or not mine[0]:
            raise _Wait("no delivery to bill")
        body = {"receipt_ids": [str(r["id"]) for r in mine], "bill_number": d["bill_number"], "bill_date": iso}
        if d.get("receipt"):
            body["amount"] = d["amount"]  # what the supplier billed, which may not be what came (the check shows it)
        return _ok(await w.call(role, "POST", f"/finance/vendors/{vid}/bills", json=body), e.kind)
    if e.kind == "transfer":
        mid, uid = material(d["material"])
        _from = w.sites[d["from_site"]][1]
        return _ok(await w.call(role, "POST", "/materials/transfers", json={
            "from_site_id": _from, "to_site_id": site, "material_id": mid, "unit_id": uid, "quantity": d["quantity"],
            "occurred_date": iso, "notes": e.what}), e.kind)
    if e.kind == "rfq":
        lines = []
        for line in d["lines"]:
            mid, uid = material(line["material"])
            req = await w.one("SELECT l.id FROM material_request_lines l JOIN material_requests r ON r.id = l.request_id "
                              "WHERE r.organization_id = :o AND r.site_id = :s AND l.material_id = :m AND r.status = 'waiting' "
                              "ORDER BY r.created_at LIMIT 1", s=site, m=mid)
            lines.append({"material_id": mid, "unit_id": uid, "quantity": line["quantity"],
                          **({"request_line_id": str(req["id"])} if req else {})})
        return _ok(await w.call(role, "POST", "/procurement/rfqs", json={
            "project_id": project, "site_id": site, "lines": lines, "vendor_ids": [w.vendors[v] for v in d["vendors"]],
            "due_date": (w.date + dt.timedelta(days=1)).isoformat()}), e.kind)
    if e.kind in ("quote", "award"):
        rfq = await w.one("SELECT id FROM rfqs WHERE organization_id = :o AND site_id = :s AND status IN ('open', 'ready') "
                          "ORDER BY created_at DESC LIMIT 1", s=site)
        if not rfq:
            raise _Wait("no request for quotes yet")
        if e.kind == "award":
            return _ok(await w.call(role, "POST", f"/procurement/rfqs/{rfq['id']}/award", json={
                "mode": d["mode"], "expected_date": (w.date + dt.timedelta(days=2)).isoformat(),
                "confirm_duplicate": True}), e.kind)
        return _ok(await w.call(role, "POST", f"/procurement/rfqs/{rfq['id']}/quotes", json={
            "vendor_id": w.vendors[d["vendor"]], "their_ref": d["their_ref"], "gst_percent": d["gst_percent"],
            "delivery_days": d["delivery_days"], "valid_until": (w.date + dt.timedelta(days=d["valid_days"])).isoformat(),
            "lines": [{"material_id": material(m)[0], "rate": r} for m, r in d["rates"].items()]}), e.kind)
    if e.kind == "return":
        got = await _story_receipt(w, e, d.get("receipt") or {"material": d["material"], "vendor": d["vendor"]})
        return _ok(await w.call(role, "POST", "/procurement/returns", json={
            "vendor_id": w.vendors[d["vendor"]], "project_id": project, "site_id": site, "returned_on": iso,
            "notes": f"Return note {d['note']}",
            "lines": [{"quantity": d["quantity"], "reason": d["reason"], "rate": d["rate"], "receipt_id": str(got["id"])}]}), e.kind)
    if e.kind == "stock_count":  # LRN-F23: started at the site (the book frozen now), then what was counted
        mid, uid = material(d["material"])
        made = _ok(await w.call(role, "POST", "/materials/stock-counts", json={"site_id": site, "scope": "all",
                                                                            "notes": "Month end"}), e.kind)
        book = next((x["book"] for x in made.get("lines", []) if str(x.get("material_id")) == str(mid)), None)
        if not made.get("id") or book is None:
            raise _Failed(f"the count has no {d['material']} line")
        return _ok(await w.call(role, "PUT", f"/materials/stock-counts/{made['id']}/lines", json={"lines": [{
            "material_id": mid, "unit_id": uid, "counted": max(0.0, float(book) - d["short"]), "reason": d["reason"]}]}), e.kind)
    if e.kind == "count_approve":
        count = await w.one("SELECT id FROM stock_counts WHERE organization_id = :o AND site_id = :s AND status = 'open' "
                            "ORDER BY created_at DESC LIMIT 1", s=site)
        if not count:
            raise _Wait("no count to approve")
        return _ok(await w.call(role, "POST", f"/materials/stock-counts/{count['id']}/approve"), e.kind)
    if e.kind in ("machine", "machine_log", "task", "task_status", "hire_bill", "hire_bill_fix"):
        return await _machine_story(w, e, role, site, project, iso)
    if e.kind == "bill_reverse":
        bill = await w.one("SELECT i.expense_id FROM material_invoices i JOIN expenses x ON x.id = i.expense_id "
                           "WHERE i.organization_id = :o AND i.invoice_number = :n AND x.workflow_status = 'confirmed' "
                           "ORDER BY i.created_at DESC LIMIT 1", n=d["bill_number"])
        if not bill:
            raise _Wait("no bill of that number")
        return _ok(await w.call(role, "POST", f"/expenses/{bill['expense_id']}/reverse"), e.kind)
    if e.kind == "return_settle":
        ret = await w.one("SELECT id FROM material_returns WHERE organization_id = :o AND site_id = :s AND vendor_id = :v "
                          "AND status IN ('waiting', 'sent') ORDER BY created_at LIMIT 1", s=site, v=w.vendors[d["vendor"]])
        bill = await w.one("SELECT i.expense_id FROM material_invoices i JOIN expenses x ON x.id = i.expense_id "
                           "WHERE i.organization_id = :o AND i.invoice_number = :n AND x.workflow_status = 'confirmed' "
                           "ORDER BY i.created_at DESC LIMIT 1", n=d["bill_number"])
        if not ret or not bill:
            raise _Wait("no return or bill to settle it against")
        return _ok(await w.call(role, "POST", f"/procurement/returns/{ret['id']}/settle", json={
            "how": d["how"], "expense_id": str(bill["expense_id"]), "settled_on": iso}), e.kind)
    if e.kind in ("supplier_payment", "sub_payment"):
        vid = w.vendors.get(d["vendor"])
        bills = await w.all("SELECT e.id, e.amount - COALESCE((SELECT SUM(p.amount) FROM expense_payments p "
                            "WHERE p.expense_id = e.id AND p.status <> 'reversed'), 0) AS due FROM expenses e "
                            "WHERE e.organization_id = :o AND e.vendor_id = :v AND e.occurred_date <= :d "
                            "AND e.workflow_status = 'confirmed' "  # a bill taken back is never paid (LRN-F18)
                            "AND e.amount > COALESCE((SELECT SUM(p.amount) FROM expense_payments p "
                            "WHERE p.expense_id = e.id AND p.status <> 'reversed'), 0) ORDER BY e.occurred_date",
                            v=vid, d=w.date - dt.timedelta(days=sp.CREDIT_DAYS if e.kind == "supplier_payment" else 0))
        if not bills:
            raise _Wait("no bill to pay")
        if not w.account:
            raise _Failed("no money account")
        if e.kind == "sub_payment":
            # What can be paid now: checked, less the retention held (the route's own rule).
            from mesiri.domains.subcontracts.store import payable_caps

            async with w.engine.connect() as conn:
                caps = await payable_caps(conn, w.org, [b["id"] for b in bills])
            for b in bills:
                amount = min(float(b["due"]), float(caps.get(b["id"], b["due"]) or 0))
                if amount > 0:
                    return _ok(await w.call(role, "POST", f"/expenses/{b['id']}/payments",
                                            json={"account_id": w.account, "paid_date": iso, "amount": round(amount, 2)}), e.kind)
            raise _Wait("nothing payable now (retention held)")
        total = round(sum(float(b["due"]) for b in bills), 2)
        return _ok(await w.call(role, "POST", f"/finance/vendors/{vid}/payments", json={
            "account_id": w.account, "amount": total, "paid_date": iso, "bill_ids": [str(b["id"]) for b in bills]}), e.kind)
    if e.kind == "boq_count":
        pid = w.sites[e.site][0]
        work = await w.call(role, "GET", f"/projects/{pid}/boq/work", params={"limit": 500})
        mine = [i for i in ((work.body or {}).get("work") or [] if work.ok else [])
                if str(i.get("site_id")) == w.sites[e.site][1] and str(i.get("work") or "") == d["work"]]
        if not mine:
            raise _Wait("no work to count")
        # New work goes on its line by itself when saved (BOQ-01): only what is left is counted by hand.
        items = [i for i in mine if not i.get("line_id")]
        if not items:
            return {"counted": 0, "already_on_line": len(mine)}
        boq = await w.call(role, "GET", f"/projects/{pid}/boq")
        # D2: Green Villa's lines are the estimate's (sections by trade), found by the line's own work name.
        line = (_estimate_line(boq.body if boq.ok else None, d["line"]) if d.get("estimate")
                else _boq_line(boq.body if boq.ok else None, d["work"], sp.SITE_NAME[e.site]))
        if not line:
            raise _Failed(f"no BOQ line for {d['work']} at {sp.SITE_NAME[e.site]}")
        for item in items:
            _ok(await w.call(role, "PUT", f"/projects/{pid}/boq/work/{item['id']}", json={"line_id": line}), e.kind)
        return {"counted": len(items)}
    if e.kind == "work_order":
        return _ok(await w.call(role, "POST", "/subcontracts/work-orders", json={
            "vendor_id": w.vendors.get(d["vendor"]), "project_id": project, "site_id": site, "name": d["work"],
            "start_date": iso, "retention_pct": d["retention_pct"], "issue": True,
            "lines": [{"description": d["work"], "unit": d["unit"], "quantity": d["quantity"], "rate": d["rate"]}]}), e.kind)
    if e.kind in ("measurement", "sub_bill"):
        wo = await w.one("SELECT o.id, l.id AS line_id FROM work_orders o JOIN work_order_lines l ON l.work_order_id = o.id "
                         "WHERE o.organization_id = :o AND o.vendor_id = :v ORDER BY o.created_at DESC LIMIT 1",
                         v=w.vendors.get(d["vendor"] if "vendor" in d else "Joy Tiling Works"))
        if not wo:
            raise _Wait("no work order yet")
        if e.kind == "measurement":
            return _ok(await w.call(role, "POST", f"/subcontracts/work-orders/{wo['id']}/measurements", json={
                "line_id": str(wo["line_id"]), "quantity": d["quantity"], "measured_on": iso}), e.kind)
        return _ok(await w.call(role, "POST", f"/subcontracts/work-orders/{wo['id']}/bills", json={
            "lines": [{"line_id": str(wo["line_id"]), "quantity": d["quantity"]}], "bill_date": iso,
            "their_bill_no": f"JTW/{w.day:02d}"}), e.kind)
    if e.kind == "advance":
        return _ok(await w.call(role, "POST", "/labour/advances", json={
            "project_id": project, "site_id": site, "worker_id": w.workers.get(d["worker"]), "amount": d["amount"],
            "given_on": iso, "note": "Advance against wages", "source": "web",
            **({"account_id": w.account} if w.account else {})}), e.kind)
    if e.kind == "wage_approve":
        week_to = w.date - dt.timedelta(days=w.day - d["week_to_day"])
        sheet = _ok(await w.call(role, "GET", "/labour/wage-sheets/open",
                                 params={"project_id": project, "date": week_to.isoformat()}), "wage sheet")
        if not sheet.get("id"):
            raise _Failed("no wage sheet")
        if str(sheet.get("status") or "") in ("approved", "paid"):
            return {"id": sheet["id"]}
        return _ok(await w.call(role, "POST", f"/labour/wage-sheets/{sheet['id']}/approve", json={}), e.kind) | {"id": sheet["id"]}
    if e.kind == "wage_pay":
        week_to = w.date - dt.timedelta(days=w.day - d["week_to_day"])
        sheet = await w.one("SELECT id FROM wage_sheets WHERE organization_id = :o AND project_id = :p AND period_to = :t "
                            "AND status = 'approved' LIMIT 1", p=project, t=week_to)
        if not sheet:
            raise _Wait("the wage sheet is not approved yet")
        return _ok(await w.call(role, "POST", f"/labour/wage-sheets/{sheet['id']}/pay", json={
            "paid_on": iso, **({"account_id": w.account} if w.account else {})}), e.kind)
    if e.kind == "ra_bill":
        bill = _ok(await w.call(role, "POST", f"/projects/{project}/ra-bills",
                                json={"bill_date": iso, "period_to": iso}), e.kind)
        _ok(await w.call(role, "POST", f"/billing/ra-bills/{bill['id']}/submit", json={}), "submit the bill")
        return bill
    if e.kind == "client_receipt":
        bill = await w.one("SELECT b.id, b.net - COALESCE((SELECT SUM(r.amount) FROM client_receipts r "
                           "WHERE r.ra_bill_id = b.id AND r.status <> 'cancelled'), 0) AS due FROM ra_bills b "
                           "WHERE b.organization_id = :o AND b.project_id = :p AND b.status IN ('submitted', 'certified') "
                           "ORDER BY b.bill_date LIMIT 1", p=project)
        if not bill or float(bill["due"] or 0) <= 0:
            raise _Wait("no running bill sent")
        if not w.account:
            raise _Failed("no money account")
        return _ok(await w.call(role, "POST", "/billing/receipts", json={
            "ra_bill_id": str(bill["id"]), "kind": "bill", "amount": float(bill["due"]), "received_on": iso,
            "account_id": w.account, "method": "bank"}), e.kind)
    if e.kind == "stage":
        return _ok(await w.call(role, "PATCH", f"/projects/{project}/start", json={"stage": d["stage"]}), e.kind)
    if e.kind == "contract":  # D2: set by the person in the guided project already? then nothing to do
        have = await w.call(role, "GET", f"/projects/{project}/contract")
        if have.ok and isinstance(have.body, dict) and have.body.get("contract"):
            return {"already": True}
        body = {k: v for k, v in d.items() if k != "client"}
        return _ok(await w.call(role, "PUT", f"/projects/{project}/contract", json={"new_client": d["client"], **body}), e.kind)
    if e.kind == "boq_import":  # D2: imported in the guided project's chapter 3 already? then nothing to do
        boq = await w.call(role, "GET", f"/projects/{project}/boq")
        if boq.ok and any((sec.get("lines") or []) for sec in (boq.body or {}).get("sections") or []):
            return {"already": True}
        lines = 0
        for heading, rows in gv.ESTIMATE:
            section = _ok(await w.call(role, "POST", f"/projects/{project}/boq/sections", json={"name": heading}), "BOQ section")
            for code, work, unit, qty, client, labour, material in rows:
                _ok(await w.call(role, "POST", f"/projects/{project}/boq/sections/{section['id']}/lines", json={
                    "work": work, "unit": unit, "planned_quantity": qty, "boq_code": code, "client_rate": client,
                    "labour_rate": labour, "material_rate": material}), "BOQ line")
                lines += 1
        return {"lines": lines}
    raise _Failed(f"unknown kind {e.kind}")


async def _machine_story(w: Any, e: sp.Entry, role: str, site: str, project: str, iso: str) -> Any:
    """LRN-F25 (episode 6): the Annex mixer on hire, its day logs, the task for its breakdown, its hire bill."""
    d = e.data
    machine = None
    if e.kind != "machine" and "machine" in d:
        machine = await w.one("SELECT id FROM equipment WHERE organization_id = :o AND name = :n ORDER BY created_at LIMIT 1",
                              n=d["machine"])
        if not machine:
            raise _Wait("the machine is not on hire yet")
    if e.kind == "machine":
        if await w.one("SELECT id FROM equipment WHERE organization_id = :o AND name = :n", n=d["machine"]):
            return {"already": True}  # put on hire by the person, on screen
        return _ok(await w.call(role, "POST", "/equipment", json={
            "name": d["machine"], "type": d["type"], "kind": "machine", "ownership": "hired",
            "vendor_id": w.vendors.get(d["vendor"]), "hire_company": d["vendor"], "rate": d["rate"], "rate_unit": "hour",
            "site_id": site, "on_hire_from": iso}), e.kind)
    if e.kind == "machine_log":
        line: dict[str, Any] = {"equipment_id": str(machine["id"]), "site_id": site, "worked_hours": d["worked"]}
        if d["breakdown"]:
            line |= {"breakdown_hours": d["breakdown"], "breakdown_reason": d["reason"]}
        return _ok(await w.call(role, "POST", "/equipment/logs", json={
            "occurred_date": iso, "lines": [line], "source": "whatsapp"}), e.kind)
    if e.kind == "task":
        if await w.one("SELECT id FROM tasks WHERE organization_id = :o AND title = :t", t=d["title"]):
            return {"already": True}  # given by the person, on screen
        issue = await w.one("SELECT id FROM site_issues WHERE organization_id = :o AND narrative = :n "
                            "ORDER BY created_at DESC LIMIT 1", n=d["narrative"])
        if not issue:
            raise _Wait("the breakdown has not raised its problem yet")
        due = (dt.date.fromisoformat(iso) + dt.timedelta(days=d["due_days"])).isoformat()
        return _ok(await w.call(role, "POST", "/tasks", json={
            "project_id": project, "site_id": site, "title": d["title"], "due_date": due, "priority": "high",
            "assignee_user_id": str(w.users[d["for"]][0]), "site_issue_id": str(issue["id"])}), e.kind)
    if e.kind == "task_status":
        task = await w.one("SELECT id FROM tasks WHERE organization_id = :o AND title = :t ORDER BY created_at DESC LIMIT 1",
                           t=d["title"])
        if not task:
            raise _Wait("no task to close")
        return _ok(await w.call(role, "POST", f"/tasks/{task['id']}/status",
                                json={"status": d["status"], "note": d["note"]}), e.kind)
    day0 = dt.date.fromisoformat(iso) - dt.timedelta(days=e.day)
    if e.kind == "hire_bill":
        return _ok(await w.call(role, "POST", "/equipment/hire-bills", json={
            "equipment_id": str(machine["id"]), "period_from": (day0 + dt.timedelta(days=d["from_day"])).isoformat(),
            "period_to": (day0 + dt.timedelta(days=d["to_day"])).isoformat(), "billed_hours": d["hours"],
            "amount": d["amount"], "bill_ref": d["bill_ref"], "bill_date": iso}), e.kind)
    bill = await w.one("SELECT id FROM equipment_hire_bills WHERE organization_id = :o AND bill_ref = :r "
                       "ORDER BY created_at DESC LIMIT 1", r=d["bill_ref"])
    if not bill:
        raise _Wait("no hire bill of that number")
    return _ok(await w.call(role, "PATCH", f"/equipment/hire-bills/{bill['id']}", json={
        "billed_hours": d["hours"], "amount": d["amount"], "notes": d["note"]}), e.kind)


def _boq_line(boq: Any, work: str, site_name: str) -> str | None:
    """The BOQ line for this work in this site's section (the seed names sections "Structure · <site>")."""
    if not isinstance(boq, dict):
        return None
    for section in boq.get("sections") or []:
        if site_name not in str(section.get("name") or ""):
            continue
        for line in section.get("lines") or []:
            if str(line.get("work") or line.get("description") or "") == work:
                return str(line["id"])
    return None


def _estimate_line(boq: Any, work: str) -> str | None:
    """D2: the BOQ line with this work name in any section (Green Villa's BOQ is the estimate, sections by trade)."""
    if not isinstance(boq, dict):
        return None
    for section in boq.get("sections") or []:
        for line in section.get("lines") or []:
            if str(line.get("work") or line.get("description") or "") == work:
                return str(line["id"])
    return None


# --- Playing days ------------------------------------------------------------------------------------------------


async def _sample(conn: Any, person: RealPerson) -> dict[str, Any]:
    row = await find(conn, person)
    if row is None:
        raise SandboxError("Open your sample company first.", 404)
    extra = (await conn.execute(sa.text("SELECT sandbox_day0, sandbox_of FROM organizations WHERE id = :o"),
                                {"o": row["id"]})).mappings().one()
    if extra["sandbox_of"] is None:
        raise SandboxError("Not a sample company.", 409)
    if extra["sandbox_day0"] is None:
        raise SandboxError("This sample company was made before days could pass: start over to play the days.", 409)
    return {**row, "day0": extra["sandbox_day0"]}


async def _played(conn: Any, org: uuid.UUID) -> dict[str, str]:
    rows = (await conn.execute(sa.text("SELECT entry_id, status FROM sandbox_played WHERE organization_id = :o"),
                               {"o": org})).all()
    return {r[0]: r[1] for r in rows}


async def _record(engine: Any, org: uuid.UUID, e: sp.Entry | None, status: str, *, entry_id: str | None = None,
                  day: int | None = None, role: str | None = None, record: Any = None, error: str | None = None) -> None:
    import json

    async with engine.begin() as conn:
        await conn.execute(sa.text(
            "INSERT INTO sandbox_played (organization_id, entry_id, day, status, by_role, record, error) "
            "VALUES (:o, :e, :d, :s, :r, CAST(:rec AS jsonb), :err) ON CONFLICT (organization_id, entry_id) DO UPDATE "
            "SET status = EXCLUDED.status, record = EXCLUDED.record, error = EXCLUDED.error, at = now()"),
            {"o": org, "e": entry_id or e.id, "d": day if day is not None else e.day, "s": status,
             "r": role or (e.role if e else None), "rec": json.dumps(record, default=str) if record is not None else None,
             "err": error})


def _yours(played: dict[str, str]) -> set[tuple[int, str]]:
    """(day, role) the person landed on: that role's entries of that day are theirs, done by them or not at all."""
    return {(int(k.split(":")[1]), k.split(":")[2]) for k in played if k.startswith("you:")}


def _day_mark(day: int) -> str:
    return f"day:{day:03d}"


async def _ids(conn: Any, org: uuid.UUID) -> dict[str, dict[str, str]]:
    """The sample's sites, projects and suppliers by the plan's keys and names."""
    names = {name: key for key, _p, name in sp.SITES}
    sites = {names[r[1]]: str(r[0]) for r in (await conn.execute(sa.text(
        "SELECT id, name FROM sites WHERE organization_id = :o"), {"o": org})).all() if r[1] in names}
    projects = {key: str(r[0]) for key, name in sp.PROJECT_NAME.items() for r in (await conn.execute(sa.text(
        "SELECT id FROM projects WHERE organization_id = :o AND name = :n"), {"o": org, "n": name})).all()}
    vendors = {r[1]: str(r[0]) for r in (await conn.execute(sa.text(
        "SELECT id, name FROM vendors WHERE organization_id = :o"), {"o": org})).all()}
    return {"site": sites, "project": projects, "vendor": vendors}


async def _tick(engine: Any, org: uuid.UUID, role: str, user_id: uuid.UUID, upto: int, day0: dt.date) -> list[ForYou]:
    """The person's entries up to day ``upto`` the cast did not play. Each is done when what it asks for is there
    (``_DONE``, ``_outcome_done``); ticked ones are kept as ``done`` and drop off the list."""
    p = sp.plan()
    async with engine.connect() as conn:
        played = await _played(conn, org)
        began = {int(r[0][4:]): r[1] for r in (await conn.execute(sa.text(
            "SELECT entry_id, at FROM sandbox_played WHERE organization_id = :o AND entry_id LIKE 'day:%'"),
            {"o": org})).all()}
        ids = await _ids(conn, org)
        mine = [e for e in p.entries if e.role == role and e.day <= upto and e.id not in played]
        out: list[ForYou] = []
        counted: dict[tuple[Any, ...], int] = {}
        used: dict[tuple[Any, ...], int] = {}
        for e in mine:
            date = day0 + dt.timedelta(days=e.day)
            rule = _DONE.get(e.kind)
            start = began.get(e.day)
            if rule is None:
                done = await _outcome_done(conn, org, e, ids, date)
            elif start is None:
                done = False
            else:
                table, who, when, count, where = rule
                place = None
                if where:
                    kind, _col = where
                    key_name = {"site": e.site, "project": e.project, "vendor": e.data.get("vendor")}[kind]
                    place = ids[kind].get(key_name or "")
                group = (e.kind, e.day, place)
                if group not in counted:
                    sql = f"SELECT {count} FROM {table} WHERE organization_id = :o AND {who} = :u AND {when} >= :t"  # noqa: S608
                    params: dict[str, Any] = {"o": org, "u": user_id, "t": start}
                    if where:
                        sql += f" AND {where[1]} = :place"
                        params["place"] = place
                    counted[group] = int((await conn.execute(sa.text(sql), params)).scalar() or 0)
                done = used.get(group, 0) < counted[group]
                if done:
                    used[group] = used.get(group, 0) + 1
            out.append(ForYou(id=e.id, day=e.day, what=e.what, kind=e.kind, page=PAGE.get(e.kind, "/today"), done=done))
    for item in out:
        if item.done:
            await _record(engine, org, None, "done", entry_id=item.id, day=item.day, role=role)
    return [i for i in out if not i.done]


async def clock(engine: Any, person: RealPerson, role: str) -> Clock:
    """Where my sample company is, and what is waiting for me in this role."""
    async with engine.connect() as conn:
        row = await _sample(conn, person)
        today = (await conn.execute(sa.text("SELECT sandbox_today FROM organizations WHERE id = :o"),
                                    {"o": row["id"]})).scalar_one()
        user = (await conn.execute(sa.text("SELECT id FROM users WHERE organization_id = :o AND upper(role) = :r "
                                           "ORDER BY created_at LIMIT 1"), {"o": row["id"], "r": role})).scalar()
        saved = await sd.days(conn, row["id"])
    day = (today - row["day0"]).days
    for_you = await _tick(engine, row["id"], role, user, day, row["day0"]) if user else []
    return Clock(day=day, date=today, last_day=sp.plan().last_day, for_you=for_you,
                 can_go_back_to=[{"day": d, "date": on} for d, on in saved if d <= day])


@asynccontextmanager
async def _one_at_a_time(engine: Any, org: uuid.UUID) -> Any:
    """Next day and Go back change the whole sample company: one at a time (a second tab, a double click)."""
    async with engine.connect() as conn:
        held = await sd.hold(conn, org)
        await conn.commit()  # the lock is the connection's, not a transaction's
        if not held:
            raise SandboxError("Days are already moving in your sample company: wait a moment and look again.", 409)
        try:
            yield
        finally:
            await sd.release(conn, org)
            await conn.commit()


async def _save(engine: Any, org: uuid.UUID, day: int, day0: dt.date) -> None:
    async with engine.begin() as conn:
        size = await sd.save(conn, org, day, day0 + dt.timedelta(days=day))
    _log.info("learn_sandbox.saved org=%s day=%s bytes=%s", org, day, size)


async def save_day_zero(engine: Any, org: uuid.UUID) -> None:
    """The first save point, right after a new sample company is filled: going back to day 0 is a fresh start."""
    async with engine.connect() as conn:
        day0 = (await conn.execute(sa.text("SELECT sandbox_day0 FROM organizations WHERE id = :o AND sandbox_of IS NOT NULL"),
                                   {"o": org})).scalar()
    if day0 is not None:
        await _save(engine, org, 0, day0)


async def go_back(engine: Any, person: RealPerson, *, day: int, role: str = OWNER) -> Moved:
    """My sample company as it was at the start of that day (SS-74d); the days after it go. Today's = try again."""
    role = (role or OWNER).upper()
    if role not in PLAYABLE_ROLES:
        raise SandboxError(f"role must be one of {list(PLAYABLE_ROLES)}", 422)
    async with engine.connect() as conn:
        row = await _sample(conn, person)
        today = (await conn.execute(sa.text("SELECT sandbox_today FROM organizations WHERE id = :o"),
                                    {"o": row["id"]})).scalar_one()
    org, day0 = row["id"], row["day0"]
    if not 0 <= day <= (today - day0).days:
        raise SandboxError("You can only go back to a day you have played.", 422)
    async with _one_at_a_time(engine, org):
        async with engine.begin() as conn:
            date = await sd.restore(conn, org, day)
        if date is None:
            raise SandboxError("That day is too far back: the last 30 days can be gone back to.", 404)
    async with engine.connect() as conn:
        user = (await conn.execute(sa.text("SELECT id, full_name FROM users WHERE organization_id = :o "
                                           "AND upper(role) = :r ORDER BY created_at LIMIT 1"),
                                   {"o": org, "r": role})).mappings().first()
    if user is None:
        raise SandboxError("That role is not in your sample company; reset it to get every role.", 409)
    for_you = await _tick(engine, org, role, user["id"], day, day0)
    token, expires = sandbox_token(user_id=user["id"], org_id=org, role=role, name=user["full_name"],
                                   real_org=person.organization_id, now=dt.datetime.now(dt.UTC), today=date)
    _log.info("learn_sandbox.went_back org=%s to_day=%s", org, day)
    return Moved(day=day, date=date, token=token, expires_at=expires, for_you=for_you)


async def next_day(engine: Any, app: Any, person: RealPerson, *, role: str = OWNER, days: int = 1) -> Moved:
    """Days pass in my sample company: the cast plays the plan (section 18.1)."""
    role = (role or OWNER).upper()
    if not 1 <= days <= MAX_DAYS:
        raise SandboxError(f"days must be 1 to {MAX_DAYS}", 422)
    async with engine.connect() as conn:
        row = await _sample(conn, person)
        today = (await conn.execute(sa.text("SELECT sandbox_today FROM organizations WHERE id = :o"),
                                    {"o": row["id"]})).scalar_one()
    org, day0 = row["id"], row["day0"]
    p = sp.plan()
    start = (today - day0).days
    if start >= p.last_day:
        raise SandboxError("The project is handed over: start over to play it again.", 409)
    target = min(start + days, p.last_day)
    # A play runs as its own task with no request state carried in (no tenant, no date), like the seed.
    async with _one_at_a_time(engine, org):
        return await asyncio.create_task(_next(engine, app, person, org, day0, start, target, role),
                                         context=contextvars.Context())


async def _next(engine: Any, app: Any, person: RealPerson, org: uuid.UUID, day0: dt.date, start: int, target: int,
                role: str) -> Moved:
    p = sp.plan()
    async with engine.connect() as conn:
        first = not await sd.has(conn, org, start)
    if first:  # a sample made before save points: today's is taken now, with what the person did today in it
        await _save(engine, org, start, day0)
    w = _World(engine, app, org, person.organization_id)
    await w.load()
    # What the person left undone today stays theirs; what they did is ticked first. That holds for every role they
    # landed on a day as (``_yours``), not only the one they move on as: someone who switched role (Ravi's message,
    # then Anil's task) has the first role's day ticked, and its undone entries are never played late by the cast,
    # dated another day (found recording episode 6: Ravi's day-5 mixer line played again on day 6).
    me = w.users.get(role, (None, ""))[0]
    async with engine.connect() as conn:
        yours = _yours(await _played(conn, org))
    for r in {role} | {r for _d, r in yours}:
        uid = w.users.get(r, (None, ""))[0]
        if uid:
            await _tick(engine, org, r, uid, start, day0)
    summary: dict[tuple[str, str], int] = {}
    failed: list[dict[str, Any]] = []
    played_now: list[sp.Entry] = []
    try:
        for day in range(start + 1, target + 1):
            await w.at(day, day0)
            await _record(engine, org, None, "played", entry_id=_day_mark(day), day=day, role=None)
            async with engine.connect() as conn:
                played = await _played(conn, org)
            yours_today = day == target
            due = [e for e in p.entries if e.day <= day and e.id not in played
                   and not (e.role == role and (yours_today or e.day < start + 1))
                   and (e.day, e.role) not in yours]
            for e in due:
                try:
                    record = await _play(w, e)
                except _Wait:
                    continue
                except _Failed as exc:
                    await _record(engine, org, e, "failed", error=str(exc))
                    failed.append({"id": e.id, "what": e.what, "error": str(exc)})
                    _log.warning("learn_sandbox.play_failed org=%s entry=%s %s", org, e.id, exc)
                    continue
                await _record(engine, org, e, "played", record=record)
                played_now.append(e)
                key = (sp.WHO[e.role], e.kind)
                summary[key] = summary.get(key, 0) + 1
            if yours_today:  # the day's entries of this role are the person's from now on (``_yours``), saved with it
                await _record(engine, org, None, "done", entry_id=f"you:{day:03d}:{role}", day=day, role=role)
            # The start of the person's day (the cast has played it): what Go back returns to (SS-74d).
            await _save(engine, org, day, day0)
        async with engine.begin() as conn:
            await conn.execute(sa.text("UPDATE organizations SET sandbox_today = :d WHERE id = :o AND sandbox_of IS NOT NULL"),
                               {"d": day0 + dt.timedelta(days=target), "o": org})

    finally:
        await w.close()
    async with engine.connect() as conn:
        played = await _played(conn, org)
    waiting = [{"id": e.id, "day": e.day, "who": sp.WHO[e.role], "what": e.what}
               for e in p.entries if e.day <= target and e.id not in played and e.role != role
               and (e.day, e.role) not in _yours(played)]
    for_you = await _tick(engine, org, role, me, target, day0) if me else []
    finale = None
    if target >= p.last_day:
        by_kind: dict[str, int] = {}
        for e in p.entries:
            if e.id in played:
                by_kind[e.kind] = by_kind.get(e.kind, 0) + 1
        finale = {"days": p.last_day, "entries": sum(by_kind.values()), "by_kind": by_kind}
    user_id, name = w.users[role]
    date = day0 + dt.timedelta(days=target)
    token, expires = sandbox_token(user_id=user_id, org_id=org, role=role, name=name, real_org=person.organization_id,
                                   now=dt.datetime.now(dt.UTC), today=date)
    return Moved(day=target, date=date, token=token, expires_at=expires,
                 summary=[{"who": who, "kind": kind, "count": n} for (who, kind), n in sorted(summary.items())],
                 for_you=for_you, waiting=waiting, failed=failed, highlights=pick_highlights(played_now), finale=finale)
