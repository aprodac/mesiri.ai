"""SA-30: reset a demo company in one tap (asked 2 Nov 2026: "a demo company you can reset in one tap").

For showing Mesiri to contractors in the field: the demo company is deleted and created again, with the same
people (same names, numbers, roles, the owner's password) and fresh sample data of the last two weeks (SA-36: two
projects, four sites, a worker register, vendors, deliveries and use, attendance, work, expenses, weather, a transfer
and issues), so every demo starts from the same clean, believable state.

Safe by construction:
- only a company whose ``demo_company`` setting is true (set by the Mesiri team only) can be reset;
- platform admins only (the route), and the reset is in the audit log;
- the delete and the re-create are one transaction: a failure leaves the old demo as it was;
- the company goes through the one create-company step every company uses, and the sample records through the
  same API the dashboard and v3 use, as the demo's owner, so they pass the real checks. A sample record that fails
  is counted, never fatal: the demo is usable without it.

The demo comes back on v3 (``assistant_mode = api``) with its other settings kept, except the ones that hold
progress (join code, setup checklist, requests), which start fresh like a new company's.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

import sqlalchemy as sa

from mesiri.application.audit.record import record_admin_action
from mesiri.application.organizations.create_company import NewCompany, create_company
from mesiri.application.organizations.delete_company import delete_company
from mesiri.domains.audit import actions as audit
from mesiri.domains.organizations import settings as org_settings

_log = logging.getLogger(__name__)

DEMO_PROJECT = "Green Villa"
DEMO_SITES = ("Main block", "Annex")
#: Settings that hold a company's progress, not its preferences: a fresh demo starts without them.
_FRESH_KEYS = frozenset({
    org_settings.JOIN_CODE, org_settings.JOIN_REQUESTS, org_settings.SETUP_PROGRESS, org_settings.GETTING_STARTED,
    org_settings.CONTINUE_REQUESTS, org_settings.BRANDING_REQUESTS,
})


class DemoResetError(Exception):
    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class DemoResetResult:
    organization_id: uuid.UUID
    name: str
    people: int
    seeded: dict[str, int] = field(default_factory=dict)
    failed: list[str] = field(default_factory=list)


async def _is_demo(conn: Any, org_id: uuid.UUID) -> bool:
    value = (await conn.execute(sa.text(
        "SELECT value FROM organization_settings WHERE organization_id = :o AND key = :k"),
        {"o": org_id, "k": org_settings.DEMO_COMPANY})).scalar()
    if isinstance(value, str):
        value = json.loads(value)
    return value is True


async def rebuild(conn: Any, org_id: uuid.UUID, *, actor: Any) -> tuple[uuid.UUID, dict[str, Any]]:
    """Inside the caller's transaction: delete the demo company and create it again with the same people and
    settings. Returns the new company id and what the sample-data step needs (owner, project, sites, people)."""
    org = (await conn.execute(sa.text("SELECT id, name, timezone FROM organizations WHERE id = :o"), {"o": org_id})).mappings().first()
    if org is None:
        raise DemoResetError("Organization not found", 404)
    if not await _is_demo(conn, org_id):
        raise DemoResetError("Only a company marked as a demo (demo_company = true) can be reset.")
    people = [dict(r) for r in (await conn.execute(sa.text(
        "SELECT id, full_name, email, whatsapp_number, role, status, hashed_password, access_policy FROM users "
        "WHERE organization_id = :o ORDER BY (role = 'ADMIN') DESC, created_at"), {"o": org_id})).mappings()]
    owner = next((p for p in people if p["role"] == "ADMIN"), None)
    if owner is None:
        raise DemoResetError("The demo company has no ADMIN to keep as its owner.")
    kept = [dict(r) for r in (await conn.execute(sa.text(
        "SELECT key, value FROM organization_settings WHERE organization_id = :o"), {"o": org_id})).mappings()
        if r["key"] not in _FRESH_KEYS]

    await delete_company(conn, org_id)  # the one delete step (records, then company, then people)

    created = await create_company(conn, NewCompany(
        name=org["name"], owner_name=owner["full_name"], owner_email=owner["email"], owner_phone=owner["whatsapp_number"],
        project_name=DEMO_PROJECT, site_names=DEMO_SITES, auto_dpr=True, signup_source="superadmin",
        timezone=org["timezone"] or "Asia/Kolkata",
    ), actor=actor)
    new_id = created.organization_id
    # The owner keeps their dashboard password.
    await conn.execute(sa.text("UPDATE users SET hashed_password = :h WHERE id = :u"),
                       {"h": owner["hashed_password"], "u": created.owner_user_id})
    others = []
    for p in people:
        if p["id"] == owner["id"]:
            continue
        uid = uuid.uuid4()
        await conn.execute(sa.text(
            "INSERT INTO users (id, organization_id, email, hashed_password, full_name, role, status, whatsapp_number, "
            "access_policy, created_at, updated_at) VALUES (:id, :o, :e, :h, :n, :r, :s, :w, CAST(:a AS json), now(), now())"),
            {"id": uid, "o": new_id, "e": p["email"], "h": p["hashed_password"], "n": p["full_name"], "r": p["role"],
             "s": p["status"] or "active", "w": p["whatsapp_number"],
             "a": None if p.get("access_policy") is None else json.dumps(p["access_policy"])})
        others.append({"id": uid, "role": p["role"]})
    settings = {r["key"]: r["value"] for r in kept}
    settings[org_settings.DEMO_COMPANY] = True
    settings[org_settings.ASSISTANT_MODE] = org_settings.ASSISTANT_MODE_API  # demos show v3
    settings[org_settings.ENABLED_MODULES] = list(org_settings.MODULES)  # and every module
    for key, value in settings.items():
        await conn.execute(sa.text(
            "INSERT INTO organization_settings (id, organization_id, key, value) VALUES (gen_random_uuid(), :o, :k, CAST(:v AS jsonb)) "
            "ON CONFLICT (organization_id, key) DO UPDATE SET value = EXCLUDED.value"),
            {"o": new_id, "k": key, "v": value if isinstance(value, str) and _is_json(value) else json.dumps(value)})
    await record_admin_action(conn, actor=actor, action=audit.COMPANY_DEMO_RESET, organization_id=new_id,
                              target_type="organization", target_id=new_id,
                              summary=f"Demo reset: {org['name']} created again with {len(people)} people",
                              details={"previous_organization_id": str(org_id), "people": len(people)})
    return new_id, {"name": org["name"], "owner_id": created.owner_user_id, "owner_name": owner["full_name"],
                    "project_id": created.project_id, "site_ids": [s.site_id for s in created.sites], "others": others,
                    "people": len(people)}


def _is_json(value: str) -> bool:
    try:
        json.loads(value)
    except ValueError:
        return False
    return True


#: How far back the sample records go (SA-36: "the data is less, add more"). Sundays are off, except today.
DEMO_DAYS = 14
#: A second project, so the demo shows a company with more than one job.
DEMO_PROJECT_2 = "Lake View Apartments"
DEMO_SITES_2 = ("Tower A", "Tower B")
#: Shops and suppliers, by name only (no phone or GSTIN: made-up ones could be a real business's).
DEMO_VENDORS = (
    ("Sri Hardwares", "MG Road, Thrissur"), ("Kerala Steels", "Industrial Estate, Kalamassery"),
    ("Malabar Cements Agency", "Palakkad"), ("Periyar Sand & Aggregates", "Aluva"), ("Thrissur Blocks", "Ollur"),
    ("Hi-Tech Electricals", "Ernakulam"), ("City Plywood", "Perumbavoor"),
)
#: The worker register: name, trade, daily wage, the site they work at (index into the four sites).
DEMO_WORKERS = (
    ("Ravi", "mason", 1100, 0), ("Suresh", "mason", 1100, 0), ("Manoj", "mason", 1050, 1), ("Biju", "mason", 1100, 2),
    ("Shibu", "mason", 1050, 2), ("Joseph", "carpenter", 1000, 0), ("Thomas", "carpenter", 1000, 2),
    ("Rajesh", "bar bender", 1000, 2), ("Dinesh", "bar bender", 950, 3), ("Prakash", "electrician", 1200, 0),
    ("Satheesh", "plumber", 1150, 1), ("Sunil", "helper", 750, 0), ("Vinod", "helper", 750, 1), ("Shaji", "helper", 700, 2),
    ("Babu", "helper", 700, 3),
)
#: Per site: the work done, oldest first (each entry runs for a few days), with a quantity per day.
#: (work_type, narrative, unit, quantity per day)
DEMO_WORK = (
    (("Block work", "First floor block work, east and north walls", "sqm", 18), ("Lintel concreting", "First floor lintel and sunshade cast", "cum", 2.5),
     ("Plastering", "Ground floor internal plastering", "sqm", 40), ("Electrical conduits", "First floor conduit and box fixing", "nos", 22)),
    (("Excavation", "Footing excavation for the annex", "cum", 14), ("PCC", "PCC below footings", "cum", 3),
     ("Footing concreting", "Footings F1 to F6 cast", "cum", 5), ("Plinth beam", "Plinth beam shuttering and steel", "rmt", 24)),
    (("Column casting", "Third floor columns cast", "cum", 4), ("Slab shuttering", "Third floor slab shuttering", "sqm", 60),
     ("Slab reinforcement", "Third floor slab steel tying", "kg", 900), ("Slab concreting", "Third floor slab poured, 48 cum RMC", "cum", 16)),
    (("Excavation", "Basement excavation, grid A to D", "cum", 40), ("Raft reinforcement", "Raft bottom mesh tying", "kg", 1400),
     ("Raft concreting", "Raft pour, first half", "cum", 30), ("Retaining wall", "Retaining wall shuttering, north side", "sqm", 35)),
)
#: Per site, daily use: (material, how much a day). Deliveries keep each site stocked; Main block's cement runs low.
DEMO_USE = (
    (("cement", 22), ("m sand", 1.5), ("solid blocks", 260), ("p sand", 1.2)),
    (("cement", 12), ("m sand", 1), ("aggregate 20mm", 2), ("steel", 120)),
    (("cement", 30), ("steel", 650), ("aggregate 20mm", 3), ("m sand", 2), ("binding wire", 9)),
    (("cement", 18), ("steel", 900), ("aggregate 20mm", 2.5), ("binding wire", 12)),
)
#: Material: (supplier, delivery size, rate per unit).
DEMO_SUPPLY = {
    "cement": ("Malabar Cements Agency", 100, 410), "m sand": ("Periyar Sand & Aggregates", 6, 1650),
    "p sand": ("Periyar Sand & Aggregates", 4, 1900), "aggregate 20mm": ("Periyar Sand & Aggregates", 10, 1450),
    "solid blocks": ("Thrissur Blocks", 1500, 42), "steel": ("Kerala Steels", 4000, 68), "binding wire": ("Kerala Steels", 50, 85),
}
#: The day's small spends per site: (vendor, category, amount, what for). One a day, in turn.
DEMO_SPENDS = (
    ("Sri Hardwares", "Hardware", 1840, "Nails, binding wire, cover blocks"), ("Tea stall", "Food", 650, "Tea and snacks for the crew"),
    ("Indian Oil", "Fuel", 2300, "Diesel for the mixer and pump"), ("Auto stand", "Transport", 900, "Shifting cement bags from the road"),
    ("Sri Hardwares", "Hardware", 1250, "Shuttering oil and hand tools"), ("Hi-Tech Electricals", "Electrical", 3400, "Conduit pipes and boxes"),
    ("City Plywood", "Shuttering", 5600, "Plywood sheets for shuttering"), ("Tea stall", "Food", 720, "Tea and snacks for the crew"),
)
#: (site index, type, severity, narrative, what happens to it: open / acknowledge / resolve + note). The API dates an
#: issue when it is reported, so these all show as reported on the reset day.
DEMO_ISSUES = (
    (2, "DRAWING_PENDING", "HIGH", "Third floor slab steel drawing not received from the structural consultant",
     ("resolve", "Revised drawing received on WhatsApp, work restarted")),
    (0, "EQUIPMENT_BREAKDOWN", "MEDIUM", "Concrete mixer motor burnt, lintel work stopped", ("resolve", "Motor rewound, mixer back on site")),
    (3, "OTHER", "MEDIUM", "Rain flooded the excavation pit; pumping out water", ("resolve", "Water pumped out, sides shored")),
    (1, "LABOUR_SHORTAGE", "MEDIUM", "Only 2 masons came, footing work slow", ("acknowledge", None)),
    (2, "INSPECTION_WAITING", "HIGH", "Waiting for engineer's inspection before slab pour", ("open", None)),
    (0, "MATERIAL_SHORTAGE", "HIGH", "Cement may run short by Friday; next load not confirmed", ("open", None)),
)
#: The day it rained: (days back, hours lost).
DEMO_RAIN = (6, 3.0)

# --- WEB-85: the records Live's stories need (docs/plans/live-value-plan.md, section 6) --------------------------
#: The least a site should hold: (site index, material, minimum, how much to order). Main block's cement is left to
#: fall under it (it is not topped up in the last days), so "below the minimum: order 200 bags" shows.
DEMO_MINIMUMS = ((0, "cement", 100, 200), (1, "cement", 40, 100), (2, "cement", 80, 200), (3, "cement", 60, 200),
                 (2, "steel", 1500, 4000), (3, "steel", 2000, 4000))
#: Open purchase orders: (site index, material, quantity ordered, agreed rate). The site's deliveries of the material
#: come against it, and part is still to come.
DEMO_ORDERS = ((2, "cement", 800, 410), (3, "steel", 24000, 68))
#: Deliveries in the last days at another rate: (site index or None for every site, material) -> (rate, from how
#: many days back). Tower A's cement comes at 420 against an order that says 410; M sand is dearer than last time.
DEMO_RATE_NOW = {(2, "cement"): (420, 2), (None, "m sand"): (1750, 3)}  # None: at every site
#: A supplier's bill for more than its deliveries come to: (vendor, how many of its first deliveries, extra billed).
DEMO_BILL = ("Thrissur Blocks", 1, 2400, "TB/2611")
#: The estimate (BOQ) of the second project, per work of DEMO_WORK: planned quantity, client rate, labour rate,
#: material rate. The work recorded on site is counted on these lines, except the newest day's (the office's tap).
DEMO_BOQ = {
    "Column casting": (60, 9800, 1900, 5600), "Slab shuttering": (900, 620, 260, 210), "Slab reinforcement": (14000, 92, 12, 70),
    "Slab concreting": (240, 8900, 900, 6100), "Excavation": (600, 480, 300, 0), "Raft reinforcement": (22000, 90, 11, 70),
    "Raft concreting": (380, 8700, 850, 6000), "Retaining wall": (520, 640, 270, 220),
}
#: Bags of cement a cubic metre of concrete uses (the lines whose work is concreting).
DEMO_CEMENT_PER_CUM = 8
#: Advances still out: (worker, amount, days back).
DEMO_ADVANCES = (("Ravi", 3000, 5), ("Biju", 5000, 3), ("Shaji", 1500, 2))
#: The second project's client and contract.
DEMO_CLIENT = {"name": "Lake View Builders", "contact_person": "Mr. Varghese", "address": "Kakkanad, Kochi"}
DEMO_CONTRACT = {"contract_no": "LVB/2026/014", "contract_value": 42000000, "retention_pct": 5, "gst_pct": 18}


async def seed(client: Any, info: dict[str, Any], *, today: dt.date) -> tuple[dict[str, int], list[str]]:
    """Two weeks of sample records on two projects through the API, as the demo's owner. Never raises.

    The records are fixed (no randomness), so every reset shows the same story, dated to the last two weeks."""
    seeded: dict[str, int] = {}
    failed: list[str] = []

    async def call(kind: str, method: str, path: str, body: dict[str, Any] | None = None, params: dict | None = None) -> dict | None:
        try:
            res = await client.call(method, path, json=body, params=params, idempotency_key=f"demo-{uuid.uuid4()}")
        except Exception as exc:  # noqa: BLE001
            failed.append(f"{kind}: {type(exc).__name__}")
            return None
        if not res.ok:
            failed.append(f"{kind}: HTTP {res.status} {str(res.body)[:120]}")
            return None
        seeded[kind] = seeded.get(kind, 0) + 1
        return res.body if isinstance(res.body, dict) else {}

    async def post(kind: str, path: str, body: dict[str, Any]) -> dict | None:
        return await call(kind, "POST", path, body)

    # The second project, its sites, and everyone on both projects.
    projects = [str(info["project_id"])]
    sites = [(projects[0], str(s)) for s in info["site_ids"]]
    second = await post("project", "/projects", {"name": DEMO_PROJECT_2, "location": "Kakkanad, Kochi", "client": "Lake View Builders"})
    if second and second.get("id"):
        projects.append(str(second["id"]))
        for name in DEMO_SITES_2:
            site = await post("site", f"/projects/{projects[1]}/sites", {"name": name})
            if site and site.get("id"):
                sites.append((projects[1], str(site["id"])))
    for project in projects:
        for other in info["others"]:
            await post("member", f"/projects/{project}/members",
                       {"userId": str(other["id"]), "role": other["role"] if other["role"] != "ADMIN" else "SITE_ENGINEER"})

    vendors: dict[str, str] = {}
    for name, address in DEMO_VENDORS:
        made = await post("vendor", "/finance/vendors", {"name": name, "address": address})
        if made and made.get("id"):
            vendors[name] = str(made["id"])
    workers: list[tuple[dict, str, str, int, int]] = []  # (worker, name, trade, wage, site index)
    for name, trade, wage, at in DEMO_WORKERS:
        made = await post("worker", "/labour/workers", {"name": name, "trade": trade, "default_daily_wage": wage})
        if at < len(sites):
            workers.append((made or {}, name, trade, wage, at))

    materials = await client.call("GET", "/materials", params={"limit": 200, "is_active": True})
    by_name = {str(m.get("name") or "").lower(): m for m in ((materials.body or {}).get("items") or [] if materials.ok else [])}

    def material(name: str) -> tuple[str, str] | None:
        m = by_name.get(name)
        return (str(m["id"]), str(m["default_unit_id"])) if m and m.get("default_unit_id") else None

    days = [today - dt.timedelta(days=back) for back in range(DEMO_DAYS - 1, -1, -1)]
    days = [d for d in days if d.weekday() != 6 or d == today]
    stock: dict[tuple[int, str], float] = {}

    # WEB-85: the least each site should hold, and the open orders its deliveries come against.
    for at, name, minimum, reorder in DEMO_MINIMUMS:
        found = material(name)
        if found and at < len(sites):
            await call("minimum stock", "PUT", "/materials/stock-levels", {
                "site_id": sites[at][1], "material_id": found[0], "min_qty": minimum, "reorder_qty": reorder})
    order_lines: dict[tuple[int, str], list[Any]] = {}  # (site, material) -> [order line id, still to come]
    for at, name, quantity, rate in DEMO_ORDERS:
        found = material(name)
        if not found or at >= len(sites):
            continue
        order = await post("order", "/procurement/orders", {
            "project_id": sites[at][0], "site_id": sites[at][1], "vendor_id": vendors.get(DEMO_SUPPLY[name][0]),
            "supplier": DEMO_SUPPLY[name][0], "expected_date": today.isoformat(),
            "lines": [{"material_id": found[0], "quantity": quantity, "unit_id": found[1], "rate": rate}]})
        line = ((order or {}).get("lines") or [{}])[0].get("id")
        if line:
            order_lines[(at, name)] = [str(line), quantity]
    delivered: list[dict[str, Any]] = []  # every delivery saved: for the supplier's bill

    async def receive(at: int, name: str, day: dt.date, quantity: float | None = None) -> None:
        found = material(name)
        if not found:
            return
        vendor, size, rate = DEMO_SUPPLY[name]
        now = DEMO_RATE_NOW.get((at, name)) or DEMO_RATE_NOW.get((None, name))
        if now and (today - day).days <= now[1]:
            rate = now[0]
        quantity = quantity or size
        project, site = sites[at]
        body = {"project_id": project, "site_id": site, "material_id": found[0], "unit_id": found[1], "quantity": quantity,
                "occurred_date": day.isoformat(), "supplier": vendor, "unit_cost": rate, "total_cost": round(quantity * rate, 2)}
        if vendors.get(vendor):
            body["vendor_id"] = vendors[vendor]
        on_order = order_lines.get((at, name))
        if on_order and on_order[1] >= quantity:
            body["purchase_order_line_id"] = on_order[0]
        elif on_order:
            body["no_order"] = True
        made = await post("material received", "/materials/inflows", body)
        if made is not None:
            stock[(at, name)] = stock.get((at, name), 0) + quantity
            if "purchase_order_line_id" in body:
                on_order[1] -= quantity
            if made.get("id"):
                delivered.append({"id": str(made["id"]), "vendor": vendor, "amount": quantity * rate, "day": day})

    for index, day in enumerate(days):
        back = (today - day).days
        iso = day.isoformat()
        for at, (project, site) in enumerate(sites):
            rained = back == DEMO_RAIN[0] and at in (0, 3)
            # Deliveries: everything a site uses arrives on the first day, then again when it runs low. Main block's
            # cement is not topped up in the last days, so the demo shows "running low".
            for name, per_day in DEMO_USE[at]:
                low = stock.get((at, name), 0) < per_day * 3
                if index == 0 or (low and not (at == 0 and name == "cement" and back <= 4)):
                    await receive(at, name, day)
            # Use.
            for name, per_day in DEMO_USE[at]:
                found = material(name)
                use = round(per_day * (0.5 if rained else 1) * (1 + ((index + at) % 3 - 1) * 0.1), 2)
                if not found or stock.get((at, name), 0) < use:
                    continue
                work_type = DEMO_WORK[at][min(index * len(DEMO_WORK[at]) // len(days), len(DEMO_WORK[at]) - 1)][0]
                if await post("material used", "/materials/outflows", {
                        "project_id": project, "site_id": site, "material_id": found[0], "unit_id": found[1], "quantity": use,
                        "occurred_date": iso, "work_item": work_type}):
                    stock[(at, name)] -= use
            # Labour: the site's named workers (one is off now and then) and a helper gang from a labour contractor.
            lines: list[dict[str, Any]] = []
            for n, (made, name, trade, wage, home) in enumerate(workers):
                if home != at:
                    continue
                status = "absent" if (index + n) % 9 == 0 else "half_day" if rained or (index + n) % 11 == 0 else "present"
                line = {"worker_name": name, "trade": trade, "headcount": 1, "daily_wage": wage, "attendance_status": status}
                if made.get("id"):
                    line["worker_id"] = str(made["id"])
                lines.append(line)
            lines.append({"trade": "helper", "headcount": 4 + (index + at) % 4, "contractor": "Bengal crew (Rahim)", "daily_wage": 700})
            await post("attendance", "/labour/attendance", {"project_id": project, "site_id": site, "occurred_date": iso,
                                                            "recorded_via": "whatsapp_text", "lines": lines})
            # Work done: the stage this site is at, with the day's quantity.
            work_type, narrative, unit, qty = DEMO_WORK[at][min(index * len(DEMO_WORK[at]) // len(days), len(DEMO_WORK[at]) - 1)]
            qty = round(qty * (0.5 if rained else 1), 2)
            await post("work done", "/progress/activities", {
                "project_id": project, "site_id": site, "activity_date": iso, "source": "whatsapp_text", "work_type": work_type,
                "narrative": narrative, "quantities": [{"quantity": qty, "unit": unit, "work_type": work_type}]})
            # The day's spend.
            vendor, category, amount, what = DEMO_SPENDS[(index * len(sites) + at) % len(DEMO_SPENDS)]
            await post("expense", "/expenses", {"project_id": project, "site_id": site, "amount": amount, "occurred_date": iso,
                                                "vendor_text": vendor, "category_text": category, "description": what, "source": "whatsapp"})
            # Weather.
            conditions: dict[str, Any] = {"weather": "rainy" if rained else ("cloudy" if index % 4 == 3 else "sunny")}
            if rained:
                conditions["hours_lost"] = DEMO_RAIN[1]
            if back == 0:
                conditions["tomorrow_plan"] = DEMO_WORK[at][-1][1]
            await call("site conditions", "PATCH", f"/dpr/site-days/{site}/conditions", conditions, params={"date": iso})
        # A transfer between the villa's two sites, a few days ago.
        if back == 4 and len(sites) > 1 and material("cement") and stock.get((1, "cement"), 0) >= 20:
            found = material("cement")
            if await post("transfer", "/materials/transfers", {
                    "from_site_id": sites[1][1], "to_site_id": sites[0][1], "material_id": found[0], "unit_id": found[1],
                    "quantity": 20, "occurred_date": iso, "notes": "Main block short of cement for plastering"}):
                stock[(1, "cement")] -= 20
                stock[(0, "cement")] = stock.get((0, "cement"), 0) + 20

    await _stories(call, post, sites=sites, projects=projects, vendors=vendors, workers=workers, delivered=delivered,
                   material=material, today=today)

    # Issues, some already handled.
    for at, kind, severity, narrative, (then, note) in DEMO_ISSUES:
        if at >= len(sites):
            continue
        issue = await post("issue", "/progress/issues", {"project_id": sites[at][0], "site_id": sites[at][1], "issue_type": kind,
                                                         "severity": severity, "narrative": narrative})
        if issue and issue.get("id") and then != "open":
            body = {"resolution_notes": note} if then == "resolve" else {}
            await post(f"issue {then}d", f"/progress/issues/{issue['id']}/{then}", body)
    return seeded, failed


async def _stories(call: Any, post: Any, *, sites: list[tuple[str, str]], projects: list[str], vendors: dict[str, str],
                   workers: list[tuple[dict, str, str, int, int]], delivered: list[dict[str, Any]], material: Any,
                   today: dt.date) -> None:
    """WEB-85: what Live's stories need beyond the day's entries, through the same API as everything else: a
    supplier's bill over its deliveries, the second project's estimate with the site's work counted on it, advances,
    last week's wage sheets approved, and the client's contract with a first bill sent."""
    # A supplier's bill for more than came.
    vendor, first, extra, number = DEMO_BILL
    mine = [d for d in delivered if d["vendor"] == vendor][:first]
    if mine and vendors.get(vendor):
        await post("supplier bill", f"/finance/vendors/{vendors[vendor]}/bills", {
            "receipt_ids": [d["id"] for d in mine], "amount": round(sum(d["amount"] for d in mine) + extra, 2),
            "bill_number": number, "bill_date": max(d["day"] for d in mine).isoformat()})

    # Advances still out.
    by_name = {name: (made, at) for made, name, _trade, _wage, at in workers}
    for name, amount, back in DEMO_ADVANCES:
        made, at = by_name.get(name, ({}, None))
        if made.get("id") and at is not None and at < len(sites):
            await post("advance", "/labour/advances", {
                "project_id": sites[at][0], "site_id": sites[at][1], "worker_id": str(made["id"]), "amount": amount,
                "given_on": (today - dt.timedelta(days=back)).isoformat(), "note": "Advance against wages", "source": "web"})

    # Last week's wages, added up and approved: what is due on pay day.
    for project in projects:
        sheet = await call("wage sheet", "GET", "/labour/wage-sheets/open",
                           params={"project_id": project, "date": (today - dt.timedelta(days=7)).isoformat()})
        if sheet and sheet.get("id"):
            await post("wage sheet approved", f"/labour/wage-sheets/{sheet['id']}/approve", {})

    if len(projects) < 2:
        return
    # The second project's estimate: a section per site, a line per work, the site's work counted on its line.
    project = projects[1]
    lines: dict[tuple[str, str], str] = {}  # (site id, work) -> line id
    cement = material("cement")
    for at, (site_project, site) in enumerate(sites):
        if site_project != project:
            continue
        section = await post("estimate section", f"/projects/{project}/boq/sections",
                             {"name": f"Structure · {(DEMO_SITES + DEMO_SITES_2)[at]}", "site_id": site})
        if not section or not section.get("id"):
            continue
        for work, _narrative, unit, _per_day in DEMO_WORK[at]:
            planned, client_rate, labour_rate, material_rate = DEMO_BOQ[work]
            line = await post("estimate line", f"/projects/{project}/boq/sections/{section['id']}/lines", {
                "work": work, "unit": unit, "planned_quantity": planned, "client_rate": client_rate,
                "labour_rate": labour_rate, "material_rate": material_rate})
            if not line or not line.get("id"):
                continue
            lines[(site, work)] = str(line["id"])
            if cement and unit == "cum" and "concreting" in work.lower() or work == "Column casting" and cement:
                await call("estimate norm", "PUT", f"/projects/{project}/boq/lines/{line['id']}/norms",
                           {"norms": [{"material_id": cement[0], "quantity_per_unit": DEMO_CEMENT_PER_CUM, "wastage_pct": 3}]})
    recorded = await call("work to count", "GET", f"/projects/{project}/boq/work", params={"unlinked": True, "limit": 500})
    for item in (recorded or {}).get("work") or []:
        line = lines.get((str(item.get("site_id")), str(item.get("work") or "")))
        # The newest day's work is left for the office to count: the tap Live's work-done card offers.
        if line and str(item.get("date") or "")[:10] != today.isoformat():
            await call("work counted", "PUT", f"/projects/{project}/boq/work/{item['id']}", {"line_id": line})

    # The client, the contract, and a first bill sent for the work measured up to a week ago.
    if await call("contract", "PUT", f"/projects/{project}/contract", {"new_client": DEMO_CLIENT, **DEMO_CONTRACT,
                                                                       "signed_on": (today - dt.timedelta(days=30)).isoformat()}):
        week_ago = (today - dt.timedelta(days=7)).isoformat()
        bill = await post("client bill", f"/projects/{project}/ra-bills", {"bill_date": week_ago, "period_to": week_ago})
        if bill and bill.get("id"):
            await post("client bill sent", f"/billing/ra-bills/{bill['id']}/submit", {})


async def reset_demo(engine: Any, database: Any, org_id: uuid.UUID, *, actor: Any, today: dt.date | None = None) -> DemoResetResult:
    """Delete and re-create the demo (one transaction), then add the sample records as its owner."""
    async with engine.begin() as conn:
        new_id, info = await rebuild(conn, org_id, actor=actor)
    from agent_api.app import build_api_app
    from agent_api.client import Actor, ApiClient

    app = build_api_app(database)
    # WEB-85: the estimate (BOQ) is the dashboard's, not one of the assistant's tools; the demo's own client reaches
    # it to give the second project an estimate. The assistant's app and its tools are unchanged.
    from mesiri.domains.progress.boq_router import router as boq_router

    app.include_router(boq_router)
    client = ApiClient(Actor(user_id=str(info["owner_id"]), organization_id=str(new_id), role="ADMIN", name=info["owner_name"]),
                       app=app)
    try:
        seeded, failed = await seed(client, info, today=today or dt.datetime.now(dt.UTC).date())
    finally:
        await client.close()
    if failed:
        _log.warning("demo_reset.sample_failed org=%s failed=%s", new_id, failed)
    return DemoResetResult(organization_id=new_id, name=info["name"], people=info["people"], seeded=seeded, failed=failed)
