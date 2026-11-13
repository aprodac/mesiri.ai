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
    # WEB-86: work done, an issue, a bill, a machine's day.
    "work_today": "The site said it once, in their own words. That is the day's progress.",
    "place": "Floor by floor, you see what is done and what is left, without a site visit.",
    "schedule": "Every work update moves the schedule, so you know today if the project is late.",
    "line": "Work that is counted on its estimate line is work you can bill the client for.",
    "line_offer": "Mesiri suggests the line. One tap by a person counts it, so nothing is billed by mistake.",
    "photos": "The photo sits with the line it proves, for the client and for any dispute.",
    "issue_open": "A problem said on site is in front of the office the same minute.",
    "issue_task": "It is somebody's job now, with a date, not a message lost in a group.",
    "bill_read": "Nobody typed this bill. Mesiri read it from the photo.",
    "expense_read": "Money spent is on the books the moment it is said, with who it went to.",
    "bill_match": "The bill is checked against what actually arrived, line by line.",
    "machine_day": "Hours, idle time, breakdown and diesel, from one message.",
    "machine_down": "Breakdown hours are on record, so you do not pay hire for them.",
    "machine_hire": "When the hire bill comes, you already know what the hours come to.",
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
          unit: str | None = None, money: bool = False, opens: str | None = None,
          action: dict[str, Any] | None = None) -> Card:
    return {
        "key": key, "title": title, "tag": tag, "question": question,
        "before": qty(before) if before is not None else None,
        "after": qty(after) if after is not None else None,
        "unit": unit, "rupees": money, "sentence": sentence, "say": SAY[key], "opens": opens,
        # WEB-88: something a person can do from the card (never done by itself): {kind, label, ...ids}.
        "action": action,
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


def _n(count: Any, one_word: str, many: str | None = None) -> str:
    c = Decimal(str(count))
    return f"{qty(c)} {one_word if c == 1 else (many or one_word + 's')}"


def _photo_card(f: dict[str, Any]) -> Card | None:
    photos = int(f.get("photos") or 0)
    if not photos:
        return None
    return _card("photos", "Photos", "proof", PROOF,
                 f"{_n(photos, 'photo')} {'is' if photos == 1 else 'are'} kept with this line of the report.",
                 after=photos, unit="photo" if photos == 1 else "photos", opens="/reports")


def work_cards(f: dict[str, Any], sees_money: bool) -> list[Card]:
    """Work done: the day's work -> the floor -> the schedule -> the estimate line (money) -> the photo -> the report.

    The estimate line is the honest one (plan decision 5): work reaches the budget and the client's bill only after a
    person puts it on a line. Counted: what it earned. Not counted: the line Mesiri suggests and what it would earn,
    for the person to tap; never said as earned."""
    cards: list[Card | None] = []
    today = f.get("today")
    if today:
        n = int(today["updates"])
        cards.append(_card("work_today", "Work today", "proof", WORK_MOVING,
                           f"{_n(n, 'work update')} from {f['site_name']} today.",
                           before=n - 1 if today.get("latest") and n > 0 else None, after=n,
                           unit="update" if n == 1 else "updates", opens="/site-log"))
    place = f.get("place")
    if place:
        done, left = len(place["done"]), len(place["left"])
        tail = f" Left: {', '.join(place['left'][:3])}{' and more' if left > 3 else ''}." if left else " Nothing left there."
        cards.append(_card("place", place["label"], "proof", WORK_MOVING,
                           f"{place['label']}: {_n(done, 'kind')} of work done, {left} left.{tail}",
                           after=done, unit="done", opens="/planning/places"))
    schedule = f.get("schedule")
    if schedule and schedule.get("progress") is not None:
        slip = int(schedule.get("slip_days") or 0)
        state = f"{_days(slip)} behind the schedule" if slip > 0 else "on schedule"
        cards.append(_card("schedule", "Schedule", "caught" if slip > 0 else "time", WORK_MOVING,
                           f"{f['project_name']} is {schedule['progress']}% done and {state}.",
                           after=schedule["progress"], unit="% done", opens="/planning/schedule"))
    if sees_money:
        for q in f.get("quantities") or []:
            line, offer = q.get("line"), q.get("suggested")
            amount = f"{qty(q['quantity'])} {q['unit']}"
            if line:
                rate = line.get("rate")
                if rate is not None and Decimal(str(rate)) > 0:
                    earned = Decimal(str(q["quantity"])) * Decimal(str(rate))
                    cards.append(_card("line", "Counted on the estimate", "money", OWE,
                                       f"{amount} is counted on “{line['name']}”: {rupees(earned)} earned at "
                                       f"{rupees(rate)} per {one(q['unit'])}, to bill the client.",
                                       after=earned, money=True, opens=f["boq_page"]))
                else:
                    cards.append(_card("line", "Counted on the estimate", "time", WORK_MOVING,
                                       f"{amount} is counted on “{line['name']}”.", opens=f["boq_page"]))
            elif offer:
                rate = offer.get("rate")
                would = (f" Once counted: {rupees(Decimal(str(q['quantity'])) * Decimal(str(rate)))} to bill the client."
                         if rate is not None and Decimal(str(rate)) > 0 else "")
                cards.append(_card("line_offer", "Estimate line", "time", OWE,
                                   f"{amount} is not on an estimate line yet. Suggested: “{offer['name']}”.{would}",
                                   opens=f["boq_page"],
                                   # WEB-88: the person's tap (decision 5), offered on the card: the estimate
                                   # page's own PUT /projects/{id}/boq/work/{quantity_id}.
                                   action=({"kind": "count_work", "label": "Count it on this line",
                                            "project_id": str(f["project_id"]), "quantity_id": str(q["id"]),
                                            "line_id": str(offer["id"])}
                                           if q.get("id") and offer.get("id") and f.get("project_id") else None)))
            break  # one line card: the first quantity's
    cards.extend([_photo_card(f), _report_card(f)])
    return [c for c in cards if c]


def issue_cards(f: dict[str, Any], sees_money: bool) -> list[Card]:  # noqa: ARG001 -- an issue has no money card
    """An issue: open issues at the site -> the task raised for it -> its photo -> the report."""
    cards: list[Card | None] = []
    n = f.get("open")
    if n is not None:
        oldest = f.get("oldest_days")
        waited = f" The oldest has waited {_days(int(oldest))}." if oldest and int(oldest) > 0 else ""
        cards.append(_card("issue_open", "Open issues", "caught", STOPS_WORK,
                           f"{_n(n, 'issue')} open at {f['site_name']}.{waited}",
                           before=int(n) - 1 if f.get("is_open") and f.get("latest") and int(n) > 0 else None,
                           after=n, unit="open", opens="/issues"))
    task = f.get("task")
    if task:
        who = f" for {task['assignee']}" if task.get("assignee") else ""
        due = f", due {task['due']:%-d %b}" if task.get("due") else ""
        cards.append(_card("issue_task", "Task", "time", STOPS_WORK,
                           f"A task is raised{who}{due}: “{task['title']}”.", opens="/tasks"))
    cards.extend([_photo_card(f), _report_card(f)])
    return [c for c in cards if c]


def expense_cards(f: dict[str, Any], sees_money: bool) -> list[Card]:
    """A bill or an expense: what was read -> the deliveries it is for and what differs -> the supplier -> the week.
    All of it is the company's spending: nothing for a role that does not see it."""
    if not sees_money:
        return []
    amount = Decimal(str(f["amount"]))
    said = f"{rupees(amount)}" + (f" to {f['vendor']}" if f.get("vendor") else "")
    tax = Decimal(str(f.get("tax") or 0))
    category = f.get("category") if (f.get("category") or "").strip().lower() != "uncategorized" else None
    parts = [p for p in (f"GST {rupees(tax)}" if tax > 0 else None, category) if p]
    how = "Read from the photo" if f.get("from_photo") else "Recorded"
    cards: list[Card | None] = [_card(
        "bill_read" if f.get("from_photo") else "expense_read", "The bill" if f.get("from_photo") else "Expense", "time",
        MONEY_GOING,
        f"{how}: {said}" + (f" ({', '.join(parts)})." if parts else "."), after=amount, money=True,
        opens="/finance/expenses")]
    deliveries = f.get("deliveries")
    if deliveries:
        differs = [f"{d['material']}: {flag}" for d in deliveries for flag in d.get("flags") or []]
        n = len(deliveries)
        # The bill against what its deliveries come to at the site's rates (only when every one has a rate).
        values = [d.get("amount") for d in deliveries]
        delivered = sum((Decimal(str(v)) for v in values), Decimal(0)) if all(v is not None for v in values) else None
        over = amount - delivered if delivered is not None else Decimal(0)
        if over > 1:
            cards.append(_card("bill_match", "Bill check", "caught", LEAKING,
                               f"The bill is {rupees(over)} more than the {_n(n, 'delivery', 'deliveries')} it is for "
                               f"({rupees(delivered)} delivered)." + (f" {'; '.join(differs[:2])}." if differs else ""),
                               before=delivered, after=amount, money=True, opens="/finance/vendors"))
        elif differs:
            cards.append(_card("bill_match", "Bill check", "caught", LEAKING,
                               f"Checked against {_n(n, 'delivery', 'deliveries')}. {'; '.join(differs[:2])}.",
                               after=len(differs), unit="to check", opens="/finance/vendors"))
        else:
            cards.append(_card("bill_match", "Bill check", "proof", LEAKING,
                               f"It matches the {_n(n, 'delivery', 'deliveries')} it bills: same quantity, same rate.",
                               after=n, unit="matched", opens="/finance/vendors"))
    supplier = f.get("supplier")
    if supplier and Decimal(str(supplier["balance"])) > 0:
        cards.append(_card("supplier", supplier["name"], "money", OWE,
                           f"You now owe {supplier['name']} {rupees(supplier['balance'])}.",
                           after=supplier["balance"], money=True, opens="/finance/vendors"))
    week = f.get("week")
    if week and Decimal(str(week["total"])) > 0:
        cards.append(_card("week_cost", "This week's cost", "money", MONEY_GOING,
                           f"{f['where']} has cost {rupees(week['total'])} in the last 7 days.",
                           after=week["total"], money=True, opens="/cost"))
    return [c for c in cards if c]


def machine_cards(f: dict[str, Any], sees_money: bool) -> list[Card]:
    """A machine's day: its hours -> breakdown -> what the hire comes to this month (money, hired machines)."""
    worked = Decimal(str(f.get("worked") or 0))
    bits = [f"{qty(worked)} h worked"]
    if Decimal(str(f.get("idle") or 0)) > 0:
        bits.append(f"{qty(f['idle'])} h idle")
    if f.get("fuel") is not None and Decimal(str(f["fuel"])) > 0:
        bits.append(f"{qty(f['fuel'])} L diesel")
    cards: list[Card | None] = [_card("machine_day", f["machine"], "proof", WORK_MOVING,
                                      f"{f['machine']} at {f['site_name']}: {', '.join(bits)}.",
                                      after=worked, unit="h worked", opens="/equipment")]
    broke = Decimal(str(f.get("breakdown") or 0))
    if broke > 0:
        why = f": {f['breakdown_reason']}" if f.get("breakdown_reason") else ""
        cards.append(_card("machine_down", "Breakdown", "caught", STOPS_WORK,
                           f"{qty(broke)} h lost to breakdown{why}.", after=broke, unit="h lost", opens="/equipment"))
    hire = f.get("hire") if sees_money else None
    if hire and Decimal(str(hire["expected"])) > 0:
        cards.append(_card("machine_hire", "Hire this month", "money", OWE,
                           f"{f['machine']}'s hire comes to {rupees(hire['expected'])} so far this month, over "
                           f"{_days(int(hire['days']))} on site" + (f" ({hire['vendor']})." if hire.get("vendor") else "."),
                           after=hire["expected"], money=True, opens="/equipment/hire"))
    return [c for c in cards if c]


#: WEB-86: records Live asks about that are not report facts (``fact_review.FACT_TYPES``).
EXPENSE, MACHINE_LOG = "expense", "machine_log"
#: A kind whose every card is the company's spending: the route answers 404 to a role that does not see it.
MONEY_KINDS: frozenset[str] = frozenset({EXPENSE})

#: Kind of entry -> (the line over its ripple, its cards). A kind not here has no ripple.
RULES: dict[str, tuple[str, Callable[[dict[str, Any], bool], list[Card]]]] = {
    fact_review.MATERIAL_RECEIPT: ("Material came", receipt_cards),
    fact_review.MATERIAL_USAGE: ("Material used", usage_cards),
    fact_review.LABOUR_REPORT: ("Attendance", attendance_cards),
    fact_review.ACTIVITY: ("Work done", work_cards),
    fact_review.SITE_ISSUE: ("Issue", issue_cards),
    EXPENSE: ("Expense", expense_cards),
    MACHINE_LOG: ("Machine log", machine_cards),
}


def cards(kind: str, facts: dict[str, Any] | None, sees_money: bool) -> dict[str, Any]:
    """The ripple for one entry. ``facts`` None: the entry was taken back (or is not one that changes anything)."""
    title, build = RULES[kind]
    out = build(facts, sees_money) if facts else []
    return {"kind": kind, "title": title, "what": facts.get("what") if facts else None, "cards": out, "count": len(out)}


# ----------------------------------------------------------------------------------------------------------------
# Reading: each figure from the read its own module uses.
# ----------------------------------------------------------------------------------------------------------------

def clock(value: Any) -> str | None:
    """A report time as people say it: "21:00" or 21:00:00 -> "9:00 pm". The project keeps it as text ("HH:MM" or
    "HH:MM:SS"); a time object is read the same way. None when it is not a time."""
    if value is None:
        return None
    if isinstance(value, datetime.time):
        hour, minute = value.hour, value.minute
    else:
        parts = str(value).strip().split(":")
        if len(parts) < 2 or not parts[0].isdigit() or not parts[1].isdigit():
            return None
        hour, minute = int(parts[0]), int(parts[1])
    if not (0 <= hour < 24 and 0 <= minute < 60):
        return None
    return f"{hour % 12 or 12}:{minute:02d} {'am' if hour < 12 else 'pm'}"


async def _report_time(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID) -> str | None:
    """When today's report goes out by itself; None when the project does not send it automatically."""
    row = (await conn.execute(text(
        "SELECT dpr_send_deadline, auto_generate_dpr FROM projects WHERE id = :p AND organization_id = :org"),
        {"p": project_id, "org": org})).first()
    if row is None or not row.auto_generate_dpr:
        return None
    return clock(row.dpr_send_deadline)


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
                       sees_money: bool, **_: Any) -> dict[str, Any] | None:
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
        f["supplier"] = await _supplier(conn, org, row.vendor_id, today, entry=f"delivery:{row.id}")
    if row.site_id is not None:
        f["week"] = await _week(conn, org, row.project_id, row.site_id, today)
    return f


