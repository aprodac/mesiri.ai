"""NXT-11: storage for the machine register (``equipment``), its events and day logs (``equipment_events``, 0110 +
0518) and hire bills (``equipment_hire_bills``). SQL only; what a row means is in ``rules.py``, the routes in
``router.py``. Every query is scoped by company (and row-level security holds it too).
"""

from __future__ import annotations

import datetime
import uuid
from collections.abc import Iterable
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

#: Columns a machine can be given or changed by (the router checks who may set which).
MACHINE_FIELDS = (
    "name", "type", "kind", "ownership", "vendor_id", "rate", "rate_unit", "min_hours_per_day", "registration_no",
    "make_model", "fuel_type", "project_id", "site_id", "status", "on_hire_from", "off_hire_on",
    "service_every_hours", "last_service_on", "last_service_meter", "operator_name", "operator_worker_id", "notes",
)

#: A day log's figures (``duration_hours`` is the hours worked, 0110's column).
LOG_FIELDS = (
    "duration_hours", "idle_hours", "breakdown_hours", "breakdown_reason", "fuel_quantity", "fuel_unit", "fuel_cost",
    "paid_from_account_id", "operator_name", "operator_worker_id", "trips", "meter_reading", "expense_id", "notes",
)

_MACHINE_SQL = """
    SELECT e.*, v.name AS vendor_name, p.name AS project_name, s.name AS site_name,
           w.name AS operator_worker_name
      FROM equipment e
      LEFT JOIN vendors v ON v.id = e.vendor_id
      LEFT JOIN projects p ON p.id = e.project_id
      LEFT JOIN sites s ON s.id = e.site_id
      LEFT JOIN workforce_workers w ON w.id = e.operator_worker_id
     WHERE e.organization_id = :org
"""


async def fetch_machines(conn: AsyncConnection, org: uuid.UUID, *, ids: Iterable[uuid.UUID] | None = None,
                         vendor_id: uuid.UUID | None = None) -> list[dict[str, Any]]:
    sql, params = _MACHINE_SQL, {"org": org}
    if ids is not None:
        sql += " AND e.id = ANY(:ids)"
        params["ids"] = list(ids)
    if vendor_id is not None:
        sql += " AND e.vendor_id = :vendor"
        params["vendor"] = vendor_id
    rows = (await conn.execute(text(sql + " ORDER BY e.number"), params)).mappings().all()
    return [dict(r) for r in rows]


async def fetch_machine(conn: AsyncConnection, org: uuid.UUID, machine_id: uuid.UUID) -> dict[str, Any] | None:
    rows = await fetch_machines(conn, org, ids=[machine_id])
    return rows[0] if rows else None


async def next_number(conn: AsyncConnection, org: uuid.UUID) -> int:
    await conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": f"equipment:{org}"})
    row = (await conn.execute(text("SELECT COALESCE(MAX(number), 0) + 1 FROM equipment WHERE organization_id = :org"),
                              {"org": org})).first()
    return int(row[0])  # type: ignore[index]


async def name_taken(conn: AsyncConnection, org: uuid.UUID, name: str, *, other_than: uuid.UUID | None = None) -> bool:
    row = (await conn.execute(text(
        "SELECT 1 FROM equipment WHERE organization_id = :org AND lower(btrim(name)) = lower(btrim(:name)) "
        "AND status <> 'retired' AND (CAST(:other AS uuid) IS NULL OR id <> :other)"),
        {"org": org, "name": name, "other": other_than})).first()
    return row is not None


async def insert_machine(conn: AsyncConnection, org: uuid.UUID, values: dict[str, Any], *, by: uuid.UUID) -> uuid.UUID:
    number = await next_number(conn, org)
    machine_id = uuid.uuid4()
    cols = [k for k in MACHINE_FIELDS if k in values]
    await conn.execute(text(
        f"INSERT INTO equipment (id, organization_id, number, created_by, updated_by, {', '.join(cols)}) "  # noqa: S608
        f"VALUES (:id, :org, :number, :by, :by, {', '.join(':' + c for c in cols)})"),
        {"id": machine_id, "org": org, "number": number, "by": by, **{c: values[c] for c in cols}})
    return machine_id


