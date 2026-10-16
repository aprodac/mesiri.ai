"""Unit tests for the WhatsApp usage-vs-stock sufficiency gate (runtime/
inbound_journey.py's _run_stock_gate and resume_pending_report_with_stock_
choice).

Real bug this fixes: a usage report quantity greater than what's in stock
used to only show a cosmetic warning on the confirmation prompt
(workflows/material/nodes.py's _low_stock_warning) -- tapping Yes anyway
still saved the full over-limit quantity and drove computed stock negative.
The gate now blocks the report before it ever reaches confirmation and offers
three explicit choices instead. Fakes only -- no live DB, no HTTP, no AI
providers.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from interactions.pending_report import PendingReportStore
from mesiri_contracts.assistant.canonical_event import (
    CanonicalEventType,
    IntentCompleteness,
)
from mesiri_contracts.assistant.enums import InputModality
from mesiri_contracts.assistant.normalized_message import NormalizedMessage, SenderInfo
from mesiri_contracts.assistant.v2.canonical_event import CanonicalEventV2
from planner import Planner
from runtime.inbound_journey import (
    _run_stock_gate,
    resume_pending_report_with_stock_choice,
)
from workflows import WorkflowRunResult, WorkflowRunStatus, WorkflowRuntime
from workflows.fakes import FakeWorkflowInstanceRepository, FakeWorkflowRegistry

ORG = "11111111-1111-4111-8111-111111111111"
USR = "22222222-2222-4222-8222-222222222222"
PRJ = "33333333-3333-4333-8333-333333333333"


def _usage_event(
    *, quantity: float = 70, available_stock: float | None = 50, material_name: str = "cement"
) -> CanonicalEventV2:
    fields: dict[str, Any] = {"material_name": material_name, "quantity": quantity, "unit": "bags"}
    if available_stock is not None:
        fields["available_stock"] = available_stock
    return CanonicalEventV2(
        event_id="evt_1",
        correlation_id="cor_1",
        source_message_id="msg_1",
        event_type=CanonicalEventType.MATERIAL_USAGE_REQUESTED,
        completeness=IntentCompleteness.ACTIONABLE,
        organization_id=ORG,
        user_id=USR,
        project_id=PRJ,
        fields=fields,
    )


class _FakeRedis:
    def __init__(self) -> None:
        self._store: dict[str, Any] = {}

    def namespaced(self, *parts: str) -> str:
        return ":".join(parts)

    async def set_json(self, key: str, value: Any, *, ttl_seconds: int | None = None) -> None:
        self._store[key] = value

    async def get_json(self, key: str) -> Any | None:
        return self._store.get(key)


def _pending_store() -> PendingReportStore:
    return PendingReportStore(_FakeRedis())


class _CaptureMode:
    """OrganizationSettingsQueryService stand-in: only capture_mode."""

    def __init__(self, mode: str) -> None:
        self._mode = mode

    async def get(self, *, organization_id: str, key: str) -> Any:
        assert key == "capture_mode"
        return self._mode


async def test_usage_over_stock_is_blocked_with_three_choices():
    """Confirm-first company: reporting 70 against 50 in stock must NOT fall
    through to the planner -- it must be held pending and return the three
    explicit buttons, never the old cosmetic-only warning."""
    store = _pending_store()
    event = _usage_event(quantity=70, available_stock=50)

    reply = await _run_stock_gate(
        event,
        pending_report_store=store,
        actor_user_id=USR,
        org_settings_query=_CaptureMode("confirm_first"),
    )

    assert reply is not None
    assert reply.buttons is not None
    button_ids = [b.id for b in reply.buttons]
    assert button_ids == ["stock_cap", "stock_arrival", "stock_cancel"]
    assert "70" in reply.text and "50" in reply.text

    pending = await store.pop_pending(user_id=USR)
    assert pending is not None, "the report must be held so a button tap can resume it"


async def test_save_first_company_is_not_asked_about_stock():
    """WA-03 quiet daytime: a save-first company (the default, also with no
    settings to read) saves the usage; BE-12 flags it on the DPR instead."""
    for settings in (_CaptureMode("save_first"), None):
        store = _pending_store()
        event = _usage_event(quantity=70, available_stock=50)

        reply = await _run_stock_gate(
            event, pending_report_store=store, actor_user_id=USR, org_settings_query=settings
        )

        assert reply is None
        assert await store.pop_pending(user_id=USR) is None


async def test_usage_within_stock_is_not_blocked():
    store = _pending_store()
    event = _usage_event(quantity=30, available_stock=50)

    reply = await _run_stock_gate(event, pending_report_store=store, actor_user_id=USR)

    assert reply is None
    assert await store.pop_pending(user_id=USR) is None


async def test_usage_equal_to_stock_is_not_blocked():
    store = _pending_store()
    event = _usage_event(quantity=50, available_stock=50)

    reply = await _run_stock_gate(event, pending_report_store=store, actor_user_id=USR)

    assert reply is None


async def test_receipt_event_is_never_checked():
    """The gate only ever applies to usage reports -- a receipt (arrival)
    has no stock ceiling to check against."""
    store = _pending_store()
    event = _usage_event(quantity=70, available_stock=50).model_copy(
        update={"event_type": CanonicalEventType.MATERIAL_RECEIPT_REQUESTED}
    )

    reply = await _run_stock_gate(event, pending_report_store=store, actor_user_id=USR)

    assert reply is None


async def test_missing_available_stock_lets_it_through():
    """No stock figure could be resolved (inventory query returned nothing) --
    degrade to letting it through rather than blocking on nothing to compare
    against, same fail-open principle as the other gates' lookup failures."""
    store = _pending_store()
    event = _usage_event(quantity=70, available_stock=None)

    reply = await _run_stock_gate(event, pending_report_store=store, actor_user_id=USR)

    assert reply is None