async def _supplier(conn: AsyncConnection, org: uuid.UUID, vendor_id: uuid.UUID, today: datetime.date, *,
                    entry: str | None = None) -> dict[str, Any] | None:
    """What a supplier is owed now, by the supplier ledger's own summary; ``unbilled_here``: ``entry`` is in it."""
    from mesiri.domains.vendors import ledger

    entries, state = await ledger.fetch_entries(conn, org, vendor_id=vendor_id, projects=None)
    vendor = state["vendors"].get(vendor_id)
    if vendor is None:
        return None
    s = ledger.summarise(vendor, entries, state, today)
    return {"name": vendor["name"], "balance": s["balance"],
            "unbilled_here": entry is not None and any(e["id"] == entry for e in entries)}


async def _week(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID, site_id: uuid.UUID | None,
                today: datetime.date) -> dict[str, Any]:
    """The last 7 days' full cost of a site (or a project), by the Full cost read."""
    from mesiri.domains.finance.costs import project_costs

    cost = await project_costs(conn, org, project_ids={project_id}, site_id=site_id,
                               date_from=today - datetime.timedelta(days=6), date_to=today,
                               visible=lambda _p, _s: True)  # the caller's site was checked before reading
    return {"total": cost["total"], "materials": cost["materials"]["amount"], "labour": cost["labour"]["amount"]}