async def update_machine(conn: AsyncConnection, org: uuid.UUID, machine_id: uuid.UUID, values: dict[str, Any], *,
                         by: uuid.UUID) -> None:
    cols = [k for k in MACHINE_FIELDS if k in values]
    if not cols:
        return
    sets = ", ".join(f"{c} = :{c}" for c in cols)
    await conn.execute(text(
        f"UPDATE equipment SET {sets}, updated_at = now(), updated_by = :by "  # noqa: S608 -- fixed names
        "WHERE id = :id AND organization_id = :org"),
        {"id": machine_id, "org": org, "by": by, **{c: values[c] for c in cols}})


async def delete_machine(conn: AsyncConnection, org: uuid.UUID, machine_id: uuid.UUID) -> None:
    await conn.execute(text("DELETE FROM equipment WHERE id = :id AND organization_id = :org"),
                       {"id": machine_id, "org": org})


async def history_count(conn: AsyncConnection, org: uuid.UUID, machine_id: uuid.UUID) -> int:
    row = (await conn.execute(text(
        "SELECT (SELECT COUNT(*) FROM equipment_events WHERE organization_id = :org AND equipment_id = :id) "
        "+ (SELECT COUNT(*) FROM equipment_hire_bills WHERE organization_id = :org AND equipment_id = :id)"),
        {"org": org, "id": machine_id})).first()
    return int(row[0] or 0)  # type: ignore[index]


_EVENT_SQL = """
    SELECT ev.*, e.name AS machine_name, e.number AS machine_number, e.kind AS machine_kind,
           e.ownership AS machine_ownership, e.type AS machine_type, s.name AS site_name, p.name AS project_name,
           fs.name AS from_site_name, ts.name AS to_site_name, u.full_name AS created_by_name,
           w.name AS operator_worker_name, i.status AS issue_status
      FROM equipment_events ev
      JOIN equipment e ON e.id = ev.equipment_id
      LEFT JOIN sites s ON s.id = ev.site_id
      LEFT JOIN projects p ON p.id = ev.project_id
      LEFT JOIN sites fs ON fs.id = ev.from_site_id
      LEFT JOIN sites ts ON ts.id = ev.to_site_id
      LEFT JOIN users u ON u.id = ev.created_by
      LEFT JOIN workforce_workers w ON w.id = ev.operator_worker_id
      LEFT JOIN site_issues i ON i.id = ev.issue_id
     WHERE ev.organization_id = :org
"""


async def fetch_events(conn: AsyncConnection, org: uuid.UUID, *, equipment_ids: Iterable[uuid.UUID] | None = None,
                       project_ids: Iterable[uuid.UUID] | None = None, site_id: uuid.UUID | None = None,
                       date_from: datetime.date | None = None, date_to: datetime.date | None = None,
                       event_types: tuple[str, ...] | None = ("day_log",), include_voided: bool = False,
                       ids: Iterable[uuid.UUID] | None = None) -> list[dict[str, Any]]:
    sql, params = _EVENT_SQL, {"org": org}
    if equipment_ids is not None:
        sql += " AND ev.equipment_id = ANY(:machines)"
        params["machines"] = list(equipment_ids)
    if project_ids is not None:
        sql += " AND ev.project_id = ANY(:projects)"
        params["projects"] = list(project_ids)
    if site_id is not None:
        sql += " AND ev.site_id = :site"
        params["site"] = site_id
    if date_from is not None:
        sql += " AND ev.occurred_date >= :f"
        params["f"] = date_from
    if date_to is not None:
        sql += " AND ev.occurred_date <= :t"
        params["t"] = date_to
    if event_types is not None:
        sql += " AND ev.event_type = ANY(:types)"
        params["types"] = list(event_types)
    if not include_voided:
        sql += " AND ev.voided_at IS NULL"
    if ids is not None:
        sql += " AND ev.id = ANY(:ids)"
        params["ids"] = list(ids)
    rows = (await conn.execute(text(sql + " ORDER BY ev.occurred_date DESC, ev.created_at DESC"), params)).mappings().all()
    return [dict(r) for r in rows]


