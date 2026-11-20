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
from collections import Counter
from pathlib import Path

from mesiri.application.learn import sample_plan as sp

OUT = Path(__file__).resolve().parent / "az-map"

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
    meta = {
        "last_day": plan.last_day,
        "who": {"owner": "Owner", "pm": "Anil · project manager", "engineer": "Ravi · site engineer", "accounts": "Meera · accounts"},
        "sites": {key: {"name": name, "project": sp.PROJECT_NAME[proj]} for key, proj, name in sp.SITES},
        "stages": stages,
        "milestones": milestones,
        "days": days,
        "kinds": KIND_NAMES,
        "counts": dict(Counter(e.kind for e in plan.entries)),
    }
    (OUT / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(rows)} entries, {plan.last_day} days -> {OUT}")


if __name__ == "__main__":
    main()