def _tap_message(row_id: str) -> NormalizedMessage:
    return NormalizedMessage(
        message_id="wamid.tap.1",
        correlation_id="cor_resume_1",
        sender=SenderInfo(wa_id="wa_engineer", profile_name="Engineer"),
        timestamp=datetime(2026, 7, 9, 10, 0, tzinfo=UTC),
        modality=InputModality.INTERACTIVE,
        metadata={"interactive_reply_id": row_id},
    )


class _RecordingWorkflowRuntime(WorkflowRuntime):
    def __init__(self) -> None:
        super().__init__(registry=FakeWorkflowRegistry(), repo=FakeWorkflowInstanceRepository())
        self.started_with: CanonicalEventV2 | None = None

    async def start(self, decision, event):  # type: ignore[override]
        self.started_with = event
        return WorkflowRunResult(
            status=WorkflowRunStatus.COMPLETED,
            workflow_key=decision.workflow_key,
            workflow_instance_id="wf_test",
            correlation_id=event.correlation_id,
            pending_prompt="ok",
        )


async def test_cap_choice_saves_only_available_quantity():
    """Tapping "Cap at available" must correct quantity down to the stock
    figure the gate computed (not the originally-reported 70) before the
    report proceeds to planner/workflow -- this is the actual fix for the
    reported bug (stock going negative)."""
    store = _pending_store()
    await store.set_pending(user_id=USR, event=_usage_event(quantity=70, available_stock=50))
    runtime = _RecordingWorkflowRuntime()

    reply = await resume_pending_report_with_stock_choice(
        _tap_message("stock_cap"),
        USR,
        pending_report_store=store,
        planner=Planner(),
        workflow_runtime=runtime,
    )

    assert reply is not None
    assert runtime.started_with is not None, "planner/workflow must have run"
    assert runtime.started_with.fields["quantity"] == 50, (
        "quantity must be corrected to the available stock figure, not the original 70"
    )
    assert runtime.started_with.event_type is CanonicalEventType.MATERIAL_USAGE_REQUESTED


async def test_arrival_choice_switches_to_material_receipt():
    """Tapping "It's an arrival" must convert the held usage report into a
    Material Receipt with the same material/quantity/unit, not silently drop
    or misrecord it."""
    store = _pending_store()
    await store.set_pending(user_id=USR, event=_usage_event(quantity=70, available_stock=50))
    runtime = _RecordingWorkflowRuntime()

    reply = await resume_pending_report_with_stock_choice(
        _tap_message("stock_arrival"),
        USR,
        pending_report_store=store,
        planner=Planner(),
        workflow_runtime=runtime,
    )

    assert reply is not None
    assert runtime.started_with is not None
    assert runtime.started_with.event_type is CanonicalEventType.MATERIAL_RECEIPT_REQUESTED
    assert runtime.started_with.fields["quantity"] == 70, (
        "the arrival keeps the originally-reported quantity -- it's not a usage anymore"
    )
    assert runtime.started_with.fields["direction"] == "received"
    assert runtime.started_with.fields["material_name"] == "cement"
    assert "available_stock" not in runtime.started_with.fields


async def test_cancel_choice_discards_without_running_planner():
    store = _pending_store()
    await store.set_pending(user_id=USR, event=_usage_event(quantity=70, available_stock=50))
    runtime = _RecordingWorkflowRuntime()

    reply = await resume_pending_report_with_stock_choice(
        _tap_message("stock_cancel"),
        USR,
        pending_report_store=store,
        planner=Planner(),
        workflow_runtime=runtime,
    )

    assert reply is not None
    assert reply.text == "❌ Discarded. Nothing was recorded."
    assert runtime.started_with is None, "planner/workflow must never run on cancel"
    assert await store.pop_pending(user_id=USR) is None


async def test_non_stock_row_id_returns_none_and_does_not_pop():
    """Any other interactive tap (e.g. a stray confirm_yes) must fall through
    untouched -- the held report must still be there afterwards."""
    store = _pending_store()
    await store.set_pending(user_id=USR, event=_usage_event(quantity=70, available_stock=50))

    reply = await resume_pending_report_with_stock_choice(
        _tap_message("confirm_yes"),
        USR,
        pending_report_store=store,
        planner=Planner(),
        workflow_runtime=_RecordingWorkflowRuntime(),
    )

    assert reply is None
    assert await store.pop_pending(user_id=USR) is not None, (
        "an unrelated tap must not consume the pending stock-choice report"
    )
