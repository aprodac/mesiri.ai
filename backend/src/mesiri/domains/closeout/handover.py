"""The handover checklist (END-03): from "work is nearly done" to "project closed", the mirror of the project start
page (ST-05). Every step is read from data that already exists; nothing here is typed twice.

Steps, in the order a contractor finishes a job:

1. **Work done**: the BOQ measured to date against planned (the schedule's own progress, CC-04's count).
2. **Snags cleared**: every snag found on the walk-round closed (END-01).
3. **Subcontractors settled**: no work order still issued, no subcontract bill waiting for a check.
4. **Final bill**: every priced BOQ line's measured work is on a submitted bill (money roles only).
5. **Client paid**: nothing outstanding on the bills (money roles only).
6. **Handed over**: the handover day is set; the defect period runs from it.
7. **Defect period**: the defect period has ended and no defect raised in it is still open.
8. **Retention received**: the client's retention released (money roles only).

The money steps are left out for a role that may not see client money (D-N3 default: owner, admin, finance), so a
PM's next step is never one they can't open.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.domains.billing import receivables
from mesiri.domains.closeout import snags


async def _n(conn: AsyncConnection, sql: str, params: dict) -> int:
    return int((await conn.execute(text(sql), params)).scalar() or 0)


async def unbilled_lines(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID) -> int:
    """Priced BOQ lines whose work measured to date is more than what bills (not withdrawn) carry."""
    from mesiri.domains.billing.bills import previous_by_line
    from mesiri.domains.progress.boq_router import done_by_line
    from mesiri.infrastructure.postgres.repositories.boq import PostgresBoqRepository

    repo = PostgresBoqRepository(conn)
    lines = [ln for ln in await repo.list_lines(org, project_id) if ln["client_rate"] is not None]
    if not lines:
        return 0
    done = await done_by_line(repo, org, project_id, lines)
    billed = await previous_by_line(conn, org, project_id)
    return sum(1 for ln in lines if Decimal(done[ln["id"]]["done"]) > billed.get(ln["id"], Decimal(0)))


async def facts(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID, today: datetime.date,
                money: bool) -> dict[str, Any]:
    from mesiri.domains.schedule import store as schedule_store

    one = {"org": org, "p": project_id}
    head = (await conn.execute(text(
        "SELECT p.handed_over_on, c.defect_liability_months FROM projects p LEFT JOIN project_contracts c "
        "ON c.project_id = p.id WHERE p.id = :p AND p.organization_id = :org"), one)).mappings().first()
    sched = await schedule_store.load(conn, org, project_id, today)
    out: dict[str, Any] = {
        "progress": sched["summary"].get("progress"),
        "snags": await snags.counts(conn, org, project_id),
        "snags_overdue": await snags.overdue(conn, org, project_id, today),
        "work_orders_open": await _n(conn, "SELECT count(*) FROM work_orders WHERE organization_id = :org AND "
                                           "project_id = :p AND status = 'issued'", one),
        "subcontract_bills_waiting": await _n(conn, "SELECT count(*) FROM work_order_bills b JOIN work_orders w ON "
                                                    "w.id = b.work_order_id WHERE w.organization_id = :org AND "
                                                    "w.project_id = :p AND b.check_status IN ('waiting', 'flagged')",
                                              one),
        "handed_over_on": head["handed_over_on"],
        "defect_liability_months": head["defect_liability_months"],
        "defects_end": receivables.defects_end(head["handed_over_on"], head["defect_liability_months"]),
    }
    if money:
        from mesiri.domains.billing import payments

        out["unbilled_lines"] = await unbilled_lines(conn, org, project_id)
        out["money"] = await payments.project_money(conn, org, project_id, today)
    return out


def _rupees(value: Any) -> str:
    from mesiri.domains.equipment.rules import inr  # one Indian-grouping formatter: "₹11,27,160"

    return inr(Decimal(value))


def steps(f: dict[str, Any], today: datetime.date, money: bool) -> list[dict[str, Any]]:
    s = f["snags"]
    pending = s["open"] + s["fixed"]
    progress = f["progress"]
    out: list[dict[str, Any]] = [
        {"key": "work", "title": "Work done", "done": progress is not None and progress >= 100,
         "detail": (f"{progress}% of the BOQ measured from site updates" if progress is not None
                    else "No BOQ lines to measure against yet"), "link": "/planning/schedule"},
        {"key": "snags", "title": "Snags cleared", "done": s["total"] > 0 and pending == 0,
         "detail": ("Walk every room with the site engineer and list what to put right" if s["total"] == 0 else
                    f"{s['open']} open, {s['fixed']} fixed and waiting for a check, {s['closed']} closed"
                    + (f"; {f['snags_overdue']} past their day" if f["snags_overdue"] else "")),
         "link": "/site/snags"},
        {"key": "subcontracts", "title": "Subcontractors settled",
         "done": f["work_orders_open"] == 0 and f["subcontract_bills_waiting"] == 0,
         "detail": ("No work order still running, no bill waiting" if f["work_orders_open"] == 0
                    and f["subcontract_bills_waiting"] == 0 else
                    f"{f['work_orders_open']} work orders still issued, {f['subcontract_bills_waiting']} bills waiting"
                    " for a check: complete them and settle the final accounts"),
         "link": "/subcontract/work-orders", "optional": True},
    ]
    if money:
        m = f["money"]
        out += [
            {"key": "final_bill", "title": "Final bill", "done": f["unbilled_lines"] == 0 and bool(m["bills"]),
             "detail": (f"{f['unbilled_lines']} BOQ lines have measured work not on a bill yet: make the final RA bill"
                        if f["unbilled_lines"] else
                        "Every measured line is billed" if m["bills"] else "No bill submitted yet"),
             "link": "/billing/ra-bills"},
            {"key": "paid", "title": "Client paid", "done": bool(m["bills"]) and m["outstanding"] == 0,
             "detail": (f"{_rupees(m['outstanding'])} still owed on the bills"
                        + (f", oldest {m['oldest_days']} days" if m["oldest_days"] else "")
                        if m["outstanding"] else "Nothing outstanding on the bills"),
             "link": "/billing/receipts"},
        ]
    handed = f["handed_over_on"]
    end = f["defects_end"]
    out.append({"key": "handover", "title": "Handed over", "done": handed is not None,
                "detail": (f"Handed over on {handed:%d %b %Y}" if handed else
                           "Set the day the client took the keys: the defect period runs from it")})
    if handed is not None:
        open_defects = s["defects_pending"]
        out.append({"key": "defects", "title": "Defect period", "done": bool(end and today >= end) and not open_defects,
                    "detail": ((f"Ends {end:%d %b %Y}" if end else "Set the defect liability months in the contract")
                               + (f"; {open_defects} defects the client raised still open" if open_defects else "")),
                    "link": "/site/snags"})
        if money:
            m = f["money"]
            out.append({"key": "retention", "title": "Retention received",
                        "done": m["retention_held"] > 0 and m["retention_left"] == 0,
                        "detail": (f"{_rupees(m['retention_left'])} held by the client"
                                   + (f", due {end:%d %b %Y}" if end else "")
                                   + (" (due now: ask for it)" if m["retention_due_now"] else "")
                                   if m["retention_left"] > 0 else "No retention held"),
                        "link": "/billing/receipts"})
    return out
