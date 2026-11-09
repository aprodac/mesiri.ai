"""Demo data for the Cost control sales video: a company, the Demo reset's two weeks of site records, and the cost
layer on top (BOQ with rates, norms, work and labour put on BOQ lines, cost centres), all through the API.

  python3 seed.py <database>      the local API must be on :8000 against <database>

Writes ``admin.token`` and ``engineer.token`` beside this file (not committed). The site records are the Demo
reset's own (apps/whatsapp-assistant/src/admin/demo.py ``seed``), so the video shows the story the demo company
tells; the cost layer is added the way a project manager would on the dashboard.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import sys
import uuid

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

HERE = os.path.dirname(os.path.abspath(__file__))
API = "http://localhost:8000"

# BOQ per demo work type (the Demo reset's DEMO_WORK): unit, planned quantity, client, labour, material rate.
# Labour rates are set so the story has green, amber and red lines; real projects bring their own estimate.
BOQ = {
    "Green Villa": {
        "Main block": [("Block work", "sqm", 900, 1150, 330, 520), ("Lintel concreting", "cum", 40, 9800, 2800, 5200),
                       ("Plastering", "sqm", 2600, 420, 130, 180), ("Electrical conduits", "nos", 600, 260, 60, 110)],
        "Annex": [("Excavation", "cum", 300, 650, 400, None), ("PCC", "cum", 30, 6500, 1900, 4200),
                  ("Footing concreting", "cum", 60, 9200, 1150, 5600), ("Plinth beam", "rmt", 220, 1400, 190, 650)],
    },
    "Lake View Apartments": {
        "Tower A": [("Column casting", "cum", 120, 9800, 1900, 5600), ("Slab shuttering", "sqm", 2400, 520, 120, 160),
                    ("Slab reinforcement", "kg", 36000, 92, 9, 68), ("Slab concreting", "cum", 480, 8900, 650, 5400)],
        "Tower B": [("Excavation", "cum", 2400, 600, 160, None), ("Raft reinforcement", "kg", 60000, 90, 8, 68),
                    ("Raft concreting", "cum", 900, 8700, 600, 5300), ("Retaining wall", "sqm", 800, 2600, 900, 1200)],
    },
}
# The Demo reset stocks every site on its first day, and material spend counts deliveries (stock included), so after
# two weeks spend runs ~3x the material the work used and the forecast at completion would show crores over. The
# demo's rates are scaled per project so the story is a believable one: Green Villa a little over, Lake View on track.
RATE_SCALE = {"Green Villa": (1.6, 3.25), "Lake View Apartments": (0.75, 2.1)}  # (labour, material)
# Material norms per unit of work, in the material's stock unit (MP-01): (material, per unit, wastage %).
NORMS = {
    "Block work": [("solid blocks", 12.5, 3), ("cement", 0.9, 2), ("m sand", 0.06, 5)],
    "Plastering": [("cement", 0.35, 2), ("p sand", 0.025, 5)],
    "Lintel concreting": [("cement", 7.5, 2), ("aggregate 20mm", 0.9, 3), ("m sand", 0.45, 5), ("steel", 85, 3)],
    "Footing concreting": [("cement", 7.5, 2), ("aggregate 20mm", 0.9, 3), ("m sand", 0.45, 5)],
}
# Which attendance trades work on the line the site did that day; the rest stay "not on a BOQ line".
ON_THE_DAYS_WORK = {"mason", "helper", "bar bender"}
CENTRES = {"hardware": "materials", "electrical": "materials", "shuttering": "materials", "fuel": "fuel", "transport": "other"}


# The Demo reset uses every material every day, whatever the work that day, so the textbook norms above make every
# material red. The demo's norms are set from its own use instead: cement over, steel near the line, the rest within.
NORM_STORY = {"cement": 1.15, "steel": 1.06}  # used / what the work needed; others 0.95


async def tune_norms(client, pid, materials):
    found = (await client.call("GET", f"/cost/projects/{pid}/materials")).body["materials"]
    k = {m["material"].lower(): float(m["used"]) / float(m["should_have_used"]) / NORM_STORY.get(m["material"].lower(), 0.95)
         for m in found if float(m["should_have_used"] or 0) > 0}
    boq = (await client.call("GET", f"/projects/{pid}/boq")).body
    for line in (ln for s in boq["sections"] for ln in s["lines"]):
        norms = NORMS.get(line["work"], [])
        if norms:
            await client.call("PUT", f"/projects/{pid}/boq/lines/{line['id']}/norms", json={"norms": [
                {"material_id": materials[m], "quantity_per_unit": f"{p * k.get(m, 1):.4f}", "wastage_pct": str(w)}
                for m, p, w in norms if m in materials]})


class Client:
    """The ``client.call`` the Demo reset's ``seed`` expects, over HTTP to the local API."""

    def __init__(self, token: str) -> None:
        self.http = httpx.AsyncClient(base_url=API, headers={"Authorization": f"Bearer {token}"}, timeout=60)

    async def call(self, method, path, json=None, params=None, idempotency_key=None):
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else {}
        r = await self.http.request(method, path, json=json, params=params, headers=headers)
        body = r.json() if r.content and r.headers.get("content-type", "").startswith("application/json") else None
        return type("Res", (), {"ok": r.is_success, "status": r.status_code, "body": body})()


