"""In-process scheduler for user-defined automations (recurring nudges and
digests -- "every day at 5pm send me the DPR", "at 3pm tell me who hasn't
reported").

An async loop started from runtime/lifecycle.py's FastAPI lifespan,
electing exactly one runner across `uvicorn --workers N` via a Postgres
advisory lock, interval/startup-delay tunable via
environment, every tick logged. This is what removes automations'
dependency on an ops-managed cron -- the existing Makefile targets
(dpr-generate, notification-checks, ...) stay as manual/backup entry
points, but automations fire from inside this running process.

One tick:
  1. Acquire the advisory lock (skip the tick if another worker holds it).
  2. For every enabled automation whose local wall-clock time has passed
     and hasn't already fired today (application/automations/scheduling.py's
     `is_due`): resolve its audience, build its payload, claim one
     `notifications` row per recipient (migration 0453's UNIQUE constraint
     is the real at-most-once guarantee; a claim lost to a race is a
     harmless no-op, not a duplicate), then mark the automation run.
  2b. Same for every project with `auto_generate_dpr=true` whose own
     reporting_cutoff_time/reporting_timezone says it's due
     (project_auto_dpr.py's `queue_due_project_auto_dprs`) -- generates
     that project's own drafts. Then `send_due_project_dprs` sends each
     project DPR that is confirmed, past its send deadline, or requested
     with "Send now" to its ADMIN/PROJECT_MANAGER recipients (BE-16). Not
     a user-owned automation row (see that module's
     docstring for why), but the same due-check/claim/mark shape, so it
     rides the same tick rather than needing its own scheduler.
  2c. Between those two, the evening review of each site's day
     (site_day_review.py, WA-04): days that changed since the cutoff are
     refreshed and each site's engineer is told what is still missing.
  3. Drain and send every pending notification
     (runtime/send_pending_notifications.py's `drain_and_send` -- the exact
     same 24h-session-window / quiet-hours / skip-with-reason policy #9
     Notifications already uses, not a second copy of it).

Both phases run while the lock is held, so two workers ticking at once
can't both drain the same 'pending' row concurrently.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import os
import uuid
from typing import Any

logger = logging.getLogger("mesiri.automation_runner")

# Unique to this scheduler -- unrelated schedulers must never contend for
# the same lock.
_ADVISORY_LOCK_KEY = 0x4A70_6D0B  # "automations" -- mnemonic only


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("automation_runner.bad_env name=%s value=%r using default=%s", name, raw, default)
        return default


def runner_enabled() -> bool:
    return os.environ.get("MESIRI_AUTOMATIONS__ENABLED", "true").strip().lower() not in (
        "false",
        "0",
        "no",
    )


def interval_seconds() -> int:
    """How often to check for due automations. Environment-tunable, floored
    so a misconfigured value can't turn this into a busy-loop."""
    return max(_env_int("MESIRI_AUTOMATIONS__INTERVAL_SECONDS", 60), 30)


def startup_delay_seconds() -> int:
    return max(_env_int("MESIRI_AUTOMATIONS__STARTUP_DELAY_SECONDS", 30), 0)


