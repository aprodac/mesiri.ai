"""Assistant review export for the scheduled Claude Code reviewer (WA-14).

Platform-admin only (see mesiri.domains.shared.auth.require_platform_admin).
Read-only: one GET that returns the last N hours of conversations, anonymised
by admin/review_export.py, plus the per-stage latency summary the Performance
page already computes. The nightly reviewer (docs/ops/assistant-review.md)
pulls it with apps/whatsapp-assistant/scripts/fetch_review_export.py.

Adds no SQL of its own, per the "one file owns a table's SQL" convention --
reads go through message_logger.py's list_for_review and trace_logger.py's
get_review_stages/get_review_providers/get_stage_summary.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from admin.review_export import build_export
from mesiri.domains.shared.auth import require_platform_admin

router = APIRouter(prefix="/admin/review", tags=["admin"])


@router.get("/export")
async def get_review_export(
    request: Request,
    hours: int = Query(default=24, ge=1, le=168),
    limit: int = Query(default=2000, ge=1, le=5000),
    _admin: dict = Depends(require_platform_admin),
) -> dict[str, Any]:
    container = request.app.state.container
    until = datetime.now(UTC)
    since = until - timedelta(hours=hours)

    # One row over the limit tells us the window was cut, without a COUNT.
    messages = await container.message_logger.list_for_review(since=since, limit=limit + 1)
    truncated = len(messages) > limit
    messages = messages[:limit]

    correlation_ids = [row["correlation_id"] for row in messages]
    trace_logger = container.trace_logger
    stages = await trace_logger.get_review_stages(correlation_ids)
    providers = await trace_logger.get_review_providers(correlation_ids)
    stage_summary = await trace_logger.get_stage_summary(since)

    export = build_export(
        messages=messages,
        stages=stages,
        providers=providers,
        since=since,
        until=until,
        truncated=truncated,
    )
    export["stage_summary"] = [
        {k: (float(v) if k.endswith("_ms") and v is not None else v) for k, v in row.items()}
        for row in stage_summary
    ]
    return export