async def main(database: str) -> None:
    from admin import demo
    from mesiri.application.organizations.create_company import NewCompany, create_company
    from mesiri.bootstrap.settings import Settings
    from mesiri.domains.identity.auth_service import create_access_token

    dsn = Settings().postgres.dsn().rsplit("/", 1)[0] + f"/{database}"
    engine = create_async_engine(dsn)
    engineer = uuid.uuid4()
    # The company as every company is made (catalogue, categories, the first project and its sites), as the Demo
    # reset does; then a site engineer, for the engineer's view.
    async with engine.begin() as c:
        created = await create_company(c, NewCompany(
            name="Demo Builders", owner_name="Anil", owner_email="owner@demo.test", project_name=demo.DEMO_PROJECT,
            site_names=demo.DEMO_SITES, auto_dpr=True, timezone="Asia/Kolkata"))
        await c.execute(sa.text(
            "INSERT INTO users (id, organization_id, email, hashed_password, full_name, role, status, access_policy, "
            "created_at, updated_at) VALUES (:id, :org, 'engineer@demo.test', 'not-a-login', 'Rahul', 'SITE_ENGINEER', "
            "'active', NULL, now(), now())"), {"id": engineer, "org": created.organization_id})
    org = created.organization_id
    tokens = {k: create_access_token(data={"sub": str(u), "org": str(org), "role": r})
              for k, u, r in (("admin", created.owner_user_id, "ADMIN"), ("engineer", engineer, "SITE_ENGINEER"))}
    for k, t in tokens.items():
        with open(os.path.join(HERE, f"{k}.token"), "w") as f:
            f.write(t)

    client = Client(tokens["admin"])
    today = dt.date.today()
    # The Demo reset's spends name categories (Hardware, Food, ...) a new company doesn't have; an expense whose
    # category text matches none lands in "Uncategorized". Made first so each spend lands in its own.
    for name in sorted({s[1] for s in demo.DEMO_SPENDS}):
        await client.call("POST", "/expenses/categories", json={"name": name})
    seeded, failed = await demo.seed(client, {"project_id": created.project_id, "site_ids": [s.site_id for s in created.sites],
                                              "others": []}, today=today)
    # The engineer works on Green Villa (POST /projects/{id}/members is broken on the local app, said in the report).
    async with engine.begin() as c:
        await c.execute(sa.text("INSERT INTO project_members (id, project_id, user_id, role, created_at, site_access_mode) "
                                "VALUES (gen_random_uuid(), :p, :u, 'SITE_ENGINEER', now(), 'all_sites')"),
                        {"p": created.project_id, "u": engineer})
    print("site records:", json.dumps(seeded), "failed:", len(failed), failed[:5])

    listed = (await client.call("GET", "/projects")).body
    projects = {p["name"]: p["id"] for p in (listed.get("items", []) if isinstance(listed, dict) else listed)}
    materials = {m["name"].lower(): m["id"] for m in (await client.call("GET", "/materials", params={"limit": 200})).body["items"]}
    for pname, by_site in BOQ.items():
        pid = projects[pname]
        site_ids = {s["name"]: s["id"] for s in (await client.call("GET", f"/projects/{pid}/sites")).body}
        lines = {}
        for sname, rows in by_site.items():
            section = (await client.call("POST", f"/projects/{pid}/boq/sections",
                                         json={"name": sname, "site_id": site_ids.get(sname)})).body
            for work, unit, qty, client_rate, labour, material in rows:
                labour = round(labour * RATE_SCALE[pname][0])
                material = round(material * RATE_SCALE[pname][1]) if material else None
                client_rate = round(max(client_rate, (labour + (material or 0)) * 1.12))
                r = await client.call("POST", f"/projects/{pid}/boq/sections/{section['id']}/lines", json={
                    "work": work, "unit": unit, "planned_quantity": str(qty), "client_rate": str(client_rate),
                    "labour_rate": str(labour), "material_rate": str(material) if material else None})
                if not r.ok:
                    print("line failed", work, r.status, r.body)
                    continue
                lines[(sname, work)] = r.body["id"]
                norms = [{"material_id": materials[m], "quantity_per_unit": str(p), "wastage_pct": str(w)}
                         for m, p, w in NORMS.get(work, []) if m in materials]
                if norms:
                    await client.call("PUT", f"/projects/{pid}/boq/lines/{r.body['id']}/norms", json={"norms": norms})
        # Work: each update on its suggested line, except the last day's, left for the "not on a BOQ line" list.
        work = (await client.call("GET", f"/projects/{pid}/boq/work", params={"limit": 500})).body["work"]
        put = 0
        for w in work:
            if w["date"] == today.isoformat() or not w["suggested_line_id"]:
                continue
            put += (await client.call("PUT", f"/projects/{pid}/boq/work/{w['id']}", json={"line_id": w["suggested_line_id"]})).ok
        # Labour: masons, helpers and bar benders on the line the site worked on that day; the rest left off.
        groups = (await client.call("GET", f"/cost/projects/{pid}/labour",
                                    params={"date_from": (today - dt.timedelta(days=20)).isoformat()})).body["groups"]
        on = 0
        for g in groups:
            if (g.get("trade_key") or "") in ON_THE_DAYS_WORK and g.get("suggested_line_id") and g["date"] != today.isoformat():
                on += (await client.call("PUT", f"/cost/projects/{pid}/labour", json={
                    "site_id": g["site_id"], "date": g["date"], "trade": g.get("trade"),
                    "lines": [{"line_id": g["suggested_line_id"], "man_days": g["man_days"]}]})).ok
        print(pname, "lines", len(lines), "work on lines", put, "labour groups on lines", on, "of", len(groups))

        await tune_norms(client, pid, materials)

    cats = (await client.call("GET", "/cost/categories")).body["categories"]
    for cat in cats:
        centre = CENTRES.get(cat["name"].lower())
        if centre and not cat["cost_centre"]:
            await client.call("PATCH", f"/cost/categories/{cat['id']}", json={"cost_centre": centre})
    print("categories:", [(c["name"], c["cost_centre"]) for c in (await client.call("GET", "/cost/categories")).body["categories"]])
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