async def read_usage(conn: AsyncConnection, org: uuid.UUID, record_id: uuid.UUID, today: datetime.date,
                     sees_money: bool, **_: Any) -> dict[str, Any] | None:
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
                          sees_money: bool, **_: Any) -> dict[str, Any] | None:
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


async def _photos(conn: AsyncConnection, org: uuid.UUID, kind: str, record_id: uuid.UUID) -> int:
    """How many photos sit with a report line: the sources panel's own read."""
    from mesiri.infrastructure.postgres.repositories.fact_reviews import (
        PostgresFactReviewRepository,
    )

    found = await PostgresFactReviewRepository(conn).sources(organization_id=org, fact_type=kind, fact_id=record_id)
    return len(found.get("photos") or [])


async def _site_day(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID, site_id: uuid.UUID,
                    day: datetime.date) -> dict[str, Any] | None:
    """The site's day as the Today page counts it (work items, open issues)."""
    from mesiri.infrastructure.postgres.repositories.dpr import PostgresDprRepository

    rows = await PostgresDprRepository(conn).list_site_days(organization_id=org, project_ids={project_id}, report_date=day)
    return next((r for r in rows if str(r["site_id"]) == str(site_id)), None)


async def read_activity(conn: AsyncConnection, org: uuid.UUID, record_id: uuid.UUID, today: datetime.date,
                        sees_money: bool, **_: Any) -> dict[str, Any] | None:
    """One work entry: the site's work today, its floor on the progress grid, the project's schedule, and (money
    roles) the estimate line it is counted on or the one suggested. Every figure from its module's own read."""
    row = (await conn.execute(text(
        "SELECT a.id, a.project_id, a.site_id, a.location_id, a.work_type, a.narrative, a.activity_date, a.created_at, "
        "a.work_package_id, s.name AS site_name, p.name AS project_name, "
        "EXISTS (SELECT 1 FROM activities x WHERE x.organization_id = a.organization_id AND x.site_id = a.site_id "
        "  AND x.activity_date = a.activity_date AND x.deleted_at IS NULL AND x.created_at > a.created_at) AS newer "
        "FROM activities a LEFT JOIN sites s ON s.id = a.site_id JOIN projects p ON p.id = a.project_id "
        "WHERE a.id = :id AND a.organization_id = :org AND a.deleted_at IS NULL"), {"id": record_id, "org": org})).first()
    if row is None or row.site_id is None:
        return None
    work = (row.work_type or row.narrative or "Work").strip()
    f: dict[str, Any] = {
        "what": work[:60], "site_name": row.site_name or "the site", "project_name": row.project_name,
        "project_id": row.project_id,
        "boq_page": f"/projects/{row.project_id}/boq", "report_time": await _report_time(conn, org, row.project_id),
        "photos": await _photos(conn, org, fact_review.ACTIVITY, record_id),
    }
    day = await _site_day(conn, org, row.project_id, row.site_id, row.activity_date)
    if day is not None:
        f["today"] = {"updates": int(day["work_items"] or 0) + int(day["progress_updates"] or 0), "latest": not row.newer}
    if row.location_id is not None:
        from mesiri.domains.places import progress
        from mesiri.domains.places import store as places

        rows = await places.places(conn, org, row.project_id)
        here = next((r for r in rows if r["id"] == row.location_id), None)
        if here is not None:
            cell = progress.roll_up(rows, await places.works(conn, org, row.project_id))["places"].get(row.location_id)
            if cell is not None:
                f["place"] = {"label": here["name"], "done": cell["done"], "left": cell["left"]}
    from mesiri.domains.schedule import store as schedule

    summary = (await schedule.load(conn, org, row.project_id, today))["summary"]
    if summary.get("scheduled"):
        f["schedule"] = {"progress": summary.get("progress"), "slip_days": summary.get("slip_days")}
    if sees_money:
        from mesiri.domains.progress.boq import suggest_line
        from mesiri.infrastructure.postgres.repositories.boq import PostgresBoqRepository

        mine = {r.id for r in (await conn.execute(text(
            "SELECT id FROM activity_quantities WHERE activity_id = :a"), {"a": record_id}))}
        if mine:
            repo = PostgresBoqRepository(conn)
            lines = await repo.list_lines(org, row.project_id)
            by_id = {ln["id"]: ln for ln in lines}
            current = await repo.current_revision_of(org, row.project_id)

            def named(line_id: Any) -> dict[str, Any] | None:
                ln = by_id.get(line_id)
                return {"id": ln["id"], "name": ln["work_type"], "rate": ln.get("client_rate")} if ln else None

            f["quantities"] = [
                {"id": w["id"], "quantity": w["quantity"], "unit": w["unit"],
                 "line": named(current.get(w["line_id"], w["line_id"])) if w["line_id"] else None,
                 "suggested": None if w["line_id"] else named(
                     suggest_line(w["work"] or w["narrative"], w["unit_id"], w["section_id"], lines))}
                for w in await repo.work_updates(org, row.project_id, unlinked_only=False, limit=500) if w["id"] in mine
            ]
    return f


