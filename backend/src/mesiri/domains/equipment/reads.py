"""NXT-11: what other modules read of the machines -- the cost centres' hire and diesel per site
(``finance/costs.py``, CC-01) and the DPR's Machinery section (``application/dpr/assembly.py``)."""

from __future__ import annotations

import datetime
import uuid
from collections import defaultdict
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.domains.equipment import rules, store


async def machine_costs(conn: AsyncConnection, org: uuid.UUID, *, project_ids: set[uuid.UUID] | None,
                        site_id: uuid.UUID | None, date_from: datetime.date, date_to: datetime.date,
                        visible) -> dict[tuple, dict[str, Decimal]]:
    """Per (project, site): hire earned (hired machines, from the logs; a day on a hire bill that is an expense is in
    Expenses already and is not counted again) and diesel priced on a log that is not on an expense."""
    from mesiri.application.dpr import project_day

    today = await project_day.company_today(conn, org)
    machines = await store.fetch_machines(conn, org)
    if not machines:
        return {}
    logs = await store.fetch_events(conn, org, equipment_ids=[m["id"] for m in machines], date_to=date_to)
    bills = await store.fetch_bills(conn, org, date_from=date_from, date_to=date_to)
    out: dict[tuple, dict[str, Decimal]] = defaultdict(lambda: {"hire": rules.ZERO, "fuel": rules.ZERO,
                                                                "hours": rules.ZERO, "litres": rules.ZERO})

    def keep(p: Any, s: Any) -> bool:
        if p is None or (project_ids is not None and p not in project_ids) or (site_id is not None and s != site_id):
            return False
        return s is None or visible(p, s)

    for m in machines:
        mine = [x for x in logs if x["equipment_id"] == m["id"]]
        my_bills = [b for b in bills if b["equipment_id"] == m["id"]]
        for h in rules.hire_lines(m, mine, date_from, date_to, today):
            if keep(h["project_id"], h["site_id"]) and rules.billed(h["date"], my_bills, with_expense_only=True) is None:
                out[(h["project_id"], h["site_id"])]["hire"] += h["amount"]
        for x in mine:
            if not (date_from <= x["occurred_date"] <= date_to) or not keep(x["project_id"], x["site_id"]):
                continue
            row = out[(x["project_id"], x["site_id"])]
            row["hours"] += rules.worked(x)
            row["litres"] += rules.d(x.get("fuel_quantity"))
            if x.get("fuel_cost") is not None and x.get("expense_id") is None:
                row["fuel"] += rules.d(x["fuel_cost"])
    return dict(out)


async def machinery_for_day(conn: AsyncConnection, org: uuid.UUID, *, day: datetime.date,
                            site_ids: list[uuid.UUID] | None = None,
                            project_id: uuid.UUID | None = None) -> list[dict[str, Any]]:
    """The DPR's Machinery section: each machine's day at these sites (or the project), plain words."""
    rows = await store.fetch_events(conn, org, project_ids=[project_id] if project_id else None, date_from=day,
                                    date_to=day)
    if site_ids is not None:
        rows = [x for x in rows if x["site_id"] in set(site_ids)]
    out = []
    for x in sorted(rows, key=lambda r: (r.get("site_name") or "", r["machine_name"].casefold())):
        out.append({
            "machine": x["machine_name"], "ref": rules.ref(x["machine_number"]), "type": x.get("machine_type"),
            "ownership": "Hired" if x.get("machine_ownership") == "hired" else "Owned",
            "site_name": x.get("site_name"),
            "worked": rules.num(rules.worked(x)) or "0", "idle": rules.num(rules.d(x.get("idle_hours"))) or "0",
            "breakdown": rules.num(rules.d(x.get("breakdown_hours"))) or "0",
            "breakdown_reason": x.get("breakdown_reason") or "",
            "fuel": rules.num(rules.d(x["fuel_quantity"])) if x.get("fuel_quantity") is not None else "",
            "operator": x.get("operator_name") or x.get("operator_worker_name") or "",
            "trips": x.get("trips"),
        })
    return out
