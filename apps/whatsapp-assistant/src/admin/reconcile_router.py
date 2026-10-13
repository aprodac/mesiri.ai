"""Context-sync watchdog visibility for the control panel.

Platform-admin only: this reports on tenant identity projection across every
organization, so it isn't a per-tenant view.

Exists because auto-repair on its own would only move the blind spot. The
watchdog (context/reconcile_watchdog.py) repairs drift between the dashboard's
project/site assignments and what the WhatsApp assistant actually reads --
but if the watchdog itself started failing, that failure would be exactly as
invisible as the drift it was added to catch. These endpoints make each run
inspectable, and let an operator force one without shelling into the VPS to
run scripts/backfill_identity_bridge.py.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import text

from context.reconcile_watchdog import (
    TRIGGER_MANUAL,
    get_service,
    interval_seconds,
    run_reconcile_once,
    watchdog_enabled,
)
from mesiri.domains.shared.auth import require_platform_admin

_log = logging.getLogger("mesiri.admin.reconcile")

router = APIRouter(prefix="/admin/reconcile", tags=["admin"])


class ReconcileRunSummary(BaseModel):
    id: uuid.UUID
    status: str
    started_at: datetime
    finished_at: datetime | None
    duration_ms: int | None
    counts: dict[str, Any] | None
    error_count: int
    errors: list[str] | None
    trigger: str


class ReconcileStatusResponse(BaseModel):
    enabled: bool
    interval_seconds: int
    last_run: ReconcileRunSummary | None
    # True when the most recent run failed outright or reported per-entity
    # errors -- the single field a dashboard can light up on, so nobody has
    # to read the run list to notice something is wrong.
    needs_attention: bool
    recent_runs: list[ReconcileRunSummary]


def _rows_to_summaries(rows) -> list[ReconcileRunSummary]:
    return [
        ReconcileRunSummary(
            id=row["id"],
            status=row["status"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            duration_ms=row["duration_ms"],
            counts=row["counts"],
            error_count=row["error_count"],
            errors=row["errors"],
            trigger=row["trigger"],
        )
        for row in rows
    ]


@router.get("", response_model=ReconcileStatusResponse)
async def get_reconcile_status(
    limit: int = Query(default=20, ge=1, le=100),
    _admin: dict = Depends(require_platform_admin),
):
    """Watchdog configuration plus recent run history, newest first."""
    service = get_service()
    try:
        with service._engine.begin() as conn:  # noqa: SLF001 — read-only, same package
            rows = (
                conn.execute(
                    text(
                        "SELECT id, status, started_at, finished_at, duration_ms, counts, "
                        "error_count, errors, trigger FROM identity_reconcile_runs "
                        "ORDER BY started_at DESC LIMIT :limit"
                    ),
                    {"limit": limit},
                )
                .mappings()
                .all()
            )
    except Exception:
        # Most likely the 0366 migration hasn't run on this environment yet.
        # Report an empty history rather than 500ing: this page is how an
        # operator checks whether sync is healthy, so it has to render
        # something even when its own storage isn't ready.
        _log.exception("reconcile.history_read_failed")
        rows = []

    runs = _rows_to_summaries(rows)
    last = runs[0] if runs else None
    # No run at all is itself worth flagging: it means the watchdog has never
    # completed since this table existed, which is indistinguishable from it
    # never having started.
    needs_attention = last is None or last.status != "succeeded"
    return ReconcileStatusResponse(
        enabled=watchdog_enabled(),
        interval_seconds=interval_seconds(),
        last_run=last,
        needs_attention=needs_attention,
        recent_runs=runs,
    )


@router.post("/run")
async def trigger_reconcile(_admin: dict = Depends(require_platform_admin)):
    """Force a reconcile now, without waiting for the next scheduled tick.

    Deliberately does not contend for the advisory lock: an operator asking
    for a reconcile should get one, not be silently skipped because a
    scheduled run happened to be in flight. reconcile_all() is idempotent,
    so an overlapping run is wasteful but not harmful.
    """
    result = await run_reconcile_once(trigger=TRIGGER_MANUAL, require_lock=False)
    return result or {"status": "skipped"}


class ShadowMismatch(BaseModel):
    port: str
    method: str
    args: Any
    context_result: Any
    main_result: Any
    hits: int
    first_seen_at: datetime
    last_seen_at: datetime


class ShadowStatusResponse(BaseModel):
    # BE-01 step 0: where the WhatsApp assistant reads identity from, and
    # every question on which the main tables and the context copy disagreed.
    identity_source: str
    mismatches: list[ShadowMismatch]


@router.get("/shadow", response_model=ShadowStatusResponse)
async def get_identity_shadow(
    limit: int = Query(default=50, ge=1, le=500),
    _admin: dict = Depends(require_platform_admin),
):
    """Main tables vs context copy differences, most recent first (BE-01)."""
    from context.shadow import identity_source

    service = get_service()
    try:
        with service._engine.begin() as conn:  # noqa: SLF001 — read-only, same package
            rows = (
                conn.execute(
                    text(
                        "SELECT port, method, args, context_result, main_result, hits, "
                        "first_seen_at, last_seen_at FROM identity_shadow_mismatches "
                        "ORDER BY last_seen_at DESC LIMIT :limit"
                    ),
                    {"limit": limit},
                )
                .mappings()
                .all()
            )
    except Exception:
        # Migration 0465 not applied yet: show nothing rather than 500.
        _log.exception("reconcile.shadow_read_failed")
        rows = []
    return ShadowStatusResponse(
        identity_source=identity_source(),
        mismatches=[ShadowMismatch(**dict(row)) for row in rows],
    )
