"""_seed_open_activity -- unit tests.

Covers the rewritten seeding layer (docs/execution/
ACTIVITY_RESOLUTION_AND_CORRECTION_PLAN.md): it now runs for the single
merged WorkflowKey.SITE_UPDATE (not a separate ACTIVITY_CONTINUATION key,
which is retired) and seeds every open activity as a candidate list
(`_open_activity_candidates`) rather than picking one by recency -- that
recency-only pick was F1's root cause. workflows/site_update/nodes.py's
resolve_target is what actually scores the candidates; this only covers the
wiring that supplies them. Mirrors test_seed_activity_search.py's shape: a
fake ActivityQueryService stands in for the Postgres-backed one.
"""

from __future__ import annotations

from mesiri_contracts.assistant.canonical_event import CanonicalEventType, IntentCompleteness
from mesiri_contracts.assistant.planner_decision import (
    PlannerDecisionType,
    PlannerPriority,
    WorkflowKey,
)
from mesiri_contracts.assistant.v2.canonical_event import CanonicalEventV2
from mesiri_contracts.assistant.v2.planner_decision import PlannerDecisionV2
from runtime.inbound_journey import _seed_open_activity

ORG = "11111111-1111-4111-8111-111111111111"
USR = "22222222-2222-4222-8222-222222222222"
PRJ = "33333333-3333-4333-8333-333333333333"
SITE = "44444444-4444-4444-8444-444444444444"
PLASTERING_ID = "55555555-5555-4555-8555-555555555555"
BLOCKWORK_ID = "66666666-6666-4666-8666-666666666666"


class _Actor:
    organization_id = ORG
    user_id = USR
    role = "site_engineer"


class _FakeActivityQueryService:
    """Stands in for runtime/activity_query.py's real Postgres-backed
    ActivityQueryService."""

    def __init__(
        self,
        *,
        open_activities: list[dict] | None = None,
        remembered_lookup: dict | None = None,
    ):
        self._open_activities = open_activities or []
        self._remembered_lookup = remembered_lookup or {}
        self.find_open_activities_calls: list[dict] = []
        self.get_activity_if_open_calls: list[dict] = []

    async def find_open_activities(self, **kwargs):
        self.find_open_activities_calls.append(kwargs)
        return list(self._open_activities)

    async def get_activity_if_open(self, *, organization_id: str, activity_id: str):
        self.get_activity_if_open_calls.append(
            {"organization_id": organization_id, "activity_id": activity_id}
        )
        return self._remembered_lookup.get(activity_id)


def _decision() -> PlannerDecisionV2:
    return PlannerDecisionV2(
        correlation_id="cor_1",
        source_message_id="msg_1",
        decision_type=PlannerDecisionType.START_WORKFLOW,
        workflow_key=WorkflowKey.SITE_UPDATE,
        reason=CanonicalEventType.GENERAL_SITE_UPDATE_REQUESTED,
        priority=PlannerPriority.NORMAL,
        organization_id=ORG,
        user_id=USR,
        project_id=PRJ,
        site_id=SITE,
    )


def _event(fields: dict) -> CanonicalEventV2:
    return CanonicalEventV2(
        event_id="evt_1",
        correlation_id="cor_1",
        source_message_id="msg_1",
        event_type=CanonicalEventType.GENERAL_SITE_UPDATE_REQUESTED,
        completeness=IntentCompleteness.ACTIONABLE,
        organization_id=ORG,
        user_id=USR,
        project_id=PRJ,
        site_id=SITE,
        fields=fields,
    )


async def test_seeds_every_open_activity_not_just_the_most_recent():
    """The F1 fix at its source: both open activities are seeded, so
    workflows/site_update/matching.py has enough information to tell them
    apart by work_type, rather than being handed only the most recent one."""
    service = _FakeActivityQueryService(
        open_activities=[
            {"activity_id": BLOCKWORK_ID, "work_type": "blockwork", "narrative": "Block A", "status": "IN_PROGRESS"},
            {"activity_id": PLASTERING_ID, "work_type": "plastering", "narrative": "2nd floor", "status": "IN_PROGRESS"},
        ]
    )
    event = _event({"work_type": "plastering", "narrative": "finished plastering"})
    decision = _decision()

    await _seed_open_activity(event, decision, service, _Actor())

    candidates = event.fields["_open_activity_candidates"]
    assert {c["activity_id"] for c in candidates} == {BLOCKWORK_ID, PLASTERING_ID}
    assert "activity_id" not in event.fields


async def test_no_open_activities_leaves_fields_untouched():
    """F2's fix, verified at the seeding layer: no candidates seeded at all
    (not even an empty list) means resolve_target's candidate check finds
    nothing and falls through to activity creation -- never a dead end."""
    service = _FakeActivityQueryService(open_activities=[])
    event = _event({"narrative": "finished the work"})
    decision = _decision()

    await _seed_open_activity(event, decision, service, _Actor())

    assert "activity_id" not in event.fields
    assert "_open_activity_candidates" not in event.fields


