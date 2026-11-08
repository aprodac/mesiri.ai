"""A project's schedule (ST-04): the maths, pure, no I/O.

The schedule is the project's BOQ sections (``work_packages``) with dates: what is built, and when. An *activity*
here is one of them, as a plain dict:

    {"id", "name", "start", "end", "milestone", "done", "progress", "actual_start", "actual_end"}

``start`` / ``end`` are the planned days, both inclusive (a 3-day job is 1st..3rd). A milestone is one day with no
duration ("Slab cast", "Handover"). ``progress`` is 0..1 from what site measured (``line_progress``), or None when
nothing on the BOQ lines can be measured. ``done`` is the PM's "this is finished".

A *link* says "B starts after A" ``{"predecessor", "successor", "lag"}``: B may start on the day after A ends, plus
``lag`` days (after a milestone, on the milestone's day plus lag).

What the schedule answers, each in one function:

- ``assess``: is it done, on time, behind, late or not started yet, and by how many days.
- ``forecast_end``: at the pace site is going, when will it really finish.
- ``knock_on``: what a late activity pushes, and the project's forecast finish.
- ``push``: the PM moved one activity; the activities after it that now start too early move with it (never
  earlier, never the ones before).
- ``critical``: the activities with no slack: a day late on any of them is a day late for the project.
- ``conflicts``: links the planned dates break (B planned to start before A ends).

Worked example: Excavation 1-5 Nov, Footings 6-12 Nov (after Excavation), Slab 13-20 Nov (after Footings). On 8 Nov
Excavation is 60% measured: it is late by 3 days; 60% in 7 days of work means about 5 more days (8-12 Nov), so
it forecasts finishing 12 Nov; Footings move to 13-19 Nov and Slab to 20-27 Nov: the project finishes 7 days late.
"""

from __future__ import annotations

import datetime
from collections.abc import Iterable, Mapping
from decimal import Decimal
from typing import Any

DAY = datetime.timedelta(days=1)

# States, in the order the dashboard sorts them (worst first).
LATE = "late"            # planned end has passed and it is not done
BEHIND = "behind"        # running (or should be) but slower than the calendar
ON_TRACK = "on_track"
NOT_STARTED = "not_started"
DONE = "done"
UNSCHEDULED = "unscheduled"

#: How far behind the calendar (as a share of the work) counts as "behind": 15 points.
BEHIND_MARGIN = Decimal("0.15")


class CycleError(ValueError):
    """The links go round in a circle (A after B after A); the message names one of them."""


# -- progress from site data ---------------------------------------------------------------------------------------

def line_progress(lines: Iterable[Mapping[str, Any]]) -> Decimal | None:
    """Share of an activity's work done, 0..1, from its BOQ lines.

    Each line: ``planned_quantity``, ``done_quantity`` (measured on site), optional ``contract_value``. Lines are
    weighted by contract value when every line has one (₹1 lakh of plastering weighs more than ₹5,000 of curing),
    else equally. A line over 100% counts as 100%. None when there are no lines to measure.
    """
    rows = [ln for ln in lines if Decimal(ln.get("planned_quantity") or 0) > 0]
    if not rows:
        return None
    shares = [min(Decimal(ln.get("done_quantity") or 0) / Decimal(ln["planned_quantity"]), Decimal(1)) for ln in rows]
    weights = [ln.get("contract_value") for ln in rows]
    if all(w is not None and Decimal(w) > 0 for w in weights):
        total = sum((Decimal(w) for w in weights), Decimal(0))
        return sum((s * Decimal(w) for s, w in zip(shares, weights, strict=True)), Decimal(0)) / total
    return sum(shares, Decimal(0)) / len(shares)


# -- one activity ----------------------------------------------------------------------------------------------------

def scheduled(a: Mapping[str, Any]) -> bool:
    return a.get("start") is not None and a.get("end") is not None


def duration(a: Mapping[str, Any]) -> int:
    """Working length in days (calendar days; a milestone is 0)."""
    if a.get("milestone"):
        return 0
    return (a["end"] - a["start"]).days + 1


def is_done(a: Mapping[str, Any]) -> bool:
    progress = a.get("progress")
    return bool(a.get("done")) or a.get("actual_end") is not None or (progress is not None and progress >= 1)


def started(a: Mapping[str, Any]) -> bool:
    progress = a.get("progress")
    return a.get("actual_start") is not None or (progress is not None and progress > 0)


def expected_progress(a: Mapping[str, Any], today: datetime.date) -> Decimal:
    """Share of the planned days already behind us (0 before the start, 1 after the end)."""
    if today < a["start"]:
        return Decimal(0)
    if today > a["end"] or a.get("milestone"):
        return Decimal(1)
    return Decimal((today - a["start"]).days) / Decimal(duration(a))