async def read_issue(conn: AsyncConnection, org: uuid.UUID, record_id: uuid.UUID, today: datetime.date,
                     sees_money: bool, **_: Any) -> dict[str, Any] | None:  # noqa: ARG001
    """One issue: how many are open at its site (the Today page's count), how long the oldest has waited, and the
    task raised for it, if one was."""
    from mesiri.application.dpr.open_issues import is_open, open_issue_sql

    row = (await conn.execute(text(
        "SELECT i.id, i.project_id, i.site_id, i.status, i.issue_type, i.narrative, i.occurred_at, i.created_at, "
        "s.name AS site_name, "
        "EXISTS (SELECT 1 FROM site_issues x WHERE x.organization_id = i.organization_id AND x.site_id = i.site_id "
        "  AND x.created_at > i.created_at) AS newer, "
        f"(SELECT min(x.occurred_at) FROM site_issues x WHERE x.organization_id = i.organization_id "
        f"  AND x.site_id = i.site_id AND {open_issue_sql('x')}) AS oldest "
        "FROM site_issues i LEFT JOIN sites s ON s.id = i.site_id WHERE i.id = :id AND i.organization_id = :org"),
        {"id": record_id, "org": org})).first()
    if row is None or row.site_id is None or str(row.status).upper() == "CANCELLED":
        return None
    words = str(row.issue_type or "issue").replace("_", " ").lower()
    f: dict[str, Any] = {
        "what": (row.narrative or words)[:60], "site_name": row.site_name or "the site",
        "is_open": is_open(row.status), "latest": not row.newer,
        "oldest_days": (today - row.oldest.date()).days if row.oldest is not None else None,
        "report_time": await _report_time(conn, org, row.project_id),
        "photos": await _photos(conn, org, fact_review.SITE_ISSUE, record_id),
    }
    day = await _site_day(conn, org, row.project_id, row.site_id, today)
    if day is not None:
        f["open"] = int(day["open_issues"] or 0)
    task = (await conn.execute(text(
        "SELECT t.title, t.due_date, COALESCE(u.full_name, v.name, t.assignee_team) AS assignee FROM tasks t "
        "LEFT JOIN users u ON u.id = t.assignee_user_id LEFT JOIN vendors v ON v.id = t.assignee_vendor_id "
        "WHERE t.site_issue_id = :id AND t.organization_id = :org ORDER BY t.created_at LIMIT 1"),
        {"id": record_id, "org": org})).first()
    if task is not None:
        f["task"] = {"title": task.title, "due": task.due_date, "assignee": task.assignee}
    return f


