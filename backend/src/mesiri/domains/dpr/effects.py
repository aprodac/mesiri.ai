"""What one saved entry changed, for Live's ripple (WEB-82; plan: docs/plans/live-value-plan.md).

A delivery, a usage or an attendance report is not the value; what it changed is: the stock, the order still to
come, the rate against last time, what the supplier is owed, the wages due. ``cards`` gives those effects for one
record, in the order Live plays them: the obvious one first, the surprise in the middle, the report last.

Two halves, on purpose:

* **Building is pure** (``RULES``: one function per kind of entry, facts in, cards out). A new effect is a few lines
  in one of them; a new kind of entry is one entry in ``RULES``.
* **Reading** (``read``) calls the read each module's own page already uses (the stock summary, the order's
  received total, the Rates purchases, the supplier ledger, the Full cost read, the wage sheet's rows, the advance
  balances). No figure is worked out a second way here, and nothing is written.

A card: ``key``, ``title``, ``tag`` (money / time / caught / proof), ``question`` (the owner's question it answers,
1-6, plan section 3), ``before`` / ``after`` (numbers as strings; ``before`` only when it is known), ``unit``,
``rupees`` (the number is money), ``sentence`` (what changed, in plain words), ``say`` (the presenter's line),
``opens`` (the page that holds it).

Money cards are built only for the roles that see the company's spending (SEC-01; decision 4 of the plan, Ilan,
12 Nov 2026): everyone else gets the same chain without them.
"""

from __future__ import annotations

import datetime
import uuid
from collections.abc import Callable
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.application.dpr import fact_review

#: The owner's questions (plan section 3), by number.
MONEY_GOING, LEAKING, WORK_MOVING, OWE, STOPS_WORK, PROOF = 1, 2, 3, 4, 5, 6

#: A rate within this much of the last one is "the same rate" (the Rates page's own steadiness rule).
SAME_RATE_PCT = Decimal("2")

#: What the presenter says for each card, in plain words. One line per card key.
SAY: dict[str, str] = {
    "stock": "Nobody opened a register. The stock is already right.",
    "order": "The office knows what is still to come without calling the supplier.",
    "rate": "Every delivery is checked against the last rate and the order, by itself.",
    "supplier": "What you owe each supplier is always up to date, before the bill even comes.",
    "week_cost": "You know what the site cost this week, today, not at the month's end.",
    "low": "You hear that it is running out before the site stops.",
    "use_cost": "Every bag used is money going into the work, and you see it.",
    "on_site": "Who was on site, from one message.",
    "wages": "The day's wages are known the moment attendance is sent.",
    "week_wages": "No Saturday counting from the register: the week's wages are already added up.",
    "advances": "Advances are remembered and come off the wages by themselves.",
    "report": "And it is already in tonight's report. Nobody wrote it.",
}

Card = dict[str, Any]


def qty(value: Any) -> str:
    """A quantity as a short exact string: 50, 2.5 (never 5E+1)."""
    return format(Decimal(str(value)).normalize(), "f")


