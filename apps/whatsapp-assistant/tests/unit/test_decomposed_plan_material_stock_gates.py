"""Phase A5 of docs/execution/UNIFIED_UNDERSTANDING_PIPELINE.md: material-
unit/stock gates now run per decomposed segment, closing the other half of
§14's gap (project/site was already closed 2026-07-30). Fakes only -- no
live DB, no LangGraph.

Exercises the real chain: decompose -> per-segment extract -> canonicalize
-> _run_segment_gates (seeding.py's real gate functions, completely
unmodified) -> pause + persist (PendingDecompositionStore, holding
built_events/pending_event/segments) -> a picker tap -> resume -> continue
the decomposition loop -> the §8 preview, exactly as a single-segment
material report would gate, just generalized across N segments.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from mesiri.infrastructure.objectstorage.fake import FakeObjectStorage
from mesiri_ai.fakes import (
    FakeDecompositionProvider,
    FakeVisionProvider,
    FakeVoiceExtractionProvider,
)
from mesiri_ai.models import DecompositionResult, ExtractionResult
from mesiri_contracts.assistant.enums import InputModality
from mesiri_contracts.assistant.normalized_message import NormalizedMessage, SenderInfo
from mesiri_contracts.assistant.understanding_result import UnderstandingResult
from mesiri_contracts.assistant.v2.resolved_context import ResolvedContextV2
from planning.plan import StepStatus
from planning.plan_store import PlanStore
from runtime.inbound_journey.decomposed_plan import (
    resume_pending_decomposition_with_material,
    resume_pending_decomposition_with_stock_choice,
    try_start_decomposed_plan,
)
from runtime.inbound_journey.pending_decomposition import PendingDecompositionStore
from understanding.pipeline import UnderstandingPipeline

ORG = "11111111-1111-4111-8111-111111111111"
USR = "22222222-2222-4222-8222-222222222222"
PRJ = "33333333-3333-4333-8333-333333333333"
SITE = "44444444-4444-4444-8444-444444444444"


class _FakeRedis:
    def __init__(self) -> None:
        self._store: dict[str, Any] = {}

    def namespaced(self, *parts: str) -> str:
        return ":".join(parts)

    async def set_json(self, key: str, value: Any, *, ttl_seconds: int | None = None) -> None:
        self._store[key] = value

    async def get_json(self, key: str) -> Any | None:
        return self._store.get(key)


class _SequentialExtractionProvider:
    provider = "fake"

    def __init__(self, results: list[ExtractionResult]) -> None:
        self._results = list(results)
        self.calls = 0

    async def extract(self, text, *, semantic_hint=None, expense_categories=None, correlation_id=None):
        result = self._results[self.calls]
        self.calls += 1
        return result


class _FakeCatalogQuery:
    """Mirrors test_material_unit_gates.py's own fake exactly -- the gate
    functions this module calls are the SAME ones that file tests, just
    driven from a decomposition segment instead of a single message."""

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


class _FakeInventoryQuery:
    def __init__(self, levels: list[dict[str, Any]]) -> None:
        self._levels = levels

    async def query(self, **kwargs) -> list[dict[str, Any]]:
        return list(self._levels)


class _Actor:
    """One project, one site -- so _resolve_project_and_site auto-resolves
    silently and every segment's event already carries project_id/site_id,
    exactly as the module docstring says it will by the time a segment
    reaches _run_segment_gates."""

    def __init__(self) -> None:
        self.role = "ENGINEER"
        self.projects = [_Obj(id=PRJ, name="Alpha", location=None)]
        self.sites = [_Obj(id=SITE, name="Site A", project_id=PRJ)]


class _Obj:
    def __init__(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)


def _understanding(*, normalized_text: str) -> UnderstandingResult:
    return UnderstandingResult(
        source_message_id="msg_1",
        correlation_id="cor_1",
        input_modality=InputModality.TEXT,
        normalized_text=normalized_text,
    )


def _resolved_context() -> ResolvedContextV2:
    return ResolvedContextV2(
        correlation_id="cor_1",
        source_message_id="msg_1",
        conversation_id="conv_1",
        context_organization_id=ORG,
        context_user_id=USR,
        organization_id=ORG,
        user_id=USR,
        permissions=["projects:write", "sites:write", "users:write"],
    )


async def _pipeline(extraction) -> UnderstandingPipeline:
    return UnderstandingPipeline(
        voice_extraction=FakeVoiceExtractionProvider(),
        vision=FakeVisionProvider(),
        extraction=extraction,
        object_storage=FakeObjectStorage(),
    )


def _tap(row_id: str) -> NormalizedMessage:
    return NormalizedMessage(
        message_id="wamid.tap.1",
        correlation_id="cor_tap",
        sender=SenderInfo(wa_id="wa_engineer", profile_name="Engineer"),
        timestamp=datetime(2026, 7, 31, 10, 0, tzinfo=UTC),
        modality=InputModality.INTERACTIVE,
        metadata={"interactive_reply_id": row_id},
    )


async def test_ambiguous_material_on_a_later_segment_holds_the_whole_decomposition():
    """The core new behaviour: segment 1 fully resolves and is remembered
    (built_events); segment 2's own material name is ambiguous, so THAT
    segment (not the whole message) pauses -- with segment 1's already-done
    work preserved, not re-processed."""
    decomposition = FakeDecompositionProvider(
        DecompositionResult(
            is_multi_intent=True,
            segments=["create a project called Starship", "used 50 bags of cement"],
        )
    )
    extraction = _SequentialExtractionProvider(
        [
            ExtractionResult(
                semantic_type="project_create", fields={"name": "Starship"}, provider="fake"
            ),
            ExtractionResult(
                semantic_type="material_update",
                fields={"material_name": "cement", "quantity": 50, "unit": "bags", "direction": "used"},
                provider="fake",
            ),
        ]
    )
    plan_store = PlanStore(_FakeRedis())
    pending_decomposition_store = PendingDecompositionStore(_FakeRedis())
    catalog_query = _FakeCatalogQuery(
        find_materials_result=[{"id": "mat_1", "name": "OPC Cement 53 Grade"}],
        # Read again once the tap sets material_id -- _run_material_unit_gates'
        # "else" branch (material_id already known) looks it up by id.
        get_material_result={"id": "mat_1", "is_active": True, "default_unit_id": None},
    )

    reply = await try_start_decomposed_plan(
        message_modality=InputModality.TEXT,
        understanding=_understanding(normalized_text="create a project, then used 50 bags of cement"),
        resolved=_resolved_context(),
        pipeline=await _pipeline(extraction),
        decomposition=decomposition,
        plan_store=plan_store,
        expense_categories=None,
        correlation_id="cor_1",
        actor=_Actor(),
        actor_user_id=USR,
        pending_decomposition_store=pending_decomposition_store,
        catalog_query=catalog_query,
    )

    assert reply is not None
    assert reply.list_rows is not None
    # render_material_picker prefixes "mat_" onto the catalog's own id.
    assert {row.id for row in reply.list_rows} >= {"mat_mat_1"}
    # Nothing persisted to PlanStore yet -- the decomposition itself is
    # still paused, not a plan.
    assert await plan_store.get_plan(user_id=USR) is None

    # Tap the material picker.
    reply2 = await resume_pending_decomposition_with_material(
        _tap("mat_mat_1"),
        USR,
        pending_decomposition_store=pending_decomposition_store,
        plan_store=plan_store,
        pipeline=await _pipeline(_SequentialExtractionProvider([])),
        actor=_Actor(),
        catalog_query=catalog_query,
    )

    assert reply2 is not None
    assert reply2.text.startswith("I'll do 2 things:")
    plan = await plan_store.get_plan(user_id=USR)
    assert plan is not None
    assert len(plan.steps) == 2
    assert all(s.status is StepStatus.PENDING for s in plan.steps)
    # Segment 2's material_id landed from the tap, not re-looked-up.
    s2 = plan.step("s2")
    assert s2 is not None
    assert s2.fields.get("material_id") == "mat_1"


class _ConfirmFirst:
    """Settings stand-in for a company switched back to confirm-first."""

    async def get(self, *, organization_id: str, key: str):
        from mesiri.domains.organizations import settings as settings_spec

        if key == settings_spec.CAPTURE_MODE:
            return settings_spec.CAPTURE_MODE_CONFIRM_FIRST
        return settings_spec.default_for(key)


async def test_an_over_stock_segment_holds_and_capping_continues_the_decomposition():
    """The stock gate, per segment, with a segment queued behind the paused
    one -- capping should both fix this segment's quantity AND let the
    decomposition continue to what's next."""
    decomposition = FakeDecompositionProvider(
        DecompositionResult(
            is_multi_intent=True,
            segments=["used 70 bags of cement", "create a site called Site B"],
        )
    )
    extraction = _SequentialExtractionProvider(
        [
            ExtractionResult(
                semantic_type="material_update",
                fields={
                    "material_name": "cement",
                    "quantity": 70,
                    "unit": "bags",
                    "direction": "used",
                    "material_id": "mat_1",
                    "unit_id": "unit_1",
                },
                provider="fake",
            ),
            ExtractionResult(semantic_type="site_create", fields={"name": "Site B"}, provider="fake"),
        ]
    )
    plan_store = PlanStore(_FakeRedis())
    pending_decomposition_store = PendingDecompositionStore(_FakeRedis())
    catalog_query = _FakeCatalogQuery(get_material_result={"id": "mat_1", "is_active": True, "default_unit_id": None})
    inventory_query = _FakeInventoryQuery([{"current_stock": 50}])

    reply = await try_start_decomposed_plan(
        message_modality=InputModality.TEXT,
        understanding=_understanding(normalized_text="used 70 bags of cement, then create Site B"),
        resolved=_resolved_context(),
        pipeline=await _pipeline(extraction),
        decomposition=decomposition,
        plan_store=plan_store,
        expense_categories=None,
        correlation_id="cor_1",
        actor=_Actor(),
        actor_user_id=USR,
        pending_decomposition_store=pending_decomposition_store,
        catalog_query=catalog_query,
        inventory_query=inventory_query,
        # WA-03: only a confirm-first company is asked about stock.
        org_settings_query=_ConfirmFirst(),
    )

    assert reply is not None
    assert reply.buttons is not None
    assert {b.title for b in reply.buttons} == {"Cap at available", "It's an arrival", "Cancel"}
    assert "only 50" in reply.text

    # The segment queued BEHIND the paused one ("create a site called Site
    # B") still has to be extracted once the decomposition continues.
    resume_extraction = _SequentialExtractionProvider(
        [ExtractionResult(semantic_type="site_create", fields={"name": "Site B"}, provider="fake")]
    )
    reply2 = await resume_pending_decomposition_with_stock_choice(
        _tap("stock_cap"),
        USR,
        pending_decomposition_store=pending_decomposition_store,
        plan_store=plan_store,
        pipeline=await _pipeline(resume_extraction),
        actor=_Actor(),
        catalog_query=catalog_query,
        inventory_query=inventory_query,
    )

    assert reply2 is not None
    assert reply2.text.startswith("I'll do 2 things:")
    plan = await plan_store.get_plan(user_id=USR)
    assert plan is not None
    assert len(plan.steps) == 2
    s1 = plan.step("s1")
    assert s1 is not None
    assert s1.fields.get("quantity") == 50  # capped down from 70


