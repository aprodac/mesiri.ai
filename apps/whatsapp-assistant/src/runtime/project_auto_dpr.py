"""Scheduler steps: make `projects.auto_generate_dpr` actually send a DPR.

Two steps (BE-16): `queue_due_project_auto_dprs` builds the drafts at the
project's cutoff; `send_due_project_dprs` sends the project DPR once every
site is confirmed, at the send deadline, or on "Send now".

Sibling to automation_runner.py's `_queue_due_automations` -- same shape
(find due rows, generate/build a payload, claim one `notifications` row per
recipient, mark the row run), called from the SAME tick
(automation_runner.py's `run_tick`) so it shares that module's advisory
lock, 60s-interval loop, and `_drain_and_send` delivery step rather than
running a second scheduler process.

Not implemented as a synthetic `automations` row on purpose: an automation
is always owned by a user (`created_by`), but a project's own standing DPR
schedule isn't anyone's personal automation -- it's a property of the
project itself, set by whoever last edited the dashboard's reporting tab.
Giving it a fake owner would mean picking one arbitrarily and having that
person's automation silently vanish/misbehave if they leave the project.
"""

from __future__ import annotations

import datetime
import logging
import uuid
from typing import Any

logger = logging.getLogger("mesiri.project_auto_dpr")


async def _project_dpr_recipients(
    db: Any, *, organization_id: str, project_id: str
) -> list[str]:
    """ADMIN + PROJECT_MANAGER reachable from this project -- the same
    audience an automation's ROLE resolution would compute for either role
    individually (see runtime/automation_audience.py's
    `_active_users_with_role`), just for two roles instead of one. Site
    engineers aren't included: a project-wide daily rollup is a management
    report, not something every site engineer needs pushed to them."""
    from .automation_audience import _active_users_with_role

    admins = await _active_users_with_role(
        db, organization_id=organization_id, project_id=project_id, role="ADMIN"
    )
    managers = await _active_users_with_role(
        db, organization_id=organization_id, project_id=project_id, role="PROJECT_MANAGER"
    )
    return sorted(set(admins) | set(managers))


async def _dpr_audience(
    conn: Any, db: Any, *, organization_id: Any, project_id: Any
) -> list[dict[str, str]]:
    """BE-15: the project's own recipient list (report_recipients) when it
    has one -- company users by user id, outside contacts by phone --
    otherwise the default admins + project managers. Whether each may
    actually be messaged (opt-in / opt-out) is decided at send time, in
    runtime/send_pending_notifications.py, so a skip is recorded per row."""
    from mesiri.infrastructure.postgres.repositories.report_recipients import (
        PostgresReportRecipientRepository,
    )

    rows = await PostgresReportRecipientRepository(conn).list_active(
        organization_id=organization_id, project_id=project_id
    )
    if not rows:
        defaults = await _project_dpr_recipients(
            db, organization_id=str(organization_id), project_id=str(project_id)
        )
        return [{"user_id": user_id} for user_id in defaults]
    return [
        {"user_id": str(row["user_id"])}
        if row["user_id"] is not None
        else {"recipient_id": str(row["id"]), "phone": row["phone"]}
        for row in rows
    ]


async def queue_due_project_auto_dprs(conn: Any, *, db: Any) -> int:
    """At each due project's cutoff: builds today's drafts (SITE-level days,
    labelled needs details / ready) and marks the cutoff run. Sends
    nothing -- since BE-16 the owner/PM get the DPR from
    `send_due_project_dprs`, once it is confirmed or at the send deadline.
    Returns the count of projects that fired.

    Every project is handled independently and best-effort: one project's
    failure is logged and skipped, never allowed to abort the rest of the
    scan (same "a bad row can't take down the tick" principle
    automation_runner.py's own loop applies)."""
    from mesiri.application.automations.scheduling import local_now
    from mesiri.application.projects.auto_dpr import (
        due_projects_for_auto_dpr,
        generate_project_dpr,
        mark_project_auto_dpr_run,
    )

    now_utc = datetime.datetime.now(datetime.UTC)
    fired = 0

    for project in await due_projects_for_auto_dpr(conn, now_utc=now_utc):
        project_id = str(project["id"])
        report_date = local_now(
            timezone_name=project["reporting_timezone"] or "UTC", now_utc=now_utc
        ).date()

        try:
            async with conn.begin_nested():
                await generate_project_dpr(
                    conn,
                    organization_id=project["organization_id"],
                    project_id=project["id"],
                    report_date=report_date,
                )
                await mark_project_auto_dpr_run(conn, project_id=project["id"], ran_on=report_date)
        except Exception:  # noqa: BLE001
            logger.exception("project_auto_dpr.generate_failed project_id=%s", project_id)
            continue
        fired += 1

    return fired


