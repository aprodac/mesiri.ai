"""WA-270 step 3 (the state layer, part 3: memory is state, not replay). What is true now, written by the code for
the model each turn, in place of the day's chat replayed.

Live on 13 Nov (Mesiri Test Builders) the replay gave: "athu 25 aakku" dropping the card's line and answering an old
question (WA-293), a new message bringing back the lines of cancelled messages (WA-294), an earlier reply copied
(WA-286). Each of those is a fact the code already holds in the chat state: the card, the cancelled lines, the saved
records, the open question. Here they are said as state, once, in fixed headings, so nothing has to be read back out
of an old conversation.

``state_block`` is a pure function of the chat state (``AgentApiWhatsAppService._state``) and the day's records read
before the turn; it calls nothing. Step 4 passes it, with the last few messages, in place of the replay, behind a
company setting (plan: docs/plans/ASSISTANT_RELIABILITY_2026-11-10.md section 11).
"""

from __future__ import annotations

import datetime as dt
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from .agent import REPEAT_WINDOW_S, line_key
from .reply_guard import without_ids

#: The headings the model reads (and the conversation tests look for). One meaning each; never reworded per turn.
TODAY = "Today, per site (from the records)"
CARD = "On the card now (waiting for Save; a change to a line changes that numbered line, never drops it)"
HELD = "Waiting for one answer (held by Mesiri; never prepare these again)"
ASKED = "The question Mesiri asked last"
CANCELLED = "Cancelled in this chat (the person said no: never prepare these again unless this message says them again)"
SAVED = "Saved in this chat (already saved: never prepare them again; a follow-up on one uses its id)"
EARLIER = "Earlier days"
ACT_ON = "The message to act on"

#: WA-278 / WA-280: how long lines wait for their answer before they are let go (the person has moved on).
HELD_SECONDS = 30 * 60
#: How long a cancel is remembered (a working day; the chat state itself lives 24 hours).
CANCELLED_SECONDS = 18 * 3600
CANCELLED_KEPT = 20
#: Lines per heading at most: the block stays small on a long day.
SAVED_SHOWN = 12
RECORDED_SHOWN = 12
#: An earlier day: at most this many records named, and this long.
EARLIER_RECORDS = 3
EARLIER_CHARS = 300
#: WA-270 step 4 (plan decision 2): the messages the model keeps beside the block, three exchanges.
WINDOW = 6


@dataclass(frozen=True)
class SiteDay:
    """One site's working day from the records: the workers that count (the Today page's count, WA-287's
    ``day_totals``) and the other records, oldest first."""

    site: str
    workers: int | None = None
    trades: tuple[tuple[str, int], ...] = ()
    recorded: tuple[str, ...] = field(default_factory=tuple)


def _place(row: dict[str, Any], names: dict[str, str]) -> str:
    """The site of a record, or its project when it has no site (a project with no site yet takes reports too)."""
    site = str(row.get("site_id") or "")
    return site if site in names else str(row.get("project_id") or "") if not site else ""


def today_by_site(day_totals: Iterable[dict[str, Any]] | None, records: Iterable[dict[str, Any]] | None,
                  names: dict[str, str], day: dt.date) -> list[SiteDay]:
    """The day per site from two reads the API already has: ``GET /labour/attendance`` ``day_totals`` (WA-287, the
    count that holds) and ``GET /timeline`` items (the day's). ``names``: the person's sites, and their projects for
    records that have no site. A timeline row for labour is left out (the total stands for it, so a corrected report
    is never counted twice); a place the person cannot see is left out."""
    workers: dict[str, tuple[int, tuple[tuple[str, int], ...]]] = {}
    for total in day_totals or []:
        place = _place(total, names)
        if place not in names or str(total.get("occurred_date") or "") != day.isoformat():
            continue
        trades = tuple((str(t.get("trade") or ""), int(t.get("workers") or 0))
                       for t in total.get("trades") or [] if int(t.get("workers") or 0) > 0)
        workers[place] = (int(total.get("workers") or 0), trades)
    recorded: dict[str, list[str]] = {}
    for row in sorted(records or [], key=lambda r: str(r.get("occurred_at") or "")):
        place = _place(row, names)
        kind = str(row.get("event_type") or "")
        if place not in names or kind.casefold().startswith("labour"):  # LabourAttendanceRecorded / Voided
            continue
        summary = without_ids(str(row.get("summary") or "")).strip()
        if summary:
            recorded.setdefault(place, []).append(f"{kind}: {summary}" if kind else summary)
    days = []
    for place, name in names.items():
        if place not in workers and place not in recorded:
            continue
        count, trades = workers.get(place, (None, ()))
        days.append(SiteDay(site=name, workers=count, trades=trades, recorded=tuple(recorded.get(place, ()))))
    return days