async def _queue_due_automations(conn: Any, *, db: Any) -> int:
    """Finds every due automation and claims one notifications row per
    resolved recipient. Returns the count of automations that fired
    (regardless of how many recipients each reached)."""
    from mesiri.application.automations.scheduling import is_due
    from mesiri.infrastructure.postgres.repositories.automations import (
        PostgresAutomationRepository,
    )
    from mesiri.infrastructure.postgres.repositories.notifications import (
        PostgresNotificationRepository,
    )

    from .automation_actions import build_payload
    from .automation_audience import resolve_audience
    from .dpr_request_query import DprRequestQueryService
    from .reporting_compliance_query import ReportingComplianceQueryService

    automations_repo = PostgresAutomationRepository(conn)
    notifications_repo = PostgresNotificationRepository(conn)
    dpr_query = DprRequestQueryService(db)
    compliance_query = ReportingComplianceQueryService(db)

    now_utc = datetime.datetime.now(datetime.UTC)
    fired = 0

    for automation in await automations_repo.list_enabled():
        try:
            due = is_due(
                frequency=automation["frequency"],
                day_of_week=automation.get("day_of_week"),
                time_of_day=automation["time_of_day"],
                timezone_name=automation.get("timezone") or "UTC",
                last_run_on=automation.get("last_run_on"),
                now_utc=now_utc,
            )
        except Exception:  # noqa: BLE001
            logger.exception("automation_runner.is_due_failed automation_id=%s", automation["id"])
            continue
        if not due:
            continue

        try:
            recipients = await resolve_audience(
                db=db, compliance_query=compliance_query, automation=automation
            )
            payload = await build_payload(
                dpr_query=dpr_query, compliance_query=compliance_query, automation=automation
            )
        except Exception:  # noqa: BLE001
            logger.exception("automation_runner.build_failed automation_id=%s", automation["id"])
            continue

        occurred_on = _local_date(automation, now_utc)
        for recipient_id in recipients:
            try:
                await notifications_repo.claim(
                    organization_id=automation["organization_id"],
                    rule_key=f"automation:{automation['id']}",
                    subject_id=recipient_id,
                    occurred_on=occurred_on,
                    recipient_user_id=uuid.UUID(recipient_id),
                    project_id=automation.get("project_id"),
                    site_id=automation.get("site_id"),
                    payload=payload,
                )
            except Exception:  # noqa: BLE001
                logger.exception(
                    "automation_runner.claim_failed automation_id=%s recipient=%s",
                    automation["id"],
                    recipient_id,
                )

        await automations_repo.mark_run(automation_id=automation["id"], ran_on=occurred_on)
        fired += 1

    return fired


def _local_date(automation: dict[str, Any], now_utc: datetime.datetime) -> datetime.date:
    from mesiri.application.automations.scheduling import local_now

    return local_now(timezone_name=automation.get("timezone") or "UTC", now_utc=now_utc).date()


async def run_tick(
    *, db: Any, summary_writer: Any = None, card_renderer: Any = None
) -> dict[str, int] | None:
    """One scheduler tick. Returns counts, or None if another worker held
    the lock (not an error -- exactly one runner per tick is the point)."""
    from sqlalchemy import text

    async with db.transaction() as conn:
        acquired = (
            await conn.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": _ADVISORY_LOCK_KEY})
        ).scalar()
        if not acquired:
            logger.debug("automation_runner.skipped_lock_held")
            return None

        try:
            fired = await _queue_due_automations(conn, db=db)

            # BE-13: entries that reached an already-confirmed site day:
            # reopen the day (report not sent yet) or record a revision.
            # Before the auto-DPR send below, so an entry that arrives before
            # the report goes out reopens the day instead of missing it.
            try:
                from mesiri.application.dpr.late_entries import process_late_entries

                async with conn.begin_nested():
                    late = await process_late_entries(conn)
                if late.recorded:
                    logger.info(
                        "automation_runner.late_entries recorded=%s reopened=%s revised=%s",
                        late.recorded,
                        late.reopened_days,
                        late.revised_days,
                    )
            except Exception:  # noqa: BLE001
                logger.exception("automation_runner.late_entries_failed")

            from .project_auto_dpr import queue_due_project_auto_dprs, send_due_project_dprs

            # Request 124: the one reminder for a card nobody tapped, before the
            # report time. In a savepoint: a failure here must not abort the tick.
            try:
                from .draft_reminder import queue_draft_reminders

                async with conn.begin_nested():
                    fired += await queue_draft_reminders(conn)
            except Exception:  # noqa: BLE001
                logger.exception("automation_runner.draft_reminders_failed")

            try:
                fired += await queue_due_project_auto_dprs(conn, db=db)
            except Exception:  # noqa: BLE001
                logger.exception("automation_runner.project_auto_dpr_failed")

            # WA-04: between the cutoff and the send deadline, each site's
            # engineer hears what their day is missing. Before the DPR send,
            # so a day the engineer just completed is refreshed first. In a
            # savepoint: a failure here must not abort this tick's transaction.
            from .site_day_review import queue_site_day_reviews

            try:
                async with conn.begin_nested():
                    fired += await queue_site_day_reviews(conn, db=db)
            except Exception:  # noqa: BLE001
                logger.exception("automation_runner.site_day_review_failed")

            try:
                fired += await send_due_project_dprs(conn, db=db, summary_writer=summary_writer)
            except Exception:  # noqa: BLE001
                logger.exception("automation_runner.project_dpr_send_failed")

            # SS-08: trial-ending reminders, queued for the drain below. In a
            # savepoint: a failure here must not abort this tick's transaction.
            try:
                from mesiri.application.organizations.trial import queue_trial_reminders

                async with conn.begin_nested():
                    fired += await queue_trial_reminders(conn)
            except Exception:  # noqa: BLE001
                logger.exception("automation_runner.trial_reminders_failed")

            sent_skipped = {"sent": 0, "skipped": 0}
            try:
                sent_skipped = await _drain_and_send(db=db, card_renderer=card_renderer)
            except Exception:  # noqa: BLE001
                logger.exception("automation_runner.drain_failed")

            if fired or sent_skipped["sent"] or sent_skipped["skipped"]:
                logger.info(
                    "automation_runner.tick fired=%s sent=%s skipped=%s",
                    fired,
                    sent_skipped["sent"],
                    sent_skipped["skipped"],
                )
            return {"fired": fired, **sent_skipped}
        finally:
            await conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": _ADVISORY_LOCK_KEY})