async def _unconfirmed_updates(
    conn: Any, *, organization_id: Any, project_id: Any, report_date: datetime.date
) -> dict[str, int]:
    """Request [58]: how many updates each site's unconfirmed day holds, by
    site name. A site whose updates are saved but not confirmed is not
    "not reported" -- it reported, nobody confirmed. Sites with no report row
    or no updates are left out. Best-effort: a failure only costs the detail."""
    import sqlalchemy as sa

    try:
        async with conn.begin_nested():  # a failed read must not poison the send's transaction
            result = await conn.execute(
                sa.text(
                    """
                    SELECT s.name AS site_name,
                           COALESCE((v.payload ->> 'activity_count')::int, 0) AS updates
                    FROM daily_reports r
                    JOIN sites s ON s.id = r.site_id
                    JOIN daily_report_versions v ON v.id = r.current_version_id
                    WHERE r.organization_id = :org_id AND r.project_id = :project_id
                      AND r.report_date = :report_date AND r.level = 'SITE'
                      AND r.status IN ('DRAFT', 'IN_REVIEW')
                    """
                ),
                {"org_id": organization_id, "project_id": project_id, "report_date": report_date},
            )
        rows = result.mappings().all()
    except Exception:  # noqa: BLE001 -- the status line is still true without the detail
        logger.warning("project_dpr_send.unconfirmed_lookup_failed project_id=%s", project_id, exc_info=True)
        return {}
    return {row["site_name"]: int(row["updates"]) for row in rows if int(row["updates"]) > 0}


def _coverage_line(payload: dict[str, Any], unconfirmed: dict[str, int] | None) -> str:
    """The roll-up's most important line: who is missing from it. A site with
    saved but unconfirmed updates is named with its count ("Kakkanad: 3
    updates, not confirmed yet"); only the rest are "not reported". Empty
    when every site reported or the report is a single site's."""
    if payload.get("level") != "PROJECT":
        return ""
    total = int(payload.get("total_site_count") or 0)
    missing = [s for s in payload.get("sites") or [] if not s.get("reported")]
    count = total - int(payload.get("reported_site_count") or 0)
    if count <= 0:
        return ""
    parts: list[str] = []
    waiting = 0
    for site in missing:
        updates = (unconfirmed or {}).get(site.get("site_name") or "", 0)
        if updates:
            waiting += 1
            parts.append(
                f"{site['site_name']}: {updates} update{'' if updates == 1 else 's'}, not confirmed yet."
            )
    rest = count - waiting
    if rest > 0:
        sites = "site" if rest == 1 else "sites"
        parts.append(f"{rest} of {total} {sites} not reported.")
    return " ".join(parts)


def _send_message(
    *,
    code: str | None,
    payload: dict[str, Any],
    reason: str,
    unconfirmed: dict[str, int] | None = None,
) -> str:
    """The text that goes with the PDF. A roll-up sent before every site
    confirmed says who is missing -- the most important line."""
    message = f"Today's DPR ({code or 'DPR'}) is attached."
    coverage = _coverage_line(payload, unconfirmed)
    if coverage:
        message += f" {coverage}"
    if reason == "requested":
        message += " Sent on request."
    return message


def _template_params(
    *,
    code: str | None,
    payload: dict[str, Any],
    reason: str,
    report_date: datetime.date,
    unconfirmed: dict[str, int] | None = None,
) -> list[str]:
    """WA-12: the three body values of the `mesiri_dpr_delivery` template
    (channel/whatsapp/templates.py), used when the recipient is outside the
    24h window: project, date, and the same status line as the in-window
    text -- above all how many sites did not report."""
    project = payload.get("project_name") or code or "your project"
    try:
        day = datetime.date.fromisoformat(str(payload.get("report_date")))
    except ValueError:
        day = report_date
    date_label = f"{day.day} {day.strftime('%b %Y')}"

    if payload.get("level") == "PROJECT":
        status = _coverage_line(payload, unconfirmed) or "All sites reported."
    else:
        status = "Confirmed by the site engineer."
    if reason == "requested":
        status += " Sent on request."
    return [str(project), date_label, status]