def earlier_days(day_totals: Iterable[dict[str, Any]] | None, records: Iterable[dict[str, Any]] | None,
                 names: dict[str, str], days: Sequence[dt.date]) -> list[tuple[dt.date, str]]:
    """One line per earlier day that has records, oldest first: per site the workers counted and the first few
    records ("Main Block: 12 workers; 2 records: 95 bags cement; Water tank leak"). A record's day is the date of its
    ``occurred_at``, as ``GET /timeline`` filters by it."""
    totals, rows = list(day_totals or []), list(records or [])
    lines = []
    for day in sorted(days):
        sites = today_by_site(totals, [r for r in rows if str(r.get("occurred_at") or "")[:10] == day.isoformat()],
                              names, day)
        parts = []
        for site in sites:
            bits = [f"{site.workers} workers"] if site.workers is not None else []
            if site.recorded:
                said = "; ".join(r.split(": ", 1)[-1] for r in site.recorded[:EARLIER_RECORDS])
                more = ", ..." if len(site.recorded) > EARLIER_RECORDS else ""
                bits.append(f"{len(site.recorded)} records: {said}{more}")
            parts.append(f"{site.site}: " + "; ".join(bits))
        if parts:
            line = " | ".join(parts)
            lines.append((day, line if len(line) <= EARLIER_CHARS else line[:EARLIER_CHARS - 3] + "..."))
    return lines


def held_lines(state: dict, now: float) -> list[dict]:
    """The lines of this chat still waiting for one answer (the site, a material, a unit, a person). "site_held" is
    the key WA-278 kept them under (site lines only); read until it has aged out."""
    kept = state.get("held") or state.get("site_held") or {}
    if not isinstance(kept, dict) or now - float(kept.get("at") or 0) > HELD_SECONDS:
        return []
    return [h for h in kept.get("lines") or [] if isinstance(h, dict) and h.get("tool")]


def _held_line(hold: dict) -> str:
    words = str((hold.get("arguments") or {}).get("summary") or hold.get("word") or hold["tool"])
    gap = str(hold.get("gap") or "")
    return without_ids(words) + (f" (waiting for: {gap})" if gap else "")


def remember_cancelled(state: dict, lines: Iterable[dict[str, Any] | str], now: float | None = None) -> None:
    """Keep what a Cancel let go, for the rest of the working day (``state["cancel_log"]``): each line's words and
    its ``key`` (``agent.line_key``), which the code checks a new line against (WA-294). The WA-146 key ``cancelled``
    is the last Cancel only, taken by the reason tap next; this one is the day's."""
    now = time.time() if now is None else now
    kept = [c for c in state.get("cancel_log") or []
            if isinstance(c, dict) and now - float(c.get("at") or 0) < CANCELLED_SECONDS]
    for line in lines:
        entry = {"summary": line} if isinstance(line, str) else dict(line)
        if str(entry.get("summary") or "").strip():
            kept.append({**entry, "at": now})
    state["cancel_log"] = kept[-CANCELLED_KEPT:] or None


def cancelled_lines(state: dict, now: float | None = None) -> list[dict[str, Any]]:
    """The lines cancelled in this chat in the working day, oldest first."""
    now = time.time() if now is None else now
    return [c for c in state.get("cancel_log") or []
            if isinstance(c, dict) and c.get("summary") and now - float(c.get("at") or 0) < CANCELLED_SECONDS]


def _summaries(rows: Any) -> list[str]:
    return [str(r.get("summary") or r.get("tool") or "") for r in rows or [] if isinstance(r, dict)]


