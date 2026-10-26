"""No-op and recording implementations of MessageLogger and TraceLogger.

``NoopMessageLogger`` / ``NoopTraceLogger`` are the default for tests and
environments without the 0210 migration applied yet.

``RecordingMessageLogger`` / ``RecordingTraceLogger`` capture calls for
test assertions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class NoopMessageLogger:
    async def log_received(
        self,
        *,
        correlation_id: str,
        sender_wa_id: str,
        message_type: str,
        raw_payload: dict[str, Any],
        normalized_message: dict[str, Any] | None,
        body_text: str | None,
        media_object_key: str | None,
        dedup_key: str,
        retry_of_id: str | None = None,
        organization_id: str | None = None,
    ) -> None: ...

    async def update_context(
        self,
        *,
        correlation_id: str,
        organization_id: str | None = None,
        project_id: str | None = None,
        site_id: str | None = None,
    ) -> None: ...

    async def mark_completed(self, *, correlation_id: str) -> None: ...

    async def mark_failed(self, *, correlation_id: str, error_code: str) -> None: ...

    async def log_reply(self, *, correlation_id: str, reply: str) -> None: ...

    async def update_body_text(
        self, *, correlation_id: str, body_text: str, translated_text: str | None = None
    ) -> None: ...

    async def link_workflow_instance(
        self, *, correlation_id: str, workflow_instance_id: str
    ) -> None: ...

    async def set_interaction_group(self, *, correlation_id: str, group_id: str) -> None: ...

    async def set_reply_wamid(self, *, correlation_id: str, reply_wamid: str) -> None: ...


class NoopTraceLogger:
    async def log_stage(
        self,
        *,
        correlation_id: str,
        stage: str,
        stage_payload: dict[str, Any] | None,
        duration_ms: int | None,
        succeeded: bool,
        error_code: str | None = None,
        error_message: str | None = None,
        severity: str = "info",
        event_source: str = "pipeline_stage",
    ) -> None: ...

    async def log_provider_execution(
        self,
        *,
        correlation_id: str,
        stage: str,
        provider: str,
        operation: str,
        model: str | None,
        latency_ms: float | None,
        succeeded: bool,
        error_code: str | None = None,
    ) -> None: ...


@dataclass
class ReceivedMessage:
    correlation_id: str
    sender_wa_id: str
    message_type: str
    raw_payload: dict[str, Any]
    normalized_message: dict[str, Any] | None
    body_text: str | None
    media_object_key: str | None
    dedup_key: str
    retry_of_id: str | None = None
    organization_id: str | None = None
    project_id: str | None = None
    site_id: str | None = None


@dataclass
class RecordingMessageLogger:
    """Captures all calls for test assertions. No DB required."""

    received: list[ReceivedMessage] = field(default_factory=list)
    completed: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    replies: list[tuple[str, str]] = field(default_factory=list)
    transcriptions: list[tuple[str, str]] = field(default_factory=list)
    #: Voice notes' English, when the speech step gave one (WEB-37).
    translations: list[tuple[str, str]] = field(default_factory=list)
    workflow_links: list[tuple[str, str]] = field(default_factory=list)
    interaction_groups: list[tuple[str, str]] = field(default_factory=list)
    reply_wamids: list[tuple[str, str]] = field(default_factory=list)

    async def log_received(
        self,
        *,
        correlation_id: str,
        sender_wa_id: str,
        message_type: str,
        raw_payload: dict[str, Any],
        normalized_message: dict[str, Any] | None,
        body_text: str | None,
        media_object_key: str | None,
        dedup_key: str,
        retry_of_id: str | None = None,
        organization_id: str | None = None,
    ) -> None:
        self.received.append(
            ReceivedMessage(
                correlation_id=correlation_id,
                sender_wa_id=sender_wa_id,
                message_type=message_type,
                raw_payload=raw_payload,
                normalized_message=normalized_message,
                body_text=body_text,
                media_object_key=media_object_key,
                dedup_key=dedup_key,
                retry_of_id=retry_of_id,
                organization_id=organization_id,
            )
        )

    async def update_context(
        self,
        *,
        correlation_id: str,
        organization_id: str | None = None,
        project_id: str | None = None,
        site_id: str | None = None,
    ) -> None:
        for r in self.received:
            if r.correlation_id == correlation_id:
                if organization_id is not None:
                    r.organization_id = organization_id
                if project_id is not None:
                    r.project_id = project_id
                if site_id is not None:
                    r.site_id = site_id

    async def mark_completed(self, *, correlation_id: str) -> None:
        self.completed.append(correlation_id)

    async def mark_failed(self, *, correlation_id: str, error_code: str) -> None:
        self.failed.append((correlation_id, error_code))

    async def log_reply(self, *, correlation_id: str, reply: str) -> None:
        self.replies.append((correlation_id, reply))

    async def update_body_text(
        self, *, correlation_id: str, body_text: str, translated_text: str | None = None
    ) -> None:
        self.transcriptions.append((correlation_id, body_text))
        if translated_text:
            self.translations.append((correlation_id, translated_text))
        for r in self.received:
            if r.correlation_id == correlation_id:
                r.body_text = body_text

    async def link_workflow_instance(
        self, *, correlation_id: str, workflow_instance_id: str
    ) -> None:
        self.workflow_links.append((correlation_id, workflow_instance_id))

    async def set_interaction_group(self, *, correlation_id: str, group_id: str) -> None:
        self.interaction_groups.append((correlation_id, group_id))

    async def set_reply_wamid(self, *, correlation_id: str, reply_wamid: str) -> None:
        self.reply_wamids.append((correlation_id, reply_wamid))


@dataclass
class TraceEntry:
    correlation_id: str
    stage: str
    stage_payload: dict[str, Any] | None
    duration_ms: int | None
    succeeded: bool
    error_code: str | None = None
    error_message: str | None = None
    severity: str = "info"
    event_source: str = "pipeline_stage"


@dataclass
class ProviderExecutionEntry:
    correlation_id: str
    stage: str
    provider: str
    operation: str
    model: str | None
    latency_ms: float | None
    succeeded: bool
    error_code: str | None = None


@dataclass
class RecordingTraceLogger:
    """Captures all trace calls for test assertions. No DB required."""

    entries: list[TraceEntry] = field(default_factory=list)
    provider_executions: list[ProviderExecutionEntry] = field(default_factory=list)

    async def log_stage(
        self,
        *,
        correlation_id: str,
        stage: str,
        stage_payload: dict[str, Any] | None,
        duration_ms: int | None,
        succeeded: bool,
        error_code: str | None = None,
        error_message: str | None = None,
        severity: str = "info",
        event_source: str = "pipeline_stage",
    ) -> None:
        self.entries.append(
            TraceEntry(
                correlation_id=correlation_id,
                stage=stage,
                stage_payload=stage_payload,
                duration_ms=duration_ms,
                succeeded=succeeded,
                error_code=error_code,
                error_message=error_message,
                severity=severity,
                event_source=event_source,
            )
        )

    async def log_provider_execution(
        self,
        *,
        correlation_id: str,
        stage: str,
        provider: str,
        operation: str,
        model: str | None,
        latency_ms: float | None,
        succeeded: bool,
        error_code: str | None = None,
    ) -> None:
        self.provider_executions.append(
            ProviderExecutionEntry(
                correlation_id=correlation_id,
                stage=stage,
                provider=provider,
                operation=operation,
                model=model,
                latency_ms=latency_ms,
                succeeded=succeeded,
                error_code=error_code,
            )
        )

    def stages(self) -> list[str]:
        """Convenience: ordered list of stage names."""
        return [e.stage for e in self.entries]

    def for_correlation(self, correlation_id: str) -> list[TraceEntry]:
        return [e for e in self.entries if e.correlation_id == correlation_id]
