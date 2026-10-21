"""Unit tests for the WhatsApp material/unit resolution gate and its picker
resume chain (runtime/inbound_journey.py's _run_material_unit_gates and the
resume_pending_report_with_material / resume_pending_report_with_unit
functions).

These are the load-bearing gate-chain functions for material reports: they
run *before* the planner ever sees the event, so an ambiguous material name,
an unknown material, or a Stock Unit mismatch is caught here rather than as
a late domain-validation failure after the user already tapped Yes. Fakes
only -- no live DB, no HTTP, no AI providers.

Covers four branches of _run_material_unit_gates plus one resume-chain
invariant:
  - ambiguous material name -> picker (multiple fuzzy matches)
  - unknown material -> not-found reply (no matches AND empty active catalog)
  - unit mismatch -> yes/no clarification (resolved material, wrong unit)
  - material picker resume re-runs the unit gate (resolving material does
    NOT guarantee unit does too -- the docstring on resume_pending_report_
    with_material calls this out explicitly)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from interactions.pending_report import PendingReportStore
from mesiri_contracts.assistant.canonical_event import (
    CanonicalEventType,
    IntentCompleteness,
)
from mesiri_contracts.assistant.enums import InputModality
from mesiri_contracts.assistant.normalized_message import NormalizedMessage, SenderInfo
from mesiri_contracts.assistant.planner_decision import PlannerDecisionType
from mesiri_contracts.assistant.v2.canonical_event import CanonicalEventV2
from mesiri_contracts.assistant.v2.planner_decision import PlannerDecisionV2
from planner import Planner
from runtime.inbound_journey import (
    _run_material_unit_gates,
    resume_pending_report_with_material,
)
from runtime.noop_loggers import RecordingMessageLogger
from workflows import WorkflowRunResult, WorkflowRunStatus, WorkflowRuntime
from workflows.fakes import FakeWorkflowInstanceRepository, FakeWorkflowRegistry

ORG = "11111111-1111-4111-8111-111111111111"
USR = "22222222-2222-4222-8222-222222222222"
PRJ = "33333333-3333-4333-8333-333333333333"


class _FakeRedis:
    def __init__(self) -> None:
        self._store: dict[str, Any] = {}

    def namespaced(self, *parts: str) -> str:
        return ":".join(parts)

    async def set_json(self, key: str, value: Any, *, ttl_seconds: int | None = None) -> None:
        self._store[key] = value

    async def get_json(self, key: str) -> Any | None:
        return self._store.get(key)


class _FakeCatalogQuery:
    """In-memory stand-in for MaterialCatalogQueryService. Each method returns
    canned data so the gate's branch logic can be exercised without a DB."""

    def __init__(
        self,
        *,
        find_materials_result: list[dict[str, Any]] | None = None,
        list_active_result: list[dict[str, Any]] | None = None,
        get_material_result: dict[str, Any] | None = None,
        resolve_unit_result: dict[str, Any] | None = None,
        get_unit_result: dict[str, Any] | None = None,
    ) -> None:
        self._find = find_materials_result
        self._list_active = list_active_result
        self._get_material = get_material_result
        self._resolve_unit = resolve_unit_result
        self._get_unit = get_unit_result

    async def find_materials(self, *, organization_id: str, name: str) -> list[dict[str, Any]]:
        return self._find if self._find is not None else []

    async def list_active_materials(self, *, organization_id: str) -> list[dict[str, Any]]:
        return self._list_active if self._list_active is not None else []

    async def get_material(self, *, organization_id: str, material_id: str) -> dict[str, Any] | None:
        return self._get_material

    async def resolve_unit(self, text: str) -> dict[str, Any] | None:
        return self._resolve_unit

    async def get_unit(self, unit_id: str) -> dict[str, Any] | None:
        return self._get_unit


