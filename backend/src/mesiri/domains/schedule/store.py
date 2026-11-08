"""PostgreSQL reads and writes for a project's schedule (ST-04) and its start checklist (ST-05).

An activity is a ``work_packages`` row (the BOQ's section): its dates (0420), ``is_milestone`` and the
``work_package_links`` between them (0522). Progress is never typed: it is measured from what site recorded on
the section's BOQ lines (``measured_by_line``), so the bars fill themselves from the daily WhatsApp updates.

Every function takes the request's connection and never commits.
"""

from __future__ import annotations

import datetime
import uuid
from collections import defaultdict
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.domains.progress.boq import line_amounts
from mesiri.domains.schedule import logic

STAGES = ("tender", "won", "running", "handover", "defects", "closed")


def _pct(value: Decimal | None) -> int | None:
    return None if value is None else int((value * 100).to_integral_value(rounding="ROUND_HALF_UP"))


async def project(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID) -> dict | None:
    row = (await conn.execute(text(
        "SELECT id, name, client, stage, start_date, planned_finish, status FROM projects "
        "WHERE id = :p AND organization_id = :org"), {"p": project_id, "org": org})).mappings().first()
    return dict(row) if row else None


async def measured_by_line(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID) -> dict[uuid.UUID, Decimal]:
    """Quantity done to date on each current BOQ line: CC-04's own count (``boq_router.done_by_line``: work updates
    put on a line, any revision, plus confirmed work-order measurements not from an update; another unit is never
    added in). One rule, so the BOQ page's "Done" and the Gantt's bars never disagree."""
    from mesiri.domains.progress.boq_router import done_by_line
    from mesiri.infrastructure.postgres.repositories.boq import PostgresBoqRepository

    repo = PostgresBoqRepository(conn)
    lines = await repo.list_lines(org, project_id)
    return {line_id: v["done"] for line_id, v in (await done_by_line(repo, org, project_id, lines)).items()}


async def _sections(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID) -> list[dict]:
    return [dict(r) for r in (await conn.execute(text(
        "SELECT w.id, w.code, w.name, w.site_id, s.name AS site_name, w.planned_start, w.planned_end, "
        "w.actual_start, w.actual_end, w.status, w.is_milestone, w.sort_order, w.assigned_user_id, "
        "u.full_name AS assigned_name "
        "FROM work_packages w LEFT JOIN sites s ON s.id = w.site_id LEFT JOIN users u ON u.id = w.assigned_user_id "
        "WHERE w.organization_id = :org AND w.project_id = :p ORDER BY w.sort_order, w.created_at"),
        {"org": org, "p": project_id})).mappings().all()]


async def links(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID) -> list[dict]:
    return [{"predecessor": r["predecessor_id"], "successor": r["successor_id"], "lag": r["lag_days"]}
            for r in (await conn.execute(text(
                "SELECT l.predecessor_id, l.successor_id, l.lag_days FROM work_package_links l "
                "JOIN work_packages w ON w.id = l.successor_id "
                "WHERE l.organization_id = :org AND w.project_id = :p"), {"org": org, "p": project_id})).mappings()]


async def _lines(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID) -> list[dict]:
    return [dict(r) for r in (await conn.execute(text(
        "SELECT i.id, i.work_package_id, i.work_type, u.code AS unit, i.planned_quantity, i.client_rate, i.boq_code "
        "FROM work_package_planned_items i JOIN work_packages w ON w.id = i.work_package_id "
        "JOIN units_of_measure u ON u.id = i.unit_id "
        "WHERE w.organization_id = :org AND w.project_id = :p AND i.superseded_by_id IS NULL "
        "ORDER BY i.sort_order, i.created_at"), {"org": org, "p": project_id})).mappings().all()]


