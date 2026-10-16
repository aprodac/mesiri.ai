"""The evening review of each site's day on WhatsApp (WA-04).

Between a project's cutoff (drafts built, each site day labelled) and its
send deadline (the project DPR goes out), each site's engineer gets one
message about their site's day. Which one is decided in the backend
(mesiri/application/dpr/evening_review.py):

    gap-check (WA-04, here)   "today's report is missing the labour count"
    confirm   (WA-05)         not built yet: such a day gets no message
    reminder  (WA-06, here)   "no update has come in today for Block A"

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
from typing import TYPE_CHECKING, Any

from channel.replies import ListRow, ReplySpec

if TYPE_CHECKING:
    from backend.ports import ActorIdentity
    from mesiri.infrastructure.postgres.database import PostgresDatabase

logger = logging.getLogger("mesiri.site_day_review")

TAP_PREFIX = "sdr:"
OPEN = "open"  # the template's "Open report"
CLOSED = "closed"  # "Site closed today" -> the day is marked no work (BE-14)
_ACTIONS = frozenset({OPEN, CLOSED})

CLOSED_BUTTON_TITLE = "Site closed today"

#: How each must-have section is named in the message.
_SECTION_NAMES = {"work_done": "work done", "labour": "labour count"}

CLOSED_DONE = "👍 Marked *{site}* as closed today. Today's report will say there was no work."
NOTHING_MISSING = "✅ Today's report for *{site}* has the work done and the labour count. Nothing is missing."
ALREADY_CONFIRMED = "Today's report for *{site}* is already confirmed."
NOT_YOUR_SITE = "That report is for a site you're not on."
EXPIRED = "That message has expired."


# ---------------------------------------------------------------------------
# Wording
# ---------------------------------------------------------------------------


def tap_id(action: str, site_id: Any, report_date: datetime.date) -> str:
    return f"{TAP_PREFIX}{action}:{site_id}:{report_date:%Y%m%d}"


def parse_tap(value: str) -> tuple[str, str, datetime.date] | None:
    """(action, site id, date) from a tap id, or None if malformed."""
    parts = value[len(TAP_PREFIX) :].split(":") if value.startswith(TAP_PREFIX) else []
    if len(parts) != 3 or parts[0] not in _ACTIONS:
        return None
    try:
        return parts[0], parts[1], datetime.datetime.strptime(parts[2], "%Y%m%d").date()
    except ValueError:
        return None


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
) -> dict[str, Any]:
    """WA-06: the reminder for a site that sent nothing by the cutoff -- in
    the window as a message with the "Site closed today" button, outside it
    as the approved template whose quick reply is the same tap."""
    from channel.whatsapp.templates import SITE_NO_UPDATE

    closed = tap_id(CLOSED, site_id, report_date)
    return {
        "message": no_update_message(
            site_name=site_name, project_name=project_name, deadline=deadline
        ),
        "buttons": [{"id": closed, "title": CLOSED_BUTTON_TITLE}],
        "template": {
            "name": SITE_NO_UPDATE.name,
            "body_params": [site_label(site_name, project_name), time_label(deadline)],
            "button_payloads": [closed],
        },
    }


def gap_check_payload(
    *,
    site_id: Any,
    site_name: str,
    project_name: str | None,
    missing: dict[str, Any],
    deadline: str,
    report_date: datetime.date,
) -> dict[str, Any]:
    """The notification payload: the in-window message with its button,
    and the template for an engineer outside the 24h window."""
    from channel.whatsapp.templates import SITE_DAY_REVIEW

    sections = _sections(list(missing.get("blocking") or []))
    verb = "is" if len(sections) == 1 else "are"
    return {
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
    }


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
    from mesiri.application.projects.auto_dpr import refresh_site_day, site_days_for_review
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
        for step in (evening_review.GAP_CHECK, evening_review.NO_UPDATE)
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
        # WA-05 (confirm) adds its branch here.
        if step not in sent or str(day["site_id"]) in sent[step]:
            continue

        if step == evening_review.NO_UPDATE:
            payload = no_update_payload(
                site_id=day["site_id"],
                site_name=day["site_name"],
                project_name=project["name"],
                deadline=project["send_deadline"],
                report_date=report_date,
            )
        else:
            payload = gap_check_payload(
                site_id=day["site_id"],
                site_name=day["site_name"],
                project_name=project["name"],
                missing=day["missing_sections"] or {},
                deadline=project["send_deadline"],
                report_date=report_date,
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
        logger.info(
            "site_day_review.%s site_id=%s missing=%s",
            step,
            day["site_id"],
            (day["missing_sections"] or {}).get("blocking"),
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
        parsed = parse_tap(tap)
        if parsed is None:
            return ReplySpec(text=EXPIRED)
        action, site_id, report_date = parsed
        site = next((s for s in actor.sites if _same_id(s.id, site_id)), None)
        if site is None or not site.project_id or not actor.organization_id:
            return ReplySpec(text=NOT_YOUR_SITE)

        organization_id = uuid.UUID(str(actor.organization_id))
        project_id = uuid.UUID(str(site.project_id))
        site_uuid = uuid.UUID(str(site_id))
        if action == CLOSED:
            return await self._mark_closed(
                organization_id, project_id, site_uuid, site.name, report_date
            )
        return await self._open(organization_id, project_id, site_uuid, site.name, report_date)

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
            return ReplySpec(text=NOTHING_MISSING.format(site=site_name))
        return ReplySpec(
            text=gap_check_message(
                site_name=site_name,
                project_name=project["name"],
                missing=missing,
                deadline=send_deadline_or_default(project["dpr_send_deadline"]),
            ),
            buttons=(ListRow(id=tap_id(CLOSED, site_id, report_date), title=CLOSED_BUTTON_TITLE),),
        )