async def send_due_project_dprs(
    conn: Any,
    *,
    db: Any,
    renderer: Any | None = None,
    object_storage: Any | None = None,
    now_utc: datetime.datetime | None = None,
    summary_writer: Any | None = None,
) -> int:
    """BE-16: sends each project DPR that is due -- every site confirmed,
    the send deadline passed, or "Send now" pressed -- to the project's
    ADMIN/PROJECT_MANAGER users, with the PDF attached. Renders the PDF
    first when the render cron has not, so the owner never gets "not yet
    rendered". Returns the count of projects sent.

    Each project runs in its own savepoint: a failure (render, storage)
    rolls that project back untouched and it is retried on the next tick,
    without taking the others down. `renderer`/`object_storage` are
    injectable for tests; otherwise built only if something is due.

    BE-18: right before a frozen version's PDF is made, `summary_writer`
    (runtime/dpr_summary.py) writes its summary of the confirmed facts. No
    writer, a failure or a rejected summary: the PDF goes without one."""
    import json

    from channel.dpr_document.letterhead import load_letterhead
    from channel.whatsapp.templates import DPR_DELIVERY
    from mesiri.application.projects.auto_dpr import (
        due_project_sends,
        finalize_project_dpr,
        mark_project_dpr_sent,
    )
    from mesiri.infrastructure.postgres.repositories.dpr import PostgresDprRepository
    from mesiri.infrastructure.postgres.repositories.notifications import (
        PostgresNotificationRepository,
    )

    from .dpr_summary import ensure_summary
    from .render_pending_dpr_pdfs import render_and_store_version

    due = await due_project_sends(conn, now_utc=now_utc or datetime.datetime.now(datetime.UTC))
    if not due:
        return 0

    owns_renderer = renderer is None
    if renderer is None:
        from channel.dpr_document.render import DprPdfRenderer

        renderer = DprPdfRenderer()
    if object_storage is None:
        from mesiri.bootstrap.settings import Settings as BackendSettings
        from mesiri.infrastructure.objectstorage import build_object_storage

        object_storage = build_object_storage(BackendSettings())

    repo = PostgresDprRepository(conn)
    notifications_repo = PostgresNotificationRepository(conn)
    sent = 0
    try:
        for project in due:
            project_id = str(project["id"])
            try:
                async with conn.begin_nested():
                    target = await finalize_project_dpr(
                        conn,
                        organization_id=project["organization_id"],
                        project_id=project["id"],
                        report_date=project["report_date"],
                    )
                    if target is None:
                        continue
                    report = await repo.get_report_for_pdf(
                        organization_id=project["organization_id"],
                        report_id=target["daily_report_id"],
                    )
                    if report is None:
                        logger.warning("project_dpr_send.no_version project_id=%s", project_id)
                        continue
                    payload = report["payload"]
                    if isinstance(payload, str):
                        payload = json.loads(payload)

                    # BE-18: a frozen version without a summary gets one now. A
                    # single-site project sends the site's own version, whose
                    # PDF may predate it: re-rendered once, so the PDF the owner
                    # gets carries the summary (stored, so never again).
                    object_key = report["rendered_object_key"]
                    summary = report.get("narrative_summary")
                    if report.get("workflow_status") in ("APPROVED", "PUBLISHED") and not summary:
                        summary = await ensure_summary(
                            summary_writer,
                            repo.set_narrative_summary,
                            version_id=report["version_id"],
                            organization_id=project["organization_id"],
                            payload=payload,
                            existing=None,
                        )
                        if summary:
                            object_key = None
                    if not object_key:
                        object_key = await render_and_store_version(
                            renderer=renderer,
                            object_storage=object_storage,
                            daily_report_id=target["daily_report_id"],
                            version_id=report["version_id"],
                            code=report["code"],
                            payload=payload,
                            letterhead=await load_letterhead(
                                conn, object_storage, target["daily_report_id"]
                            ),
                            summary=summary,
                        )
                        await repo.set_rendered_object_key(
                            version_id=report["version_id"], object_key=object_key
                        )

                    unconfirmed = await _unconfirmed_updates(
                        conn,
                        organization_id=project["organization_id"],
                        project_id=project["id"],
                        report_date=project["report_date"],
                    )
                    message = _send_message(
                        code=report["code"],
                        payload=payload,
                        reason=project["reason"],
                        unconfirmed=unconfirmed,
                    )
                    template_params = _template_params(
                        code=report["code"],
                        payload=payload,
                        reason=project["reason"],
                        report_date=project["report_date"],
                        unconfirmed=unconfirmed,
                    )
                    recipients = await _dpr_audience(
                        conn,
                        db,
                        organization_id=project["organization_id"],
                        project_id=project["id"],
                    )
                    for recipient in recipients:
                        payload = {
                            "message": message,
                            "document_object_key": object_key,
                            "template": {
                                "name": DPR_DELIVERY.name,
                                "body_params": template_params,
                            },
                        }
                        user_id = recipient.get("user_id")
                        if user_id is None:
                            # BE-15 outside contact: no user row, so the
                            # number rides in the payload, and nothing goes
                            # until they have opted in.
                            payload["to_wa_id"] = recipient["phone"]
                            payload["requires_opt_in"] = True
                        # subject = the recipient: the notifications UNIQUE
                        # key is (org, rule, subject, date), so a shared
                        # subject let only the first recipient through --
                        # the pre-BE-16 cutoff message had that bug.
                        await notifications_repo.claim(
                            organization_id=project["organization_id"],
                            rule_key=f"project_dpr_send:{project_id}",
                            subject_id=user_id or f"contact:{recipient['recipient_id']}",
                            occurred_on=project["report_date"],
                            recipient_user_id=uuid.UUID(user_id) if user_id else None,
                            project_id=project["id"],
                            site_id=target["site_id"],
                            payload=payload,
                        )
                    await mark_project_dpr_sent(
                        conn,
                        project_id=project["id"],
                        report_date=project["report_date"],
                        daily_report_id=target["daily_report_id"],
                    )
                logger.info(
                    "project_dpr_send.sent project_id=%s reason=%s level=%s recipients=%s",
                    project_id,
                    project["reason"],
                    target["level"],
                    len(recipients),
                )
                sent += 1
            except Exception:  # noqa: BLE001
                logger.exception("project_dpr_send.failed project_id=%s", project_id)
    finally:
        if owns_renderer:
            await renderer.close()
    return sent