def _event(
    *,
    material_name: str = "cement",
    unit: str | None = "bags",
    material_id: str | None = None,
    unit_id: str | None = None,
) -> CanonicalEventV2:
    fields: dict[str, Any] = {"material_name": material_name, "quantity": 50}
    if unit is not None:
        fields["unit"] = unit
    if material_id is not None:
        fields["material_id"] = material_id
    if unit_id is not None:
        fields["unit_id"] = unit_id
    return CanonicalEventV2(
        event_id="evt_1",
        correlation_id="cor_1",
        source_message_id="msg_1",
        event_type=CanonicalEventType.MATERIAL_RECEIPT_REQUESTED,
        completeness=IntentCompleteness.ACTIONABLE,
        organization_id=ORG,
        user_id=USR,
        project_id=PRJ,
        fields=fields,
    )


def _pending_store() -> PendingReportStore:
    return PendingReportStore(_FakeRedis())


async def test_ambiguous_material_name_returns_picker_and_stores_pending():
    """A reported name that fuzzy-matches more than one active catalog entry
    ("cement" -> OPC Cement + PPC Cement) must pause the report and return a
    picker ReplySpec whose list_rows carry mat_<id> ids -- the exact prefix
    resume_pending_report_with_material matches verbatim. The event is held
    in pending_report_store so the tap can resume it with material_id filled
    in (pop-once, so a stale tap can't resurrect an old report)."""
    opc_id = str(uuid.uuid4())
    ppc_id = str(uuid.uuid4())
    catalog = _FakeCatalogQuery(
        find_materials_result=[
            {"id": opc_id, "name": "OPC Cement", "is_active": True, "default_unit_id": None},
            {"id": ppc_id, "name": "PPC Cement", "is_active": True, "default_unit_id": None},
        ]
    )
    store = _pending_store()
    event = _event()

    reply = await _run_material_unit_gates(
        event, catalog_query=catalog, pending_report_store=store, actor_user_id=USR
    )

    assert reply is not None
    assert reply.list_rows is not None
    row_ids = [r.id for r in reply.list_rows]
    assert f"mat_{opc_id}" in row_ids
    assert f"mat_{ppc_id}" in row_ids
    assert all(r.id.startswith("mat_") for r in reply.list_rows)

    pending = await store.pop_pending(user_id=USR)
    assert pending is not None, "the event must be held pending so the tap can resume it"
    assert pending.fields["material_name"] == "cement"


async def test_unknown_material_with_empty_catalog_returns_not_found_reply():
    """When find_materials returns nothing AND the org's whole active catalog
    is also empty, the gate must return render_material_not_found_reply's
    text -- distinct from the picker case because tapping won't help (there's
    nothing to choose from). The report is not held pending in this branch."""
    catalog = _FakeCatalogQuery(find_materials_result=[], list_active_result=[])
    store = _pending_store()
    event = _event(material_name="unobtainium")

    reply = await _run_material_unit_gates(
        event, catalog_query=catalog, pending_report_store=store, actor_user_id=USR
    )

    assert reply is not None
    assert reply.list_rows is None, "no picker rows when there's nothing to choose from"
    assert "couldn't find" in reply.text.lower() or "unobtainium" in reply.text

    pending = await store.pop_pending(user_id=USR)
    assert pending is None, "nothing to resume when the material doesn't exist at all"


async def test_unit_mismatch_returns_yes_no_clarification_with_stock_unit_id():
    """A resolved material whose Stock Unit (default_unit_id) differs from the
    unit the user reported must pause the report and return a yes/no
    clarification -- never a global unit picker that could let an incompatible
    unit through. The Yes button's id is unit_yes_<stock_unit_id>, matched
    verbatim by resume_pending_report_with_unit; No is the fixed id unit_no."""
    stock_unit_id = str(uuid.uuid4())
    bags_id = str(uuid.uuid4())
    material_id = str(uuid.uuid4())
    catalog = _FakeCatalogQuery(
        find_materials_result=[
            {
                "id": material_id,
                "name": "Cement",
                "is_active": True,
                "default_unit_id": stock_unit_id,
            }
        ],
        resolve_unit_result={"id": bags_id, "code": "bags"},  # resolves, but to wrong unit
        get_unit_result={"id": stock_unit_id, "code": "tons", "display_name": "Tons"},
    )
    store = _pending_store()
    event = _event(material_name="Cement", unit="bags")

    reply = await _run_material_unit_gates(
        event, catalog_query=catalog, pending_report_store=store, actor_user_id=USR
    )

    assert reply is not None
    assert reply.buttons is not None, "unit mismatch must produce yes/no buttons, not a list"
    button_ids = [b.id for b in reply.buttons]
    assert f"unit_yes_{stock_unit_id}" in button_ids, (
        "Yes must carry the stock_unit_id so resume_pending_report_with_unit can fill it in"
    )
    assert "unit_no" in button_ids, "No must use the fixed unit_no id"

    pending = await store.pop_pending(user_id=USR)
    assert pending is not None, "the event must be held pending so the yes/no tap can resume it"