async def _site_updates(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID) -> dict[uuid.UUID, dict]:
    """First and last day site reported work on each section, and how many updates (work updates on the section or
    on its lines)."""
    rows = (await conn.execute(text(
        "SELECT wp, MIN(d) AS first_day, MAX(d) AS last_day, COUNT(DISTINCT aid) AS updates FROM ("
        "  SELECT a.work_package_id AS wp, a.activity_date AS d, a.id AS aid FROM activities a "
        "  WHERE a.organization_id = :org AND a.project_id = :p AND a.work_package_id IS NOT NULL "
        "  AND a.deleted_at IS NULL "
        "  UNION ALL "
        "  SELECT i.work_package_id, a.activity_date, a.id FROM activity_quantities aq "
        "  JOIN activities a ON a.id = aq.activity_id JOIN work_package_planned_items i ON i.id = aq.planned_item_id "
        "  WHERE a.organization_id = :org AND a.project_id = :p AND a.deleted_at IS NULL) x GROUP BY wp"),
        {"org": org, "p": project_id})).mappings().all()
    return {r["wp"]: dict(r) for r in rows}


async def _work_orders(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID) -> dict[uuid.UUID, list[dict]]:
    """Subcontract work orders that carry a line of each section: who is doing the work."""
    rows = (await conn.execute(text(
        "SELECT DISTINCT i.work_package_id, wo.id, wo.number, v.name AS vendor FROM work_order_lines wl "
        "JOIN work_orders wo ON wo.id = wl.work_order_id JOIN vendors v ON v.id = wo.vendor_id "
        "JOIN work_package_planned_items i ON i.id = wl.planned_item_id "
        "WHERE wo.organization_id = :org AND wo.project_id = :p AND wo.status NOT IN ('cancelled')"),
        {"org": org, "p": project_id})).mappings().all()
    out: dict[uuid.UUID, list[dict]] = defaultdict(list)
    for r in rows:
        out[r["work_package_id"]].append({"id": r["id"], "ref": f"WO-{r['number']:04d}", "vendor": r["vendor"]})
    return dict(out)


async def _open_issues(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID) -> list[dict]:
    """Open site issues (hindrances) with the site and section they were reported on."""
    return [dict(r) for r in (await conn.execute(text(
        "SELECT site_id, work_package_id FROM site_issues WHERE organization_id = :org AND project_id = :p "
        "AND status IN ('OPEN', 'ACKNOWLEDGED')"), {"org": org, "p": project_id})).mappings()]


def _issues_for(issues: list[dict], section_id: Any, site_id: Any) -> int:
    """Issues on the section itself, plus the ones on its site not tied to another section."""
    return sum(1 for i in issues if i["work_package_id"] == section_id
               or (i["work_package_id"] is None and site_id is not None and i["site_id"] == site_id))


