"""CC-01 (approved in session by the owner, 7 Nov 2026): what a project really cost in a period -- not only the
expenses typed in, but the materials delivered and the labour on site, each counted once.

- **Expenses**: confirmed expenses (``expenses``), however paid (PRC-18).
- **Materials**: deliveries with a price (``material_receipts``, the same set as the Rates page: received, not taken
  back, not a move between sites) that are not *billed* (``rates.BILLED_SQL``): a bill that made an expense is in
  Expenses and is not counted again. A bill recorded without a price, or taken back, leaves its deliveries counted
  here (8 Nov 2026: before, any ``invoice_id`` hid the delivery, so those cost nothing anywhere). Deliveries without a price are counted, not valued.
- **Labour**: attendance valued at the wage on each line (``PostgresWorkforceReadRepository.aggregate_attendance``,
  the Labour module's own rule: corrected and voided reports out, lines without a wage give man-days but no cost).

Known overlap, said on the page: a delivery priced on site *and* paid later by an expense typed without the bill
counts twice until someone says which bill it was on: the supplier ledger's "On this bill" (CC-09) links them, and
from then on the delivery is billed and counted once.
"""

from __future__ import annotations

import datetime
import uuid
from collections import defaultdict
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.domains.procurement import rates as purchases
from mesiri.infrastructure.postgres.repositories.workforce import PostgresWorkforceReadRepository

_C = Decimal("0.01")


def _m(v: Decimal) -> str:
    return str(Decimal(v).quantize(_C))


async def project_costs(
    conn: AsyncConnection,
    org: uuid.UUID,
    *,
    project_ids: set[uuid.UUID] | None,
    site_id: uuid.UUID | None,
    date_from: datetime.date,
    date_to: datetime.date,
    visible,
) -> dict:
    """``visible(project_id, site_id) -> bool`` applies the caller's site scope."""
    where, params = ["e.organization_id = :org", "e.workflow_status = 'confirmed'",
                     "e.occurred_date BETWEEN :f AND :t"], {"org": org, "f": date_from, "t": date_to}
    if project_ids is not None:
        where.append("e.project_id = ANY(:projects)")
        params["projects"] = list(project_ids)
    if site_id is not None:
        where.append("e.site_id = :site")
        params["site"] = site_id
    rows = (await conn.execute(text(
        "SELECT e.project_id, e.site_id, COUNT(*) AS n, SUM(e.amount) AS amount FROM expenses e "
        f"WHERE {' AND '.join(where)} GROUP BY e.project_id, e.site_id"), params)).mappings().all()  # noqa: S608

    sites: dict[tuple, dict] = defaultdict(lambda: {"expenses": Decimal(0), "materials": Decimal(0), "labour": Decimal(0),
                                                    "expense_count": 0, "deliveries": 0})
    for r in rows:
        if r["site_id"] is not None and not visible(r["project_id"], r["site_id"]):
            continue
        s = sites[(r["project_id"], r["site_id"])]
        s["expenses"] += Decimal(r["amount"] or 0)
        s["expense_count"] += int(r["n"])

    # Materials: priced deliveries without a bill (a bill made an expense already), and how many had no price.
    delivered = await purchases.fetch_purchases(conn, org, project_ids=project_ids, date_from=date_from, date_to=date_to)
    for r in delivered:
        if r.get("billed") or (site_id is not None and r.get("site_id") != site_id):
            continue
        if r.get("site_id") is not None and not visible(r["project_id"], r["site_id"]):
            continue
        s = sites[(r["project_id"], r.get("site_id"))]
        amount = Decimal(r["total_cost"]) if r.get("total_cost") is not None else Decimal(r["unit_cost"]) * Decimal(r["quantity"])
        s["materials"] += amount
        s["deliveries"] += 1
    unpriced = await _unpriced_deliveries(conn, org, project_ids, site_id, date_from, date_to)

    # Labour: per site in scope (the Labour module's aggregate; it has no per-site grouping, so one call per site).
    site_rows = (await conn.execute(text(
        "SELECT s.id, s.project_id FROM sites s WHERE s.organization_id = :org"
        + (" AND s.project_id = ANY(:projects)" if project_ids is not None else "")
        + (" AND s.id = :site" if site_id is not None else "")),
        {"org": org, **({"projects": list(project_ids)} if project_ids is not None else {}),
         **({"site": site_id} if site_id is not None else {})})).mappings().all()
    repo = PostgresWorkforceReadRepository(conn)
    man_days = priced_days = Decimal(0)
    for srow in site_rows:
        if not visible(srow["project_id"], srow["id"]):
            continue
        agg = await repo.aggregate_attendance(organization_id=org, group_by="date", project_ids={srow["project_id"]},
                                              site_id=srow["id"], date_from=date_from, date_to=date_to)
        cost = sum((Decimal(str(a["total_cost"] or 0)) for a in agg), Decimal(0))
        man_days += sum((Decimal(str(a["man_days"] or 0)) for a in agg), Decimal(0))
        priced_days += sum((Decimal(str(a["priced_man_days"] or 0)) for a in agg), Decimal(0))
        if cost:
            sites[(srow["project_id"], srow["id"])]["labour"] += cost

    names = await _names(conn, org, {k[0] for k in sites}, {k[1] for k in sites if k[1]})
    by_site = sorted(
        ({"project_id": str(p), "project_name": names["projects"].get(p, ""), "site_id": str(s) if s else None,
          "site_name": names["sites"].get(s) if s else None, "expenses": _m(v["expenses"]), "materials": _m(v["materials"]),
          "labour": _m(v["labour"]), "total": _m(v["expenses"] + v["materials"] + v["labour"])}
         for (p, s), v in sites.items()),
        key=lambda x: -Decimal(x["total"]),
    )
    total = {k: sum((v[k] for v in sites.values()), Decimal(0)) for k in ("expenses", "materials", "labour")}
    return {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "expenses": {"amount": _m(total["expenses"]), "count": sum(v["expense_count"] for v in sites.values())},
        "materials": {"amount": _m(total["materials"]), "deliveries": sum(v["deliveries"] for v in sites.values()),
                      "unpriced": unpriced},
        "labour": {"amount": _m(total["labour"]), "man_days": str(man_days.normalize()),
                   "priced_man_days": str(priced_days.normalize())},
        "total": _m(total["expenses"] + total["materials"] + total["labour"]),
        "by_site": by_site,
    }


