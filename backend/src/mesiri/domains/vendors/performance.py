"""PRC-50: supplier performance -- a 0-5 score worked out from what Mesiri already records, never typed.

Five measures over the last ``WINDOW_DAYS`` (a supplier is the vendor record on the order / delivery / RFQ):

- **On time %**: goods received notes (``goods_receipts``) on or before their order's expected date. A GRN of an
  order with no expected date is not counted.
- **Complete %**: on finished orders (closed short, or everything came), how much of each line came (the order's own
  counted-delivery rule, ``orders._COUNTED``), averaged per line then per order: a closed-short order counts against.
- **Rejected %**: per GRN line, rejected / (accepted + rejected), averaged; lower is better.
- **Price index**: what the supplier charged against the company's average for the same items in the window, by the
  Rates rule (``rates.summarise``): 1.00 = average, 0.95 = 5% cheaper. Only items another supplier also delivered
  count; with none, no price index.
- **Quote response**: RFQs quoted / RFQs they were asked in (an RFQ still waiting for them is not counted). Shown,
  never in the score.

The score: each measure becomes 0-5 (``_part``), weighted by ``WEIGHTS`` (D-P2-5), over the measures that have data
(a missing one does not count as zero). Fewer than ``MIN_DELIVERIES`` GRNs in the window: no score ("Not enough orders
yet"). The trend is the same score per month (last ``TREND_MONTHS``) from that month's GRNs and finished orders (no
price part: a month is too few purchases). A manual rating (``vendor_ratings``) is shown beside the score, never in it.
"""

from __future__ import annotations

import datetime
import uuid
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.domains.procurement import rates as rate_store
from mesiri.domains.procurement.grn import ref as grn_ref
from mesiri.domains.procurement.orders import _COUNTED
from mesiri.domains.procurement.orders import ref as order_ref

#: D-P2-5. Quote response is shown, not weighted.
WEIGHTS: dict[str, int] = {"on_time": 35, "complete": 20, "quality": 25, "price": 20}
WINDOW_DAYS = 365
TREND_MONTHS = 6
#: Below this many GRNs in the window the score is not shown.
MIN_DELIVERIES = 3
#: Rejected share at which quality scores 0 (linear from 0% = 5).
REJECTED_AT_ZERO = Decimal("10")
#: Price index at or below which price scores 5, and at or above which it scores 0 (linear between).
PRICE_BEST, PRICE_WORST = Decimal("0.95"), Decimal("1.15")
PROBLEMS_SHOWN = 5

_ONE = Decimal("0.1")


def _round(value: Decimal | None, q: Decimal = _ONE) -> str | None:
    return None if value is None else str(value.quantize(q, rounding=ROUND_HALF_UP))


def _clamp(value: Decimal) -> Decimal:
    return max(Decimal(0), min(Decimal(5), value))


def _part(measure: str, value: Decimal) -> Decimal:
    """One measure as 0-5. ``value``: a percentage, or the price index."""
    if measure in ("on_time", "complete"):
        return _clamp(value / 20)
    if measure == "quality":  # value: rejected %
        return _clamp(5 - value * 5 / REJECTED_AT_ZERO)
    return _clamp((PRICE_WORST - value) * 5 / (PRICE_WORST - PRICE_BEST))


def score(values: dict[str, Decimal | None]) -> tuple[Decimal | None, dict[str, Decimal]]:
    """The weighted 0-5 score over the measures present, and each present measure's 0-5 part."""
    parts = {m: _part(m, v) for m, v in values.items() if m in WEIGHTS and v is not None}
    if not parts:
        return None, parts
    total = sum(WEIGHTS[m] for m in parts)
    return sum((parts[m] * WEIGHTS[m] for m in parts), Decimal(0)) / total, parts


def _mean(values: list[Decimal]) -> Decimal | None:
    return sum(values, Decimal(0)) / len(values) if values else None


def _grn_measures(grns: list[dict]) -> tuple[Decimal | None, Decimal | None, int]:
    dated = [g for g in grns if g["expected_date"] is not None]
    on_time = (Decimal(sum(1 for g in dated if g["received_on"] <= g["expected_date"])) * 100 / len(dated)
               if dated else None)
    shares = [Decimal(x["rejected"]) * 100 / (Decimal(x["accepted"]) + Decimal(x["rejected"]))
              for g in grns for x in g["lines"]]
    return on_time, _mean(shares), len(dated)


