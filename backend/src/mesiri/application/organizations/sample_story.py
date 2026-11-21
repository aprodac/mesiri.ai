"""SS-65: the sample company's story, shared by the demo reset (SA-30) and the learning sandbox (guided demo).

Two weeks of a believable building company, made through the real API as the company's owner, so every record
passes the same checks the dashboard and the assistant apply (SA-36, WEB-85): two projects and four sites (Green
Villa: Main block, Annex; Lake View Apartments: Tower A, Tower B), a worker register, suppliers and a subcontractor,
deliveries and use, attendance, work, expenses, weather, a transfer, issues, minimum stock, open orders, a supplier
bill over its deliveries, advances, approved wage sheets, the second project's estimate and its client's first bill.

Green Villa is left without an estimate on purpose: the guided demo's BOQ chapter uploads one
(docs/plans/guided-demo-plan.md, sections 3 and 6).

Fixed data, no randomness: every run tells the same story, dated to the last two weeks. ``seed`` takes any client
with ``await client.call(method, path, json=, params=, idempotency_key=)`` returning an object with ``ok``,
``status`` and ``body``: the assistant's in-process ``ApiClient`` is one. It never raises: a record that fails is
counted in ``failed``, and the company is usable without it.

Moved here from ``apps/whatsapp-assistant/src/admin/demo.py`` (SS-65) so the backend can make a sandbox without the
assistant's code; the demo reset calls it from there.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from mesiri.application.learn import lake_view

#: The first project and its sites: the company is created with them (``create_company``).
DEMO_PROJECT = "Green Villa"
DEMO_SITES = ("Main block", "Annex")

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
    # LRN-F25: the Annex mixer's hire company (episode 6; the kit's hire bill, green_villa.HIRE).
    ("Kerala Earthmovers & Equipments", "Thrissur"),
)
#: SS-65: a subcontractor, so the guided demo's subcontract chapter (work order, measurement, bill) has one to give
#: work to. In the vendor register as kind ``subcontractor``; no work order yet (the chapter writes it).
DEMO_SUBCONTRACTORS = (("Joy Tiling Works", "Angamaly", "Tiling and flooring, own crew of 6"),)
#: The worker register: name, trade, daily wage, the site they work at (index into the four sites). The first mason is
#: Rajan, not Ravi: Ravi is the site engineer (project bible D3, 20 Nov 2026).
DEMO_WORKERS = (
    ("Rajan", "mason", 1100, 0), ("Suresh", "mason", 1100, 0), ("Manoj", "mason", 1050, 1), ("Biju", "mason", 1100, 2),
    ("Shibu", "mason", 1050, 2), ("Joseph", "carpenter", 1000, 0), ("Thomas", "carpenter", 1000, 2),
    ("Rajesh", "bar bender", 1000, 2), ("Dinesh", "bar bender", 950, 3), ("Prakash", "electrician", 1200, 0),
    ("Satheesh", "plumber", 1150, 1), ("Sunil", "helper", 750, 0), ("Vinod", "helper", 750, 1), ("Shaji", "helper", 700, 2),
    ("Babu", "helper", 700, 3),
)
#: Per site: the work done, oldest first. Each stage runs for as many working days as it has quantities (one a day,
#: never the same every day: a site's output varies), and uses only the materials it names (None: all the site's).
#: (work_type, narrative, unit, quantity each day, materials used)
#: The two weeks are month 7 of Green Villa (project bible D1): the Main block's frame is finished, so it is on its
#: parapet, partitions, plastering and conduits (the 62-day plan carries on from there to handover); the Annex starts
#: from the ground, in the order a site does it: clearance and setting out, excavation, anti-termite in the pits, PCC,
#: footings (the plan carries on with its plinth beam).
DEMO_WORK: tuple[tuple[tuple[str, str, str, tuple[float, ...], tuple[str, ...] | None], ...], ...] = (
    (("Parapet wall", "Terrace parapet wall, block work", "rmt", (10, 12, 11), ("cement", "solid blocks", "m sand")),
     ("Brick work in partitions", "First floor partition walls, bathrooms and store", "sqm", (14, 16, 15),
      ("cement", "solid blocks", "m sand")),
     ("Plastering", "Ground floor internal plastering", "sqm", (38, 42, 40), ("cement", "m sand", "p sand")),
     ("Electrical conduits", "First floor conduit and box fixing", "nos", (20, 24, 22), ("cement", "m sand"))),
    (("Site clearance", "Site clearance and setting out for the annex", "sqm", (65, 55), ()),
     ("Excavation", "Footing excavation for the annex", "cum", (12, 15, 14), ()),
     ("Anti-termite treatment", "Anti-termite treatment of the footing pits", "sqm", (45, 35), ()),
     ("PCC", "PCC below footings", "cum", (3, 3.5), ("cement", "m sand", "aggregate 20mm")),
     ("Footing concreting", "Footings F1 to F6 cast", "cum", (4, 5, 3.5), ("cement", "m sand", "aggregate 20mm", "steel"))),
    (("Column casting", "Third floor columns cast", "cum", (4, 4.5, 3.5), None),
     ("Slab shuttering", "Third floor slab shuttering", "sqm", (55, 65, 60), None),
     ("Slab reinforcement", "Third floor slab steel tying", "kg", (850, 950, 900), None),
     ("Slab concreting", "Third floor slab poured, 48 cum RMC", "cum", (16, 16, 16), None)),
    (("Excavation", "Basement excavation, grid A to D", "cum", (38, 42, 40), None),
     ("Raft reinforcement", "Raft bottom mesh tying", "kg", (1300, 1500, 1400), None),
     ("Raft concreting", "Raft pour, first half", "cum", (30, 28, 32), None),
     ("Retaining wall", "Retaining wall shuttering, north side", "sqm", (30, 35, 40), None)),
)


def stage_on(at: int, index: int) -> tuple[str, str, str, float, tuple[str, ...] | None]:
    """What site ``at`` does on the seed's ``index``-th working day: (work, narrative, unit, that day's quantity,
    materials used). Past the last stage's days the site carries on with its last stage."""
    left = index
    for work, narrative, unit, days, uses in DEMO_WORK[at]:
        if left < len(days):
            return work, narrative, unit, days[left], uses
        left -= len(days)
    work, narrative, unit, days, uses = DEMO_WORK[at][-1]
    return work, narrative, unit, days[-1], uses