class _RecordingWorkflowRuntime(WorkflowRuntime):
    """Captures whether the planner/workflow ever ran during a resume -- the
    resume-chain test asserts it did NOT run when a downstream gate still
    holds the report."""

    def __init__(self) -> None:
        super().__init__(
            registry=FakeWorkflowRegistry(),
            repo=FakeWorkflowInstanceRepository(),
        )
        self.started = False

    async def start(self, decision, event):  # type: ignore[override]
        self.started = True
        return WorkflowRunResult(
            status=WorkflowRunStatus.COMPLETED,
            workflow_key=decision.workflow_key,
            workflow_instance_id="wf_test",
        )


def _planner_decision_start() -> PlannerDecisionV2:
    return PlannerDecisionV2(
        decision_type=PlannerDecisionType.START_WORKFLOW,
        workflow_key="material.receipt",
        reason=CanonicalEventType.MATERIAL_RECEIPT_REQUESTED,
        organization_id=ORG,
        user_id=USR,
        project_id=PRJ,
    )


def _material_tap_message(material_id: str) -> NormalizedMessage:
    return NormalizedMessage(
        message_id="wamid.tap.1",
        correlation_id="cor_resume_1",
        sender=SenderInfo(wa_id="wa_engineer", profile_name="Engineer"),
        timestamp=datetime(2026, 7, 9, 10, 0, tzinfo=UTC),
        modality=InputModality.INTERACTIVE,
        metadata={"interactive_reply_id": f"mat_{material_id}"},
    )


async def test_material_picker_resume_reruns_unit_gate_when_unit_still_mismatched():
    """resume_pending_report_with_material must NOT jump straight to the
    planner after a material tap -- resolving the material doesn't guarantee
    the unit does too. The docstring on the function (inbound_journey.py:819)
    calls this out explicitly. This test seeds a pending report whose unit
    still mismatches the tapped material's Stock Unit, taps the material,
    and asserts: (a) the unit gate re-fires (returns a yes/no ReplySpec,
    not None), (b) the planner/workflow never started, (c) the report is
    re-held pending so the unit tap can resume it next."""
    material_id = str(uuid.uuid4())
    stock_unit_id = str(uuid.uuid4())
    bags_id = str(uuid.uuid4())

    catalog = _FakeCatalogQuery(
        get_material_result={
            "id": material_id,
            "name": "Cement",
            "is_active": True,
            "default_unit_id": stock_unit_id,
        },
        resolve_unit_result={"id": bags_id, "code": "bags"},  # wrong unit
        get_unit_result={"id": stock_unit_id, "code": "tons", "display_name": "Tons"},
    )
    store = _pending_store()
    await store.set_pending(user_id=USR, event=_event(material_name="Cement", unit="bags"))

    runtime = _RecordingWorkflowRuntime()
    reply = await resume_pending_report_with_material(
        _material_tap_message(material_id),
        USR,
        pending_report_store=store,
        catalog_query=catalog,
        planner=Planner(),
        workflow_runtime=runtime,
    )

    assert reply is not None, "the unit gate must re-fire and return a clarification"
    assert reply.buttons is not None, "re-fired unit mismatch must produce yes/no buttons"
    assert any(b.id.startswith("unit_yes_") for b in reply.buttons), (
        "the yes button must carry the stock_unit_id"
    )
    assert not runtime.started, (
        "planner/workflow must NOT have started -- the unit gate held the report, "
        "so the resume chain stopped at the unit clarification, not at _plan_and_run"
    )

    re_held = await store.pop_pending(user_id=USR)
    assert re_held is not None, (
        "the report must be re-held pending so the unit yes/no tap can resume it"
    )
    assert re_held.fields.get("material_id") == material_id, (
        "the tapped material_id must persist into the re-held event"
    )