def _complete(orders: list[dict]) -> Decimal | None:
    return _mean([o["complete"] for o in orders])


def price_index(items: list[dict], vendor_id: str) -> tuple[Decimal | None, int]:
    """From ``rates.summarise`` items: Σ(their qty × their avg) / Σ(their qty × company avg), on items someone else
    also delivered; and how many items that is."""
    paid = fair = Decimal(0)
    n = 0
    for item in items:
        mine = next((v for v in item["vendors"] if v["vendor_id"] == vendor_id), None)
        if mine is None or len(item["vendors"]) < 2:
            continue
        q = Decimal(mine["quantity"])
        paid += q * Decimal(mine["avg_rate"])
        fair += q * Decimal(item["avg_rate"])
        n += 1
    return (paid / fair if fair > 0 else None), n


def _month(day: datetime.date) -> str:
    return f"{day.year:04d}-{day.month:02d}"


def _months(today: datetime.date) -> list[str]:
    y, m = today.year, today.month
    out = []
    for _ in range(TREND_MONTHS):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return list(reversed(out))


def problems(grns: list[dict], orders: list[dict]) -> list[dict]:
    """Late, rejected (from GRNs) and closed-short (orders): newest first, at most ``PROBLEMS_SHOWN``."""
    out = []
    for g in grns:
        base = {"date": g["received_on"].isoformat(), "grn_id": str(g["id"]), "grn_ref": grn_ref(g["number"]),
                "order_id": str(g["order_id"]), "order_ref": order_ref(g["order_number"])}
        if g["expected_date"] is not None and g["received_on"] > g["expected_date"]:
            days = (g["received_on"] - g["expected_date"]).days
            out.append({**base, "kind": "late", "what": f"{days} day{'s' if days != 1 else ''} late"})
        rejected = [x for x in g["lines"] if Decimal(x["rejected"]) > 0]
        if rejected:
            out.append({**base, "kind": "rejected", "what": "; ".join(
                f"{x['material']}: {Decimal(x['rejected']).normalize():f} {x['unit']} rejected"
                + (f" ({x['reason']})" if x["reason"] else "") for x in rejected)})
    for o in orders:
        if o["status"] == "closed" and o["complete"] < 100:
            out.append({"date": o["finished_on"].isoformat(), "kind": "short", "grn_id": None, "grn_ref": None,
                        "order_id": str(o["id"]), "order_ref": order_ref(o["number"]),
                        "what": f"Closed short, {_round(o['complete'], Decimal(1))}% came"
                        + (f": {o['note']}" if o["note"] else "")})
    out.sort(key=lambda p: p["date"], reverse=True)
    return out[:PROBLEMS_SHOWN]


def build(vendor_id: str, *, grns: list[dict], orders: list[dict], rate_items: list[dict], quotes: dict[str, int],
          rating: dict | None, today: datetime.date, with_problems: bool = True) -> dict[str, Any]:
    """One supplier's performance from its rows (see the module)."""
    on_time, rejected, dated = _grn_measures(grns)
    complete = _complete(orders)
    index, items = price_index(rate_items, vendor_id)
    values = {"on_time": on_time, "complete": complete, "quality": rejected, "price": index}
    total, parts = score(values)
    enough = len(grns) >= MIN_DELIVERIES
    asked = quotes.get("asked", 0)

    def measure(key: str, **extra) -> dict:
        part = parts.get(key)
        return {**extra, "score": _round(part), "weight": WEIGHTS[key]}

    trend = []
    if with_problems:
        by_month: dict[str, dict[str, list]] = defaultdict(lambda: {"grns": [], "orders": []})
        for g in grns:
            by_month[_month(g["received_on"])]["grns"].append(g)
        for o in orders:
            by_month[_month(o["finished_on"])]["orders"].append(o)
        for month in _months(today):
            got = by_month.get(month)
            if not got or not got["grns"]:
                trend.append({"month": month, "score": None})
                continue
            t, r, _ = _grn_measures(got["grns"])
            s, _ = score({"on_time": t, "quality": r, "complete": _complete(got["orders"])})
            trend.append({"month": month, "score": _round(s)})
    return {
        "vendor_id": vendor_id,
        "deliveries": len(grns),
        "orders_finished": len(orders),
        "enough": enough,
        "min_deliveries": MIN_DELIVERIES,
        "score": _round(total) if enough else None,
        "measures": {
            "on_time": measure("on_time", pct=_round(on_time), of=dated),
            "complete": measure("complete", pct=_round(complete), of=len(orders)),
            "rejected": measure("quality", pct=_round(rejected), of=sum(len(g["lines"]) for g in grns)),
            "price": measure("price", index=_round(index, Decimal("0.01")), items=items),
            "quote_response": {"pct": _round(Decimal(quotes.get("quoted", 0)) * 100 / asked) if asked else None,
                               "quoted": quotes.get("quoted", 0), "asked": asked},
        },
        "trend": trend,
        "problems": problems(grns, orders) if with_problems else [],
        "rating": rating,
    }