async def _drain_and_send(*, db: Any, card_renderer: Any = None) -> dict[str, int]:
    """Builds a throwaway WhatsApp sender + object storage for this tick and
    drains every pending notification through the shared #9 Notifications
    send policy. A fresh httpx client per tick is simpler and safe at this
    interval (default 60s floor 30s) -- the alternative (a long-lived
    client threaded in from lifecycle.py) is a reasonable future
    optimization, not a correctness requirement."""
    import httpx

    from backend.postgres.actor import PostgresActorReader
    from channel.whatsapp.outbound import WhatsAppSender
    from channel.whatsapp.templates import approved_template_names
    from mesiri.bootstrap.settings import Settings as BackendSettings
    from mesiri.infrastructure.objectstorage import build_object_storage
    from runtime.dependencies import Settings as WhatsAppSettings
    from runtime.send_pending_notifications import drain_and_send

    whatsapp_settings = WhatsAppSettings()  # type: ignore[call-arg]
    backend_settings = BackendSettings()

    async with httpx.AsyncClient(timeout=15.0) as http_client:
        sender = WhatsAppSender(
            client=http_client,
            access_token=whatsapp_settings.access_token,
            phone_number_id=whatsapp_settings.phone_number_id,
            api_version=whatsapp_settings.api_version,
            graph_base_url=whatsapp_settings.graph_base_url,
        )
        actor_reader = PostgresActorReader()
        object_storage = build_object_storage(backend_settings)
        return await drain_and_send(
            db=db,
            actor_reader=actor_reader,
            sender=sender,
            object_storage=object_storage,
            approved_templates=approved_template_names(whatsapp_settings.approved_templates),
            card_renderer=card_renderer,
        )


async def runner_loop(*, db: Any, summary_writer: Any = None, card_renderer: Any = None) -> None:
    """Forever-loop driving the scheduled tick. Cancelled on shutdown.

    Every failure mode is swallowed and retried on the next tick: this is the thing
    that exists to make sure automations fire, so it must not be able to
    die from one bad tick.
    """
    delay = startup_delay_seconds()
    logger.info(
        "automation_runner.starting interval_seconds=%s startup_delay_seconds=%s",
        interval_seconds(),
        delay,
    )
    try:
        await asyncio.sleep(delay)
        while True:
            try:
                await run_tick(db=db, summary_writer=summary_writer, card_renderer=card_renderer)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception("automation_runner.tick_failed")
            await asyncio.sleep(interval_seconds())
    except asyncio.CancelledError:
        logger.info("automation_runner.stopped")
        raise
