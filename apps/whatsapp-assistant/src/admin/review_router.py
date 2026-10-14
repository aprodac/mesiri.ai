"""Assistant review export for the scheduled Claude Code reviewer (WA-14).

Platform-admin only (see mesiri.domains.shared.auth.require_platform_admin).
Read-only: one GET that returns the last N hours of conversations, anonymised
by admin/review_export.py, plus the per-stage latency summary the Performance
page already computes. The nightly reviewer (docs/ops/assistant-review.md)
pulls it with apps/whatsapp-assistant/scripts/fetch_review_export.py.

Adds no SQL of its own, per the "one file owns a table's SQL" convention --
reads go through message_logger.py's list_for_review and trace_logger.py's
get_review_stages/get_review_providers/get_review_understanding/get_stage_summary;
findings (WA-15) through backend/postgres/review_findings.py.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from admin.friction import summarize
from admin.review_export import build_export
from mesiri.domains.shared.auth import require_platform_admin

router = APIRouter(prefix="/admin/review", tags=["admin"])

# The trend reads raw messages for up to 60 days; past this many it says so.
_TREND_MESSAGE_LIMIT = 50_000

_findings_store = None


def _findings(request: Request):
    """The findings store: the container's if it has one (tests inject a
    fake), else one Postgres store built on first use -- so this stage needs
    no change to the shared app container."""
    global _findings_store
    store = getattr(request.app.state.container, "review_findings", None)
    if store is not None:
        return store
    if _findings_store is None:
        from backend.postgres.review_findings import PostgresReviewFindings

        _findings_store = PostgresReviewFindings()
    return _findings_store


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
    understanding = await trace_logger.get_review_understanding(correlation_ids)
    stage_summary = await trace_logger.get_stage_summary(since)

    export = build_export(
        messages=messages,
        stages=stages,
        providers=providers,
        understanding=understanding,
        since=since,
        until=until,
        truncated=truncated,
    )
    export["stage_summary"] = [
        {k: (float(v) if k.endswith("_ms") and v is not None else v) for k, v in row.items()}
        for row in stage_summary
    ]
    return export


@router.get("/friction")
async def get_friction_trend(
    request: Request,
    days: int = Query(default=14, ge=1, le=60),
    tz: str = Query(default="Asia/Kolkata"),
    _admin: dict = Depends(require_platform_admin),
) -> dict[str, Any]:
    """Friction per day (in `tz`) and per workflow, for comparing before and
    after a change. A conversation counts on the day it started."""
    try:
        zone = ZoneInfo(tz)
    except Exception as exc:  # noqa: BLE001 -- ZoneInfoNotFoundError and bad keys alike
        raise HTTPException(status_code=422, detail=f"unknown timezone {tz!r}") from exc
    until = datetime.now(UTC)
    since = until - timedelta(days=days)
    messages = await request.app.state.container.message_logger.list_for_review(
        since=since, limit=_TREND_MESSAGE_LIMIT + 1
    )
    truncated = len(messages) > _TREND_MESSAGE_LIMIT
    export = build_export(
        messages=messages[:_TREND_MESSAGE_LIMIT],
        stages=[],
        providers=[],
        since=since,
        until=until,
        truncated=truncated,
    )
    by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for conv in export["conversations"]:
        day = datetime.fromisoformat(conv["started_at"]).astimezone(zone).date().isoformat()
        by_day[day].append(conv)
    return {
        "window": export["window"],
        "truncated": truncated,
        "tz": tz,
        "overall": export["friction"],
        "days": [{"day": day, **summarize(convs)} for day, convs in sorted(by_day.items())],
    }


class FindingIn(BaseModel):
    fingerprint: str = Field(min_length=3, max_length=120, pattern=r"^[a-z0-9][a-z0-9-]*$")
    category: str
    title: str = Field(min_length=3, max_length=200)
    detail: str | None = None
    suspected_location: str | None = Field(default=None, max_length=300)
    workflow_key: str | None = Field(default=None, max_length=80)
    severity: int = Field(default=2, ge=1, le=3)
    occurrences: int = Field(default=1, ge=1)
    examples: list[str] = Field(default_factory=list, max_length=10)
    replay_cases: list[str] = Field(default_factory=list)


class FindingsIn(BaseModel):
    seen_on: date
    findings: list[FindingIn] = Field(max_length=200)


class FindingPatch(BaseModel):
    status: str | None = None
    fix_commit: str | None = Field(default=None, max_length=40)
    note: str | None = None
    replay_cases: list[str] | None = None


@router.get("/findings")
async def list_findings(
    request: Request,
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    _admin: dict = Depends(require_platform_admin),
) -> dict[str, Any]:
    return {"findings": await _findings(request).list(status=status, limit=limit)}


@router.post("/findings")
async def record_findings(
    request: Request,
    body: FindingsIn,
    _admin: dict = Depends(require_platform_admin),
) -> dict[str, Any]:
    """The nightly reviewer's problems for one day; upserted by fingerprint."""
    try:
        stored = await _findings(request).record(
            [f.model_dump() for f in body.findings], seen_on=body.seen_on
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"findings": stored}


@router.patch("/findings/{fingerprint}")
async def update_finding(
    request: Request,
    fingerprint: str,
    body: FindingPatch,
    _admin: dict = Depends(require_platform_admin),
) -> dict[str, Any]:
    try:
        row = await _findings(request).update(fingerprint, **body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="no such finding")
    return row
