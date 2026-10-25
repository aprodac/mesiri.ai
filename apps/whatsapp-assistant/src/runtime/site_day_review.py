"""The evening review of each site's day on WhatsApp (WA-04).

Between a project's cutoff (drafts built, each site day labelled) and its
send deadline (the project DPR goes out), each site's engineer gets one
message about their site's day. Which one is decided in the backend
(mesiri/application/dpr/evening_review.py):

    gap-check (WA-04, here)   "today's report is missing the labour count"
    confirm   (WA-05, here)   "today's report is ready" + Confirm all / Fix something
    reminder  (WA-06, here)   "no update has come in today for Block A"

WA-05: "Confirm all" is offered only when nothing on the day needs a second
look (evening_review.confirm_all_holds: likely repeats, items the AI was
unsure of, heavily forwarded or undated forwarded ones); otherwise the
message says what to check and offers only "Fix something". Fix something
lists the day's drafts; each can be kept or removed (BE-09's confirm /
reject), and the day's message comes back up to date after each tap.
"Confirm all" confirms the day the same way the dashboard does
(approve_report: its drafts are confirmed with it).

What the engineer sends back is saved the usual way (save first, WA-01);
every tick `refresh_site_day` brings a day that changed up to date, so a
filled gap turns the day ready within about a minute.

Runs inside automation_runner.py's tick, like project_auto_dpr.py: one
`notifications` row per (site, recipient, day) -- the table's UNIQUE key
makes it go once -- delivered by the shared send step. Outside WhatsApp's
24-hour window the row goes as the approved template `mesiri_site_day_review`,
whose "Open report" tap brings the full message; until that template is
approved, such a row is skipped with `template_not_approved:...`.

Taps carry what they are about -- `sdr:<action>:<site id>:<yyyymmdd>` -- and
are checked against the sites the person may report on, so no state is kept
between the message and the tap.
"""

from __future__ import annotations

import datetime
import logging
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from channel.replies import ListRow, ReplySpec

if TYPE_CHECKING:
    from backend.ports import ActorIdentity
    from mesiri.infrastructure.postgres.database import PostgresDatabase

logger = logging.getLogger("mesiri.site_day_review")

TAP_PREFIX = "sdr:"
OPEN = "open"  # the template's "Open report"
CLOSED = "closed"  # "Site closed today" -> the day is marked no work (BE-14)
CONFIRM = "confirm"  # "Confirm all" -> the day is confirmed (WA-05)
FIX = "fix"  # "Fix something" -> the day's drafts to keep or remove
_ACTIONS = frozenset({OPEN, CLOSED, CONFIRM, FIX})
# Taps about one item: sdr:<action>:<site id>:<yyyymmdd>:<fact type>:<fact id>
ITEM = "item"  # an item picked from the list -> Keep / Remove
KEEP = "keep"
REMOVE = "rm"
_ITEM_ACTIONS = frozenset({ITEM, KEEP, REMOVE})

CLOSED_BUTTON_TITLE = "Site closed today"
CONFIRM_BUTTON_TITLE = "Confirm all"
FIX_BUTTON_TITLE = "Fix something"
KEEP_BUTTON_TITLE = "Keep it"
REMOVE_BUTTON_TITLE = "Remove it"
#: WhatsApp lists hold at most 10 rows.
_MAX_ROWS = 10

#: How each must-have section is named in the message.
_SECTION_NAMES = {"work_done": "work done", "labour": "labour count"}

CLOSED_DONE = "👍 Marked *{site}* as closed today. Today's report will say there was no work."
ALREADY_CONFIRMED = "Today's report for *{site}* is already confirmed."
NOT_YOUR_SITE = "That report is for a site you're not on."
EXPIRED = "That message has expired."
CONFIRMED_DONE = "✅ Confirmed today's report for *{site}*. It goes out with the project report."
FIX_INTRO = (
    "Tap an item to keep or remove it. A wrong figure? Send the right one here, "
    "then remove the wrong one."
)
FIX_MORE = "\n_{n} more on the dashboard._"
NOTHING_TO_FIX = "Nothing left to check on *{site}*. Tap *Confirm all* when it looks right."
ITEM_GONE = "That item is no longer on today's report."
REMOVED_REASON = "Removed in the evening check on WhatsApp"

#: How each hold is named in the message (evening_review.HOLDS).
_HOLD_LINES = {
    "possible_duplicate": ("{n} work item may be a repeat", "{n} work items may be repeats"),
    "low_confidence": ("{n} item I wasn't sure I read right", "{n} items I wasn't sure I read right"),
    "frequently_forwarded": ("{n} item was forwarded many times", "{n} items were forwarded many times"),
    "date_guessed": (
        "{n} forwarded item didn't say which day it was",
        "{n} forwarded items didn't say which day they were",
    ),
}