async def _unpriced_deliveries(conn, org, project_ids, site_id, date_from, date_to) -> int:
    sql = ("SELECT COUNT(*) FROM material_receipts r WHERE r.organization_id = :org AND r.unit_cost IS NULL "
           "AND r.total_cost IS NULL AND r.movement_reason = 'RECEIVED' AND r.transfer_id IS NULL "
           "AND r.reverses_movement_id IS NULL AND NOT " + purchases.BILLED_SQL + " AND r.occurred_date BETWEEN :f AND :t "
           "AND NOT EXISTS (SELECT 1 FROM material_usage x WHERE x.reverses_movement_id = r.id)")
    params: dict = {"org": org, "f": date_from, "t": date_to}
    if project_ids is not None:
        sql += " AND r.project_id = ANY(:projects)"
        params["projects"] = list(project_ids)
    if site_id is not None:
        sql += " AND r.site_id = :site"
        params["site"] = site_id
    return int((await conn.execute(text(sql), params)).scalar() or 0)


async def _names(conn, org, project_ids: set, site_ids: set) -> dict:
    out: dict = {"projects": {}, "sites": {}}
    for kind, ids in (("projects", project_ids), ("sites", site_ids)):
        ids = {i for i in ids if i}
        if ids:
            rows = await conn.execute(text(f"SELECT id, name FROM {kind} WHERE organization_id = :org AND id = ANY(:ids)"),  # noqa: S608
                                      {"org": org, "ids": list(ids)})
            out[kind] = {r.id: r.name for r in rows}
    return out