async def day_log_of(conn: AsyncConnection, org: uuid.UUID, machine_id: uuid.UUID,
                     day: datetime.date) -> dict[str, Any] | None:
    row = (await conn.execute(text(
        "SELECT * FROM equipment_events WHERE organization_id = :org AND equipment_id = :m AND occurred_date = :d "
        "AND event_type = 'day_log' AND voided_at IS NULL"), {"org": org, "m": machine_id, "d": day})).mappings().first()
    return dict(row) if row else None


async def insert_event(conn: AsyncConnection, org: uuid.UUID, machine: dict[str, Any], *, event_type: str,
                       project_id: uuid.UUID, site_id: uuid.UUID | None, day: datetime.date, by: uuid.UUID,
                       source: str, values: dict[str, Any] | None = None, from_site_id: uuid.UUID | None = None,
                       to_site_id: uuid.UUID | None = None, issue_id: uuid.UUID | None = None) -> uuid.UUID:
    values = values or {}
    event_id = uuid.uuid4()
    cols = [k for k in LOG_FIELDS if k in values]
    extra = "".join(f", {c}" for c in cols)
    extra_v = "".join(f", :{c}" for c in cols)
    await conn.execute(text(
        "INSERT INTO equipment_events (id, organization_id, project_id, site_id, equipment_id, equipment_name, "
        "equipment_type, event_type, occurred_date, from_site_id, to_site_id, issue_id, source, created_by, updated_by"
        f"{extra}) VALUES (:id, :org, :project, :site, :machine, :name, :type, :event_type, :day, :from_site, "  # noqa: S608
        f":to_site, :issue, :source, :by, :by{extra_v})"),
        {"id": event_id, "org": org, "project": project_id, "site": site_id, "machine": machine["id"],
         "name": machine["name"], "type": machine.get("type"), "event_type": event_type, "day": day,
         "from_site": from_site_id, "to_site": to_site_id, "issue": issue_id, "source": source, "by": by,
         **{c: values[c] for c in cols}})
    return event_id


async def update_day_log(conn: AsyncConnection, org: uuid.UUID, event_id: uuid.UUID, *, project_id: uuid.UUID,
                         site_id: uuid.UUID, values: dict[str, Any], by: uuid.UUID, source: str,
                         issue_id: uuid.UUID | None) -> None:
    """Change the day's figures: each field given replaces the one saved (None clears it); one not given stays
    ("JCB 6 hrs", then "JCB 30 L diesel": both are the day's)."""
    cols = [c for c in LOG_FIELDS if c in values]
    sets = "".join(f", {c} = :{c}" for c in cols)
    await conn.execute(text(
        f"UPDATE equipment_events SET project_id = :project, site_id = :site, issue_id = :issue{sets}, "  # noqa: S608
        "source = :source, updated_at = now(), updated_by = :by WHERE id = :id AND organization_id = :org"),
        {"id": event_id, "org": org, "project": project_id, "site": site_id, "by": by, "source": source,
         "issue": issue_id, **{c: values[c] for c in cols}})


async def void_event(conn: AsyncConnection, org: uuid.UUID, event_id: uuid.UUID, *, by: uuid.UUID) -> None:
    await conn.execute(text(
        "UPDATE equipment_events SET voided_at = now(), voided_by = :by, updated_at = now(), updated_by = :by "
        "WHERE id = :id AND organization_id = :org AND voided_at IS NULL"), {"id": event_id, "org": org, "by": by})