# ---------------------------------------------------------------------------
# Wording
# ---------------------------------------------------------------------------


def tap_id(action: str, site_id: Any, report_date: datetime.date) -> str:
    return f"{TAP_PREFIX}{action}:{site_id}:{report_date:%Y%m%d}"


def item_tap_id(
    action: str, site_id: Any, report_date: datetime.date, fact_type: str, fact_id: Any
) -> str:
    return f"{tap_id(action, site_id, report_date)}:{fact_type}:{fact_id}"


def parse_tap(value: str) -> tuple[str, str, datetime.date] | None:
    """(action, site id, date) from a tap id, or None if malformed."""
    parts = value[len(TAP_PREFIX) :].split(":") if value.startswith(TAP_PREFIX) else []
    if len(parts) != 3 or parts[0] not in _ACTIONS:
        return None
    try:
        return parts[0], parts[1], datetime.datetime.strptime(parts[2], "%Y%m%d").date()
    except ValueError:
        return None


def parse_item_tap(value: str) -> tuple[str, str, datetime.date, str, str] | None:
    """(action, site id, date, fact type, fact id) from an item tap id, or None."""
    parts = value[len(TAP_PREFIX) :].split(":") if value.startswith(TAP_PREFIX) else []
    if len(parts) != 5 or parts[0] not in _ITEM_ACTIONS:
        return None
    try:
        report_date = datetime.datetime.strptime(parts[2], "%Y%m%d").date()
    except ValueError:
        return None
    return parts[0], parts[1], report_date, parts[3], parts[4]


def time_label(value: str) -> str:
    """"21:00" -> "9:00 pm"."""
    hour, minute = (int(part) for part in value.split(":", 1))
    suffix = "am" if hour < 12 else "pm"
    return f"{hour % 12 or 12}:{minute:02d} {suffix}"


def site_label(site_name: str, project_name: str | None) -> str:
    """"Block A (Green Towers)", or just the name for a single-site project
    whose site is named after it."""
    if not project_name or project_name.strip().lower() == site_name.strip().lower():
        return site_name
    return f"{site_name} ({project_name})"


def day_card(
    day_payload: dict[str, Any] | None,
    *,
    site_name: str,
    report_date: datetime.date,
    deadline: str,
    status: str | None = None,
) -> dict[str, Any] | None:
    """Request 91: the Today card for a site day, as the notification payload's
    ``card`` (drawn when the row is sent, in the 24h window only). Its numbers
    are read from the day's report payload, the one the DPR draft is built
    from. None if the card cannot be built: the message goes out as text."""
    from channel.cards import build_today_card, today_payload

    confirmed = status in ("APPROVED", "PUBLISHED")
    footer = "Confirmed" if confirmed else f"Draft · goes out at {time_label(deadline)}"
    try:
        return today_payload(
            build_today_card(
                day_payload or {}, site_name=site_name, report_date=report_date, footer=footer
            )
        )
    except Exception:  # noqa: BLE001 -- the card is an extra
        logger.warning("site_day_review.card_failed site=%s", site_name, exc_info=True)
        return None


def _with_card(payload: dict[str, Any], card: dict[str, Any] | None) -> dict[str, Any]:
    return {**payload, "card": card} if card else payload


def _sections(blocking: list[str]) -> list[str]:
    return [_SECTION_NAMES.get(section, section.replace("_", " ")) for section in blocking]


def gap_check_message(
    *, site_name: str, project_name: str | None, missing: dict[str, Any], deadline: str
) -> str:
    sections = _sections(list(missing.get("blocking") or []))
    named = " and the ".join(f"*{name}*" for name in sections)
    it = "it" if len(sections) == 1 else "them"
    site = f"*{site_name}*" + (
        f" ({project_name})" if site_label(site_name, project_name) != site_name else ""
    )
    lines = [
        f"📋 {site}: today's report is missing the {named}.",
        f"Send {it} here (text, voice note or photo) before *{time_label(deadline)}* "
        "so the report goes out complete.",
    ]
    if "photos" in (missing.get("optional") or []):
        lines.append("No photos yet either. Send one or two if you can.")
    lines.append("Site closed today? Tap below.")
    return "\n".join(lines)


def no_update_message(*, site_name: str, project_name: str | None, deadline: str) -> str:
    site = f"*{site_name}*" + (
        f" ({project_name})" if site_label(site_name, project_name) != site_name else ""
    )
    return "\n".join(
        [
            f"📋 No update has come in today for {site}.",
            f"Send today's work, labour and photos here (text, voice note or photo) "
            f"before *{time_label(deadline)}* so the report goes out.",
            "Site closed today? Tap below.",
        ]
    )