async def read_expense(conn: AsyncConnection, org: uuid.UUID, record_id: uuid.UUID, today: datetime.date,
                       sees_money: bool, *, auth: Any = None, **_: Any) -> dict[str, Any] | None:
    """One expense or bill: what was read, the deliveries the bill is for with what differs (the supplier page's own
    list), what the supplier is owed, the week's cost. Money roles only; nothing is linked or written here."""
    if not sees_money:
        return None
    row = (await conn.execute(text(
        "SELECT e.id, e.project_id, e.site_id, e.amount, e.tax_amount, e.vendor_id, e.workflow_status, "
        "v.name AS vendor, c.name AS category, s.name AS site_name, p.name AS project_name, "
        "EXISTS (SELECT 1 FROM expense_attachments x WHERE x.expense_id = e.id) AS from_photo "
        "FROM expenses e LEFT JOIN vendors v ON v.id = e.vendor_id LEFT JOIN expense_categories c ON c.id = e.category_id "
        "LEFT JOIN sites s ON s.id = e.site_id LEFT JOIN projects p ON p.id = e.project_id "
        "WHERE e.id = :id AND e.organization_id = :org"), {"id": record_id, "org": org})).first()
    if row is None or row.project_id is None or row.workflow_status != "confirmed":
        return None
    f: dict[str, Any] = {
        "what": f"{rupees(row.amount)}" + (f" · {row.vendor}" if row.vendor else ""), "amount": row.amount,
        "tax": row.tax_amount, "vendor": row.vendor, "category": row.category, "from_photo": bool(row.from_photo),
        "where": row.site_name or row.project_name or "The project",
        "week": await _week(conn, org, row.project_id, row.site_id, today),
    }
    if row.vendor_id is not None:
        f["supplier"] = await _supplier(conn, org, row.vendor_id, today)
        if auth is not None:
            from fastapi import HTTPException

            from mesiri.domains.vendors.router import bill_delivery_list

            try:  # the supplier page's own list of the bill's deliveries, with its own role and scope rule
                f["deliveries"] = await bill_delivery_list(vendor_id=row.vendor_id, expense_id=record_id,
                                                           auth_context=auth, conn=conn)
            except HTTPException:
                pass  # not a bill with deliveries, or not this person's to see: no card
    return f