#: Materials counted in whole pieces, so a day's use of them is a whole number (LRN-F14).
DEMO_WHOLE = ("cement", "solid blocks")
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
    (0, "EQUIPMENT_BREAKDOWN", "MEDIUM", "Mixer motor burnt, parapet work stopped", ("resolve", "Motor rewound, mixer back on site")),
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
#: Bags of cement a cubic metre of concrete uses (the lines whose work is concreting).
DEMO_CEMENT_PER_CUM = 8
#: Advances still out: (worker, amount, days back).
DEMO_ADVANCES = (("Rajan", 3000, 5), ("Biju", 5000, 3), ("Shaji", 1500, 2))
#: LRN-F5 (project bible D5, 20 Nov 2026): where the company's money is kept, from the start, so payments have an
#: account and the Money page is not empty: the bank account (name, bank, opening balance) and a petty-cash box per
#: site (opening float). The sample company's player uses the same bank account (learn/sandbox_player.py).
DEMO_BANK = ("Federal Bank current account", "Federal Bank", 2500000)
DEMO_PETTY_FLOAT = 20000
#: The second project's client and contract: Lake View's own paperwork (learn/lake_view.py, also the 62-day plan's).
DEMO_CLIENT = lake_view.CLIENT
DEMO_CONTRACT = lake_view.CONTRACT


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
    for name, address, notes in DEMO_SUBCONTRACTORS:
        made = await post("subcontractor", "/finance/vendors", {"name": name, "address": address, "kind": "subcontractor",
                                                                "notes": notes})
        if made and made.get("id"):
            vendors[name] = str(made["id"])
    # D5: the bank account and each site's petty cash, before anything is paid.
    await post("money account", "/finance/accounts", {"name": DEMO_BANK[0], "account_type": "bank", "bank_name": DEMO_BANK[1],
                                                      "opening_balance": DEMO_BANK[2]})
    site_names = (*DEMO_SITES, *DEMO_SITES_2)
    for i, (project_id, site_id) in enumerate(sites):
        site_name = site_names[i] if i < len(site_names) else f"site {i + 1}"
        await post("money account", "/finance/accounts", {"name": f"Petty cash · {site_name}", "account_type": "cash",
                                                          "opening_balance": DEMO_PETTY_FLOAT, "project_id": project_id,
                                                          "site_id": site_id})
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
            # Use: what the day's work takes, from what the site keeps.
            work_type, _narrative, _unit, _qty, uses = stage_on(at, index)
            for name, per_day in DEMO_USE[at]:
                if uses is not None and name not in uses:
                    continue
                found = material(name)
                use = round(per_day * (0.5 if rained else 1) * (1 + ((index + at) % 3 - 1) * 0.1), 2)
                if name in DEMO_WHOLE:  # LRN-F14: cement in whole bags, blocks in whole pieces
                    use = float(round(use))
                if not found or stock.get((at, name), 0) < use:
                    continue
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
            work_type, narrative, unit, qty, _uses = stage_on(at, index)
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
                conditions["tomorrow_plan"] = stage_on(at, index + 1)[1]
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
    # The second project's estimate, the whole of it (learn/lake_view.py): site works, then per tower its
    # substructure, structure, and masonry and plaster; the site's work counted on its own tower's line.
    project = projects[1]
    lines: dict[tuple[str, str], str] = {}  # (site id, work) -> line id
    cement = material("cement")
    tower_site = {name: site for at, (site_project, site) in enumerate(sites)
                  if site_project == project for name in [(DEMO_SITES + DEMO_SITES_2)[at]]}
    for name, tower, rows in lake_view.ESTIMATE:
        site = tower_site.get(tower) if tower else None
        if tower and not site:
            continue
        section = await post("estimate section", f"/projects/{project}/boq/sections",
                             {"name": name, **({"site_id": site} if site else {})})
        if not section or not section.get("id"):
            continue
        for work, unit, planned, client_rate, labour_rate, material_rate in rows:
            line = await post("estimate line", f"/projects/{project}/boq/sections/{section['id']}/lines", {
                "work": work, "unit": unit, "planned_quantity": planned, "client_rate": client_rate,
                "labour_rate": labour_rate, "material_rate": material_rate})
            if not line or not line.get("id"):
                continue
            if site:
                lines[(site, work)] = str(line["id"])
            if cement and unit == "cum" and ("concreting" in work.lower() or work in ("Column casting", "PCC")):
                await call("estimate norm", "PUT", f"/projects/{project}/boq/lines/{line['id']}/norms",
                           {"norms": [{"material_id": cement[0], "quantity_per_unit": DEMO_CEMENT_PER_CUM, "wastage_pct": 3}]})
    recorded = await call("work to count", "GET", f"/projects/{project}/boq/work", params={"unlinked": True, "limit": 500})
    for item in (recorded or {}).get("work") or []:
        line = lines.get((str(item.get("site_id")), str(item.get("work") or "")))
        # The newest day's work is left for the office to count: the tap Live's work-done card offers.
        if line and str(item.get("date") or "")[:10] != today.isoformat():
            await call("work counted", "PUT", f"/projects/{project}/boq/work/{item['id']}", {"line_id": line})

    # The client, the contract, and a first bill sent for the work measured up to a week ago.
    if await call("contract", "PUT", f"/projects/{project}/contract", {
            "new_client": DEMO_CLIENT, **DEMO_CONTRACT,
            "signed_on": (today - dt.timedelta(days=lake_view.SIGNED_DAYS_AGO)).isoformat()}):
        week_ago = (today - dt.timedelta(days=7)).isoformat()
        bill = await post("client bill", f"/projects/{project}/ra-bills", {"bill_date": week_ago, "period_to": week_ago})
        if bill and bill.get("id"):
            await post("client bill sent", f"/billing/ra-bills/{bill['id']}/submit", {})
