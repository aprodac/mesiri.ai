#!/usr/bin/env python3
"""LRN-F3: the A-to-Z map's data: the sample company's whole planned project (SS-74b), for the map page and as the
film's storyboard (asked 20 Nov 2026: "from the start to end how each thing happens, what role does what when").

    PYTHONPATH=backend/src:shared/contracts/src:platform/ai/src python3 docs/learning/film/az_map.py

Reads ``mesiri.application.learn.sample_plan.plan()`` (fixed: every sample company plays the same days) and writes,
beside this file in ``az-map/``:

- ``entries.json``: one array, a record per line: ``{i, d, k, r, t, s, p, n}`` = id, day, kind, role, the words,
  site, project, and the ids it needs first (a delivery its order, a bill its delivery, a payment its bills);
- ``meta.json``: the days (weekday, Sunday), each site's stages as day ranges, the milestones, the kinds' names.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from mesiri.application.learn import sample_plan as sp

OUT = Path(__file__).resolve().parent / "az-map"
MODULE_MAP = Path(__file__).resolve().parents[3] / "apps/dashboard/src/lib/module-map.ts"

# Every built page and the story (LRN-F3 "Pages"): where each kind of entry is recorded, which pages show the results,
# and which are one-time setup before day 1. A page in none of these is "not in the story yet": a gap to fill.
RECORDS: dict[str, list[str]] = {
    "/today": ["conditions", "attendance", "work", "use", "expense"], "/reports": ["conditions"], "/site-log": ["work"],
    "/issues": ["issue", "issue_resolve"], "/site/approvals": ["wage_approve"], "/labour": ["attendance"],
    "/labour/wages": ["wage_approve", "wage_pay"], "/labour/advances": ["advance"],
    "/materials?view=stock": ["delivery", "use"], "/materials?view=movements": ["delivery", "use"], "/materials/requests": ["request"],
    "/procurement/orders": ["order"], "/procurement/pending": ["order"], "/finance/vendors": ["supplier_bill", "supplier_payment"],
    "/finance/expenses": ["expense"], "/boq": ["boq_count"], "/subcontract/work-orders": ["work_order", "measurement"],
    "/subcontract/bills": ["sub_bill", "sub_payment"], "/billing/ra-bills": ["ra_bill"], "/accounts/receivables": ["client_receipt"],
    "/projects": ["stage"],
}
SHOWS: dict[str, list[str]] = {
    "/home": ["wage_approve", "request", "supplier_bill", "ra_bill", "boq_count"], "/reports/period": ["work", "attendance", "use"],
    "/analytics": ["attendance", "work", "issue"], "/cost": ["boq_count", "work", "use"], "/cost/green-red": ["boq_count", "attendance"],
    "/cost/budget": ["boq_count", "supplier_bill"], "/cost/materials": ["use", "boq_count"], "/cost/centres": ["expense", "supplier_bill"],
    "/materials/value": ["delivery", "use"], "/labour?view=muster": ["attendance"], "/labour?view=workers": ["attendance"],
    "/subcontract/teams": ["work_order", "sub_bill"], "/finance/money": ["supplier_payment", "wage_pay", "client_receipt"],
    "/accounts/projects": ["supplier_bill", "client_receipt"], "/accounts/ledgers": ["supplier_bill", "supplier_payment"],
    "/accounts/day-book": ["supplier_payment", "expense"], "/accounts/cash-flow": ["supplier_payment", "client_receipt"],
    "/accounts/pl": ["supplier_bill", "ra_bill"], "/billing/clients": ["ra_bill", "client_receipt"],
}
#: One-time setup before day 1; the guided project's chapters walk through the ones named here.
SETUP: dict[str, str] = {
    "/planning/setup": "Guided project, chapter 2: Set up Green Villa", "/projects": "Company setup", "/team": "Company setup",
    "/company": "Company setup", "/whatsapp": "Company setup", "/bring-data": "Company setup", "/settings": "Company setup",
    "/finance/settings": "Company setup",
}
GUIDED = {"/boq": "Guided project, chapter 3: The BOQ"}


def modules() -> list[dict]:
    """The dashboard's modules and their built pages, read from lib/module-map.ts (the one list the sidebar uses)."""
    src = MODULE_MAP.read_text(encoding="utf-8")
    heads = [(m.start(), m.group(1), m.group(2)) for m in re.finditer(r"key: '([a-z_-]+)',\s*\n\s*title: '([^']+)'", src)]
    out: list[dict] = []
    for i, (at, key, title) in enumerate(heads):
        body = src[at: heads[i + 1][0] if i + 1 < len(heads) else len(src)]
        section = re.search(r"section: '([a-z]+)'", body)
        pages = []
        for m in re.finditer(r"\{ title: '((?:[^'\\]|\\.)*)', url: '([^']+)', status: 'built'(.*?)\}(?:,\n|\n)", body):
            rest = m.group(3)
            about = re.search(r"about: '((?:[^'\\]|\\.)*)'", rest) or re.search(r'about: "([^"]*)"', rest)
            pages.append({"title": m.group(1).replace("\\'", "'"), "url": m.group(2), "shortcut": "shortcut: true" in rest,
                          "about": (about.group(1).replace("\\'", "'") if about else "")})
        if pages:
            out.append({"key": key, "title": title, "section": section.group(1) if section else "", "pages": pages})
    return out

