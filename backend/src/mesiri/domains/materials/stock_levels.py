"""PRC-47: the minimum each site should hold of a material, and the daily note when it holds less.

The office sets, per site and material, a minimum (``min_qty``) and how much to ask for when it goes below
(``reorder_qty``), in the material's stock unit: typed in Materials > Stock, from the Excel import ("Minimum stock"
sheet), "suggested from use" (a week's use plus the supplier's lead time, ``stock_summary.suggest_minimum``) or on
WhatsApp. Stock itself is not read here: the stock summary (``stock_summary.finish_row``) owns "below minimum" and
"running low", so the Stock page, the API, WhatsApp and this note say the same.

**Covered:** an item below its minimum is not brought up again while an open purchase order, a live RFQ or a waiting
material request already has it for that site: someone is already buying it.

**The daily note** (``queue_reorder_reminders``), one per project and person a day, to the people who run the project
(owner, admin, project manager on it), queued like the other reminders (``application/procurement/alerts``): the
items below minimum and not covered, per site, with two links that open Materials > Stock with a draft request or a
draft RFQ already holding the reorder quantities. English only for now, like the material plan's note (MP-03).
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.domains.materials.stock_summary import reorder_quantity

RULE = "stock_below_minimum"
SET_HOW = ("typed", "excel", "suggested", "whatsapp")
#: Days from order to delivery when the supplier's lead time is not known (the material plan's D-MP2).
DEFAULT_LEAD_DAYS = 2
MANAGER_ROLES = ("ADMIN", "OWNER", "SUPER_ADMIN", "PROJECT_MANAGER")
#: Items listed by name in one site's part of the note; the rest are counted.
NOTE_ITEMS = 6


def num(value: Any) -> str:
    n = Decimal(str(value))
    return f"{n.quantize(Decimal(1)) if n == n.to_integral_value() else n.normalize():f}"


async def levels_by_site(conn: AsyncConnection, organization_id: uuid.UUID,
                         site_ids: list[uuid.UUID] | None = None) -> dict[tuple[str, str], dict[str, Any]]:
    """Every minimum set, by (site id, material id) as strings: what ``finish_row`` takes."""
    sql = ("SELECT l.id, l.site_id, l.material_id, l.min_qty, l.reorder_qty, l.set_how, l.updated_at, "
           "u.full_name AS set_by_name FROM stock_levels l LEFT JOIN users u ON u.id = l.set_by "
           "WHERE l.organization_id = :org")
    params: dict[str, Any] = {"org": organization_id}
    if site_ids is not None:
        sql += " AND l.site_id = ANY(:sites)"
        params["sites"] = list(site_ids)
    rows = (await conn.execute(text(sql), params)).mappings().all()
    return {(str(r["site_id"]), str(r["material_id"])): dict(r) for r in rows}


async def save_level(conn: AsyncConnection, organization_id: uuid.UUID, *, site_id: uuid.UUID, material_id: uuid.UUID,
                     min_qty: Decimal, reorder_qty: Decimal | None, set_how: str, user_id: uuid.UUID | None) -> uuid.UUID:
    """Set (or change) one site's minimum for one material. Returns the row's id."""
    return (await conn.execute(text(
        """
        INSERT INTO stock_levels (organization_id, site_id, material_id, min_qty, reorder_qty, set_how, set_by)
        VALUES (:org, :site, :material, :min, :reorder, :how, :by)
        ON CONFLICT (site_id, material_id) DO UPDATE
           SET min_qty = EXCLUDED.min_qty, reorder_qty = EXCLUDED.reorder_qty, set_how = EXCLUDED.set_how,
               set_by = EXCLUDED.set_by, updated_at = now()
        RETURNING id
        """), {"org": organization_id, "site": site_id, "material": material_id, "min": min_qty,
               "reorder": reorder_qty, "how": set_how, "by": user_id})).scalar_one()


async def remove_level(conn: AsyncConnection, organization_id: uuid.UUID, site_id: uuid.UUID,
                       material_id: uuid.UUID) -> bool:
    gone = await conn.execute(text(
        "DELETE FROM stock_levels WHERE organization_id = :org AND site_id = :site AND material_id = :material"),
        {"org": organization_id, "site": site_id, "material": material_id})
    return bool(gone.rowcount)


async def lead_days(conn: AsyncConnection, organization_id: uuid.UUID,
                    material_ids: list[uuid.UUID]) -> dict[str, tuple[int, str | None]]:
    """Per material: the lead time of the supplier who last delivered it (``DEFAULT_LEAD_DAYS`` when not set), and
    that supplier's name. The material plan's rule (MP-03)."""
    from mesiri.domains.materials.plan_router import _suppliers

    found = await _suppliers(conn, organization_id, material_ids)
    out: dict[str, tuple[int, str | None]] = {}
    for mid in material_ids:
        sup = found.get(mid) or found.get(uuid.UUID(str(mid)))
        days = sup.get("lead_time_days") if sup else None
        out[str(mid)] = (DEFAULT_LEAD_DAYS if days is None else int(days), sup.get("name") if sup else None)
    return out


async def covered(conn: AsyncConnection, organization_id: uuid.UUID) -> dict[tuple[str, str], str]:
    """(site, material) already being bought, and by what: a live RFQ or a waiting material request (open orders are
    counted in the stock summary's ``on_order`` already)."""
    from mesiri.domains.procurement.requests import WAITING

    rows = (await conn.execute(text(
        """
        SELECT q.site_id, l.material_id, 'RFQ-' || lpad(q.number::text, 4, '0') AS what
          FROM rfq_lines l JOIN rfqs q ON q.id = l.rfq_id
         WHERE q.organization_id = :org AND q.status = 'open'
        UNION ALL
        SELECT r.site_id, l.material_id, 'REQ-' || lpad(r.number::text, 4, '0') AS what
          FROM material_request_lines l JOIN material_requests r ON r.id = l.request_id
         WHERE r.organization_id = :org AND r.status = :waiting
        """), {"org": organization_id, "waiting": WAITING})).all()
    out: dict[tuple[str, str], str] = {}
    for r in rows:
        out.setdefault((str(r.site_id), str(r.material_id)), r.what)
    return out


def below_rows(summary: list[dict[str, Any]], levels: dict[tuple[str, str], dict[str, Any]],
               buying: dict[tuple[str, str], str], materials: dict[str, dict[str, Any]],
               sites: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """The items each site holds less of than its minimum, worst first (least held for the minimum).

    ``summary``: today's stock summary rows (with ``below_min``); a minimum set for an item the site never held is
    below it with nothing held. ``covered_by``: the open order, RFQ or request already buying it (then no alert)."""
    seen = {(str(r["site_id"]), str(r["material_id"])): r for r in summary}
    out = []
    for key, level in levels.items():
        row = seen.get(key)
        site = sites.get(key[0])
        material = materials.get(key[1])
        if site is None or material is None:
            continue
        closing = Decimal(str(row["closing"])) if row else Decimal(0)
        on_order = Decimal(str(row.get("on_order") or 0)) if row else Decimal(0)
        minimum = Decimal(str(level["min_qty"]))
        if closing >= minimum:
            continue
        reorder = Decimal(str(level["reorder_qty"])) if level.get("reorder_qty") is not None else None
        by = None
        if on_order > 0 and closing + on_order >= minimum:
            by = "on order"
        elif key in buying:
            by = buying[key]
        out.append({
            "site_id": key[0], "site_name": site["name"], "project_id": str(site["project_id"]),
            "project_name": site["project_name"], "material_id": key[1], "material": material["name"],
            "unit": material["unit"], "unit_id": str(material["unit_id"]), "main_category": material.get("main_category"),
            "closing": num(closing), "on_order": num(on_order), "min_qty": num(minimum),
            "reorder_qty": num(reorder) if reorder is not None else None,
            "to_order": num(reorder_quantity(closing, on_order, minimum, reorder)),
            "short_by": num(minimum - closing), "covered_by": by,
            "days_left": row.get("days_left") if row else None,
        })
    out.sort(key=lambda r: (r["covered_by"] is not None, Decimal(r["closing"]) / Decimal(r["min_qty"])
                            if Decimal(r["min_qty"]) else Decimal(0), r["material"]))
    return out


def draft_link(base: str, site_id: str, make: str) -> str:
    """Materials > Stock with a draft request (``make=request``) or RFQ (``make=rfq``) for the site's items below
    minimum, holding the reorder quantities (the page reads ``GET /materials/stock-levels/below``)."""
    return f"{base}/materials?{urlencode({'view': 'stock', 'reorder': site_id, 'make': make})}"


def note(project_name: str, rows: list[dict[str, Any]], base: str) -> str | None:
    """The day's note for one project: per site, the items below minimum that nothing is buying yet."""
    rows = [r for r in rows if r["covered_by"] is None]
    if not rows:
        return None
    by_site: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_site.setdefault(r["site_id"], []).append(r)
    parts = []
    for site_id, items in by_site.items():
        n = len(items)
        head = f"⚠️ *{n} {'item' if n == 1 else 'items'} below minimum at {items[0]['site_name']}*"
        listed = [f"• {r['material']} {r['closing']} {r['unit']} (min {r['min_qty']}), order {r['to_order']}"
                  for r in items[:NOTE_ITEMS]]
        if n > NOTE_ITEMS:
            listed.append(f"• and {n - NOTE_ITEMS} more")
        parts.append("\n".join([head, *listed,
                                f"Make request: {draft_link(base, site_id, 'request')}",
                                f"Get quotes: {draft_link(base, site_id, 'rfq')}"]))
    return f"📦 *{project_name}*: stock below minimum\n\n" + "\n\n".join(parts)


async def below_minimum(conn: AsyncConnection, organization_id: uuid.UUID, today: datetime.date, *,
                        project_ids: set[uuid.UUID] | None = None,
                        site_id: uuid.UUID | None = None, live_only: bool = False) -> list[dict[str, Any]]:
    """Every item below its minimum today, within ``project_ids`` / ``site_id`` (None: the whole company).
    ``live_only``: leave out projects archived, closed or still at tender (the note's rule)."""
    from mesiri.domains.procurement.orders import on_order_by_site
    from mesiri.infrastructure.postgres.repositories.materials import PostgresMaterialReadRepository

    levels = await levels_by_site(conn, organization_id, [site_id] if site_id else None)
    if not levels:
        return []
    site_rows = (await conn.execute(text(
        "SELECT s.id, s.name, s.project_id, p.name AS project_name, "
        "(COALESCE(p.status, '') <> 'archived' AND COALESCE(p.stage, '') NOT IN ('tender', 'closed')) AS live "
        "FROM sites s JOIN projects p ON p.id = s.project_id WHERE s.organization_id = :org AND s.id = ANY(:ids)"),
        {"org": organization_id, "ids": list({uuid.UUID(k[0]) for k in levels})})).mappings().all()
    sites = {str(r["id"]): dict(r) for r in site_rows
             if (project_ids is None or r["project_id"] in project_ids) and (r["live"] or not live_only)}
    levels = {k: v for k, v in levels.items() if k[0] in sites}
    if not levels:
        return []
    material_rows = (await conn.execute(text(
        "SELECT m.id, m.name, u.code AS unit, u.id AS unit_id, COALESCE(parent.name, cat.name) AS main_category "
        "FROM materials_catalog m JOIN units_of_measure u ON u.id = m.default_unit_id "
        "LEFT JOIN material_categories cat ON cat.id = m.category_id "
        "LEFT JOIN material_categories parent ON parent.id = cat.parent_id "
        "WHERE m.organization_id = :org AND m.id = ANY(:ids)"),
        {"org": organization_id, "ids": list({uuid.UUID(k[1]) for k in levels})})).mappings().all()
    materials = {str(r["id"]): dict(r) for r in material_rows}
    summary = await PostgresMaterialReadRepository(conn).get_stock_summary(
        organization_id, date_from=today, date_to=today, project_ids={s["project_id"] for s in sites.values()},
        site_id=site_id, on_order=await on_order_by_site(conn, organization_id), levels=levels)
    return below_rows(summary, levels, await covered(conn, organization_id), materials, sites)


async def queue_reorder_reminders(conn: AsyncConnection, organization_id: uuid.UUID, today: datetime.date) -> int:
    """The day's below-minimum note to the people who run each project (one per project and person a day)."""
    from mesiri.domains.reports.period.send import dashboard_url
    from mesiri.domains.schedule.reminders import _people
    from mesiri.infrastructure.postgres.repositories.notifications import (
        PostgresNotificationRepository,
    )

    rows = await below_minimum(conn, organization_id, today, live_only=True)
    by_project: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_project.setdefault(r["project_id"], []).append(r)
    repo = PostgresNotificationRepository(conn)
    queued = 0
    for project_id, items in by_project.items():
        message = note(items[0]["project_name"], items, dashboard_url())
        if message is None:
            continue
        pid = uuid.UUID(project_id)
        for user_id in await _people(conn, organization_id, pid, MANAGER_ROLES):
            async with conn.begin_nested():
                claimed = await repo.claim(
                    organization_id=organization_id, rule_key=RULE, subject_id=f"{project_id}:{user_id}",
                    occurred_on=today, recipient_user_id=user_id, project_id=pid, site_id=None,
                    payload={"message": message, "hold_until_window": True, "hold_days": 1})
            queued += 1 if claimed else 0
    return queued
