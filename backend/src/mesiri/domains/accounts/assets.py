"""ACC-16: the fixed asset register. Machines, shuttering, vehicles, computers, furniture and buildings the company
owns, what each cost, what it is worth now and its depreciation year by year (``depreciation.py``); the books follow
through the posting sweep (``posting.asset_entries``).

**Where the cost comes from.** An asset bought in Mesiri's time is entered from its bill (an expense): its cost moves
from the bill's category to the asset (the bill, its supplier and its payment are not touched). An asset owned
before the books start comes in at its value at the start of that financial year, against "Opening balance
difference" (as other opening balances do).

**Selling or scrapping.** The sale date and what it fetched (nil for scrap): the book value goes out, the money to
receive and the loss or gain go to their ledgers. The money itself comes in through Finance as usual.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.domains.accounts import chart, depreciation, periods

_ZERO = Decimal(0)
FIELDS = ("name", "asset_class", "cost", "acquired_on", "put_to_use_on", "method", "rate", "useful_life_years",
          "salvage_value", "opening_depreciation", "books_from", "expense_id", "project_id", "site_id", "notes")


class AssetError(ValueError):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


async def default_method(conn: AsyncConnection, org: uuid.UUID) -> str:
    return (await conn.execute(text("SELECT depreciation_method FROM accounting_settings WHERE organization_id = :org"),
                               {"org": org})).scalar() or "wdv"


async def _check(conn: AsyncConnection, org: uuid.UUID, body: dict[str, Any], asset_id: uuid.UUID | None) -> dict[str, Any]:
    if body["asset_class"] not in chart.ASSET_CLASSES:
        raise AssetError(f"asset_class is one of {', '.join(chart.ASSET_CLASSES)}.")
    defaults = chart.ASSET_CLASSES[body["asset_class"]]
    body["method"] = body.get("method") or await default_method(conn, org)
    if body["method"] == "wdv":
        body["rate"] = body.get("rate") or defaults["rate"]
        body["useful_life_years"] = None
    else:
        body["useful_life_years"] = body.get("useful_life_years") or defaults["life"]
        body["rate"] = None
    if body.get("put_to_use_on") and body["put_to_use_on"] < body["acquired_on"]:
        raise AssetError("It cannot be put to use before it was bought.")
    if Decimal(str(body.get("opening_depreciation") or 0)) >= Decimal(str(body["cost"])):
        raise AssetError("What was written off before cannot be the whole cost.")
    if body.get("expense_id"):
        e = (await conn.execute(text(
            "SELECT e.occurred_date, e.workflow_status, (SELECT a.id FROM fixed_assets a WHERE a.expense_id = e.id "
            " AND a.id IS DISTINCT FROM CAST(:me AS uuid)) AS taken FROM expenses e WHERE e.id = :e AND e.organization_id = :org"),
            {"e": body["expense_id"], "org": org, "me": asset_id})).mappings().first()
        if e is None:
            raise AssetError("That bill is not this company's.", 404)
        if e["workflow_status"] != "confirmed":
            raise AssetError("That bill is not confirmed yet: confirm it in Expenses first.")
        if e["taken"]:
            raise AssetError("That bill is already an asset in the register.", 409)
        body["books_from"] = None
    else:
        body["books_from"] = body.get("books_from") or body["acquired_on"]
    for key, table in (("project_id", "projects"), ("site_id", "sites")):
        if body.get(key) and not (await conn.execute(text(
                f"SELECT 1 FROM {table} WHERE id = :i AND organization_id = :org"),  # noqa: S608 (fixed names)
                {"i": body[key], "org": org})).first():
            raise AssetError(f"That {key[:-3]} is not this company's.", 404)
    return body


async def create(conn: AsyncConnection, org: uuid.UUID, user_id: uuid.UUID, body: dict[str, Any]) -> uuid.UUID:
    body = await _check(conn, org, dict(body), None)
    cols = ", ".join(FIELDS)
    vals = ", ".join(f":{f}" for f in FIELDS)
    return (await conn.execute(text(
        f"INSERT INTO fixed_assets (organization_id, created_by, {cols}) VALUES (:org, :u, {vals}) RETURNING id"),  # noqa: S608
        {"org": org, "u": user_id, **{f: body.get(f) for f in FIELDS}})).scalar_one()


async def _get(conn: AsyncConnection, org: uuid.UUID, asset_id: uuid.UUID) -> dict[str, Any]:
    row = (await conn.execute(text("SELECT * FROM fixed_assets WHERE id = :a AND organization_id = :org"),
                              {"a": asset_id, "org": org})).mappings().first()
    if row is None:
        raise AssetError("Asset not found.", 404)
    return dict(row)


async def update(conn: AsyncConnection, org: uuid.UUID, asset_id: uuid.UUID, body: dict[str, Any]) -> None:
    await _get(conn, org, asset_id)
    body = await _check(conn, org, dict(body), asset_id)
    sets = ", ".join(f"{f} = :{f}" for f in FIELDS)
    await conn.execute(text(f"UPDATE fixed_assets SET {sets}, updated_at = now() WHERE id = :id"),  # noqa: S608
                       {"id": asset_id, **{f: body.get(f) for f in FIELDS}})


async def dispose(conn: AsyncConnection, org: uuid.UUID, asset_id: uuid.UUID, day: datetime.date | None,
                  value: Decimal | None) -> None:
    """Sold or scrapped on ``day`` for ``value`` (nil: scrapped); ``day`` None takes the sale back."""
    a = await _get(conn, org, asset_id)
    if day is not None and day < a["acquired_on"]:
        raise AssetError("It cannot be sold before it was bought.")
    await conn.execute(text(
        "UPDATE fixed_assets SET disposed_on = :d, disposal_value = :v, updated_at = now() WHERE id = :id"),
        {"d": day, "v": (value or _ZERO) if day is not None else None, "id": asset_id})


async def delete(conn: AsyncConnection, org: uuid.UUID, asset_id: uuid.UUID) -> None:
    """Out of the register (and so out of the books: the sweep takes its entries back; after close, on the first open
    day)."""
    await _get(conn, org, asset_id)
    await conn.execute(text("DELETE FROM fixed_assets WHERE id = :id"), {"id": asset_id})


async def register(conn: AsyncConnection, org: uuid.UUID, today: datetime.date) -> dict[str, Any]:
    """Every asset with its value today, this year's depreciation (posted at the year's end) and its schedule."""
    rows = [dict(r) for r in (await conn.execute(text(
        "SELECT a.*, p.name AS project, s.name AS site, e.expense_number, e.amount AS expense_amount, "
        "v.name AS supplier FROM fixed_assets a LEFT JOIN projects p ON p.id = a.project_id "
        "LEFT JOIN sites s ON s.id = a.site_id LEFT JOIN expenses e ON e.id = a.expense_id "
        "LEFT JOIN vendors v ON v.id = e.vendor_id WHERE a.organization_id = :org ORDER BY a.acquired_on, a.name"),
        {"org": org})).mappings()]
    fy = periods.fy_start(today)
    out, by_class = [], {}
    for a in rows:
        years = depreciation.schedule(a, today)
        now = next((y for y in years if y["starts_on"] == fy), None)
        value = depreciation.value_on(a, today, today)
        info = chart.ASSET_CLASSES.get(a["asset_class"], chart.ASSET_CLASSES["plant"])
        row = {**a, "class_label": info["label"], "value": value, "years": years,
               "this_year": now["depreciation"] if now else _ZERO,
               "written_off": Decimal(a["cost"]) - value if not a["disposed_on"] else None,
               "status": "sold" if a["disposed_on"] else "in_use"}
        out.append(row)
        c = by_class.setdefault(a["asset_class"], {"asset_class": a["asset_class"], "label": info["label"],
                                                   "count": 0, "cost": _ZERO, "value": _ZERO, "this_year": _ZERO})
        if not a["disposed_on"]:
            c["count"] += 1
            c["cost"] += Decimal(a["cost"])
            c["value"] += value
            c["this_year"] += row["this_year"]
    live = [r for r in out if not r["disposed_on"]]
    return {"today": today, "financial_year": periods.fy_label(today), "assets": out,
            "classes": sorted(by_class.values(), key=lambda c: -c["value"]),
            "totals": {"count": len(live), "cost": sum((Decimal(r["cost"]) for r in live), _ZERO),
                       "value": sum((r["value"] for r in live), _ZERO),
                       "this_year": sum((r["this_year"] for r in live), _ZERO)},
            "method": await default_method(conn, org),
            "class_defaults": [{"asset_class": k, **v} for k, v in chart.ASSET_CLASSES.items()]}


async def candidates(conn: AsyncConnection, org: uuid.UUID) -> list[dict[str, Any]]:
    """Confirmed bills that look like a purchase of an asset (big, not already in the register), newest first."""
    from mesiri.domains.finance.costs import CLAIMABLE_GST_SQL

    return [dict(r) for r in (await conn.execute(text(
        f"SELECT e.id, e.expense_number, e.occurred_date, e.amount, e.amount - ({CLAIMABLE_GST_SQL}) AS cost, "
        "e.description, v.name AS supplier, c.name AS category, p.name AS project, e.project_id, e.site_id "
        "FROM expenses e LEFT JOIN vendors v ON v.id = e.vendor_id LEFT JOIN expense_categories c ON c.id = e.category_id "
        "LEFT JOIN projects p ON p.id = e.project_id WHERE e.organization_id = :org AND e.workflow_status = 'confirmed' "
        "AND e.amount >= 10000 AND NOT EXISTS (SELECT 1 FROM fixed_assets a WHERE a.expense_id = e.id) "
        "ORDER BY e.occurred_date DESC LIMIT 100"), {"org": org})).mappings()]