def forecast_end(a: Mapping[str, Any], today: datetime.date) -> datetime.date | None:
    """When it will really finish at the pace site has shown; the planned end when nothing says otherwise.

    Done: the day it ended (or the planned end). Not started and its start has passed: it starts today and takes its
    planned length. Running with measured progress: the days left at the pace so far. Never earlier than planned.
    """
    if not scheduled(a):
        return None
    if is_done(a):
        return a.get("actual_end") or a["end"]
    if a.get("milestone"):
        return max(a["end"], today)
    progress = a.get("progress")
    if not started(a):
        if today <= a["start"]:
            return a["end"]
        return today + DAY * (duration(a) - 1)
    began = a.get("actual_start") or a["start"]
    # Days of work already behind us (today's work is not reported yet), and the days left from today on.
    days_so_far = max((today - began).days, 1)
    if progress is None or progress <= 0:
        return max(a["end"], today)
    total = Decimal(days_so_far) / progress
    left = int((total - days_so_far).to_integral_value(rounding="ROUND_CEILING"))
    return max(a["end"], today + DAY * max(left - 1, 0))


def assess(a: Mapping[str, Any], today: datetime.date) -> dict[str, Any]:
    """State of one activity on ``today``, with the numbers the screen and the WhatsApp note show."""
    if not scheduled(a):
        return {"state": DONE if is_done(a) else UNSCHEDULED, "days_late": 0, "expected": None, "forecast_end": None,
                "slip_days": 0}
    expected = expected_progress(a, today)
    forecast = forecast_end(a, today)
    slip = max((forecast - a["end"]).days, 0) if forecast else 0
    if is_done(a):
        state, late = DONE, max(((a.get("actual_end") or a["end"]) - a["end"]).days, 0)
        return {"state": state, "days_late": late, "expected": expected, "forecast_end": forecast, "slip_days": late}
    if today > a["end"]:
        return {"state": LATE, "days_late": (today - a["end"]).days, "expected": expected, "forecast_end": forecast,
                "slip_days": slip}
    if today < a["start"]:
        return {"state": NOT_STARTED, "days_late": 0, "expected": expected, "forecast_end": forecast, "slip_days": 0}
    progress = a.get("progress")
    if not started(a) and today > a["start"]:
        state = BEHIND
    elif progress is not None and expected - progress > BEHIND_MARGIN:
        state = BEHIND
    elif slip > 0:
        state = BEHIND
    else:
        state = ON_TRACK
    return {"state": state, "days_late": 0, "expected": expected, "forecast_end": forecast, "slip_days": slip}


# -- links -----------------------------------------------------------------------------------------------------------

def earliest_after(pred: Mapping[str, Any], lag: int, end: datetime.date | None = None) -> datetime.date:
    """The first day a successor may start: the day after the predecessor ends (a milestone's own day), plus lag."""
    finish = end or pred["end"]
    return finish + DAY * ((0 if pred.get("milestone") else 1) + lag)


def order(ids: Iterable[Any], links: Iterable[Mapping[str, Any]]) -> list[Any]:
    """Activities so that each comes after all it starts after (Kahn's algorithm); CycleError on a circle."""
    ids = list(ids)
    known = set(ids)
    after: dict[Any, list[Any]] = {i: [] for i in ids}
    waiting = {i: 0 for i in ids}
    for link in links:
        p, s = link["predecessor"], link["successor"]
        if p in known and s in known:
            after[p].append(s)
            waiting[s] += 1
    ready = [i for i in ids if waiting[i] == 0]
    out: list[Any] = []
    while ready:
        i = ready.pop(0)
        out.append(i)
        for s in after[i]:
            waiting[s] -= 1
            if waiting[s] == 0:
                ready.append(s)
    if len(out) != len(ids):
        stuck = next(i for i in ids if waiting[i] > 0)
        raise CycleError(f"The 'starts after' links go round in a circle through {stuck}")
    return out


def makes_cycle(links: Iterable[Mapping[str, Any]], predecessor: Any, successor: Any) -> bool:
    """Would "successor starts after predecessor" close a circle (predecessor already after successor)?"""
    if predecessor == successor:
        return True
    graph: dict[Any, list[Any]] = {}
    for link in links:
        graph.setdefault(link["predecessor"], []).append(link["successor"])
    seen, stack = set(), [successor]
    while stack:
        node = stack.pop()
        if node == predecessor:
            return True
        if node in seen:
            continue
        seen.add(node)
        stack.extend(graph.get(node, []))
    return False


def _by_id(activities: Iterable[Mapping[str, Any]]) -> dict[Any, dict[str, Any]]:
    return {a["id"]: dict(a) for a in activities}