def rupees(value: Any) -> str:
    """Whole rupees with Indian grouping: 1245000 -> "₹12,45,000"."""
    n = int(Decimal(str(value)).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    sign, digits = ("-" if n < 0 else ""), str(abs(n))
    head, tail = digits[:-3], digits[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return f"{sign}₹{','.join([*groups, tail])}"


def _card(key: str, title: str, tag: str, question: int, sentence: str, *, before: Any = None, after: Any = None,
          unit: str | None = None, money: bool = False, opens: str | None = None) -> Card:
    return {
        "key": key, "title": title, "tag": tag, "question": question,
        "before": qty(before) if before is not None else None,
        "after": qty(after) if after is not None else None,
        "unit": unit, "rupees": money, "sentence": sentence, "say": SAY[key], "opens": opens,
    }


def one(unit: str | None) -> str:
    """One of a unit, for "per ...": bags -> bag, loads -> load. Short codes (nos, kg, cft) stay as they are."""
    u = (unit or "").strip() or "unit"
    return u[:-1] if len(u) > 3 and u.endswith("s") and not u.endswith("ss") else u


def _days(n: int) -> str:
    return "1 day" if n == 1 else f"{n} days"


def _stock_card(f: dict[str, Any], change: Decimal) -> Card | None:
    """Stock before -> after. ``before`` only when this entry is the newest movement of the material at the site:
    otherwise "now" already holds later entries, and a before worked out from it would be wrong."""
    stock = f.get("stock")
    if not stock:
        return None
    closing, unit = Decimal(str(stock["closing"])), f["unit"] or ""
    sentence = f"{f['site_name']} now holds {qty(closing)} {unit} of {f['material']}.".replace("  ", " ")
    days = stock.get("days_left")
    if days is not None and closing > 0:
        sentence += f" At the last week's use that lasts {_days(int(days))}."
    return _card("stock", "Stock", "time", STOPS_WORK, sentence,
                 before=closing - change if stock.get("latest") else None, after=closing, unit=unit, opens="/materials")


def _low_card(f: dict[str, Any]) -> Card | None:
    """Below the minimum the office set, or about to run out at the last week's use."""
    stock = f.get("stock")
    if not stock:
        return None
    closing, unit = Decimal(str(stock["closing"])), f["unit"] or ""
    minimum = stock.get("min_qty")
    on_order = Decimal(str(stock.get("on_order") or 0))
    coming = f" {qty(on_order)} {unit} is on order." if on_order > 0 else ""
    if minimum is not None and closing < Decimal(str(minimum)):
        to_order = stock.get("to_order")
        ask = f" Order {qty(to_order)} {unit}." if to_order is not None and Decimal(str(to_order)) > 0 and not coming else ""
        return _card("low", "Running low", "caught", STOPS_WORK,
                     f"{f['material']} is below the minimum of {qty(minimum)} {unit}.{coming}{ask}",
                     after=closing, unit=unit, opens="/materials")
    if stock.get("running_low") and stock.get("days_left") is not None:
        return _card("low", "Running low", "caught", STOPS_WORK,
                     f"At this rate {f['material']} runs out in {_days(int(stock['days_left']))}.{coming}",
                     after=closing, unit=unit, opens="/materials")
    return None


def _report_card(f: dict[str, Any]) -> Card:
    at = f.get("report_time")
    when = f", which goes out at {at}" if at else ""
    return _card("report", "Tonight's report", "proof", PROOF,
                 f"It is already in today's report for {f['site_name']}{when}.", opens="/reports")


def receipt_cards(f: dict[str, Any], sees_money: bool) -> list[Card]:
    """Material came: stock -> the order -> the rate -> the supplier -> the week's cost -> the report."""
    unit, quantity = f["unit"] or "", Decimal(str(f["quantity"]))
    cards: list[Card | None] = [_stock_card(f, quantity)]

    order = f.get("order")
    if order:
        pending = Decimal(str(order["pending"]))
        tail = f"{qty(pending)} {unit} still to come." if pending > 0 else "The order is complete."
        cards.append(_card("order", f"Order {order['ref']}", "time", STOPS_WORK,
                           f"{qty(order['received'])} of {qty(order['ordered'])} {unit} delivered. {tail}",
                           before=Decimal(str(order["received"])) - quantity, after=order["received"], unit=unit,
                           opens="/procurement/orders"))

    rate = f.get("rate") if sees_money else None
    if rate:
        cards.append(_rate_card(f, rate, quantity))

    supplier = f.get("supplier") if sees_money else None
    if supplier:
        amount = f.get("amount")
        mine = f" {rupees(amount)} of it is this delivery, not billed yet." if amount is not None and supplier.get("unbilled_here") else ""
        cards.append(_card("supplier", supplier["name"], "money", OWE,
                           f"You now owe {supplier['name']} {rupees(supplier['balance'])}.{mine}",
                           before=(Decimal(str(supplier["balance"])) - Decimal(str(amount))
                                   if amount is not None and supplier.get("unbilled_here") else None),
                           after=supplier["balance"], money=True, opens="/finance/vendors"))

    week = f.get("week") if sees_money else None
    if week and Decimal(str(week["total"])) > 0:
        cards.append(_card("week_cost", "This week's cost", "money", MONEY_GOING,
                           f"{f['site_name']} has cost {rupees(week['total'])} in the last 7 days: materials "
                           f"{rupees(week['materials'])}, labour {rupees(week['labour'])}.",
                           after=week["total"], money=True, opens="/cost"))
    cards.append(_report_card(f))
    return [c for c in cards if c]


def _rate_card(f: dict[str, Any], rate: dict[str, Any], quantity: Decimal) -> Card:
    """The delivery's rate against its order's, else against the last time the material was bought."""
    unit, now = one(f["unit"]), Decimal(str(rate["rate"]))
    base = f"{rupees(now)} per {unit}."
    ordered, previous = rate.get("ordered_rate"), rate.get("previous")
    if ordered is not None and rate.get("differs_from_order"):
        diff = Decimal(str(rate["entered"])) - Decimal(str(ordered))
        word = "more" if diff > 0 else "less"
        return _card("rate", "Rate check", "caught" if diff > 0 else "money", LEAKING if diff > 0 else MONEY_GOING,
                     f"{base} The order said {rupees(ordered)}: {rupees(abs(diff))} {word} per {unit}, "
                     f"{rupees(abs(diff) * quantity)} on this delivery.",
                     before=ordered, after=rate["entered"], money=True, opens="/procurement/rates")
    if previous is None:
        return _card("rate", "Rate", "money", MONEY_GOING, f"{base} The first rate recorded for {f['material']}.",
                     after=now, money=True, opens="/procurement/rates")
    old = Decimal(str(previous["rate"]))
    diff = now - old
    last = f"Last time ({previous['vendor']}, {previous['date']:%-d %b}) it was {rupees(old)}"
    if old > 0 and abs(diff) / old * 100 <= SAME_RATE_PCT:
        return _card("rate", "Rate check", "money", MONEY_GOING, f"{base} The same rate as last time.",
                     before=old, after=now, money=True, opens="/procurement/rates")
    if diff > 0:
        return _card("rate", "Rate check", "caught", LEAKING,
                     f"{base} {last}: {rupees(diff * quantity)} more on this delivery.",
                     before=old, after=now, money=True, opens="/procurement/rates")
    return _card("rate", "Rate check", "money", MONEY_GOING,
                 f"{base} {last}: {rupees(-diff * quantity)} saved on this delivery.",
                 before=old, after=now, money=True, opens="/procurement/rates")


def usage_cards(f: dict[str, Any], sees_money: bool) -> list[Card]:
    """Material used: stock -> running low -> what it cost -> the report."""
    quantity = Decimal(str(f["quantity"]))
    cards: list[Card | None] = [_stock_card(f, -quantity), _low_card(f)]
    last_rate = (f.get("stock") or {}).get("last_rate") if sees_money else None
    if last_rate is not None and Decimal(str(last_rate)) > 0:
        cost = quantity * Decimal(str(last_rate))
        cards.append(_card("use_cost", "Into the work", "money", MONEY_GOING,
                           f"That is about {rupees(cost)} of {f['material']} into the work, at the last rate paid "
                           f"({rupees(last_rate)} per {one(f['unit'])}).",
                           after=cost, money=True, opens="/cost"))
    cards.append(_report_card(f))
    return [c for c in cards if c]


def attendance_cards(f: dict[str, Any], sees_money: bool) -> list[Card]:
    """Attendance: who is on site -> today's wages -> the pay week -> advances -> the report."""
    heads = Decimal(str(f["headcount"]))
    trades = ", ".join(f"{qty(n)} {trade}" for trade, n in f.get("trades") or [])
    people = "1 person" if heads == 1 else f"{qty(heads)} people"
    cards: list[Card | None] = [_card(
        "on_site", "On site", "proof", WORK_MOVING,
        f"{people} at {f['site_name']} today" + (f": {trades}." if trades else "."),
        after=heads, unit="workers", opens="/labour")]
    wages = f.get("wages") if sees_money else None
    if wages:
        today = Decimal(str(wages["today"]))
        unpriced = Decimal(str(wages.get("unpriced_man_days") or 0))
        gap = f" {qty(unpriced)} man-days have no wage set yet." if unpriced > 0 else ""
        if today > 0 or unpriced > 0:
            cards.append(_card("wages", "Today's wages", "money", MONEY_GOING,
                               f"{rupees(today)} in wages today.{gap}", after=today, money=True, opens="/labour/wages"))
        week = wages.get("week")
        if week is not None and Decimal(str(week)) > 0:
            counted = wages.get("counted")
            cards.append(_card("week_wages", "This pay week", "money", OWE,
                               f"{rupees(week)} in wages so far this pay week "
                               f"({wages['week_from']:%-d %b} to {wages['week_to']:%-d %b}).",
                               before=Decimal(str(week)) - today if counted else None, after=week, money=True,
                               opens="/labour/wages"))
        advances = Decimal(str(wages.get("advances") or 0))
        if advances > 0:
            cards.append(_card("advances", "Advances", "money", OWE,
                               f"{rupees(advances)} in advances is still to come off wages on this project.",
                               after=advances, money=True, opens="/labour/advances"))
    cards.append(_report_card(f))
    return [c for c in cards if c]


#: Kind of entry -> (the line over its ripple, its cards). A kind not here has no ripple yet (WEB-86 adds work
#: done, issues, bills and machine logs).
RULES: dict[str, tuple[str, Callable[[dict[str, Any], bool], list[Card]]]] = {
    fact_review.MATERIAL_RECEIPT: ("Material came", receipt_cards),
    fact_review.MATERIAL_USAGE: ("Material used", usage_cards),
    fact_review.LABOUR_REPORT: ("Attendance", attendance_cards),
}


def cards(kind: str, facts: dict[str, Any] | None, sees_money: bool) -> dict[str, Any]:
    """The ripple for one entry. ``facts`` None: the entry was taken back (or is not one that changes anything)."""
    title, build = RULES[kind]
    out = build(facts, sees_money) if facts else []
    return {"kind": kind, "title": title, "what": facts.get("what") if facts else None, "cards": out, "count": len(out)}


# ----------------------------------------------------------------------------------------------------------------
# Reading: each figure from the read its own module uses.
# ----------------------------------------------------------------------------------------------------------------

async def _report_time(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID) -> str | None:
    row = (await conn.execute(text(
        "SELECT dpr_send_deadline, auto_generate_dpr FROM projects WHERE id = :p AND organization_id = :org"),
        {"p": project_id, "org": org})).first()
    if row is None or not row.auto_generate_dpr or row.dpr_send_deadline is None:
        return None
    return f"{row.dpr_send_deadline:%-I:%M %p}".lower()


async def _stock(conn: AsyncConnection, org: uuid.UUID, row: Any, today: datetime.date, sees_money: bool) -> dict | None:
    """The site's stock of the material now (the Stock page's own summary), and whether this entry is its newest
    movement there."""
    from mesiri.domains.materials.stock_levels import levels_by_site
    from mesiri.domains.materials.stock_summary import reorder_quantity
    from mesiri.domains.procurement.orders import on_order_by_site
    from mesiri.infrastructure.postgres.repositories.materials import PostgresMaterialReadRepository

    found = await PostgresMaterialReadRepository(conn).get_stock_summary(
        org, date_from=today - datetime.timedelta(days=6), date_to=today, project_ids={row.project_id},
        site_id=row.site_id, material_id=row.material_id, with_money=sees_money,
        on_order=await on_order_by_site(conn, org), levels=await levels_by_site(conn, org, [row.site_id]))
    if not found:
        return None
    s = found[0]
    newer = (await conn.execute(text(
        "SELECT EXISTS (SELECT 1 FROM material_receipts x WHERE x.organization_id = :org AND x.site_id = :s "
        "  AND x.material_id = :m AND x.id <> :id AND x.created_at > :at) "
        "OR EXISTS (SELECT 1 FROM material_usage x WHERE x.organization_id = :org AND x.site_id = :s "
        "  AND x.material_id = :m AND x.id <> :id AND x.created_at > :at)"),
        {"org": org, "s": row.site_id, "m": row.material_id, "id": row.id, "at": row.created_at})).scalar()
    minimum = s.get("min_qty")
    return {
        "closing": s["closing"], "days_left": s.get("days_left"), "on_order": s.get("on_order") or 0,
        "min_qty": minimum, "running_low": bool(s.get("running_low")), "last_rate": s.get("last_rate"),
        "to_order": (reorder_quantity(Decimal(str(s["closing"])), Decimal(str(s.get("on_order") or 0)),
                                      Decimal(str(minimum)), s.get("reorder_qty")) if minimum is not None else None),
        "latest": not newer,
    }


_MOVEMENT = (
    "SELECT r.id, r.project_id, r.site_id, r.material_id, r.quantity, r.occurred_date, r.created_at, "
    "r.movement_reason, r.reverses_movement_id, r.transfer_id, mc.name AS material, COALESCE(u.code, r.unit) AS unit, "
    "s.name AS site_name, {extra} "
    "EXISTS (SELECT 1 FROM material_usage x WHERE x.reverses_movement_id = r.id) "
    "OR EXISTS (SELECT 1 FROM material_receipts y WHERE y.reverses_movement_id = r.id) AS taken_back "
    "FROM {table} r JOIN materials_catalog mc ON mc.id = r.material_id "
    "LEFT JOIN units_of_measure u ON u.id = mc.default_unit_id LEFT JOIN sites s ON s.id = r.site_id "
    "WHERE r.id = :id AND r.organization_id = :org"
)


def _standing(row: Any, reason: str) -> bool:
    """A plain delivery or use that still stands: not taken back, not a correction, not half of a transfer."""
    return (row is not None and row.site_id is not None and row.material_id is not None and not row.taken_back
            and row.reverses_movement_id is None and row.transfer_id is None and row.movement_reason == reason
            and Decimal(str(row.quantity)) > 0)


async def read_receipt(conn: AsyncConnection, org: uuid.UUID, record_id: uuid.UUID, today: datetime.date,
                       sees_money: bool) -> dict[str, Any] | None:
    row = (await conn.execute(text(_MOVEMENT.format(
        table="material_receipts",
        extra="r.unit_cost, r.total_cost, r.vendor_id, r.purchase_order_line_id,")),
        {"id": record_id, "org": org})).first()
    if not _standing(row, "RECEIVED"):
        return None
    unit = row.unit or ""
    f: dict[str, Any] = {
        "what": f"{row.material} · {qty(row.quantity)} {unit}".strip(), "material": row.material, "unit": unit,
        "quantity": row.quantity, "site_name": row.site_name or "the site",
        "stock": await _stock(conn, org, row, today, sees_money),
        "report_time": await _report_time(conn, org, row.project_id),
    }
    if row.purchase_order_line_id is not None:
        from mesiri.domains.procurement.orders import line_received, ref

        line = (await conn.execute(text(
            "SELECT l.quantity, o.number FROM purchase_order_lines l JOIN purchase_orders o ON o.id = l.purchase_order_id "
            "WHERE l.id = :l AND o.organization_id = :org"), {"l": row.purchase_order_line_id, "org": org})).first()
        if line is not None:
            received = await line_received(conn, row.purchase_order_line_id)
            f["order"] = {"ref": ref(line.number), "ordered": line.quantity, "received": received,
                          "pending": max(Decimal(line.quantity) - received, Decimal(0))}
    if not sees_money:
        return f
    if row.unit_cost is not None:
        from mesiri.domains.procurement import rates

        bought = await rates.fetch_purchases(conn, org, project_ids=None, date_from=None, date_to=row.occurred_date,
                                             material_id=row.material_id)
        mine = next((b for b in bought if b["id"] == row.id), None)
        if mine is not None:
            earlier = [b for b in bought if b["id"] != row.id and (b["occurred_date"], b["created_at"])
                       < (mine["occurred_date"], mine["created_at"])]
            g = rates.gst_of(mine)
            ordered = mine.get("ordered_rate")
            f["rate"] = {
                "rate": rates.cost_rate(mine), "entered": g.entered, "ordered_rate": ordered,
                "differs_from_order": ordered is not None and Decimal(ordered) != g.entered,
                "previous": ({"rate": rates.cost_rate(earlier[-1]), "vendor": rates.vendor_name(earlier[-1]),
                              "date": earlier[-1]["occurred_date"]} if earlier else None),
            }
            f["amount"] = (Decimal(mine["total_cost"]) if mine.get("total_cost") is not None
                           else g.entered * Decimal(mine["quantity"]))
    if row.vendor_id is not None:
        from mesiri.domains.vendors import ledger

        entries, state = await ledger.fetch_entries(conn, org, vendor_id=row.vendor_id, projects=None)
        vendor = state["vendors"].get(row.vendor_id)
        if vendor is not None:
            s = ledger.summarise(vendor, entries, state, today)
            f["supplier"] = {"name": vendor["name"], "balance": s["balance"],
                             "unbilled_here": any(e["id"] == f"delivery:{row.id}" for e in entries)}
    if row.site_id is not None:
        from mesiri.domains.finance.costs import project_costs

        cost = await project_costs(conn, org, project_ids={row.project_id}, site_id=row.site_id,
                                   date_from=today - datetime.timedelta(days=6), date_to=today,
                                   visible=lambda _p, _s: True)  # the caller's site was checked before reading
        f["week"] = {"total": cost["total"], "materials": cost["materials"]["amount"], "labour": cost["labour"]["amount"]}
    return f


async def read_usage(conn: AsyncConnection, org: uuid.UUID, record_id: uuid.UUID, today: datetime.date,
                     sees_money: bool) -> dict[str, Any] | None:
    row = (await conn.execute(text(_MOVEMENT.format(table="material_usage", extra="")),
                              {"id": record_id, "org": org})).first()
    if not _standing(row, "CONSUMED"):
        return None
    unit = row.unit or ""
    return {
        "what": f"{row.material} · {qty(row.quantity)} {unit} used".strip(), "material": row.material, "unit": unit,
        "quantity": row.quantity, "site_name": row.site_name or "the site",
        "stock": await _stock(conn, org, row, today, sees_money),
        "report_time": await _report_time(conn, org, row.project_id),
    }


async def read_attendance(conn: AsyncConnection, org: uuid.UUID, record_id: uuid.UUID, today: datetime.date,
                          sees_money: bool) -> dict[str, Any] | None:
    """One attendance report: its people, and (money roles) its wages by the wage sheet's own arithmetic
    (``pay.build_rows``), the pay week so far and the advances still out. Labour and Wages are only read."""
    from mesiri.domains.workforce import pay, pay_store
    from mesiri.infrastructure.postgres.repositories.workforce import counted_line_sql

    row = (await conn.execute(text(
        "SELECT r.id, r.project_id, r.site_id, r.occurred_date, r.voided_at, s.name AS site_name, "
        f"EXISTS (SELECT 1 FROM labour_attendance_lines l WHERE l.report_id = r.id AND {counted_line_sql('l', 'r')}) AS counted "
        "FROM labour_attendance_reports r LEFT JOIN sites s ON s.id = r.site_id "
        "WHERE r.id = :id AND r.organization_id = :org"), {"id": record_id, "org": org})).first()
    if row is None or row.voided_at is not None:
        return None
    lines = [dict(x) for x in (await conn.execute(text(
        "SELECT l.worker_id, l.worker_name, l.trade, l.headcount, l.daily_wage, l.contractor, l.vendor_id, "
        "l.attendance_status, l.overtime_hours FROM labour_attendance_lines l WHERE l.report_id = :id"),
        {"id": record_id})).mappings()]
    present = [ln for ln in lines if (ln.get("attendance_status") or "present") != "absent"]
    trades: dict[str, Decimal] = {}
    for ln in present:
        name = (ln.get("trade") or "worker").strip().lower().replace("_", " ")
        trades[name] = trades.get(name, Decimal(0)) + Decimal(int(ln.get("headcount") or 1))
    heads = sum(trades.values(), Decimal(0))
    f: dict[str, Any] = {
        "what": f"{qty(heads)} on site", "site_name": row.site_name or "the site", "headcount": heads,
        "trades": sorted(trades.items(), key=lambda t: -t[1]),
        "report_time": await _report_time(conn, org, row.project_id),
    }
    if not sees_money:
        return f

    def total(rows: dict[str, dict[str, Any]], key: str) -> Decimal:
        return sum((Decimal(str(r[key])) for r in rows.values()), Decimal(0))

    mine = pay.build_rows([{**ln, "date": row.occurred_date} for ln in lines], {})
    week_from, week_to = pay.week_of(row.occurred_date)
    week = pay.build_rows(await pay_store.attendance_lines(conn, org, row.project_id, row.site_id, week_from, week_to), {})
    balances = await pay_store.advance_balances(conn, org, row.project_id)
    f["wages"] = {
        "today": total(mine, "gross") + total(mine, "overtime_amount"),
        "unpriced_man_days": total(mine, "unpriced_man_days"),
        "week": total(week, "gross") + total(week, "overtime_amount"), "week_from": week_from, "week_to": week_to,
        "counted": bool(row.counted),
        "advances": sum((v for v in balances.values() if v > 0), Decimal(0)),
    }
    return f


READS = {
    fact_review.MATERIAL_RECEIPT: read_receipt,
    fact_review.MATERIAL_USAGE: read_usage,
    fact_review.LABOUR_REPORT: read_attendance,
}