async def load(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID, today: datetime.date) -> dict[str, Any]:
    """The whole schedule as the dashboard and WhatsApp read it: activities with their state, the links, the
    knock-on of what is late, the critical path, and a summary."""
    proj = await project(conn, org, project_id)
    sections = await _sections(conn, org, project_id)
    link_rows = await links(conn, org, project_id)
    measured = await measured_by_line(conn, org, project_id)
    by_section: dict[Any, list[dict]] = defaultdict(list)
    for line in await _lines(conn, org, project_id):
        done = measured.get(line["id"], Decimal(0))
        money = line_amounts({"planned_quantity": line["planned_quantity"], "client_rate": line["client_rate"]})
        by_section[line["work_package_id"]].append({
            "id": line["id"], "work": line["work_type"], "unit": line["unit"], "boq_code": line["boq_code"],
            "planned_quantity": Decimal(line["planned_quantity"]), "done_quantity": done,
            "contract_value": money["contract_value"],
        })
    updates = await _site_updates(conn, org, project_id)
    orders = await _work_orders(conn, org, project_id)
    issues = await _open_issues(conn, org, project_id)

    acts = []
    for s in sections:
        lines = by_section.get(s["id"], [])
        progress = logic.line_progress(lines)
        seen = updates.get(s["id"]) or {}
        acts.append({
            "id": s["id"], "name": s["name"], "start": s["planned_start"], "end": s["planned_end"],
            "milestone": s["is_milestone"], "done": s["status"] == "COMPLETED", "progress": progress,
            "actual_start": s["actual_start"] or seen.get("first_day"), "actual_end": s["actual_end"],
        })
    try:
        critical = logic.critical(acts, link_rows)
        knock = logic.knock_on(acts, link_rows, today)
    except logic.CycleError:
        critical, knock = set(), {"moves": {}, "planned_finish": None, "forecast_finish": None, "slip_days": 0}
    conflicts = logic.conflicts(acts, link_rows)
    after: dict[Any, list[dict]] = defaultdict(list)
    for lk in link_rows:
        after[lk["successor"]].append({"id": lk["predecessor"], "lag": lk["lag"]})

    out = []
    counts: dict[str, int] = defaultdict(int)
    for s, a in zip(sections, acts, strict=True):
        state = logic.assess(a, today)
        counts[state["state"]] += 1
        seen = updates.get(s["id"]) or {}
        lines = by_section.get(s["id"], [])
        out.append({
            "id": s["id"], "code": s["code"], "name": s["name"], "site_id": s["site_id"], "site_name": s["site_name"],
            "start": a["start"], "end": a["end"], "milestone": a["milestone"], "done": a["done"],
            "duration": logic.duration(a) if logic.scheduled(a) else None,
            "actual_start": a["actual_start"], "actual_end": a["actual_end"],
            "progress": _pct(a["progress"]), "expected": _pct(state["expected"]),
            "state": state["state"], "days_late": state["days_late"], "forecast_end": state["forecast_end"],
            "slip_days": state["slip_days"], "pushed_days": knock["moves"].get(s["id"], 0) if not a["done"] else 0,
            "critical": s["id"] in critical, "after": after.get(s["id"], []),
            "assigned_to": s["assigned_name"], "last_update": seen.get("last_day"), "updates": seen.get("updates", 0),
            "open_issues": _issues_for(issues, s["id"], s["site_id"]),
            "work_orders": orders.get(s["id"], []),
            "lines": [{"id": ln["id"], "work": ln["work"], "unit": ln["unit"], "boq_code": ln["boq_code"],
                       "planned_quantity": str(ln["planned_quantity"]), "done_quantity": str(ln["done_quantity"]),
                       "progress": _pct(min(ln["done_quantity"] / ln["planned_quantity"], Decimal(1)))
                       if ln["planned_quantity"] > 0 else None} for ln in lines],
            "sort_order": s["sort_order"],
        })
    planned_finish = proj["planned_finish"] if proj else None
    forecast = knock["forecast_finish"]
    target = planned_finish or knock["planned_finish"]
    summary = {
        "activities": len(out), "scheduled": sum(1 for a in acts if logic.scheduled(a)),
        "counts": dict(counts), "planned_finish": knock["planned_finish"], "contract_finish": planned_finish,
        "forecast_finish": forecast,
        "slip_days": max((forecast - target).days, 0) if forecast and target else 0,
        "progress": _pct(logic.line_progress([ln for ls in by_section.values() for ln in ls])),
        "first_start": min((a["start"] for a in acts if a["start"]), default=None),
        "conflicts": len(conflicts),
    }
    return {"project": proj, "today": today, "activities": out, "links": link_rows, "conflicts": conflicts,
            "summary": summary}


# -- writes -----------------------------------------------------------------------------------------------------------

async def section(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID, section_id: uuid.UUID) -> dict | None:
    row = (await conn.execute(text(
        "SELECT id, name, site_id, planned_start, planned_end, is_milestone, status, actual_start, actual_end "
        "FROM work_packages WHERE id = :id AND organization_id = :org AND project_id = :p"),
        {"id": section_id, "org": org, "p": project_id})).mappings().first()
    return dict(row) if row else None


async def set_dates(conn: AsyncConnection, moves: dict[Any, tuple[datetime.date, datetime.date]]) -> None:
    for sid, (start, end) in moves.items():
        await conn.execute(text("UPDATE work_packages SET planned_start = :s, planned_end = :e, updated_at = now() "
                                "WHERE id = :id"), {"s": start, "e": end, "id": sid})