def no_update_payload(
    *,
    site_id: Any,
    site_name: str,
    project_name: str | None,
    deadline: str,
    report_date: datetime.date,
    card: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """WA-06: the reminder for a site that sent nothing by the cutoff -- in
    the window as a message with the "Site closed today" button, outside it
    as the approved template whose quick reply is the same tap."""
    from channel.whatsapp.templates import SITE_NO_UPDATE

    closed = tap_id(CLOSED, site_id, report_date)
    return _with_card(
        {
            "message": no_update_message(
                site_name=site_name, project_name=project_name, deadline=deadline
            ),
            "buttons": [{"id": closed, "title": CLOSED_BUTTON_TITLE}],
            "template": {
                "name": SITE_NO_UPDATE.name,
                "body_params": [site_label(site_name, project_name), time_label(deadline)],
                "button_payloads": [closed],
            },
        },
        card,
    )


def gap_check_payload(
    *,
    site_id: Any,
    site_name: str,
    project_name: str | None,
    missing: dict[str, Any],
    deadline: str,
    report_date: datetime.date,
    card: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The notification payload: the in-window message with its button,
    and the template for an engineer outside the 24h window."""
    from channel.whatsapp.templates import SITE_DAY_REVIEW

    sections = _sections(list(missing.get("blocking") or []))
    verb = "is" if len(sections) == 1 else "are"
    return _with_card(
        {
            "message": gap_check_message(
                site_name=site_name, project_name=project_name, missing=missing, deadline=deadline
            ),
            "buttons": [{"id": tap_id(CLOSED, site_id, report_date), "title": CLOSED_BUTTON_TITLE}],
            "template": {
                "name": SITE_DAY_REVIEW.name,
                "body_params": [
                    site_label(site_name, project_name),
                    f"{' and '.join(sections)} {verb} missing.".capitalize(),
                    time_label(deadline),
                ],
                "button_payloads": [tap_id(OPEN, site_id, report_date)],
            },
        },
        card,
    )


def _count(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def day_lines(payload: dict[str, Any]) -> list[str]:
    """What the day holds, one short line per section."""
    if (payload.get("conditions") or {}).get("site_working") == "none":
        return ["• Site closed today, no work"]
    lines = []
    if payload.get("activity_count"):
        # DPR-07: what is being confirmed, not just how many ("Confirm all" on
        # "Work: 2 items" was a tap on something unseen).
        works = [
            str(a.get("work_type") or "").replace("_", " ").strip().capitalize()
            for a in payload.get("activities") or []
            if a.get("review") != "rejected"
        ]
        works = list(dict.fromkeys(w for w in works if w))
        count = _count(int(payload["activity_count"]), "item", "items")
        shown = ", ".join(works[:4]) + (f" and {len(works) - 4} more" if len(works) > 4 else "")
        lines.append(f"• Work: {shown} ({count})" if shown else f"• Work: {count}")
    labour = payload.get("labour") or {}
    headcount = labour.get("headcount")
    if headcount:
        trades = ", ".join(
            f"{t['headcount']} {str(t['trade']).replace('_', ' ').lower()}"
            for t in (labour.get("trades") or [])[:4]
            if t.get("trade") and t.get("headcount")
        )
        workers = _count(int(headcount), "worker", "workers")
        lines.append(f"• Labour: {workers} ({trades})" if trades else f"• Labour: {workers}")
    if payload.get("materials"):
        # The names, not a count: "2 entries" read as two saves when it was
        # two materials (round 3, 21 Oct).
        names = [
            str(m.get("material_name") or m.get("name") or "").strip() for m in payload["materials"]
        ]
        names = list(dict.fromkeys(n for n in names if n))
        shown = ", ".join(names[:4]) + (f" and {len(names) - 4} more" if len(names) > 4 else "")
        if not shown:
            shown = _count(len(payload["materials"]), "entry", "entries")
        lines.append(f"• Materials: {shown}")
    # The day's own issues only: an issue still open from an earlier day
    # (BE-51's carried_issues) is not something the day holds, and an empty
    # list here means "nothing logged today".
    if "issues" in payload:
        day_open = sum(
            1 for i in payload["issues"] or [] if i.get("status") in ("OPEN", "ACKNOWLEDGED")
        )
    else:  # a summary without the issue list
        day_open = int(payload.get("open_issue_count") or 0)
    if day_open:
        lines.append(f"• Issues: {day_open} open")
    if payload.get("evidence_count"):
        lines.append(f"• Photos: {payload['evidence_count']}")
    return lines


def confirm_message(
    *,
    site_name: str,
    project_name: str | None,
    payload: dict[str, Any],
    holds: dict[str, int],
    deadline: str,
) -> str:
    """WA-05: the day's summary, and either the one-tap confirm or what to
    check first."""
    site = f"*{site_name}*" + (
        f" ({project_name})" if site_label(site_name, project_name) != site_name else ""
    )
    lines = [f"📋 {site}: today's report is ready.", *day_lines(payload)]
    stock = int(payload.get("stock_flags") or 0)
    if stock:
        lines.append(
            "⚠️ "
            + _count(stock, "material is", "materials are")
            + " more than the stock on record."
        )
    if holds:
        lines.append("")
        lines.append("Please check first:")
        for hold, n in holds.items():
            one, many = _HOLD_LINES.get(hold, ("{n} item to check", "{n} items to check"))
            lines.append("• " + (one if n == 1 else many).format(n=n))
        lines.append(f"Tap *Fix something* to go through them before *{time_label(deadline)}*.")
    else:
        lines.append("")
        lines.append(
            f"Tap *Confirm all* if it's right. It goes out with the project report at "
            f"*{time_label(deadline)}*."
        )
    return "\n".join(lines)


def confirm_buttons(
    site_id: Any, report_date: datetime.date, *, holds: dict[str, int]
) -> tuple[ListRow, ...]:
    fix = ListRow(id=tap_id(FIX, site_id, report_date), title=FIX_BUTTON_TITLE)
    if holds:
        return (fix,)
    return (ListRow(id=tap_id(CONFIRM, site_id, report_date), title=CONFIRM_BUTTON_TITLE), fix)


def confirm_payload(
    *,
    site_id: Any,
    site_name: str,
    project_name: str | None,
    day_payload: dict[str, Any],
    holds: dict[str, int],
    deadline: str,
    report_date: datetime.date,
    card: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The notification payload for a ready day. Outside the 24h window it
    goes as the gap-check's template (WA-04, same wording slot); its "Open
    report" tap brings this message with its buttons."""
    from channel.whatsapp.templates import SITE_DAY_REVIEW

    buttons = confirm_buttons(site_id, report_date, holds=holds)
    return _with_card(
        {
            "message": confirm_message(
                site_name=site_name,
                project_name=project_name,
                payload=day_payload,
                holds=holds,
                deadline=deadline,
            ),
            "buttons": [{"id": b.id, "title": b.title} for b in buttons],
            "template": {
                "name": SITE_DAY_REVIEW.name,
                "body_params": [
                    site_label(site_name, project_name),
                    "Some items need a look before you confirm."
                    if holds
                    else "It is ready to confirm.",
                    time_label(deadline),
                ],
                "button_payloads": [tap_id(OPEN, site_id, report_date)],
            },
        },
        card,
    )


# ---------------------------------------------------------------------------
# The scheduler step
# ---------------------------------------------------------------------------


async def _recipients(
    conn: Any, db: Any, *, organization_id: Any, project_id: Any, site_id: Any, report_date: datetime.date
) -> list[str]:
    """The site's engineers; else whoever saved drafts on the day; else the
    project's admins and managers."""
    from mesiri.application.projects.auto_dpr import site_day_reporters

    from .automation_audience import _site_engineers_for_sites
    from .project_auto_dpr import _project_dpr_recipients

    engineers = await _site_engineers_for_sites(
        db, organization_id=str(organization_id), site_ids=[str(site_id)]
    )
    if engineers:
        return sorted(engineers)
    reporters = await site_day_reporters(
        conn, organization_id=organization_id, site_id=site_id, report_date=report_date
    )
    if reporters:
        return reporters
    return await _project_dpr_recipients(
        db, organization_id=str(organization_id), project_id=str(project_id)
    )


async def _sites_already_messaged(
    conn: Any, *, organization_id: Any, project_id: Any, report_date: datetime.date, prefix: str
) -> set[str]:
    import sqlalchemy as sa

    rows = (
        await conn.execute(
            sa.text(
                "SELECT DISTINCT site_id FROM notifications "
                "WHERE organization_id = :org_id AND project_id = :project_id "
                "AND occurred_on = :d AND rule_key LIKE :prefix"
            ),
            {
                "org_id": organization_id,
                "project_id": project_id,
                "d": report_date,
                "prefix": f"{prefix}%",
            },
        )
    ).mappings().all()
    return {str(row["site_id"]) for row in rows}


async def _review_project(conn: Any, db: Any, project: dict[str, Any]) -> int:
    from mesiri.application.dpr import evening_review
    from mesiri.application.projects.auto_dpr import (
        refresh_site_day,
        site_day_for_confirm,
        site_days_for_review,
    )
    from mesiri.infrastructure.postgres.repositories.notifications import (
        PostgresNotificationRepository,
    )

    organization_id, project_id = project["organization_id"], project["id"]
    report_date = project["report_date"]
    # Sites already sent each message today (one of each per site per day).
    sent = {
        step: await _sites_already_messaged(
            conn,
            organization_id=organization_id,
            project_id=project_id,
            report_date=report_date,
            prefix=evening_review.RULE_KEY_PREFIXES[step],
        )
        for step in (evening_review.GAP_CHECK, evening_review.NO_UPDATE, evening_review.CONFIRM)
    }
    notifications = PostgresNotificationRepository(conn)
    queued = 0
    for day in await site_days_for_review(
        conn, organization_id=organization_id, project_id=project_id, report_date=report_date
    ):
        if evening_review.needs_refresh(
            last_fact_at=day["last_fact_at"], day_updated_at=day["day_updated_at"]
        ):
            refreshed = await refresh_site_day(
                conn,
                organization_id=organization_id,
                project_id=project_id,
                site_id=day["site_id"],
                report_date=report_date,
            )
            if refreshed is not None:
                day = {**day, "status": refreshed["status"], "missing_sections": refreshed["missing_sections"]}

        step = evening_review.evening_step(
            status=day["status"], missing=day["missing_sections"], has_facts=day["has_facts"]
        )
        if step not in sent or str(day["site_id"]) in sent[step]:
            continue

        holds: dict[str, int] = {}
        if step == evening_review.CONFIRM:
            confirm_day = await site_day_for_confirm(
                conn,
                organization_id=organization_id,
                site_id=day["site_id"],
                report_date=report_date,
            )
            if confirm_day is None:
                continue
            holds = evening_review.confirm_all_holds(
                payload=confirm_day["payload"], drafts=confirm_day["drafts"]
            )
            payload = confirm_payload(
                site_id=day["site_id"],
                site_name=day["site_name"],
                project_name=project["name"],
                day_payload=confirm_day["payload"],
                holds=holds,
                deadline=project["send_deadline"],
                report_date=report_date,
                card=day_card(
                    confirm_day["payload"],
                    site_name=day["site_name"],
                    report_date=report_date,
                    deadline=project["send_deadline"],
                    status=confirm_day["status"],
                ),
            )
        elif step == evening_review.NO_UPDATE:
            payload = no_update_payload(
                site_id=day["site_id"],
                site_name=day["site_name"],
                project_name=project["name"],
                deadline=project["send_deadline"],
                report_date=report_date,
                card=day_card(
                    None,
                    site_name=day["site_name"],
                    report_date=report_date,
                    deadline=project["send_deadline"],
                ),
            )
        else:
            # The day so far, from the same report payload as the DPR draft.
            gap_day = await site_day_for_confirm(
                conn,
                organization_id=organization_id,
                site_id=day["site_id"],
                report_date=report_date,
            )
            payload = gap_check_payload(
                site_id=day["site_id"],
                site_name=day["site_name"],
                project_name=project["name"],
                missing=day["missing_sections"] or {},
                deadline=project["send_deadline"],
                report_date=report_date,
                card=day_card(
                    gap_day["payload"] if gap_day else None,
                    site_name=day["site_name"],
                    report_date=report_date,
                    deadline=project["send_deadline"],
                    status=gap_day["status"] if gap_day else None,
                ),
            )
        for user_id in await _recipients(
            conn,
            db,
            organization_id=organization_id,
            project_id=project_id,
            site_id=day["site_id"],
            report_date=report_date,
        ):
            claimed = await notifications.claim(
                organization_id=organization_id,
                rule_key=evening_review.rule_key(step, day["site_id"]),
                subject_id=user_id,
                occurred_on=report_date,
                recipient_user_id=uuid.UUID(user_id),
                project_id=project_id,
                site_id=day["site_id"],
                payload=payload,
            )
            if claimed is not None:
                queued += 1
        # WA-05: `holds` is logged so how often each signal fires can be counted.
        logger.info(
            "site_day_review.%s site_id=%s missing=%s holds=%s",
            step,
            day["site_id"],
            (day["missing_sections"] or {}).get("blocking"),
            ",".join(f"{hold}={n}" for hold, n in holds.items()) or "-",
        )
    return queued


async def queue_site_day_reviews(
    conn: Any, *, db: Any, now_utc: datetime.datetime | None = None
) -> int:
    """For every project whose day is under review (cutoff run, DPR not sent,
    before the deadline): refresh the site days that changed and queue the
    evening message each one calls for. Returns how many were queued. One
    project's failure is rolled back and logged, never stopping the rest."""
    from mesiri.application.projects.auto_dpr import projects_in_review_window

    queued = 0
    now = now_utc or datetime.datetime.now(datetime.UTC)
    for project in await projects_in_review_window(conn, now_utc=now):
        try:
            async with conn.begin_nested():
                queued += await _review_project(conn, db, project)
        except Exception:  # noqa: BLE001
            logger.exception("site_day_review.failed project_id=%s", project["id"])
    return queued


# ---------------------------------------------------------------------------
# Taps
# ---------------------------------------------------------------------------


def _same_id(a: Any, b: Any) -> bool:
    from .save_first import canonical_uuid

    return canonical_uuid(a) is not None and canonical_uuid(a) == canonical_uuid(b)


class SiteDayReview:
    """Answers the evening message's taps."""

    def __init__(self, db: PostgresDatabase) -> None:
        self._db = db

    async def handle_tap(self, message: Any, actor: ActorIdentity) -> ReplySpec | None:
        tap = str((message.metadata or {}).get("interactive_reply_id") or "")
        if not tap.startswith(TAP_PREFIX):
            return None
        item = parse_item_tap(tap)
        parsed = parse_tap(tap) if item is None else item[:3]
        if parsed is None:
            return ReplySpec(text=EXPIRED)
        action, site_id, report_date = parsed
        site = next((s for s in actor.sites if _same_id(s.id, site_id)), None)
        if site is None or not site.project_id or not actor.organization_id:
            return ReplySpec(text=NOT_YOUR_SITE)

        day = _Day(
            organization_id=uuid.UUID(str(actor.organization_id)),
            project_id=uuid.UUID(str(site.project_id)),
            site_id=uuid.UUID(str(site_id)),
            site_name=site.name,
            report_date=report_date,
            user_id=_uuid_or_none(getattr(actor, "user_id", None)),
        )
        if item is not None:
            from .save_first import canonical_uuid

            fact_id = canonical_uuid(item[4])
            if fact_id is None:
                return ReplySpec(text=EXPIRED)
            return await self._item(day, action, item[3], uuid.UUID(str(fact_id)))
        if action == CLOSED:
            return await self._mark_closed(
                day.organization_id, day.project_id, day.site_id, day.site_name, report_date
            )
        if action == CONFIRM:
            return await self._confirm(day)
        if action == FIX:
            return await self._fix(day)
        return await self._open(
            day.organization_id, day.project_id, day.site_id, day.site_name, report_date
        )

    async def _mark_closed(
        self,
        organization_id: uuid.UUID,
        project_id: uuid.UUID,
        site_id: uuid.UUID,
        site_name: str,
        report_date: datetime.date,
    ) -> ReplySpec:
        from mesiri.application.dpr import site_day
        from mesiri.infrastructure.postgres.repositories.dpr import PostgresDprRepository

        try:
            async with self._db.transaction() as conn:
                await PostgresDprRepository(conn).set_site_day_conditions(
                    organization_id=organization_id,
                    project_id=project_id,
                    site_id=site_id,
                    report_date=report_date,
                    changes={"site_working": site_day.SITE_WORKING_NONE},
                )
        except site_day.InvalidSiteDayTransition:
            return ReplySpec(text=ALREADY_CONFIRMED.format(site=site_name))
        logger.info("site_day_review.closed site_id=%s date=%s", site_id, report_date)
        return ReplySpec(text=CLOSED_DONE.format(site=site_name))

    async def _open(
        self,
        organization_id: uuid.UUID,
        project_id: uuid.UUID,
        site_id: uuid.UUID,
        site_name: str,
        report_date: datetime.date,
    ) -> ReplySpec:
        """The template's "Open report": the full message, as it stands now."""
        import sqlalchemy as sa

        from mesiri.application.dpr import evening_review, site_day
        from mesiri.application.projects.auto_dpr import (
            refresh_site_day,
            send_deadline_or_default,
            site_days_for_review,
        )

        async with self._db.transaction() as conn:
            project = (
                await conn.execute(
                    sa.text("SELECT name, dpr_send_deadline FROM projects WHERE id = :id"),
                    {"id": project_id},
                )
            ).mappings().first()
            days = await site_days_for_review(
                conn, organization_id=organization_id, project_id=project_id, report_date=report_date
            )
            day = next((d for d in days if d["site_id"] == site_id), None)
            if day is None or project is None:
                return ReplySpec(text=EXPIRED)
            if day["status"] in site_day.FROZEN:
                return ReplySpec(text=ALREADY_CONFIRMED.format(site=site_name))
            if evening_review.needs_refresh(
                last_fact_at=day["last_fact_at"], day_updated_at=day["day_updated_at"]
            ):
                refreshed = await refresh_site_day(
                    conn,
                    organization_id=organization_id,
                    project_id=project_id,
                    site_id=site_id,
                    report_date=report_date,
                )
                if refreshed is not None:
                    day = {**day, **refreshed}

        missing = day["missing_sections"] or {}
        if not missing.get("blocking"):
            # WA-05: a ready day's "Open report" brings the confirmation.
            return await self._current(
                _Day(organization_id, project_id, site_id, site_name, report_date, None)
            )
        return ReplySpec(
            text=gap_check_message(
                site_name=site_name,
                project_name=project["name"],
                missing=missing,
                deadline=send_deadline_or_default(project["dpr_send_deadline"]),
            ),
            buttons=(ListRow(id=tap_id(CLOSED, site_id, report_date), title=CLOSED_BUTTON_TITLE),),
        )

    # -- WA-05 ---------------------------------------------------------------

    async def _current(self, day: _Day) -> ReplySpec:
        """The day's confirmation message as it stands now, with its buttons."""
        import sqlalchemy as sa

        from mesiri.application.dpr import evening_review, site_day
        from mesiri.application.projects.auto_dpr import (
            refresh_site_day,
            send_deadline_or_default,
            site_day_for_confirm,
        )

        async with self._db.transaction() as conn:
            project = (
                await conn.execute(
                    sa.text("SELECT name, dpr_send_deadline FROM projects WHERE id = :id"),
                    {"id": day.project_id},
                )
            ).mappings().first()
            refreshed = await refresh_site_day(
                conn,
                organization_id=day.organization_id,
                project_id=day.project_id,
                site_id=day.site_id,
                report_date=day.report_date,
            )
            confirm_day = await site_day_for_confirm(
                conn,
                organization_id=day.organization_id,
                site_id=day.site_id,
                report_date=day.report_date,
            )
        if confirm_day is None or project is None:
            return ReplySpec(text=EXPIRED)
        if refreshed is None or confirm_day["status"] in site_day.FROZEN:
            return ReplySpec(text=ALREADY_CONFIRMED.format(site=day.site_name))
        deadline = send_deadline_or_default(project["dpr_send_deadline"])
        missing = refreshed.get("missing_sections") or {}
        if missing.get("blocking"):
            return ReplySpec(
                text=gap_check_message(
                    site_name=day.site_name,
                    project_name=project["name"],
                    missing=missing,
                    deadline=deadline,
                ),
                buttons=(
                    ListRow(id=tap_id(CLOSED, day.site_id, day.report_date), title=CLOSED_BUTTON_TITLE),
                ),
            )
        holds = evening_review.confirm_all_holds(
            payload=confirm_day["payload"], drafts=confirm_day["drafts"]
        )
        return ReplySpec(
            text=confirm_message(
                site_name=day.site_name,
                project_name=project["name"],
                payload=confirm_day["payload"],
                holds=holds,
                deadline=deadline,
            ),
            buttons=confirm_buttons(day.site_id, day.report_date, holds=holds),
        )

    async def _confirm(self, day: _Day) -> ReplySpec:
        """"Confirm all": the day is confirmed as the dashboard does it, unless
        something that holds it back arrived since the message went."""
        from mesiri.application.dpr import evening_review, site_day
        from mesiri.application.projects.auto_dpr import site_day_for_confirm
        from mesiri.infrastructure.postgres.repositories.dpr import PostgresDprRepository

        async with self._db.transaction() as conn:
            confirm_day = await site_day_for_confirm(
                conn,
                organization_id=day.organization_id,
                site_id=day.site_id,
                report_date=day.report_date,
            )
            if confirm_day is None:
                return ReplySpec(text=EXPIRED)
            if confirm_day["status"] in site_day.FROZEN:
                return ReplySpec(text=ALREADY_CONFIRMED.format(site=day.site_name))
            holds = evening_review.confirm_all_holds(
                payload=confirm_day["payload"], drafts=confirm_day["drafts"]
            )
            if not holds and day.user_id is not None:
                approved = await PostgresDprRepository(conn).approve_report(
                    organization_id=day.organization_id,
                    user_id=day.user_id,
                    report_id=confirm_day["daily_report_id"],
                    notes=None,
                )
                if approved:
                    logger.info(
                        "site_day_review.confirmed site_id=%s date=%s", day.site_id, day.report_date
                    )
                    return ReplySpec(text=CONFIRMED_DONE.format(site=day.site_name))
        # Something changed (a new draft to check, a missing section): show
        # the day as it is now.
        return await self._current(day)

    async def _fix(self, day: _Day) -> ReplySpec:
        """"Fix something": the day's drafts, the ones to check first."""
        from mesiri.application.dpr import fact_review
        from mesiri.infrastructure.postgres.repositories.dpr import PostgresDprRepository

        async with self._db.transaction() as conn:
            _, items = await PostgresDprRepository(conn).assemble_site_day(
                organization_id=day.organization_id,
                project_id=day.project_id,
                site_id=day.site_id,
                report_date=day.report_date,
            )
        drafts = [i for i in items if i.get("review") == fact_review.DRAFT]
        if not drafts:
            return ReplySpec(
                text=NOTHING_TO_FIX.format(site=day.site_name),
                buttons=(
                    ListRow(id=tap_id(CONFIRM, day.site_id, day.report_date), title=CONFIRM_BUTTON_TITLE),
                ),
            )
        drafts.sort(key=lambda i: not i.get("flags"))
        rows = tuple(
            ListRow(
                id=item_tap_id(ITEM, day.site_id, day.report_date, i["fact_type"], i["id"]),
                title=_short(i.get("title") or "Item", 24),
                description=_short(_item_detail(i), 72),
            )
            for i in drafts[:_MAX_ROWS]
        )
        extra = len(drafts) - len(rows)
        return ReplySpec(
            text=FIX_INTRO + (FIX_MORE.format(n=extra) if extra > 0 else ""),
            list_button_label="Today's items",
            list_rows=rows,
        )

    async def _item(self, day: _Day, action: str, fact_type: str, fact_id: uuid.UUID) -> ReplySpec:
        from mesiri.application.dpr import fact_review
        from mesiri.infrastructure.postgres.repositories.dpr import PostgresDprRepository
        from mesiri.infrastructure.postgres.repositories.fact_reviews import (
            PostgresFactReviewRepository,
        )

        if fact_type not in fact_review.FACT_TYPES:
            return ReplySpec(text=EXPIRED)
        async with self._db.transaction() as conn:
            reviews = PostgresFactReviewRepository(conn)
            try:
                located = await reviews.locate(day.organization_id, fact_type, fact_id)
            except fact_review.FactReviewError:
                return ReplySpec(text=ITEM_GONE)
            if not _same_id(located.get("site_id"), day.site_id):
                return ReplySpec(text=NOT_YOUR_SITE)
            state = (await reviews.states_for(fact_type, [fact_id])).get(fact_id)
            if state != fact_review.DRAFT:
                return ReplySpec(text=ITEM_GONE)
            if action == ITEM:
                _, items = await PostgresDprRepository(conn).assemble_site_day(
                    organization_id=day.organization_id,
                    project_id=day.project_id,
                    site_id=day.site_id,
                    report_date=day.report_date,
                )
                picked = next((i for i in items if i["id"] == str(fact_id)), None)
                if picked is None:
                    return ReplySpec(text=ITEM_GONE)
                detail = _item_detail(picked)
                return ReplySpec(
                    text=f"*{picked.get('title') or 'Item'}*" + (f"\n{detail}" if detail else ""),
                    buttons=(
                        ListRow(
                            id=item_tap_id(KEEP, day.site_id, day.report_date, fact_type, fact_id),
                            title=KEEP_BUTTON_TITLE,
                        ),
                        ListRow(
                            id=item_tap_id(REMOVE, day.site_id, day.report_date, fact_type, fact_id),
                            title=REMOVE_BUTTON_TITLE,
                        ),
                    ),
                )
            try:
                if action == KEEP:
                    await reviews.confirm(
                        organization_id=day.organization_id,
                        fact_type=fact_type,
                        fact_id=fact_id,
                        actor_user_id=day.user_id,
                    )
                else:
                    await reviews.reject(
                        organization_id=day.organization_id,
                        fact_type=fact_type,
                        fact_id=fact_id,
                        actor_user_id=day.user_id,
                        reason=REMOVED_REASON,
                    )
            except fact_review.FactReviewError:
                return ReplySpec(text=ITEM_GONE)
        logger.info("site_day_review.item_%s fact_type=%s site_id=%s", action, fact_type, day.site_id)
        # The day's message again, up to date: one fewer item to check.
        return await self._current(day)


@dataclass(frozen=True, slots=True)
class _Day:
    organization_id: uuid.UUID
    project_id: uuid.UUID
    site_id: uuid.UUID
    site_name: str
    report_date: datetime.date
    user_id: uuid.UUID | None


def _item_detail(item: dict[str, Any]) -> str:
    parts = []
    if "possible_duplicate" in (item.get("flags") or []):
        parts.append("May be a repeat")
    if item.get("detail"):
        parts.append(str(item["detail"]))
    quantities = item.get("quantities") or []
    if quantities:
        parts.append(
            ", ".join(f"{q.get('quantity')} {q.get('unit') or ''}".strip() for q in quantities)
        )
    return " · ".join(parts)


def _short(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _uuid_or_none(value: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None