async def test_resume_material_returns_expired_message_when_nothing_is_pending():
    reply = await resume_pending_decomposition_with_material(
        _tap("mat_1"),
        USR,
        pending_decomposition_store=PendingDecompositionStore(_FakeRedis()),
        plan_store=PlanStore(_FakeRedis()),
        pipeline=await _pipeline(_SequentialExtractionProvider([])),
        actor=_Actor(),
    )
    assert reply is not None
    assert "expired" in reply.text


async def test_resume_material_ignores_a_non_material_row_id():
    reply = await resume_pending_decomposition_with_material(
        _tap("stock_cap"),
        USR,
        pending_decomposition_store=PendingDecompositionStore(_FakeRedis()),
        plan_store=PlanStore(_FakeRedis()),
        pipeline=await _pipeline(_SequentialExtractionProvider([])),
        actor=None,
    )
    assert reply is None


async def test_a_project_or_site_pause_is_not_mistaken_for_a_gate_pause():
    """_pop_gate_pending must treat a held project/site pause (pending_event
    is None) the same as nothing held -- never resume a gate leg against a
    PendingDecomposition that was never paused on a gate at all."""
    from planning.plan_store import PlanStore as _PS
    from runtime.inbound_journey.pending_decomposition import PendingDecomposition

    store = PendingDecompositionStore(_FakeRedis())
    await store.set_pending(
        user_id=USR,
        pending=PendingDecomposition(
            segments=("used 50 bags of cement",),
            resolved=_resolved_context(),
            expense_categories=None,
        ),
    )

    reply = await resume_pending_decomposition_with_material(
        _tap("mat_1"),
        USR,
        pending_decomposition_store=store,
        plan_store=_PS(_FakeRedis()),
        pipeline=await _pipeline(_SequentialExtractionProvider([])),
        actor=_Actor(),
    )
    assert reply is not None
    assert "expired" in reply.text
