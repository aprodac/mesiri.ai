"""Unit tests for runtime/inbound_journey/decomposed_plan.py -- the wiring
that gives an UNKNOWN-classified message a second chance to become a
multi-step Plan (docs/execution/COMPOSITE_REQUEST_PLAN_LAYER.md §9).

Fakes only, but exercises the REAL chain: decompose -> per-segment extract
via a real UnderstandingPipeline -> build_canonical_event -> entity linking
-> PlanStore.start_plan (all-PENDING) -> the whole-plan preview (§8). No
WorkflowRuntime involved here at all: this function never starts a workflow,
only persists a plan and describes it -- see test_plan_confirmation.py for
what happens once the user actually taps Yes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from backend.ports import ActorIdentity, ProjectSummary, SiteSummary
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
    resume_pending_decomposition_with_project,
    resume_pending_decomposition_with_site,
    try_start_decomposed_plan,
)
from runtime.inbound_journey.pending_decomposition import PendingDecompositionStore
from understanding.pipeline import UnderstandingPipeline

ORG = "11111111-1111-4111-8111-111111111111"
USR = "22222222-2222-4222-8222-222222222222"


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
    """Returns a different canned ExtractionResult per call, in order --
    what a real provider does when given a different segment each time.
    FakeExtractionProvider only supports one fixed result for every call."""

    provider = "fake"

    def __init__(self, results: list[ExtractionResult]) -> None:
        self._results = list(results)
        self.calls = 0
        self.texts: list[str] = []

    async def extract(self, text, *, semantic_hint=None, expense_categories=None, correlation_id=None):
        self.texts.append(text)
        result = self._results[self.calls]
        self.calls += 1
        return result


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


async def test_returns_none_when_no_decomposition_provider_is_wired():
    """The overwhelmingly common deployment state today -- must be a cheap,
    silent no-op so the caller falls through to its existing behaviour."""
    reply = await try_start_decomposed_plan(
        message_modality=InputModality.TEXT,
        understanding=_understanding(normalized_text="asdkjhaskjdh"),
        resolved=_resolved_context(),
        pipeline=await _pipeline(_SequentialExtractionProvider([])),
        decomposition=None,
        plan_store=PlanStore(_FakeRedis()),
        expense_categories=None,
        correlation_id="cor_1",
    )
    assert reply is None


async def test_returns_none_for_a_non_decomposable_modality():
    reply = await try_start_decomposed_plan(
        message_modality=InputModality.IMAGE,
        understanding=_understanding(normalized_text="whatever"),
        resolved=_resolved_context(),
        pipeline=await _pipeline(_SequentialExtractionProvider([])),
        decomposition=FakeDecompositionProvider(
            DecompositionResult(is_multi_intent=True, segments=["a", "b"])
        ),
        plan_store=PlanStore(_FakeRedis()),
        expense_categories=None,
        correlation_id="cor_1",
    )
    assert reply is None


async def test_returns_none_when_decomposition_says_not_multi_intent():
    """Genuine gibberish/one real intent must fall through to today's
    ordinary unrecognized-message reply, not become a size-1 "plan"."""
    reply = await try_start_decomposed_plan(
        message_modality=InputModality.TEXT,
        understanding=_understanding(normalized_text="asdkjhaskjdh"),
        resolved=_resolved_context(),
        pipeline=await _pipeline(_SequentialExtractionProvider([])),
        decomposition=FakeDecompositionProvider(DecompositionResult(is_multi_intent=False)),
        plan_store=PlanStore(_FakeRedis()),
        expense_categories=None,
        correlation_id="cor_1",
    )
    assert reply is None


async def test_returns_none_when_decomposition_provider_raises():
    class _Boom:
        provider = "boom"

        async def decompose(self, text, *, correlation_id=None):
            raise RuntimeError("provider outage")

    reply = await try_start_decomposed_plan(
        message_modality=InputModality.TEXT,
        understanding=_understanding(normalized_text="whatever"),
        resolved=_resolved_context(),
        pipeline=await _pipeline(_SequentialExtractionProvider([])),
        decomposition=_Boom(),
        plan_store=PlanStore(_FakeRedis()),
        expense_categories=None,
        correlation_id="cor_1",
    )
    assert reply is None


async def test_the_starship_message_produces_the_whole_plan_preview():
    """The scenario that motivated all of this: "create a project called
    Starship and then create a site called Site A, then create a new user
    Hysam, 9198765xxxxx" -- decompose -> per-segment extract -> canonicalize
    -> link -> persist all-PENDING -> the §8 preview, not a running step.

    The user segment states BOTH full_name and whatsapp_number -- see
    test_a_deferred_required_field_drops_the_segment_from_the_plan below for
    what happens to §9's original example, where the number was promised in
    a follow-up message instead of stated in the same breath.
    """
    decomposition = FakeDecompositionProvider(
        DecompositionResult(
            is_multi_intent=True,
            segments=[
                "create a project called Starship",
                "create a site called Site A",
                "create a new user named Hysam, 9198765xxxxx",
            ],
        )
    )
    extraction = _SequentialExtractionProvider(
        [
            ExtractionResult(
                semantic_type="project_create", fields={"name": "Starship"}, provider="fake"
            ),
            ExtractionResult(
                semantic_type="site_create", fields={"name": "Site A"}, provider="fake"
            ),
            ExtractionResult(
                semantic_type="create_user",
                fields={"full_name": "Hysam", "whatsapp_number": "9198765xxxxx"},
                provider="fake",
            ),
        ]
    )
    plan_store = PlanStore(_FakeRedis())

    reply = await try_start_decomposed_plan(
        message_modality=InputModality.TEXT,
        understanding=_understanding(
            normalized_text=(
                "create a project called Starship and then create a site called Site A, "
                "then create a new user named Hysam, 9198765xxxxx"
            )
        ),
        resolved=_resolved_context(),
        pipeline=await _pipeline(extraction),
        decomposition=decomposition,
        plan_store=plan_store,
        expense_categories=None,
        correlation_id="cor_starship",
    )

    assert reply is not None
    assert reply.text.startswith("I'll do 3 things:")
    assert "Create project Starship" in reply.text
    assert "Create site Site A under Starship" in reply.text
    assert "Add Hysam (9198765xxxxx) as a new user" in reply.text
    # Yes/No/Edit, not a per-step confirmation -- nothing has started.
    assert reply.buttons is not None
    assert {b.title for b in reply.buttons} == {"Yes", "No", "Edit"}
    assert decomposition.calls == 1
    assert extraction.calls == 3

    plan = await plan_store.get_plan(user_id=USR)
    assert plan is not None
    assert len(plan.steps) == 3
    assert all(s.status is StepStatus.PENDING for s in plan.steps)


async def test_a_deferred_required_field_drops_the_segment_from_the_plan():
    """A KNOWN V1 GAP, not a bug in this test: §9's original real message
    said "create a new user named Hysam, I'll send his number now" -- the
    number arrives in a LATER, separate message. canonicalization's own
    REQUIRED_FIELDS gate (mapping.py) requires whatsapp_number for
    CREATE_USER_REQUESTED, so this segment canonicalizes to
    CLARIFICATION_REQUIRED, which routing.py's WORKFLOW_KEY_BY_EVENT has no
    entry for by design (its docstring: CLARIFICATION_REQUIRED never starts
    a workflow) -- so build_plan_from_segments correctly, silently drops it,
    the same as any other unroutable segment.

    This differs from the single-message path, where the SAME missing field
    gets render_clarify_reply's targeted "Almost there -- I still need
    WhatsApp number" (channel/replies.py) -- and from the entity-resolution
    layer's offer-driven create (resume.py's start_member_create_plan),
    which hand-builds its CanonicalEventV2 and so never goes through this
    gate at all. Neither escape hatch exists for a decomposed segment yet.
    Silent (not a failure or a misleading reply) is the deliberate interim
    choice: the project still gets its own step in the plan, which is still
    real progress on the message, and is safer than guessing at a phone
    number. Surfacing this to the user ("I couldn't include Hysam yet --
    also send me his number") is real follow-up work, now that the preview
    exists to say it in.
    """
    decomposition = FakeDecompositionProvider(
        DecompositionResult(
            is_multi_intent=True,
            segments=[
                "create a project called Starship",
                "create a new user named Hysam",  # no phone number stated
            ],
        )
    )
    extraction = _SequentialExtractionProvider(
        [
            ExtractionResult(
                semantic_type="project_create", fields={"name": "Starship"}, provider="fake"
            ),
            ExtractionResult(
                semantic_type="create_user", fields={"full_name": "Hysam"}, provider="fake"
            ),
        ]
    )
    plan_store = PlanStore(_FakeRedis())

    reply = await try_start_decomposed_plan(
        message_modality=InputModality.TEXT,
        understanding=_understanding(
            normalized_text="create a project called Starship, then a new user named Hysam"
        ),
        resolved=_resolved_context(),
        pipeline=await _pipeline(extraction),
        decomposition=decomposition,
        plan_store=plan_store,
        expense_categories=None,
        correlation_id="cor_1",
    )

    assert reply is not None
    assert reply.text.startswith("I'll do this:")  # only the project step made it into the plan
    plan = await plan_store.get_plan(user_id=USR)
    assert [s.step_id for s in plan.steps] == ["s1"]


async def test_a_segment_that_fails_to_understand_does_not_sink_the_rest():
    decomposition = FakeDecompositionProvider(
        DecompositionResult(is_multi_intent=True, segments=["good segment", "bad segment"])
    )

    class _PartlyFailingExtraction:
        provider = "fake"

        def __init__(self) -> None:
            self.calls = 0

        async def extract(self, text, **kwargs):
            self.calls += 1
            if text == "bad segment":
                raise RuntimeError("extraction blew up")
            return ExtractionResult(
                semantic_type="project_create", fields={"name": "Starship"}, provider="fake"
            )

    plan_store = PlanStore(_FakeRedis())

    reply = await try_start_decomposed_plan(
        message_modality=InputModality.TEXT,
        understanding=_understanding(normalized_text="good segment. bad segment."),
        resolved=_resolved_context(),
        pipeline=await _pipeline(_PartlyFailingExtraction()),
        decomposition=decomposition,
        plan_store=plan_store,
        expense_categories=None,
        correlation_id="cor_1",
    )

    assert reply is not None
    plan = await plan_store.get_plan(user_id=USR)
    assert len(plan.steps) == 1  # the failing segment never became a step


async def test_no_plannable_segments_falls_through_to_none():
    """Every segment came back unroutable (e.g. all UNKNOWN again) -- no
    plan is worth starting, so the caller's ordinary fallback applies."""
    decomposition = FakeDecompositionProvider(
        DecompositionResult(is_multi_intent=True, segments=["gibberish one", "gibberish two"])
    )
    extraction = _SequentialExtractionProvider(
        [
            ExtractionResult(semantic_type="unknown", provider="fake"),
            ExtractionResult(semantic_type="unknown", provider="fake"),
        ]
    )
    reply = await try_start_decomposed_plan(
        message_modality=InputModality.TEXT,
        understanding=_understanding(normalized_text="gibberish one. gibberish two."),
        resolved=_resolved_context(),
        pipeline=await _pipeline(extraction),
        decomposition=decomposition,
        plan_store=PlanStore(_FakeRedis()),
        expense_categories=None,
        correlation_id="cor_1",
    )
    assert reply is None


# ---------------------------------------------------------------------------
# Project/site gate (§14, added 2026-07-30) -- _resolve_project_and_site and
# the two picker-tap resumes.
# ---------------------------------------------------------------------------

PROJECT_A = "33333333-3333-4333-8333-333333333333"
PROJECT_B = "44444444-4444-4444-8444-444444444444"
SITE_A = "55555555-5555-4555-8555-555555555555"
SITE_B = "66666666-6666-4666-8666-666666666666"


def _actor(*, projects: list[ProjectSummary], sites: list[SiteSummary]) -> ActorIdentity:
    return ActorIdentity(
        user_id=USR,
        full_name="Engineer",
        role="engineer",
        organization_id=ORG,
        org_name="Org",
        org_active=True,
        projects=projects,
        sites=sites,
    )


def _tap(row_id: str) -> NormalizedMessage:
    return NormalizedMessage(
        message_id="wamid.tap.1",
        correlation_id="cor_tap",
        sender=SenderInfo(wa_id="wa_engineer", profile_name="Engineer"),
        timestamp=datetime(2026, 7, 30, 10, 0, tzinfo=UTC),
        modality=InputModality.INTERACTIVE,
        metadata={"interactive_reply_id": row_id},
    )


_STARSHIP_DECOMPOSITION = DecompositionResult(
    is_multi_intent=True,
    segments=["log 5 bags of cement used", "add a labour entry for 3 masons"],
)


def _one_step_extraction() -> _SequentialExtractionProvider:
    return _SequentialExtractionProvider(
        [ExtractionResult(semantic_type="project_create", fields={"name": "Whatever"}, provider="fake")]
    )


async def test_no_projects_at_all_short_circuits_with_no_projects_reply():
    reply = await try_start_decomposed_plan(
        message_modality=InputModality.TEXT,
        understanding=_understanding(normalized_text="log cement used, add masons"),
        resolved=_resolved_context(),
        pipeline=await _pipeline(_SequentialExtractionProvider([])),
        decomposition=FakeDecompositionProvider(_STARSHIP_DECOMPOSITION),
        plan_store=PlanStore(_FakeRedis()),
        expense_categories=None,
        correlation_id="cor_1",
        actor=_actor(projects=[], sites=[]),
        actor_user_id=USR,
        pending_decomposition_store=PendingDecompositionStore(_FakeRedis()),
    )
    assert reply is not None
    assert "don't have any projects" in reply.text


async def test_single_project_and_single_site_auto_resolve_without_asking():
    """The common case: one project, one site -- the gate must not interrupt
    with a picker just because it exists, same as _run_project_gate/
    _run_site_gate's own single-option auto-resolve."""
    plan_store = PlanStore(_FakeRedis())
    extraction = _SequentialExtractionProvider(
        [
            ExtractionResult(semantic_type="project_create", fields={"name": "X"}, provider="fake"),
            ExtractionResult(semantic_type="project_create", fields={"name": "Y"}, provider="fake"),
        ]
    )
    reply = await try_start_decomposed_plan(
        message_modality=InputModality.TEXT,
        understanding=_understanding(normalized_text="log cement used, add masons"),
        resolved=_resolved_context(),
        pipeline=await _pipeline(extraction),
        decomposition=FakeDecompositionProvider(_STARSHIP_DECOMPOSITION),
        plan_store=plan_store,
        expense_categories=None,
        correlation_id="cor_1",
        actor=_actor(
            projects=[ProjectSummary(id=PROJECT_A, name="Starship")],
            sites=[SiteSummary(id=SITE_A, name="Site A", project_id=PROJECT_A)],
        ),
        actor_user_id=USR,
        pending_decomposition_store=PendingDecompositionStore(_FakeRedis()),
    )
    assert reply is not None
    assert reply.buttons is not None  # the plan preview, not a picker
    plan = await plan_store.get_plan(user_id=USR)
    assert plan is not None


async def test_multiple_projects_holds_the_decomposition_and_asks():
    reply = await try_start_decomposed_plan(
        message_modality=InputModality.TEXT,
        understanding=_understanding(normalized_text="log cement used, add masons"),
        resolved=_resolved_context(),
        pipeline=await _pipeline(_one_step_extraction()),
        decomposition=FakeDecompositionProvider(_STARSHIP_DECOMPOSITION),
        plan_store=PlanStore(_FakeRedis()),
        expense_categories=None,
        correlation_id="cor_1",
        actor=_actor(
            projects=[
                ProjectSummary(id=PROJECT_A, name="Starship"),
                ProjectSummary(id=PROJECT_B, name="Paraclette"),
            ],
            sites=[],
        ),
        actor_user_id=USR,
        pending_decomposition_store=PendingDecompositionStore(_FakeRedis()),
    )
    assert reply is not None
    assert reply.text == "Which project is this for?"
    assert reply.list_rows is not None
    assert {row.id for row in reply.list_rows} == {f"proj_{PROJECT_A}", f"proj_{PROJECT_B}"}


async def test_project_picker_tap_with_single_site_resolves_straight_to_the_plan_preview():
    pending_store = PendingDecompositionStore(_FakeRedis())
    actor = _actor(
        projects=[
            ProjectSummary(id=PROJECT_A, name="Starship"),
            ProjectSummary(id=PROJECT_B, name="Paraclette"),
        ],
        sites=[SiteSummary(id=SITE_A, name="Site A", project_id=PROJECT_A)],
    )
    # First message holds the decomposition awaiting a project pick.
    first_reply = await try_start_decomposed_plan(
        message_modality=InputModality.TEXT,
        understanding=_understanding(normalized_text="log cement used, add masons"),
        resolved=_resolved_context(),
        pipeline=await _pipeline(_one_step_extraction()),
        decomposition=FakeDecompositionProvider(_STARSHIP_DECOMPOSITION),
        plan_store=PlanStore(_FakeRedis()),
        expense_categories=None,
        correlation_id="cor_1",
        actor=actor,
        actor_user_id=USR,
        pending_decomposition_store=pending_store,
    )
    assert first_reply is not None and first_reply.list_rows is not None

    plan_store = PlanStore(_FakeRedis())
    extraction = _SequentialExtractionProvider(
        [
            ExtractionResult(semantic_type="project_create", fields={"name": "X"}, provider="fake"),
            ExtractionResult(semantic_type="project_create", fields={"name": "Y"}, provider="fake"),
        ]
    )
    reply = await resume_pending_decomposition_with_project(
        _tap(f"proj_{PROJECT_A}"),
        USR,
        pending_decomposition_store=pending_store,
        plan_store=plan_store,
        pipeline=await _pipeline(extraction),
        actor=actor,
    )
    assert reply is not None
    assert reply.buttons is not None  # site auto-resolved (only one) -- straight to the preview
    plan = await plan_store.get_plan(user_id=USR)
    assert plan is not None
    assert len(plan.steps) == 2


async def test_project_picker_tap_with_multiple_sites_asks_for_site_next():
    pending_store = PendingDecompositionStore(_FakeRedis())
    actor = _actor(
        projects=[
            ProjectSummary(id=PROJECT_A, name="Starship"),
            ProjectSummary(id=PROJECT_B, name="Paraclette"),
        ],
        sites=[
            SiteSummary(id=SITE_A, name="Site A", project_id=PROJECT_A),
            SiteSummary(id=SITE_B, name="Site B", project_id=PROJECT_A),
        ],
    )
    await try_start_decomposed_plan(
        message_modality=InputModality.TEXT,
        understanding=_understanding(normalized_text="log cement used, add masons"),
        resolved=_resolved_context(),
        pipeline=await _pipeline(_one_step_extraction()),
        decomposition=FakeDecompositionProvider(_STARSHIP_DECOMPOSITION),
        plan_store=PlanStore(_FakeRedis()),
        expense_categories=None,
        correlation_id="cor_1",
        actor=actor,
        actor_user_id=USR,
        pending_decomposition_store=pending_store,
    )

    reply = await resume_pending_decomposition_with_project(
        _tap(f"proj_{PROJECT_A}"),
        USR,
        pending_decomposition_store=pending_store,
        plan_store=PlanStore(_FakeRedis()),
        pipeline=await _pipeline(_one_step_extraction()),
        actor=actor,
    )
    assert reply is not None
    assert reply.list_rows is not None
    assert {row.id for row in reply.list_rows} == {f"site_{SITE_A}", f"site_{SITE_B}"}


async def test_site_picker_tap_builds_and_persists_the_plan():
    pending_store = PendingDecompositionStore(_FakeRedis())
    actor = _actor(
        projects=[ProjectSummary(id=PROJECT_A, name="Starship")],
        sites=[
            SiteSummary(id=SITE_A, name="Site A", project_id=PROJECT_A),
            SiteSummary(id=SITE_B, name="Site B", project_id=PROJECT_A),
        ],
    )
    await try_start_decomposed_plan(
        message_modality=InputModality.TEXT,
        understanding=_understanding(normalized_text="log cement used, add masons"),
        resolved=_resolved_context(),
        pipeline=await _pipeline(_one_step_extraction()),
        decomposition=FakeDecompositionProvider(_STARSHIP_DECOMPOSITION),
        plan_store=PlanStore(_FakeRedis()),
        expense_categories=None,
        correlation_id="cor_1",
        actor=actor,
        actor_user_id=USR,
        pending_decomposition_store=pending_store,
    )

    plan_store = PlanStore(_FakeRedis())
    extraction = _SequentialExtractionProvider(
        [
            ExtractionResult(semantic_type="project_create", fields={"name": "X"}, provider="fake"),
            ExtractionResult(semantic_type="project_create", fields={"name": "Y"}, provider="fake"),
        ]
    )
    reply = await resume_pending_decomposition_with_site(
        _tap(f"site_{SITE_B}"),
        USR,
        pending_decomposition_store=pending_store,
        plan_store=plan_store,
        pipeline=await _pipeline(extraction),
        actor=actor,
    )
    assert reply is not None
    assert reply.buttons is not None
    plan = await plan_store.get_plan(user_id=USR)
    assert plan is not None
    assert len(plan.steps) == 2


async def test_project_picker_tap_rejects_an_unauthorized_project_id():
    """An interactive reply id is untrusted client input -- must be re-checked
    against the picker's own authorized set, same defence
    resume_pending_report_with_project applies to its own tap."""
    pending_store = PendingDecompositionStore(_FakeRedis())
    actor = _actor(
        projects=[
            ProjectSummary(id=PROJECT_A, name="Starship"),
            ProjectSummary(id=PROJECT_B, name="Paraclette"),
        ],
        sites=[],
    )
    await try_start_decomposed_plan(
        message_modality=InputModality.TEXT,
        understanding=_understanding(normalized_text="log cement used, add masons"),
        resolved=_resolved_context(),
        pipeline=await _pipeline(_one_step_extraction()),
        decomposition=FakeDecompositionProvider(_STARSHIP_DECOMPOSITION),
        plan_store=PlanStore(_FakeRedis()),
        expense_categories=None,
        correlation_id="cor_1",
        actor=actor,
        actor_user_id=USR,
        pending_decomposition_store=pending_store,
    )

    reply = await resume_pending_decomposition_with_project(
        _tap("proj_not-a-real-project"),
        USR,
        pending_decomposition_store=pending_store,
        plan_store=PlanStore(_FakeRedis()),
        pipeline=await _pipeline(_one_step_extraction()),
        actor=actor,
    )
    assert reply is not None
    assert "isn't available to you" in reply.text


async def test_resume_project_returns_expired_message_when_nothing_is_pending():
    reply = await resume_pending_decomposition_with_project(
        _tap(f"proj_{PROJECT_A}"),
        USR,
        pending_decomposition_store=PendingDecompositionStore(_FakeRedis()),
        plan_store=PlanStore(_FakeRedis()),
        pipeline=await _pipeline(_SequentialExtractionProvider([])),
        actor=_actor(projects=[ProjectSummary(id=PROJECT_A, name="Starship")], sites=[]),
    )
    assert reply is not None
    assert "expired" in reply.text


async def test_resume_site_returns_expired_message_when_nothing_is_pending():
    reply = await resume_pending_decomposition_with_site(
        _tap(f"site_{SITE_A}"),
        USR,
        pending_decomposition_store=PendingDecompositionStore(_FakeRedis()),
        plan_store=PlanStore(_FakeRedis()),
        pipeline=await _pipeline(_SequentialExtractionProvider([])),
        actor=_actor(projects=[], sites=[]),
    )
    assert reply is not None
    assert "expired" in reply.text


async def test_resume_project_ignores_a_non_project_row_id():
    """A stray tap that isn't a project row must be a no-op (None), letting
    the caller's dispatch chain try the next resume function -- not swallow
    an unrelated interactive reply."""
    reply = await resume_pending_decomposition_with_project(
        _tap("site_not_a_project_row"),
        USR,
        pending_decomposition_store=PendingDecompositionStore(_FakeRedis()),
        plan_store=PlanStore(_FakeRedis()),
        pipeline=await _pipeline(_SequentialExtractionProvider([])),
        actor=None,
    )
    assert reply is None


# --- Questions and unreadable parts are not silently dropped (request [55]) --------


class _ScriptedExtraction:
    """One canned result per call; a ``None`` entry raises, like a provider
    failing on that one part."""

    provider = "fake"

    def __init__(self, results: list[ExtractionResult | None]) -> None:
        self._results = list(results)

    async def extract(self, text, *, semantic_hint=None, expense_categories=None, correlation_id=None):
        result = self._results.pop(0)
        if result is None:
            raise RuntimeError("provider failed on this part")
        return result


async def _preview_for(segments: list[str], results: list[ExtractionResult | None]):
    return await try_start_decomposed_plan(
        message_modality=InputModality.TEXT,
        understanding=_understanding(normalized_text=" and ".join(segments)),
        resolved=_resolved_context(),
        pipeline=await _pipeline(_ScriptedExtraction(results)),
        decomposition=FakeDecompositionProvider(
            DecompositionResult(is_multi_intent=True, segments=segments)
        ),
        plan_store=PlanStore(_FakeRedis()),
        expense_categories=None,
        correlation_id="cor_1",
    )


_PROJECT = ExtractionResult(semantic_type="project_create", fields={"name": "Starship"}, provider="fake")
_QUESTION = ExtractionResult(semantic_type="general_question", fields={}, provider="fake")


async def test_a_question_inside_a_site_note_is_acknowledged_in_the_same_reply():
    reply = await _preview_for(
        ["create a project called Starship", "can we pour concrete tomorrow?"],
        [_PROJECT, _QUESTION],
    )
    assert reply is not None
    assert "Starship" in reply.text
    assert 'Your question "can we pour concrete tomorrow?"' in reply.text
    assert "engineer" in reply.text
    assert reply.buttons  # still the one Yes/No preview, no second message


async def test_a_part_that_could_not_be_understood_is_named_in_the_same_reply():
    reply = await _preview_for(
        ["create a project called Starship", "asdf qwerty zzz"],
        [_PROJECT, None],
    )
    assert reply is not None
    assert "Starship" in reply.text
    assert 'I couldn\'t understand: "asdf qwerty zzz"' in reply.text


async def test_a_note_with_nothing_left_out_has_no_extra_line():
    reply = await _preview_for(
        ["create a project called Starship", "create a site called Site A"],
        [
            _PROJECT,
            ExtractionResult(semantic_type="site_create", fields={"name": "Site A"}, provider="fake"),
        ],
    )
    assert reply is not None
    assert "Your question" not in reply.text and "couldn't understand" not in reply.text