async def test_remembered_activity_id_wins_outright_without_calling_find_open_activities():
    """A conversation-scoped remembered activity_id (memory/
    conversation_scope.py's CurrentActivityStore) is tried first and, if
    still open, resolves activity_id directly -- skipping the candidate-list
    lookup (and therefore all scoring) entirely, since it's strictly better
    evidence than anything content-based."""
    service = _FakeActivityQueryService(
        open_activities=[
            {"activity_id": BLOCKWORK_ID, "work_type": "blockwork", "narrative": "Block A", "status": "IN_PROGRESS"}
        ],
        remembered_lookup={
            PLASTERING_ID: {
                "activity_id": PLASTERING_ID,
                "work_type": "plastering",
                "narrative": "2nd floor",
                "status": "IN_PROGRESS",
            }
        },
    )
    event = _event({"narrative": "another 40 sqm done"})
    decision = _decision()

    await _seed_open_activity(
        event, decision, service, _Actor(), remembered_activity_id=PLASTERING_ID
    )

    assert event.fields["activity_id"] == PLASTERING_ID
    assert event.fields["activity_summary"] == "plastering — 2nd floor"
    assert service.find_open_activities_calls == []
    assert "_open_activity_candidates" not in event.fields


async def test_stale_remembered_activity_id_falls_through_to_candidate_list():
    """A remembered id that no longer resolves (already completed, deleted,
    or never existed) is not an error -- it degrades to the normal
    candidate-list seeding."""
    service = _FakeActivityQueryService(
        open_activities=[
            {"activity_id": BLOCKWORK_ID, "work_type": "blockwork", "narrative": "Block A", "status": "IN_PROGRESS"}
        ],
        remembered_lookup={},
    )
    event = _event({"narrative": "finished it"})
    decision = _decision()

    await _seed_open_activity(
        event, decision, service, _Actor(), remembered_activity_id="stale-id-not-found"
    )

    assert "activity_id" not in event.fields
    assert len(event.fields["_open_activity_candidates"]) == 1
    assert len(service.find_open_activities_calls) == 1


async def test_is_a_no_op_for_a_different_workflow():
    """WorkflowKey.ACTIVITY_CONTINUATION is retired as a registry entry, but
    the seed function must still correctly ignore any workflow key other
    than SITE_UPDATE -- e.g. a completely unrelated one like LABOUR_QUERY."""
    service = _FakeActivityQueryService(
        open_activities=[
            {"activity_id": BLOCKWORK_ID, "work_type": "blockwork", "narrative": None, "status": "IN_PROGRESS"}
        ]
    )
    event = _event({"narrative": "how many workers today"})
    decision = PlannerDecisionV2(
        correlation_id="cor_1",
        source_message_id="msg_1",
        decision_type=PlannerDecisionType.START_WORKFLOW,
        workflow_key=WorkflowKey.LABOUR_QUERY,
        reason=CanonicalEventType.LABOUR_QUERY_ASKED,
        priority=PlannerPriority.NORMAL,
        organization_id=ORG,
        user_id=USR,
        project_id=PRJ,
        site_id=SITE,
    )

    await _seed_open_activity(event, decision, service, _Actor())

    assert service.find_open_activities_calls == []
    assert "activity_id" not in event.fields
    assert "_open_activity_candidates" not in event.fields


async def test_is_a_safe_no_op_with_no_service_wired():
    event = _event({"narrative": "finished it"})
    decision = _decision()

    await _seed_open_activity(event, decision, None, _Actor())

    assert "activity_id" not in event.fields


class _CaptureMode:
    def __init__(self, mode: str) -> None:
        self._mode = mode

    async def get(self, *, organization_id: str, key: str):
        assert key == "capture_mode"
        return self._mode


async def test_save_first_company_is_told_to_save_unclear_work_as_new():
    """WA-03: seeding marks the event so resolve_target won't ask; a
    confirm-first company keeps the question."""
    from workflows.site_update.nodes import UNCLEAR_TARGET_IS_NEW_KEY

    open_ = [{"activity_id": BLOCKWORK_ID, "work_type": "blockwork", "narrative": "Block A"}]
    for mode, flagged in (("save_first", True), ("confirm_first", False)):
        event = _event({"work_type": "plastering"})
        await _seed_open_activity(
            event,
            _decision(),
            _FakeActivityQueryService(open_activities=open_),
            _Actor(),
            org_settings_query=_CaptureMode(mode),
        )
        assert bool(event.fields.get(UNCLEAR_TARGET_IS_NEW_KEY)) is flagged
