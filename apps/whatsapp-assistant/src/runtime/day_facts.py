"""Day Facts (request 137): what is saved for one site on one day, and the one
rule every part of the assistant uses to ask about it.

Before this, each part read saved work its own way: the correction lookup wanted a
quantity, the card matched lines by position, and the readers counted a progress
update only through its parent activity. A percentage ("tiling 80%") has no
quantity, so a correction found nothing, and a continuation hung off a parent
the readers hid. This module is the shared definition. It adds no table: facts
come from the saved card (each item carries its fact id) and the day readers
(``runtime/agent/project_day``); the database rule is ``fact_review``'s.

- ``counted``: a fact is saved when its latest review is not a draft. One
  definition, delegated to ``fact_review.counts`` so the readers and this module
  cannot drift apart.
- ``WorkFact``: a saved work item with its fact id, site, work key (the work and
  the place) and its value (a percent or a quantity).
- ``resolve_percent``: a newer percent for the same work is a NEW line; only an
  explicit correction ("alla, 75%") edits the saved one, found by fact id.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from mesiri.application.dpr import fact_review

PERCENT = "percent"
QUANTITY = "quantity"

#: What the resolver decides for one percent the sender sent.
NEW_LINE = "new_line"
CHANGE = "change"
NOTHING = "nothing"


def counted(state: str | None) -> bool:
    """Whether a fact in this review state is part of the record. Saved facts
    (confirmed, or never reviewed) count; a draft does not until it is saved."""
    return fact_review.counts(state)


#: SQL for "this activity can be continued": its latest review is not rejected
#: (cancelled). A draft stays continuable: in the save-first flow the day's entries
#: are drafts until the evening confirmation, and skipping them made a second
#: activity for the same work. A draft_v2 Save that continues one confirms it
#: (draft_flow). ``column`` is the activity id column, from code, never input.
def open_work_sql(column: str) -> str:
    return (
        "COALESCE((SELECT fr_o.state FROM fact_reviews fr_o "
        f"WHERE fr_o.fact_type = '{fact_review.ACTIVITY}' AND fr_o.fact_id = {column} "
        f"ORDER BY fr_o.created_at DESC LIMIT 1), '{fact_review.CONFIRMED}') <> '{fact_review.REJECTED}'"
    )


def _said(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold()


def work_key(work_type: Any, location: Any) -> str:
    """The work and the place, as one comparable key ("tiling|ground floor")."""
    return f"{_said(work_type)}|{_said(location)}"


@dataclass(frozen=True, slots=True)
class WorkFact:
    """One saved work item of a day."""

    fact_id: str
    fact_type: str
    site_id: str | None
    key: str
    field: str
    value: float | None
    saved: bool = True
    work_type: str = ""
    location: str = ""
    note: str = ""
    unit: str = ""
    activity_id: str = ""
    #: The amount recorded with it (an update can carry both a percent and an
    #: amount), its unit id, and for an activity the id of its starting amount.
    quantity: float | None = None
    unit_id: str = ""
    quantity_id: str = ""


def work_fact_of(item: Any, site_id: str | None = None) -> WorkFact | None:
    """A saved card item as a work fact; None for anything but a work item."""
    args = getattr(item, "args", None) or {}
    if getattr(item, "tool", "") != "save_work_done" or not _said(args.get("work_type")):
        return None
    percent = args.get("progress_percent")
    quantities = args.get("quantities") or []
    if percent is not None:
        field, value = PERCENT, _number(percent)
    elif quantities and isinstance(quantities[0], dict):
        field, value = QUANTITY, _number(quantities[0].get("quantity"))
    else:
        field, value = QUANTITY, None
    return WorkFact(
        fact_id=str(getattr(item, "fact_id", "") or ""),
        fact_type=str(getattr(item, "fact_type", "") or ""),
        site_id=str(site_id) if site_id else (str(args.get("site")) if args.get("site") else None),
        key=work_key(args.get("work_type"), place_of(args.get("location")) or args.get("location")),
        field=field,
        value=value,
        work_type=str(args.get("work_type") or ""),
        location=str(args.get("location") or ""),
    )


def work_facts(items: Any, site_id: str | None = None) -> list[WorkFact]:
    return [f for f in (work_fact_of(i, site_id) for i in items or []) if f is not None and f.fact_id]


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


_PERCENT_UNITS = frozenset({"%", "percent", "percentage", "pct", "per cent"})
_PERCENT_WORDS = r"(?:%|percent|percentage|per\s*cent|shatham|ശതമാനം|प्रतिशत)"

#: Words that say the last figure was wrong, not that the work moved on.
_CORRECTION_CUE = re.compile(
    r"\b(alla|allaa|illa|thettu|thettiyath|thett|galat|nahi|nahin|wrong|mistake|correction|correct\s+it|"
    r"not\s+\d|no\s*,|sorry|actually|instead|change\s+(?:it|that|to)|make\s+(?:it|that))\b|അല്ല|തെറ്റ്|गलत",
    re.IGNORECASE,
)


def is_correction(text: str) -> bool:
    return bool(_CORRECTION_CUE.search(text or ""))


def is_percent(value: Any, unit: Any, text: str) -> bool:
    """Whether a figure the sender gave is a percentage: said with a percent unit,
    or written next to a percent sign in their words."""
    if _said(unit) in _PERCENT_UNITS:
        return True
    number = _number(value)
    if number is None:
        return False
    shown = f"{number:g}"
    return bool(re.search(rf"(?<![\d.]){re.escape(shown)}\s*{_PERCENT_WORDS}", text or "", re.IGNORECASE))


@dataclass(frozen=True, slots=True)
class Resolution:
    action: str
    fact: WorkFact | None = None
    reason: str = ""


def merged(card: list[WorkFact], day: list[WorkFact]) -> list[WorkFact]:
    """The day's facts (oldest first) with the saved card's on top: one entry per
    fact id, so the card and the database never disagree about which is which."""
    seen = {f.fact_id for f in day}
    return [*day, *(f for f in card if f.fact_id not in seen)]


def _named(facts: list[WorkFact], text: str) -> list[WorkFact]:
    """The facts whose work the message names ("tiling alla 75%"); all of them when
    it names none."""
    said = _said(text)
    named = [f for f in facts if f.work_type and _said(f.work_type) in said]
    return named or facts


def _newest_of_one_work(facts: list[WorkFact], text: str) -> Resolution:
    facts = _named(facts, text)
    if not facts:
        return Resolution(NOTHING, reason="nothing of yours is saved today to change")
    if len({f.key for f in facts}) > 1:
        return Resolution(NOTHING, reason="more than one work is saved today; say which work")
    return Resolution(CHANGE, facts[-1])


def resolve_percent(facts: list[WorkFact], value: Any, text: str, *, site_id: str | None = None) -> Resolution:
    """What a percent the sender sent means against what is saved.

    A correction ("alla, 75%") edits the newest saved percent of the work it names
    (or of the only work with a percent today); with several and none named,
    nothing is guessed. Any other percent ("tiling 80% aayi") is progress: a new
    line, never a correction of the earlier percent."""
    if _number(value) is None:
        return Resolution(NOTHING, reason="no figure was given")
    percents = [f for f in facts if f.field == PERCENT and (site_id is None or f.site_id in (None, site_id))]
    if not percents or not is_correction(text):
        return Resolution(NEW_LINE)
    return _newest_of_one_work(percents, text)


def resolve_quantity(facts: list[WorkFact], value: Any, unit: Any, text: str) -> Resolution:
    """A corrected amount ("correction, it was 150 not 180") edits the newest saved
    amount of the work it names (or the only work with an amount today), in the
    unit given when one is."""
    if _number(value) is None:
        return Resolution(NOTHING, reason="the right figure was not given")
    amounts = [f for f in facts if f.field == QUANTITY and f.value is not None]
    if unit and (same := [f for f in amounts if _said(f.unit) == _said(unit)]):
        amounts = same
    return _newest_of_one_work(amounts, text)


def correction_target(facts: list[WorkFact], remembered_activity_id: str | None = None) -> dict[str, Any] | None:
    """The classic Yes / No correction's target (WRK-06), from the day's facts: the
    newest amount on the activity this conversation touched, else the sender's
    newest amount. The shape the ACTIVITY_CORRECTION workflow reads."""
    amounts = [f for f in facts if f.quantity is not None]
    if remembered_activity_id:
        amounts = [f for f in amounts if f.activity_id == str(remembered_activity_id)] or amounts
    if not amounts:
        return None
    fact = amounts[-1]
    target: dict[str, Any] = {
        "quantity": fact.quantity,
        "unit_id": fact.unit_id or None,
        "unit": fact.unit or None,
        "work_type": fact.work_type,
        "narrative": fact.note,
    }
    if fact.fact_type == PROGRESS_UPDATE:
        target["progress_update_id"] = fact.fact_id
    elif fact.quantity_id:
        target["activity_quantity_id"] = fact.quantity_id
    else:
        return None
    return target


def card_item_for(fact: WorkFact, card_items: Any) -> Any:
    """The saved entry a correction changes: the saved card's own item when the
    fact is on it, else one built from the day's fact (same tool and fields, so the
    corrected entry is saved through save_work_done like any other)."""
    from runtime.agent.cards import CardItem

    for item in card_items or []:
        if str(getattr(item, "fact_id", "")) == fact.fact_id:
            return item
    args: dict[str, Any] = {"narrative": fact.note or fact.work_type, "work_type": fact.work_type}
    if fact.location:
        args["location"] = fact.location
    if fact.field == PERCENT and fact.value is not None:
        args["progress_percent"] = int(fact.value) if float(fact.value).is_integer() else fact.value
    elif fact.value is not None:
        args["quantities"] = [{"work_type": fact.work_type, "quantity": fact.value, "unit": fact.unit}]
    if fact.fact_type == PROGRESS_UPDATE:
        args["continues"] = fact.work_type
    return CardItem("save_work_done", args, fact.fact_type, fact.fact_id, fact.note or fact.work_type)


# -- the day from the database ----------------------------------------------------

#: The fact type of one progress update (work continuing an activity). Not a review
#: type (``fact_reviews`` covers the activity it belongs to): undo voids the update
#: through the progress module's own ``void_progress_update``.
PROGRESS_UPDATE = "progress_update"


def date_sql(day: Any) -> str:
    """A date from code as an SQL literal (never input: a ``datetime.date``)."""
    import datetime as dt

    if not isinstance(day, dt.date):
        raise TypeError("a date is needed")
    return f"DATE '{day.isoformat()}'"


def project_date_sql(timestamp_column: str, organization_sql: str) -> str:
    """SQL for the project's calendar date of a moment: the company's zone, India
    when unset or the untouched "UTC" (as ``channel.receipt.data.company_zone``).
    A bare ``CAST(occurred_at AS date)`` is the UTC date, so an update saved after
    midnight IST (before 05:30) counted on the day before, while its activity was
    already dated today (29 Oct re-test: tiling 82% missing from "innale").
    Both arguments are SQL from code, never input."""
    return (
        f"CAST(({timestamp_column} AT TIME ZONE COALESCE(NULLIF((SELECT o_z.timezone FROM organizations o_z "
        f"WHERE o_z.id = {organization_sql}), 'UTC'), 'Asia/Kolkata')) AS date)"
    )


def latest_note_sql(activity_column: str, end_date_param: str = ":day_facts_end") -> str:
    """SQL for what a work item says NOW: the note of its latest progress update up
    to the period's last day, else the activity's own note. ``activity_column`` is
    from code; the end date is a bound parameter. Used by every day reader, so
    "tiling 70%" then "tiling 80%" reads 80% everywhere."""
    update_day = project_date_sql(
        "pu_l.occurred_at", "(SELECT a_o.organization_id FROM activities a_o WHERE a_o.id = pu_l.activity_id)"
    )
    return (
        "COALESCE((SELECT pu_l.narrative FROM progress_updates pu_l "
        f"WHERE pu_l.activity_id = {activity_column} AND pu_l.deleted_at IS NULL "
        f"AND pu_l.narrative IS NOT NULL AND {update_day} <= {end_date_param} "
        "ORDER BY pu_l.occurred_at DESC, pu_l.created_at DESC LIMIT 1), "
        "(SELECT a_l.narrative FROM activities a_l WHERE a_l.id = " + activity_column + "))"
    )


def project_today_for(actor: Any) -> Any:
    """The sender's project day (the company's zone), as every day reader takes it."""
    from canonicalization.occurred_date import today_for
    from channel.receipt.data import company_zone

    return today_for(str(company_zone(getattr(actor, "timezone", None))))


def place_of(text: str | None) -> str:
    """The floor or place named in a saved note ("Tiling, ground floor: 70%")."""
    from canonicalization.progress import find_place

    return find_place(text or "") or ""


def _fact_from_row(row: Any) -> WorkFact:
    from canonicalization.progress import find_percent

    note = str(row["narrative"] or "")
    percent = find_percent(note)
    if percent is not None:
        field, value = PERCENT, float(percent)
    else:
        field, value = QUANTITY, _number(row["quantity"])
    place = place_of(note)
    return WorkFact(
        fact_id=str(row["fact_id"]),
        fact_type=str(row["fact_type"]),
        site_id=str(row["site_id"]) if row["site_id"] else None,
        key=work_key(row["work_type"], place),
        field=field,
        value=value,
        saved=bool(row["saved"]),
        work_type=str(row["work_type"] or ""),
        location=place,
        note=note,
        unit=str(row["unit"] or ""),
        activity_id=str(row["activity_id"]),
        quantity=_number(row["quantity"]),
        unit_id=str(row["unit_id"] or ""),
        quantity_id=str(row["quantity_id"] or ""),
    )


class DayFactsReader:
    """The day's work facts from the database, the one way: every activity of the
    period and every progress update on it, each with its own fact id, in the
    order they were recorded. Read-only."""

    def __init__(self, db: Any) -> None:
        self._db = db

    async def work(
        self,
        *,
        organization_id: str,
        start: Any,
        end: Any,
        site_id: str | None = None,
        reported_by_user_id: str | None = None,
        include_pending: bool = False,
    ) -> list[WorkFact]:
        import uuid

        import sqlalchemy as sa

        try:
            params: dict[str, Any] = {"org": uuid.UUID(str(organization_id)), "start": start, "end": end}
            scope = ""
            if site_id:
                params["site"] = uuid.UUID(str(site_id))
                scope += " AND a.site_id = :site"
            if reported_by_user_id:
                params["user"] = uuid.UUID(str(reported_by_user_id).removeprefix("ctx_user_"))
                scope += " AND a.reported_by_user_id = :user"
        except (TypeError, ValueError):
            return []
        saved = f"({fact_review.counted_sql(fact_review.ACTIVITY, 'a.id')})"
        pending = "" if include_pending else f" AND {saved}"
        sql = (
            "SELECT * FROM ("
            f" SELECT 'activity' AS fact_type, a.id AS fact_id, a.id AS activity_id, a.site_id, a.work_type,"
            f"        a.narrative, aq.quantity, u.code AS unit, aq.unit_id, aq.id AS quantity_id, a.created_at,"
            f"        {saved} AS saved"
            " FROM activities a"
            " LEFT JOIN LATERAL (SELECT id, quantity, unit_id FROM activity_quantities q WHERE q.activity_id = a.id"
            "                    ORDER BY q.created_at LIMIT 1) aq ON true"
            " LEFT JOIN units_of_measure u ON u.id = aq.unit_id"
            " WHERE a.organization_id = :org AND a.deleted_at IS NULL"
            "   AND a.activity_date BETWEEN :start AND :end" + scope + pending +
            " UNION ALL"
            f" SELECT '{PROGRESS_UPDATE}', pu.id, a.id, a.site_id, a.work_type, pu.narrative, pu.quantity, u.code,"
            f"        pu.unit_id, NULL, pu.created_at, {saved}"
            " FROM progress_updates pu JOIN activities a ON a.id = pu.activity_id"
            " LEFT JOIN units_of_measure u ON u.id = pu.unit_id"
            " WHERE a.organization_id = :org AND a.deleted_at IS NULL AND pu.deleted_at IS NULL"
            f"   AND {project_date_sql('pu.occurred_at', 'a.organization_id')} BETWEEN :start AND :end" + scope + pending +
            ") f ORDER BY created_at"
        )
        async with self._db.transaction() as conn:
            rows = (await conn.execute(sa.text(sql), params)).mappings().all()
        return [_fact_from_row(r) for r in rows]

    async def latest_update(self, activity_id: str) -> str | None:
        """The newest progress update on an activity: the fact a Save that continued
        it just wrote (read inside the Save's own transaction)."""
        import uuid

        import sqlalchemy as sa

        try:
            act = uuid.UUID(str(activity_id))
        except (TypeError, ValueError):
            return None
        async with self._db.transaction() as conn:
            found = (
                await conn.execute(
                    sa.text(
                        "SELECT id FROM progress_updates WHERE activity_id = :a AND deleted_at IS NULL"
                        " ORDER BY created_at DESC LIMIT 1"
                    ),
                    {"a": act},
                )
            ).scalar_one_or_none()
        return str(found) if found is not None else None