async def test_material_picker_tap_is_tagged_with_the_originating_report_correlation_id():
    """The logs-viewer grouping bug this guards: a material report's picker
    taps (and every other gate-resume leg) must be tagged with the ORIGIN
    report's correlation_id -- CanonicalEventV2.correlation_id, unchanged
    since the report was first seeded into pending_report_store -- not the
    tap message's own correlation_id. Without this, only the message that
    happens to touch workflow_instance_id directly (usually just the final
    "yes") ever grouped in the control-panel logs viewer; every intermediate
    material/unit/project clarification tap, and the original voice/text
    report itself, showed up as unrelated rows."""
    material_id = str(uuid.uuid4())
    stock_unit_id = str(uuid.uuid4())

    catalog = _FakeCatalogQuery(
        get_material_result={
            "id": material_id,
            "name": "Cement",
            "is_active": True,
            "default_unit_id": stock_unit_id,
        },
        resolve_unit_result={"id": stock_unit_id, "code": "tons"},  # matches -- unit resolves clean
        get_unit_result={"id": stock_unit_id, "code": "tons", "display_name": "Tons"},
    )
    store = _pending_store()
    origin_event = _event(material_name="Cement", unit="tons")
    assert origin_event.correlation_id == "cor_1"
    await store.set_pending(user_id=USR, event=origin_event)

    mlog = RecordingMessageLogger()
    tap_message = _material_tap_message(material_id)
    assert tap_message.correlation_id == "cor_resume_1"

    await resume_pending_report_with_material(
        tap_message,
        USR,
        pending_report_store=store,
        catalog_query=catalog,
        planner=Planner(),
        workflow_runtime=WorkflowRuntime(
            registry=FakeWorkflowRegistry(), repo=FakeWorkflowInstanceRepository()
        ),
        message_logger=mlog,
    )

    assert ("cor_resume_1", "cor_1") in mlog.interaction_groups, (
        "the tap message must be tagged with the origin report's correlation_id, "
        f"got {mlog.interaction_groups!r}"
    )


async def test_under_the_agent_a_unit_mismatch_asks_for_the_amount_and_holds_nothing():
    """WA-39 (live test, 21 Oct): "Received 40 bags sand" against sand counted
    in m³. Yes would have saved 40 m³; No dropped the entry. Under the agent
    the gate says the fact and asks for the amount in the stock unit; nothing
    is held, so the answer comes back as a new save through the model."""
    stock_unit_id = str(uuid.uuid4())
    catalog = _FakeCatalogQuery(
        find_materials_result=[
            {"id": str(uuid.uuid4()), "name": "Sand", "is_active": True, "default_unit_id": stock_unit_id}
        ],
        resolve_unit_result={"id": str(uuid.uuid4()), "code": "bags"},
        get_unit_result={"id": stock_unit_id, "code": "cum", "display_name": "m³"},
    )
    store = _pending_store()
    event = _event(material_name="Sand", unit="bags")
    event.fields["quantity"] = 40

    reply = await _run_material_unit_gates(
        event, catalog_query=catalog, pending_report_store=store, actor_user_id=USR, ask_amount=True
    )

    assert reply.buttons is None and reply.list_rows is None
    assert reply.text == (
        "Not saved yet: Sand is counted in m³ here, so 40 bags can't be saved as it is. "
        "How much is that in m³?"
    )
    assert await store.pop_pending(user_id=USR) is None
    assert "unit_id" not in event.fields  # never recorded in the wrong unit