def push(
    activities: Iterable[Mapping[str, Any]],
    links: Iterable[Mapping[str, Any]],
    changed: Mapping[Any, tuple[datetime.date, datetime.date]],
    *,
    pinned: bool = True,
) -> dict[Any, tuple[datetime.date, datetime.date]]:
    """New (start, end) for every activity that must move because of ``changed`` (which is included).

    Only forward: an activity moves when it would now start before its predecessor allows, and keeps its length.
    An activity already done never moves. Unscheduled ones are skipped. ``pinned``: the changed dates are the PM's
    own and stay as given; otherwise (a forecast) they are pushed by their predecessors too.
    """
    acts = _by_id(activities)
    links = list(links)
    for i, (s, e) in changed.items():
        acts[i]["start"], acts[i]["end"] = s, e
    moved: dict[Any, tuple[datetime.date, datetime.date]] = dict(changed)
    preds: dict[Any, list[Mapping[str, Any]]] = {}
    for link in links:
        preds.setdefault(link["successor"], []).append(link)
    for i in order(acts, links):
        a = acts[i]
        if (pinned and i in changed) or not scheduled(a) or is_done(a):
            continue
        floor = None
        for link in preds.get(i, []):
            p = acts.get(link["predecessor"])
            if p is None or not scheduled(p):
                continue
            day = earliest_after(p, int(link.get("lag") or 0))
            floor = day if floor is None or day > floor else floor
        if floor is not None and floor > a["start"]:
            shift = floor - a["start"]
            a["start"], a["end"] = a["start"] + shift, a["end"] + shift
            moved[i] = (a["start"], a["end"])
    return moved


def knock_on(
    activities: Iterable[Mapping[str, Any]], links: Iterable[Mapping[str, Any]], today: datetime.date
) -> dict[str, Any]:
    """What the slipping activities push, at the pace site is going.

    Returns ``{"moves": {id: days}, "planned_finish", "forecast_finish", "slip_days"}``: how many days each activity
    after a late one moves, and the project's last day as planned and as forecast.
    """
    acts = [dict(a) for a in activities if scheduled(a)]
    links = list(links)
    if not acts:
        return {"moves": {}, "planned_finish": None, "forecast_finish": None, "slip_days": 0}
    changed = {}
    for a in acts:
        f = forecast_end(a, today)
        if f is not None and f > a["end"]:
            start = a["start"] if started(a) or today <= a["start"] else today
            changed[a["id"]] = (start, f)
    new = push(acts, links, changed, pinned=False)
    original = {a["id"]: a for a in acts}
    moves = {i: (e - original[i]["end"]).days for i, (s, e) in new.items() if e != original[i]["end"]}
    planned = max(a["end"] for a in acts)
    forecast = max(new.get(a["id"], (a["start"], a["end"]))[1] for a in acts)
    return {"moves": moves, "planned_finish": planned, "forecast_finish": forecast,
            "slip_days": max((forecast - planned).days, 0)}


def critical(activities: Iterable[Mapping[str, Any]], links: Iterable[Mapping[str, Any]]) -> set[Any]:
    """The activities with no slack before the project's last day (zero total float), on the planned dates.

    Backward pass: an activity may finish as late as the earliest its successors allow (their latest start, minus
    lag, minus the day between), or the project's last day when nothing follows. Its slack is how much later than
    planned it could finish. Unfinished activities with no slack are critical.
    """
    acts = _by_id(a for a in activities if scheduled(a))
    if not acts:
        return set()
    links = [lk for lk in links if lk["predecessor"] in acts and lk["successor"] in acts]
    finish = max(a["end"] for a in acts.values())
    succ: dict[Any, list[Mapping[str, Any]]] = {}
    for link in links:
        succ.setdefault(link["predecessor"], []).append(link)
    latest_end: dict[Any, datetime.date] = {}
    latest_start: dict[Any, datetime.date] = {}
    for i in reversed(order(acts, links)):
        a = acts[i]
        bound = finish
        for link in succ.get(i, []):
            s_start = latest_start[link["successor"]]
            gap = (0 if a.get("milestone") else 1) + int(link.get("lag") or 0)
            day = s_start - DAY * gap
            bound = min(bound, day)
        latest_end[i] = bound
        latest_start[i] = bound if a.get("milestone") else bound - DAY * (duration(a) - 1)
    return {i for i, a in acts.items() if not is_done(a) and (latest_end[i] - a["end"]).days <= 0}


def conflicts(activities: Iterable[Mapping[str, Any]], links: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Links whose planned dates break them: the successor is planned to start before its predecessor allows."""
    acts = _by_id(activities)
    out = []
    for link in links:
        p, s = acts.get(link["predecessor"]), acts.get(link["successor"])
        if not p or not s or not scheduled(p) or not scheduled(s):
            continue
        allowed = earliest_after(p, int(link.get("lag") or 0))
        if s["start"] < allowed:
            out.append({"predecessor": p["id"], "successor": s["id"], "days": (allowed - s["start"]).days})
    return out
