"""Payment stages (FB-01): the client's payment schedule, tied to the schedule, and the follow-up when money is late.

A stage is a point in the work at which the client pays an agreed amount ("Lintel: ₹4,00,000"). It is **reached**
when the schedule activity it is tied to is completed (the same "done" the Gantt shows: status ``COMPLETED``, set
from the site's updates or by hand on the schedule), or, for a stage tied to nothing, when someone marks it reached.

**What should have come in** = the amounts of the stages reached so far. **Received** = the client's confirmed
receipts on the project (against a bill, on account, or the advance: all of it is the client's money in hand).
When received is less than what should have come in, the project is **behind on payment**: the alert names the
latest stage reached and the amount short, so finance follows up the day the milestone is marked, not at month end.

Lump-sum contracts (``project_contracts.contract_type = 'lump_sum'``) are billed from the stages: a new RA bill takes
each reached stage that is on no bill yet as one line (1 LS × the stage amount); the contract's GST, retention,
advance recovery and TDS apply to it as to any bill (``ra.totals``). Measured contracts keep billing from the BOQ;
their stages are the payment schedule only.

Worked example: stages Footing ₹3,00,000 (done 1 Sep), Lintel ₹4,00,000 (done 5 Oct), Roof slab ₹5,00,000 (not yet).
Received ₹3,20,000 → should have come in ₹7,00,000, short ₹3,80,000 since Lintel (5 Oct).

``summarise`` is pure; the rest take the request's connection and never commit.
"""

from __future__ import annotations

import datetime
import uuid
from collections.abc import Iterable, Mapping
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

_ZERO = Decimal(0)
CONTRACT_TYPES = ("measured", "lump_sum")
STAGE_FIELDS = ("name", "amount", "work_package_id", "reached_on", "sort_order", "notes")


def reached_date(stage: Mapping[str, Any]) -> datetime.date | None:
    """When the stage was reached: its activity's completion, else the date it was marked by hand, else never.
    An activity marked completed with no actual end date counts as reached on the day it was last changed."""
    if stage.get("work_package_id") is not None:
        if stage.get("activity_status") != "COMPLETED":
            return None
        return stage.get("activity_actual_end") or stage.get("activity_updated_on") or stage.get("reached_on")
    return stage.get("reached_on")


def summarise(stages: Iterable[Mapping[str, Any]], received: Decimal) -> dict[str, Any]:
    """The schedule's state: each stage with ``reached_on`` worked out, what should have come in, what did, and the
    shortfall with the stage it dates from (the earliest reached stage the money received does not cover)."""
    rows = []
    for s in stages:
        row = dict(s)
        row["reached_on"] = reached_date(s)
        row["reached"] = row["reached_on"] is not None
        rows.append(row)
    due = sum((Decimal(r["amount"]) for r in rows if r["reached"]), _ZERO)
    total = sum((Decimal(r["amount"]) for r in rows), _ZERO)
    received = Decimal(received)
    short = max(due - received, _ZERO)
    # Money received covers the reached stages in the order they were reached; the first one it does not cover
    # fully is where the client fell behind.
    behind_since = None
    covered = received
    for r in sorted((r for r in rows if r["reached"]), key=lambda r: (r["reached_on"], r.get("sort_order") or 0)):
        covered -= Decimal(r["amount"])
        r["paid"] = covered >= 0
        if covered < 0 and behind_since is None:
            behind_since = r
    for r in rows:
        r.setdefault("paid", False)
    latest = max((r for r in rows if r["reached"]), key=lambda r: (r["reached_on"], r.get("sort_order") or 0),
                 default=None)
    return {"stages": rows, "total": total, "due": due, "received": received, "short": short,
            "behind_since": ({"id": behind_since["id"], "name": behind_since["name"],
                              "reached_on": behind_since["reached_on"]} if behind_since else None),
            "latest_reached": ({"id": latest["id"], "name": latest["name"], "reached_on": latest["reached_on"]}
                               if latest else None)}


_SELECT = (
    "SELECT s.id, s.project_id, s.name, s.amount, s.work_package_id, s.reached_on, s.sort_order, s.notes, "
    "w.name AS activity_name, CAST(w.status AS text) AS activity_status, w.actual_end AS activity_actual_end, "
    "CAST(w.updated_at AS date) AS activity_updated_on, w.is_milestone AS activity_is_milestone, "
    "(SELECT b.number FROM ra_bill_lines l JOIN ra_bills b ON b.id = l.ra_bill_id WHERE l.payment_stage_id = s.id "
    " AND b.status <> 'cancelled' ORDER BY b.number LIMIT 1) AS bill_number "
    "FROM payment_stages s LEFT JOIN work_packages w ON w.id = s.work_package_id "
    "WHERE s.organization_id = :org"
)


async def list_stages(conn: AsyncConnection, org: uuid.UUID, project_ids: Iterable[Any]) -> list[dict[str, Any]]:
    ids = list(project_ids)
    if not ids:
        return []
    return [dict(r) for r in (await conn.execute(text(
        _SELECT + " AND s.project_id = ANY(:ps) ORDER BY s.sort_order, s.created_at"),
        {"org": org, "ps": ids})).mappings()]


async def get_stage(conn: AsyncConnection, org: uuid.UUID, stage_id: uuid.UUID) -> dict[str, Any] | None:
    row = (await conn.execute(text(_SELECT + " AND s.id = :id"), {"org": org, "id": stage_id})).mappings().first()
    return dict(row) if row else None