def _site_line(day: SiteDay) -> list[str]:
    head = f"- {day.site}:"
    if day.workers is not None:
        trades = ", ".join(f"{n} {t}" for t, n in day.trades)
        head += f" {day.workers} workers counted" + (f" ({trades})" if trades else "")
    else:
        head += " no attendance yet"
    lines = [head]
    shown = day.recorded[-RECORDED_SHOWN:]
    if len(day.recorded) > len(shown):
        lines.append(f"  ({len(day.recorded) - len(shown)} earlier records not shown)")
    lines += [f"  - {r}" for r in shown]
    return lines


def state_block(state: dict, *, message: str, now: float | None = None,
                today: Sequence[SiteDay] | None = None,
                earlier: Sequence[tuple[dt.date, str]] = (), since: float | None = None) -> str:
    """The block the model reads before the last few messages. ``state``: the chat state as stored (``pending``,
    ``held``, ``asked``, ``cancel_log``, ``recent_saves``); ``today``: the day per site (``today_by_site``), None when
    it could not be read (said so, never "nothing"); ``earlier``: one line per earlier day, oldest first.
    ``since``: when the working day began (epoch seconds); a save before it is an earlier day's, not "in this chat".
    ``message`` is what this turn answers, marked last. A heading with nothing under it is left out, except the
    card, which always says whether one is waiting."""
    now = time.time() if now is None else now
    parts: list[str] = []

    if today is None:
        parts.append(f"{TODAY}: could not be read now; look it up if the answer needs it.")
    elif not today:
        parts.append(f"{TODAY}: nothing recorded yet.")
    else:
        parts.append(f"{TODAY}:\n" + "\n".join(line for day in today for line in _site_line(day)))

    card = [without_ids(s) for s in _summaries(state.get("pending"))]
    if card:
        parts.append(f"{CARD}:\n" + "\n".join(f"{i}. {s}" for i, s in enumerate(card, 1)))
    else:
        parts.append("On the card now: nothing is waiting for Save.")

    held = held_lines(state, now)
    if held:
        parts.append(f"{HELD}:\n" + "\n".join(f"- {_held_line(h)}" for h in held))

    asked = state.get("asked") if isinstance(state.get("asked"), dict) else None
    if asked and str(asked.get("question") or "").strip():
        options = " / ".join(str(o) for o in asked.get("options") or [])
        parts.append(f"{ASKED}: \"{without_ids(str(asked['question']).strip())}\""
                     + (f" (options: {options})" if options else "")
                     + ". Only a message that answers it is its answer.")

    # Live, 14 Nov: the same cancel listed three times, and a line said again (now on the card) still listed as
    # cancelled. Once each, newest kept; a line on the card now is not "cancelled".
    on_card = {line_key(str(e.get("tool") or ""), e.get("body") or {}) for e in state.get("pending") or []
               if isinstance(e, dict)} - {None}
    on_card_words = {without_ids(s) for s in _summaries(state.get("pending"))}
    cancelled, seen = [], set()
    for c in reversed(cancelled_lines(state, now)):
        words = without_ids(str(c["summary"]))
        repeat = words in seen or bool(c.get("key") and c["key"] in seen)
        seen.update(x for x in (words, c.get("key")) if x)  # live, 14 Nov 05:19: logged before keys and after: one line
        if repeat or c.get("key") in on_card or words in on_card_words:
            continue
        cancelled.insert(0, words)
    if cancelled:
        parts.append(f"{CANCELLED}:\n" + "\n".join(f"- {c}" for c in cancelled))

    saved = [r for r in state.get("recent_saves") or []
             if isinstance(r, dict) and now - float(r.get("at") or 0) < REPEAT_WINDOW_S
             and float(r.get("at") or 0) >= (since or 0)][-SAVED_SHOWN:]
    if saved:
        parts.append(f"{SAVED}:\n" + "\n".join(
            f"- {without_ids(str(r.get('summary') or ''))}" + (f" ({r['tool']}, id {r['id']})" if r.get("id") else "")
            for r in saved))

    if earlier:
        parts.append(f"{EARLIER}:\n" + "\n".join(f"- {day:%a %d %b}: {line}" for day, line in earlier))

    parts.append(f"{ACT_ON} (the only one to act on; everything above is state, not a request):\n\"{message.strip()}\"")
    return "\n\n".join(parts)