# -- reads ------------------------------------------------------------------------------------------------------------

def _scope(sql: str, params: dict, alias: str, project_ids: set[uuid.UUID] | None, vendor_id: uuid.UUID | None,
           vendor_col: str) -> str:
    if project_ids is not None:
        sql += f" AND {alias}.project_id = ANY(:projects)"
        params["projects"] = list(project_ids)
    if vendor_id is not None:
        sql += f" AND {vendor_col} = :vendor"
        params["vendor"] = vendor_id
    return sql


async def fetch_grns(conn: AsyncConnection, org: uuid.UUID, *, since: datetime.date,
                     project_ids: set[uuid.UUID] | None, vendor_id: uuid.UUID | None) -> dict[str, list[dict]]:
    """Per vendor, its GRNs in the window with their lines."""
    params: dict = {"org": org, "since": since}
    sql = _scope("""
        SELECT po.vendor_id, g.id, g.number, g.received_on, po.id AS order_id, po.number AS order_number,
               po.expected_date, gl.accepted, gl.rejected, gl.rejected_reason AS reason, m.name AS material,
               u.code AS unit
          FROM goods_receipts g
          JOIN purchase_orders po ON po.id = g.purchase_order_id
          JOIN goods_receipt_lines gl ON gl.goods_receipt_id = g.id
          JOIN purchase_order_lines l ON l.id = gl.purchase_order_line_id
          JOIN materials_catalog m ON m.id = l.material_id
          JOIN units_of_measure u ON u.id = l.unit_id
         WHERE g.organization_id = :org AND po.vendor_id IS NOT NULL AND g.received_on >= :since""",
                 params, "po", project_ids, vendor_id, "po.vendor_id")
    sql += " ORDER BY g.received_on, g.number"
    out: dict[str, dict[uuid.UUID, dict]] = defaultdict(dict)
    for r in (await conn.execute(text(sql), params)).mappings().all():
        g = out[str(r["vendor_id"])].setdefault(r["id"], {k: r[k] for k in (
            "id", "number", "received_on", "order_id", "order_number", "expected_date")} | {"lines": []})
        g["lines"].append({k: r[k] for k in ("accepted", "rejected", "reason", "material", "unit")})
    return {v: list(gs.values()) for v, gs in out.items()}


async def fetch_finished_orders(conn: AsyncConnection, org: uuid.UUID, *, since: datetime.date,
                                project_ids: set[uuid.UUID] | None, vendor_id: uuid.UUID | None) -> dict[str, list[dict]]:
    """Per vendor, its finished orders (closed short, or everything came) in the window, with how complete each is."""
    params: dict = {"org": org, "since": since}
    sql = _scope(f"""
        SELECT po.vendor_id, po.id, po.number, po.status, po.status_note, po.status_at, po.created_at,
               l.quantity,
               COALESCE((SELECT SUM(r.quantity) FROM material_receipts r WHERE r.purchase_order_line_id = l.id
                         AND {_COUNTED}), 0) AS received,
               (SELECT MAX(r.occurred_date) FROM material_receipts r WHERE r.purchase_order_line_id = l.id
                         AND {_COUNTED}) AS last_came
          FROM purchase_orders po JOIN purchase_order_lines l ON l.purchase_order_id = po.id
         WHERE po.organization_id = :org AND po.vendor_id IS NOT NULL AND po.status IN ('open', 'closed')
           AND po.created_at >= :since""", params, "po", project_ids, vendor_id, "po.vendor_id")
    orders: dict[uuid.UUID, dict] = {}
    for r in (await conn.execute(text(sql), params)).mappings().all():
        o = orders.setdefault(r["id"], {"vendor_id": str(r["vendor_id"]), "id": r["id"], "number": r["number"],
                                        "status": r["status"], "note": r["status_note"], "status_at": r["status_at"],
                                        "created_at": r["created_at"], "lines": [], "last_came": None})
        o["lines"].append(min(Decimal(r["received"]) / Decimal(r["quantity"]), Decimal(1)) * 100)
        if r["last_came"] and (o["last_came"] is None or r["last_came"] > o["last_came"]):
            o["last_came"] = r["last_came"]
    out: dict[str, list[dict]] = defaultdict(list)
    for o in orders.values():
        full = all(share >= 100 for share in o["lines"])
        if o["status"] == "open" and not full:
            continue  # still coming
        o["complete"] = _mean(o["lines"])
        o["finished_on"] = (o["status_at"].date() if o["status"] == "closed" and o["status_at"]
                            else o["last_came"] or o["created_at"].date())
        out[o["vendor_id"]].append(o)
    return out


