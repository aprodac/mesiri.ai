"""Read/action WhatsApp assistant log viewer for the control panel.

Platform-admin only (see mesiri.domains.shared.auth.require_platform_admin) --
this exposes real customer message content and phone numbers. Reads through
apps/whatsapp-assistant/src/backend/postgres/message_logger.py's list_recent/
get_message_detail/acknowledge and trace_logger.py's get_by_correlation_id/
get_provider_executions/get_stage_context; this router adds no SQL of its own, per the
"one file owns a table's SQL" convention used throughout M8.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from mesiri.domains.shared.auth import require_platform_admin

router = APIRouter(prefix="/admin/logs", tags=["admin"])


class InboundMessageSummary(BaseModel):
    id: uuid.UUID
    correlation_id: str
    sender_wa_id: str
    message_type: str
    body_preview: str
    processing_status: str
    error_code: str | None = None
    received_at: datetime
    processed_at: datetime | None = None
    acknowledged_at: datetime | None = None
    acknowledged_by: str | None = None
    raw_payload_captured: bool = False
    assistant_reply: str | None = None
    project_id: uuid.UUID | None = None
    project_name: str | None = None
    site_id: uuid.UUID | None = None
    site_name: str | None = None
    workflow_instance_id: uuid.UUID | None = None
    workflow_key: str | None = None
    workflow_phase: str | None = None
    # BE-26: whose message, which company, and how many records it created.
    organization_id: uuid.UUID | None = None
    organization_name: str | None = None
    sender_user_id: uuid.UUID | None = None
    sender_name: str | None = None
    created_count: int = 0


class InboundMessageList(BaseModel):
    items: list[InboundMessageSummary]
    total: int | None = None


class InboundMessageDetail(BaseModel):
    id: uuid.UUID
    correlation_id: str
    sender_wa_id: str
    message_type: str
    body_text: str | None = None
    raw_payload: dict
    normalized_message: dict | None = None
    media_object_key: str | None = None
    processing_status: str
    error_code: str | None = None
    received_at: datetime
    processed_at: datetime | None = None
    raw_payload_captured: bool
    acknowledged_at: datetime | None = None
    acknowledged_by: str | None = None
    retry_of_id: uuid.UUID | None = None
    assistant_reply: str | None = None
    project_id: uuid.UUID | None = None
    project_name: str | None = None
    site_id: uuid.UUID | None = None
    site_name: str | None = None
    workflow_instance_id: uuid.UUID | None = None
    workflow_key: str | None = None
    workflow_phase: str | None = None


class JourneyTraceEntry(BaseModel):
    stage: str
    succeeded: bool
    duration_ms: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    severity: str = "info"
    event_source: str = "pipeline_stage"
    created_at: datetime


class StageContextEntry(BaseModel):
    stage: str
    succeeded: bool
    created_at: datetime
    stage_payload: dict | None = None


class ProviderExecutionEntry(BaseModel):
    stage: str
    provider: str
    operation: str
    model: str | None = None
    latency_ms: float | None = None
    succeeded: bool
    error_code: str | None = None
    created_at: datetime


class CreatedRecord(BaseModel):
    """One record a message created or changed (BE-26), from its domain event."""

    event_type: str
    aggregate_type: str
    aggregate_id: uuid.UUID
    correlation_id: str | None = None
    created_at: datetime


class AcknowledgeResponse(BaseModel):
    acknowledged: bool


class RetryResponse(BaseModel):
    correlation_id: str


@router.get("/messages", response_model=InboundMessageList)
async def list_messages(
    request: Request,
    wa_id: str | None = None,
    status: str | None = None,
    provider: str | None = None,
    since_received_at: datetime | None = None,
    since_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    organization_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    site_id: uuid.UUID | None = None,
    _admin: dict = Depends(require_platform_admin),
) -> InboundMessageList:
    message_logger = request.app.state.container.message_logger
    rows, total = await message_logger.list_recent(
        organization_id=organization_id,
        user_id=user_id,
        project_id=project_id,
        site_id=site_id,
        wa_id=wa_id,
        status=status,
        provider=provider,
        since_received_at=since_received_at,
        since_id=since_id,
        limit=limit,
        offset=offset,
    )
    return InboundMessageList(
        items=[InboundMessageSummary(**row) for row in rows],
        total=total,
    )


@router.get("/messages/{message_id}", response_model=InboundMessageDetail)
async def get_message(
    request: Request,
    message_id: str,
    _admin: dict = Depends(require_platform_admin),
) -> InboundMessageDetail:
    message_logger = request.app.state.container.message_logger
    row = await message_logger.get_message_detail(message_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Message not found")
    return InboundMessageDetail(**row)


@router.get("/messages/{correlation_id}/created", response_model=list[CreatedRecord])
async def get_message_created(
    request: Request,
    correlation_id: str,
    _admin: dict = Depends(require_platform_admin),
) -> list[CreatedRecord]:
    """What this message created or changed (BE-26): attendance, materials,
    expenses, work done, ... -- one entry per domain event, including the
    answers and taps that continued the same report."""
    message_logger = request.app.state.container.message_logger
    rows = await message_logger.list_created(correlation_id)
    return [CreatedRecord(**row) for row in rows]


@router.get("/messages/{correlation_id}/trace", response_model=list[JourneyTraceEntry])
async def get_message_trace(
    request: Request,
    correlation_id: str,
    _admin: dict = Depends(require_platform_admin),
) -> list[JourneyTraceEntry]:
    trace_logger = request.app.state.container.trace_logger
    rows = await trace_logger.get_by_correlation_id(correlation_id)
    return [JourneyTraceEntry(**row) for row in rows]


@router.get("/messages/{correlation_id}/context", response_model=list[StageContextEntry])
async def get_message_context(
    request: Request,
    correlation_id: str,
    _admin: dict = Depends(require_platform_admin),
) -> list[StageContextEntry]:
    """The full per-stage AI context (understanding/resolved-context/
    canonical-event/planner payloads) — deliberately kept on a separate route
    from /trace, which excludes stage_payload by design (see trace_logger.py).
    Same platform-admin guard as every other route here; this is the one
    place a raw stage_payload is ever returned to the control panel."""
    trace_logger = request.app.state.container.trace_logger
    rows = await trace_logger.get_stage_context(correlation_id)
    return [StageContextEntry(**row) for row in rows]


@router.get("/messages/{correlation_id}/providers", response_model=list[ProviderExecutionEntry])
async def get_message_providers(
    request: Request,
    correlation_id: str,
    _admin: dict = Depends(require_platform_admin),
) -> list[ProviderExecutionEntry]:
    trace_logger = request.app.state.container.trace_logger
    rows = await trace_logger.get_provider_executions(correlation_id)
    return [ProviderExecutionEntry(**row) for row in rows]


@router.post("/messages/{message_id}/acknowledge", response_model=AcknowledgeResponse)
async def acknowledge_message(
    request: Request,
    message_id: str,
    admin: dict = Depends(require_platform_admin),
) -> AcknowledgeResponse:
    message_logger = request.app.state.container.message_logger
    trace_logger = request.app.state.container.trace_logger
    acknowledged_by = admin.get("sub") or "unknown"
    ok = await message_logger.acknowledge(message_id=message_id, acknowledged_by=acknowledged_by)
    if not ok:
        raise HTTPException(status_code=404, detail="Message not found")
    detail = await message_logger.get_message_detail(message_id)
    if detail is not None:
        await trace_logger.log_stage(
            correlation_id=detail["correlation_id"],
            stage="acknowledge",
            stage_payload=None,
            duration_ms=None,
            succeeded=True,
            event_source="admin_action",
        )
    return AcknowledgeResponse(acknowledged=True)


@router.post("/messages/{message_id}/retry", response_model=RetryResponse)
async def retry_message(
    request: Request,
    message_id: str,
    admin: dict = Depends(require_platform_admin),
) -> RetryResponse:
    message_logger = request.app.state.container.message_logger
    trace_logger = request.app.state.container.trace_logger
    receiver = request.app.state.container.receiver

    detail = await message_logger.get_message_detail(message_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Message not found")
    if detail["processing_status"] != "failed":
        raise HTTPException(status_code=409, detail="Only failed messages can be retried")
    if not detail["raw_payload_captured"]:
        raise HTTPException(
            status_code=409,
            detail="Original webhook payload wasn't captured for this message; it cannot be replayed",
        )

    await trace_logger.log_stage(
        correlation_id=detail["correlation_id"],
        stage="retry",
        stage_payload=None,
        duration_ms=None,
        succeeded=True,
        event_source="admin_action",
        error_message=f"retried by {admin.get('sub') or 'unknown'}",
    )
    new_correlation_id = await receiver.replay(detail["raw_payload"], retry_of_id=message_id)
    if new_correlation_id is None:
        raise HTTPException(
            status_code=502, detail="Retry failed before the message could be reprocessed"
        )
    return RetryResponse(correlation_id=new_correlation_id)