async def update_section(conn: AsyncConnection, section_id: uuid.UUID, changes: dict[str, Any]) -> None:
    if not changes:
        return
    sets = ", ".join(f"{k} = :{k}" for k in changes)
    await conn.execute(text(f"UPDATE work_packages SET {sets}, updated_at = now() WHERE id = :id"),  # noqa: S608
                       {**changes, "id": section_id})


async def replace_predecessors(conn: AsyncConnection, org: uuid.UUID, successor: uuid.UUID,
                               predecessors: list[tuple[uuid.UUID, int]]) -> None:
    await conn.execute(text("DELETE FROM work_package_links WHERE successor_id = :s"), {"s": successor})
    for pred, lag in predecessors:
        await conn.execute(text(
            "INSERT INTO work_package_links (organization_id, predecessor_id, successor_id, lag_days) "
            "VALUES (:org, :p, :s, :lag)"), {"org": org, "p": pred, "s": successor, "lag": lag})


async def section_in_use(conn: AsyncConnection, section_id: uuid.UUID) -> str | None:
    """Why a schedule activity cannot be deleted (it is a BOQ section with lines, or site reported on it)."""
    if (await conn.execute(text("SELECT 1 FROM work_package_planned_items WHERE work_package_id = :s LIMIT 1"),
                           {"s": section_id})).first():
        return "It is a BOQ section with lines: clear its dates to take it off the schedule, or remove it in the BOQ."
    if (await conn.execute(text("SELECT 1 FROM activities WHERE work_package_id = :s LIMIT 1"),
                           {"s": section_id})).first():
        return "Site has reported work on it, so it stays. Clear its dates to take it off the schedule."
    return None


# -- project start checklist -------------------------------------------------------------------------------------------

async def checklist(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID) -> dict[str, Any]:
    """The counts behind each step of the project start page."""
    one = {"org": org, "p": project_id}

    async def n(sql: str) -> int:
        return int((await conn.execute(text(sql), one)).scalar() or 0)

    return {
        "sections": await n("SELECT count(*) FROM work_packages WHERE organization_id = :org AND project_id = :p"),
        "lines": await n("SELECT count(*) FROM work_package_planned_items i JOIN work_packages w ON w.id = "
                         "i.work_package_id WHERE w.organization_id = :org AND w.project_id = :p "
                         "AND i.superseded_by_id IS NULL"),
        "priced_lines": await n("SELECT count(*) FROM work_package_planned_items i JOIN work_packages w ON w.id = "
                                "i.work_package_id WHERE w.organization_id = :org AND w.project_id = :p "
                                "AND i.superseded_by_id IS NULL AND i.client_rate IS NOT NULL"),
        "scheduled": await n("SELECT count(*) FROM work_packages WHERE organization_id = :org AND project_id = :p "
                             "AND planned_start IS NOT NULL AND planned_end IS NOT NULL"),
        "links": await n("SELECT count(*) FROM work_package_links l JOIN work_packages w ON w.id = l.successor_id "
                         "WHERE l.organization_id = :org AND w.project_id = :p"),
        "sites": await n("SELECT count(*) FROM sites WHERE organization_id = :org AND project_id = :p "
                         "AND COALESCE(status, 'active') <> 'archived'"),
        "reporters": await n("SELECT count(DISTINCT u.id) FROM users u JOIN project_members m ON m.user_id = u.id "
                             "WHERE m.project_id = :p AND u.organization_id = :org AND u.status = 'active' "
                             "AND u.whatsapp_number IS NOT NULL"),
        "suppliers": await n("SELECT count(*) FROM vendors WHERE organization_id = :org"),
        "stock_moves": await n("SELECT count(*) FROM material_receipts WHERE project_id = :p AND organization_id = :org"),
        "work_orders": await n("SELECT count(*) FROM work_orders WHERE organization_id = :org AND project_id = :p "
                               "AND status <> 'cancelled'"),
        "updates": await n("SELECT count(*) FROM activities WHERE organization_id = :org AND project_id = :p "
                           "AND deleted_at IS NULL"),
    }