async def received_by_project(conn: AsyncConnection, org: uuid.UUID, project_ids: Iterable[Any]) -> dict[Any, Decimal]:
    ids = list(project_ids)
    if not ids:
        return {}
    rows = (await conn.execute(text(
        "SELECT project_id, COALESCE(SUM(amount), 0) FROM client_receipts WHERE organization_id = :org "
        "AND project_id = ANY(:ps) AND status = 'confirmed' GROUP BY project_id"), {"org": org, "ps": ids})).all()
    return {p: Decimal(a) for p, a in rows}


async def contract_type(conn: AsyncConnection, org: uuid.UUID, project_id: Any) -> str | None:
    return (await conn.execute(text(
        "SELECT contract_type FROM project_contracts WHERE organization_id = :org AND project_id = :p"),
        {"org": org, "p": project_id})).scalar()


async def project_state(conn: AsyncConnection, org: uuid.UUID, project_id: Any) -> dict[str, Any]:
    stages = await list_stages(conn, org, [project_id])
    received = (await received_by_project(conn, org, [project_id])).get(project_id, _ZERO)
    out = summarise(stages, received)
    out["contract_type"] = await contract_type(conn, org, project_id)
    return out


async def alerts(conn: AsyncConnection, org: uuid.UUID, project_ids: set | None) -> list[dict[str, Any]]:
    """Every project behind on payment: the money short and the stage it dates from, most short first."""
    sql = ("SELECT DISTINCT s.project_id, p.name FROM payment_stages s JOIN projects p ON p.id = s.project_id "
           "WHERE s.organization_id = :org AND COALESCE(p.status, '') <> 'archived'")
    rows = (await conn.execute(text(sql), {"org": org})).all()
    names = {p: n for p, n in rows if project_ids is None or p in project_ids}
    if not names:
        return []
    by_project: dict[Any, list[dict[str, Any]]] = {}
    for s in await list_stages(conn, org, names):
        by_project.setdefault(s["project_id"], []).append(s)
    received = await received_by_project(conn, org, names)
    out = []
    for pid, stages in by_project.items():
        state = summarise(stages, received.get(pid, _ZERO))
        if state["short"] > 0:
            out.append({"project_id": pid, "project": names[pid], "due": state["due"], "received": state["received"],
                        "short": state["short"], "behind_since": state["behind_since"],
                        "latest_reached": state["latest_reached"]})
    out.sort(key=lambda a: -a["short"])
    return out


async def create_stage(conn: AsyncConnection, org: uuid.UUID, project_id: Any, values: dict[str, Any],
                       user_id: uuid.UUID) -> Any:
    if values.get("sort_order") is None:
        values["sort_order"] = (await conn.execute(text(
            "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM payment_stages WHERE organization_id = :org "
            "AND project_id = :p"), {"org": org, "p": project_id})).scalar_one()
    cols = [c for c in STAGE_FIELDS if c in values]
    return (await conn.execute(text(
        f"INSERT INTO payment_stages (organization_id, project_id, created_by, {', '.join(cols)}) "  # noqa: S608
        f"VALUES (:org, :p, :by, {', '.join(':' + c for c in cols)}) RETURNING id"),
        {"org": org, "p": project_id, "by": user_id, **{c: values[c] for c in cols}})).scalar_one()


async def update_stage(conn: AsyncConnection, org: uuid.UUID, stage_id: uuid.UUID, values: dict[str, Any]) -> None:
    cols = [c for c in STAGE_FIELDS if c in values]
    if cols:
        await conn.execute(text(
            f"UPDATE payment_stages SET {', '.join(f'{c} = :{c}' for c in cols)}, updated_at = now() "  # noqa: S608
            "WHERE organization_id = :org AND id = :id"), {"org": org, "id": stage_id, **{c: values[c] for c in cols}})


async def delete_stage(conn: AsyncConnection, org: uuid.UUID, stage_id: uuid.UUID) -> None:
    await conn.execute(text("DELETE FROM payment_stages WHERE organization_id = :org AND id = :id"),
                       {"org": org, "id": stage_id})


async def activity_in_project(conn: AsyncConnection, org: uuid.UUID, project_id: Any, activity_id: Any) -> bool:
    return bool((await conn.execute(text(
        "SELECT 1 FROM work_packages WHERE organization_id = :org AND project_id = :p AND id = :w"),
        {"org": org, "p": project_id, "w": activity_id})).scalar())


async def unbilled(conn: AsyncConnection, org: uuid.UUID, project_id: Any) -> list[dict[str, Any]]:
    """Reached stages on no bill yet (a cancelled bill gives its stages back), shaped like ``bills.unbilled_lines``
    rows so a lump-sum bill, "to bill" and the cash forecast read them the same way as BOQ lines."""
    state = summarise(await list_stages(conn, org, [project_id]), _ZERO)
    out = []
    for i, s in enumerate(state["stages"]):
        if not s["reached"] or s["bill_number"] is not None or Decimal(s["amount"]) <= 0:
            continue
        line = {"id": None, "payment_stage_id": s["id"], "boq_code": None, "work_type": s["name"], "unit": "LS",
                "client_rate": Decimal(s["amount"])}
        out.append({"line": line, "sort_order": i, "measured": Decimal(1), "previous": _ZERO, "quantity": Decimal(1)})
    return out