async def fetch_quote_response(conn: AsyncConnection, org: uuid.UUID, *, since: datetime.date, today: datetime.date,
                               project_ids: set[uuid.UUID] | None, vendor_id: uuid.UUID | None) -> dict[str, dict]:
    """Per vendor, RFQs asked (not cancelled, not still waiting for them) and quoted."""
    params: dict = {"org": org, "since": since, "today": today}
    sql = _scope("""
        SELECT rv.vendor_id, COUNT(*) AS asked, COUNT(*) FILTER (WHERE rv.status = 'quoted') AS quoted
          FROM rfq_vendors rv JOIN rfqs q ON q.id = rv.rfq_id
         WHERE rv.organization_id = :org AND q.status <> 'cancelled' AND rv.created_at >= :since
           AND NOT (rv.status = 'invited' AND q.status = 'open' AND (q.due_date IS NULL OR q.due_date >= :today))""",
                 params, "q", project_ids, vendor_id, "rv.vendor_id")
    sql += " GROUP BY rv.vendor_id"
    return {str(r["vendor_id"]): {"asked": r["asked"], "quoted": r["quoted"]}
            for r in (await conn.execute(text(sql), params)).mappings().all()}


async def fetch_ratings(conn: AsyncConnection, org: uuid.UUID, *, vendor_id: uuid.UUID | None) -> dict[str, dict]:
    """Per vendor, the manual ratings given (skips not counted): average stars, how many, the newest note."""
    params: dict = {"org": org}
    sql = """
        SELECT vendor_id, stars, note, created_at FROM vendor_ratings
         WHERE organization_id = :org AND stars IS NOT NULL"""
    if vendor_id is not None:
        sql += " AND vendor_id = :vendor"
        params["vendor"] = vendor_id
    sql += " ORDER BY created_at"
    by: dict[str, list] = defaultdict(list)
    for r in (await conn.execute(text(sql), params)).mappings().all():
        by[str(r["vendor_id"])].append(r)
    out = {}
    for v, rows in by.items():
        noted = [r for r in rows if r["note"]]
        out[v] = {"stars": _round(Decimal(sum(r["stars"] for r in rows)) / len(rows)), "count": len(rows),
                  "last_note": noted[-1]["note"] if noted else None}
    return out


async def performance(conn: AsyncConnection, org: uuid.UUID, *, today: datetime.date,
                      project_ids: set[uuid.UUID] | None, vendor_id: uuid.UUID | None,
                      vendor_ids: list[str], with_problems: bool) -> list[dict]:
    """Performance for ``vendor_ids`` (all reads grouped: one query each, whatever the number of suppliers)."""
    since = today - datetime.timedelta(days=WINDOW_DAYS - 1)
    grns = await fetch_grns(conn, org, since=since, project_ids=project_ids, vendor_id=vendor_id)
    orders = await fetch_finished_orders(conn, org, since=since, project_ids=project_ids, vendor_id=vendor_id)
    quotes = await fetch_quote_response(conn, org, since=since, today=today, project_ids=project_ids,
                                        vendor_id=vendor_id)
    ratings = await fetch_ratings(conn, org, vendor_id=vendor_id)
    purchases = await rate_store.fetch_purchases(conn, org, project_ids=project_ids, date_from=since, date_to=today)
    items = rate_store.summarise(purchases, {})
    return [build(v, grns=grns.get(v, []), orders=orders.get(v, []), rate_items=items, quotes=quotes.get(v, {}),
                  rating=ratings.get(v), today=today, with_problems=with_problems) for v in vendor_ids]