async def worked_since(conn: AsyncConnection, org: uuid.UUID, machine_ids: list[uuid.UUID]) -> dict[uuid.UUID, Any]:
    """Hours worked per machine since its last service (or since it was added)."""
    if not machine_ids:
        return {}
    rows = (await conn.execute(text(
        "SELECT e.id, COALESCE(SUM(ev.duration_hours), 0) AS hours FROM equipment e "
        "LEFT JOIN equipment_events ev ON ev.equipment_id = e.id AND ev.event_type = 'day_log' "
        "AND ev.voided_at IS NULL AND (e.last_service_on IS NULL OR ev.occurred_date > e.last_service_on) "
        "WHERE e.organization_id = :org AND e.id = ANY(:ids) GROUP BY e.id"),
        {"org": org, "ids": machine_ids})).mappings().all()
    return {r["id"]: r["hours"] for r in rows}


_BILL_SQL = """
    SELECT b.*, e.name AS machine_name, e.number AS machine_number, v.name AS vendor_name, x.amount AS expense_amount,
           u.full_name AS created_by_name
      FROM equipment_hire_bills b
      JOIN equipment e ON e.id = b.equipment_id
      LEFT JOIN vendors v ON v.id = b.vendor_id
      LEFT JOIN expenses x ON x.id = b.expense_id
      LEFT JOIN users u ON u.id = b.created_by
     WHERE b.organization_id = :org
"""


async def fetch_bills(conn: AsyncConnection, org: uuid.UUID, *, equipment_ids: Iterable[uuid.UUID] | None = None,
                      date_from: datetime.date | None = None, date_to: datetime.date | None = None,
                      ids: Iterable[uuid.UUID] | None = None) -> list[dict[str, Any]]:
    sql, params = _BILL_SQL, {"org": org}
    if equipment_ids is not None:
        sql += " AND b.equipment_id = ANY(:machines)"
        params["machines"] = list(equipment_ids)
    if date_from is not None:  # overlaps the period
        sql += " AND b.period_to >= :f"
        params["f"] = date_from
    if date_to is not None:
        sql += " AND b.period_from <= :t"
        params["t"] = date_to
    if ids is not None:
        sql += " AND b.id = ANY(:ids)"
        params["ids"] = list(ids)
    rows = (await conn.execute(text(sql + " ORDER BY b.period_from DESC, b.created_at DESC"), params)).mappings().all()
    return [dict(r) for r in rows]


async def insert_bill(conn: AsyncConnection, org: uuid.UUID, values: dict[str, Any], *, by: uuid.UUID) -> uuid.UUID:
    bill_id = uuid.uuid4()
    cols = ("equipment_id", "vendor_id", "period_from", "period_to", "billed_hours", "billed_days", "amount", "bill_ref",
            "bill_date", "expense_id", "notes")
    await conn.execute(text(
        f"INSERT INTO equipment_hire_bills (id, organization_id, created_by, {', '.join(cols)}) "  # noqa: S608
        f"VALUES (:id, :org, :by, {', '.join(':' + c for c in cols)})"),
        {"id": bill_id, "org": org, "by": by, **{c: values.get(c) for c in cols}})
    return bill_id


async def update_bill(conn: AsyncConnection, org: uuid.UUID, bill_id: uuid.UUID, values: dict[str, Any]) -> None:
    cols = [c for c in ("period_from", "period_to", "billed_hours", "billed_days", "amount", "bill_ref", "bill_date",
                        "expense_id", "notes") if c in values]
    if cols:
        await conn.execute(text(
            f"UPDATE equipment_hire_bills SET {', '.join(f'{c} = :{c}' for c in cols)} "  # noqa: S608
            "WHERE id = :id AND organization_id = :org"), {"id": bill_id, "org": org, **{c: values[c] for c in cols}})


async def delete_bill(conn: AsyncConnection, org: uuid.UUID, bill_id: uuid.UUID) -> None:
    await conn.execute(text("DELETE FROM equipment_hire_bills WHERE id = :id AND organization_id = :org"),
                       {"id": bill_id, "org": org})


async def site_project(conn: AsyncConnection, org: uuid.UUID, site_id: uuid.UUID) -> uuid.UUID | None:
    row = (await conn.execute(text("SELECT project_id FROM sites WHERE id = :s AND organization_id = :org"),
                              {"s": site_id, "org": org})).first()
    return row[0] if row else None  # type: ignore[index]
