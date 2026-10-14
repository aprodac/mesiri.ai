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


def _send_message(*, code: str | None, payload: dict[str, Any], reason: str) -> str:
    """The text that goes with the PDF. A roll-up sent before every site
    confirmed says how many did not report -- the most important line."""
    message = f"Today's DPR ({code or 'DPR'}) is attached."
    if payload.get("level") == "PROJECT":
        total = int(payload.get("total_site_count") or 0)
        missing = total - int(payload.get("reported_site_count") or 0)
        if missing > 0:
            sites = "site" if missing == 1 else "sites"
            message += f" {missing} of {total} {sites} not reported."
    if reason == "requested":
        message += " Sent on request."
    return message


async def send_due_project_dprs(
    conn: Any,
    *,
    db: Any,
    renderer: Any | None = None,
    object_storage: Any | None = None,
    now_utc: datetime.datetime | None = None,
) -> int:
    """BE-16: sends each project DPR that is due -- every site confirmed,
    the send deadline passed, or "Send now" pressed -- to the project's
    ADMIN/PROJECT_MANAGER users, with the PDF attached. Renders the PDF
    first when the render cron has not, so the owner never gets "not yet
    rendered". Returns the count of projects sent.

    Each project runs in its own savepoint: a failure (render, storage)
    rolls that project back untouched and it is retried on the next tick,
    without taking the others down. `renderer`/`object_storage` are
    injectable for tests; otherwise built only if something is due."""
    import json

    from channel.dpr_document.letterhead import load_letterhead
    from mesiri.application.projects.auto_dpr import (
        due_project_sends,
        finalize_project_dpr,
        mark_project_dpr_sent,
    )
    from mesiri.infrastructure.postgres.repositories.dpr import PostgresDprRepository
    from mesiri.infrastructure.postgres.repositories.notifications import (
        PostgresNotificationRepository,
    )

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

                    object_key = report["rendered_object_key"]
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
                        )
                        await repo.set_rendered_object_key(
                            version_id=report["version_id"], object_key=object_key
                        )

                    message = _send_message(
                        code=report["code"], payload=payload, reason=project["reason"]
                    )
                    recipients = await _project_dpr_recipients(
                        db,
                        organization_id=str(project["organization_id"]),
                        project_id=project_id,
                    )
                    for recipient_id in recipients:
                        # subject = the recipient: the notifications UNIQUE
                        # key is (org, rule, subject, date), so a shared
                        # subject let only the first recipient through --
                        # the pre-BE-16 cutoff message had that bug.
                        await notifications_repo.claim(
                            organization_id=project["organization_id"],
                            rule_key=f"project_dpr_send:{project_id}",
                            subject_id=recipient_id,
                            occurred_on=project["report_date"],
                            recipient_user_id=uuid.UUID(recipient_id),
                            project_id=project["id"],
                            site_id=target["site_id"],
                            payload={"message": message, "document_object_key": object_key},
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