ROLE = {sp.OWNER: "owner", sp.PM: "pm", sp.ENGINEER: "engineer", sp.ACCOUNTS: "accounts"}
KIND_NAMES = {
    "conditions": "Site conditions", "attendance": "Attendance", "work": "Work done", "use": "Material used",
    "expense": "Site expense", "issue": "Problem raised", "request": "Material request", "delivery": "Delivery received",
    "order": "Purchase order", "boq_count": "Work counted on the BOQ", "issue_resolve": "Problem fixed",
    "work_order": "Subcontract work order", "measurement": "Subcontract work measured", "supplier_bill": "Supplier bill",
    "supplier_payment": "Supplier paid", "sub_bill": "Subcontractor bill", "sub_payment": "Subcontractor paid",
    "advance": "Advance to a worker", "wage_pay": "Wages paid", "client_receipt": "Client paid", "wage_approve": "Wages approved",
    "ra_bill": "Running bill to the client", "stage": "Project stage",
}


def main() -> None:
    plan = sp.plan()
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for e in plan.entries:
        rows.append({"i": e.id, "d": e.day, "k": e.kind, "r": ROLE[e.role], "t": e.what, "s": e.site, "p": e.project, "n": list(e.needs)})
    (OUT / "entries.json").write_text("[\n" + ",\n".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) for r in rows) + "\n]\n", encoding="utf-8")

    # Each site's stages: consecutive days of the same work, from the "work" entries.
    stages: dict[str, list[dict]] = {}
    for e in sorted((x for x in plan.entries if x.kind == "work"), key=lambda x: (x.site or "", x.day)):
        work = e.data.get("work") or e.what.split(":")[0]
        runs = stages.setdefault(e.site or "", [])
        if runs and runs[-1]["work"] == work and e.day - runs[-1]["to"] <= 2:
            runs[-1]["to"] = e.day
        else:
            runs.append({"work": work, "from": e.day, "to": e.day})
    milestones = [{"d": e.day, "k": e.kind, "t": e.what, "p": e.project} for e in plan.entries
                  if e.kind in ("ra_bill", "client_receipt", "work_order", "stage")]
    days = [{"d": n, "wd": sp._DAY_NAMES[sp.weekday(n)], "sun": sp.is_sunday(n)} for n in range(1, plan.last_day + 1)]
    by_kind: dict[str, list] = {}
    for e in plan.entries:
        by_kind.setdefault(e.kind, []).append(e)
    needs_kinds: dict[str, set[str]] = {}
    for e in plan.entries:
        for n in e.needs:
            needs_kinds.setdefault(e.kind, set()).add(next(x.kind for x in [plan.by_id()[n]]))
    led_by: dict[str, set[str]] = {}
    for k, ups in needs_kinds.items():
        for u in ups:
            led_by.setdefault(u, set()).add(k)
    page_of_kind = {}
    for url, kinds in RECORDS.items():
        for k in kinds:
            page_of_kind.setdefault(k, url)
    mods = modules()
    for mod in mods:
        for pg in mod["pages"]:
            url = pg["url"]
            kinds = RECORDS.get(url) or SHOWS.get(url) or []
            pg["state"] = "recorded" if url in RECORDS else "shows" if url in SHOWS else "setup" if url in SETUP else "gap"
            pg["setup"] = SETUP.get(url) or GUIDED.get(url)
            pg["kinds"] = kinds
            ents = [e for k in kinds for e in by_kind.get(k, [])]
            pg["roles"] = sorted({ROLE[e.role] for e in ents}) if pg["state"] == "recorded" else []
            pg["days"] = sorted({e.day for e in ents})
            pg["count"] = len(ents) if pg["state"] == "recorded" else 0
            if pg["state"] == "recorded":
                pg["from"] = sorted({page_of_kind[u] for k in kinds for u in needs_kinds.get(k, ()) if page_of_kind.get(u) and page_of_kind[u] != url})
                pg["to"] = sorted({page_of_kind[d] for k in kinds for d in led_by.get(k, ()) if page_of_kind.get(d) and page_of_kind[d] != url})
    meta = {
        "last_day": plan.last_day,
        "who": {"owner": "Owner", "pm": "Anil · project manager", "engineer": "Ravi · site engineer", "accounts": "Meera · accounts"},
        "sites": {key: {"name": name, "project": sp.PROJECT_NAME[proj]} for key, proj, name in sp.SITES},
        "stages": stages,
        "milestones": milestones,
        "days": days,
        "kinds": KIND_NAMES,
        "counts": dict(Counter(e.kind for e in plan.entries)),
        "modules": mods,
    }
    (OUT / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    states = Counter(pg["state"] for m in mods for pg in m["pages"] if not pg["shortcut"])
    print(f"{len(rows)} entries, {plan.last_day} days, pages {dict(states)} -> {OUT}")


if __name__ == "__main__":
    main()