async def read_machine_log(conn: AsyncConnection, org: uuid.UUID, record_id: uuid.UUID, today: datetime.date,
                           sees_money: bool, **_: Any) -> dict[str, Any] | None:
    """One machine's day: its hours by the equipment module's own rule, and (money roles, a hired machine) what
    the month's hire comes to so far by ``rules.hire_lines``, as the hire check counts it."""
    from mesiri.domains.equipment import rules, store

    found = await store.fetch_events(conn, org, ids=[record_id])
    x = found[0] if found else None
    if x is None or x.get("voided_at") is not None or x.get("event_type") != "day_log":
        return None
    name = x.get("machine_name") or x.get("equipment_name") or "The machine"
    f: dict[str, Any] = {
        "what": name, "machine": name, "site_name": x.get("site_name") or "the site",
        "worked": rules.worked(x), "idle": rules.d(x.get("idle_hours")), "breakdown": rules.d(x.get("breakdown_hours")),
        "breakdown_reason": x.get("breakdown_reason"), "fuel": x.get("fuel_quantity"),
    }
    if sees_money and x.get("equipment_id") is not None:
        machines = await store.fetch_machines(conn, org, ids=[x["equipment_id"]])
        if machines and machines[0].get("ownership") == "hired":
            m = machines[0]
            logs = await store.fetch_events(conn, org, equipment_ids=[m["id"]], date_to=today)
            lines = rules.hire_lines(m, logs, today.replace(day=1), today, today)
            f["hire"] = {"expected": sum((ln["amount"] for ln in lines), Decimal(0)), "days": len(lines),
                         "vendor": m.get("vendor_name")}
    return f


#: Where a record that is not a report fact lives: (table, extra condition). The route reads its project and site
#: from here for the scope rule; a fact goes through ``PostgresFactReviewRepository.locate``.
RECORD_TABLES: dict[str, str] = {EXPENSE: "expenses", MACHINE_LOG: "equipment_events"}


async def locate(conn: AsyncConnection, org: uuid.UUID, kind: str, record_id: uuid.UUID) -> dict[str, Any] | None:
    """project_id / site_id of an expense or a machine log; None when it is not this company's."""
    row = (await conn.execute(text(
        f"SELECT project_id, site_id FROM {RECORD_TABLES[kind]} WHERE id = :id AND organization_id = :org"),
        {"id": record_id, "org": org})).mappings().first()
    return dict(row) if row else None


READS = {
    fact_review.MATERIAL_RECEIPT: read_receipt,
    fact_review.MATERIAL_USAGE: read_usage,
    fact_review.LABOUR_REPORT: read_attendance,
    fact_review.ACTIVITY: read_activity,
    fact_review.SITE_ISSUE: read_issue,
    EXPENSE: read_expense,
    MACHINE_LOG: read_machine_log,
}
