"""_seed_activity_search -- #17 Search / Ask Mesiri's seeding branch.

Mirrors test_seed_reversal_target.py's shape: a fake ActivitySearchService
stands in for the real Postgres-backed one (which needs a live DB and is
covered by that service's own SQL, not here). What's protected here is pure
wiring: ACTIVITY_QUERY resolves a date range and calls search() with the
event's scope, writing the result onto collected_fields the reply node
reads.

Also covers _seed_labour_query the same way: that seed function existed but
was never actually invoked from the gather() list in process_inbound_message
(a real wiring bug fixed alongside this feature -- see inbound_journey.py's
gather() comment), so its own wiring had no direct test either.
"""

from __future__ import annotations

import datetime

from mesiri_contracts.assistant.canonical_event import CanonicalEventType, IntentCompleteness
from mesiri_contracts.assistant.planner_decision import (
    PlannerDecisionType,
    PlannerPriority,
    WorkflowKey,
)
from mesiri_contracts.assistant.v2.canonical_event import CanonicalEventV2
from mesiri_contracts.assistant.v2.planner_decision import PlannerDecisionV2
from runtime.inbound_journey import _seed_activity_search, _seed_labour_query

ORG = "11111111-1111-4111-8111-111111111111"
USR = "22222222-2222-4222-8222-222222222222"
PRJ = "33333333-3333-4333-8333-333333333333"
SITE = "44444444-4444-4444-8444-444444444444"


class _Actor:
    organization_id = ORG
    user_id = USR
    role = "site_engineer"


class _FakeActivitySearchService:
    def __init__(self, result: dict):
        self._result = result
        self.calls: list[dict] = []

    async def search(self, **kwargs):
        self.calls.append(kwargs)
        return dict(self._result)


class _FakeLabourQueryService:
    def __init__(self, result: dict):
        self._result = result
        self.calls: list[dict] = []

    async def summarize_attendance(self, **kwargs):
        self.calls.append(kwargs)
        return dict(self._result)


def _decision(workflow_key: WorkflowKey, reason: CanonicalEventType) -> PlannerDecisionV2:
    return PlannerDecisionV2(
        correlation_id="cor_1",
        source_message_id="msg_1",
        decision_type=PlannerDecisionType.START_WORKFLOW,
        workflow_key=workflow_key,
        reason=reason,
        priority=PlannerPriority.NORMAL,
        organization_id=ORG,
        user_id=USR,
        project_id=PRJ,
        site_id=SITE,
    )


def _event(event_type: CanonicalEventType, fields: dict) -> CanonicalEventV2:
    return CanonicalEventV2(
        event_id="evt_1",
        correlation_id="cor_1",
        source_message_id="msg_1",
        event_type=event_type,
        completeness=IntentCompleteness.ACTIONABLE,
        organization_id=ORG,
        user_id=USR,
        project_id=PRJ,
        site_id=SITE,
        fields=fields,
    )


async def test_activity_search_calls_service_with_event_scope_and_seeds_results():
    service = _FakeActivitySearchService(
        {"activities": [], "activity_count": 0, "open_issues": [], "open_issue_count": 0}
    )
    event = _event(CanonicalEventType.ACTIVITY_QUERY_ASKED, {})
    decision = _decision(WorkflowKey.ACTIVITY_QUERY, CanonicalEventType.ACTIVITY_QUERY_ASKED)

    await _seed_activity_search(event, decision, service, _Actor(), "Asia/Kolkata")

    assert len(service.calls) == 1
    call = service.calls[0]
    assert call["organization_id"] == ORG
    assert call["project_id"] == PRJ
    assert call["site_id"] == SITE
    assert call["start_date"] == call["end_date"]  # defaults to "today"
    assert "activity_search_results" in event.fields
    assert event.fields["activity_search_results"]["date_range_label"] == "today"


async def test_activity_search_respects_extracted_date_range_and_work_type():
    service = _FakeActivitySearchService(
        {"activities": [], "activity_count": 0, "open_issues": [], "open_issue_count": 0}
    )
    event = _event(
        CanonicalEventType.ACTIVITY_QUERY_ASKED,
        {"date_range": "this_week", "work_type": "plastering"},
    )
    decision = _decision(WorkflowKey.ACTIVITY_QUERY, CanonicalEventType.ACTIVITY_QUERY_ASKED)

    await _seed_activity_search(event, decision, service, _Actor(), "Asia/Kolkata")

    call = service.calls[0]
    assert call["work_type"] == "plastering"
    assert call["start_date"] <= call["end_date"]
    assert event.fields["activity_search_results"]["date_range_label"] == "this week"


async def test_activity_search_yesterday_searches_yesterday_not_today():
    """V1 audit WRK-03: "what work was done yesterday?" listed today's work."""
    from canonicalization.occurred_date import today_for

    service = _FakeActivitySearchService(
        {"activities": [], "activity_count": 0, "open_issues": [], "open_issue_count": 0}
    )
    event = _event(CanonicalEventType.ACTIVITY_QUERY_ASKED, {"day": "yesterday"})
    decision = _decision(WorkflowKey.ACTIVITY_QUERY, CanonicalEventType.ACTIVITY_QUERY_ASKED)

    await _seed_activity_search(event, decision, service, _Actor(), "Asia/Kolkata")

    yesterday = today_for("Asia/Kolkata") - datetime.timedelta(days=1)
    call = service.calls[0]
    assert call["start_date"] == call["end_date"] == yesterday
    assert event.fields["activity_search_results"]["date_range_label"] == "yesterday"


async def test_activity_search_iso_day_and_future_day():
    from canonicalization.occurred_date import today_for

    today = today_for("Asia/Kolkata")
    service = _FakeActivitySearchService(
        {"activities": [], "activity_count": 0, "open_issues": [], "open_issue_count": 0}
    )
    decision = _decision(WorkflowKey.ACTIVITY_QUERY, CanonicalEventType.ACTIVITY_QUERY_ASKED)
    day = today - datetime.timedelta(days=5)
    event = _event(CanonicalEventType.ACTIVITY_QUERY_ASKED, {"day": day.isoformat()})
    await _seed_activity_search(event, decision, service, _Actor(), "Asia/Kolkata")
    assert service.calls[-1]["start_date"] == day
    assert event.fields["activity_search_results"]["date_range_label"] == f"{day.day} {day:%b}"

    # A future day is a misread: fall back to the range (today), as before.
    future = _event(
        CanonicalEventType.ACTIVITY_QUERY_ASKED, {"day": (today + datetime.timedelta(days=2)).isoformat()}
    )
    await _seed_activity_search(future, decision, service, _Actor(), "Asia/Kolkata")
    assert service.calls[-1]["start_date"] == today


async def test_activity_search_is_a_no_op_for_a_different_workflow():
    service = _FakeActivitySearchService({})
    event = _event(CanonicalEventType.LABOUR_QUERY_ASKED, {})
    decision = _decision(WorkflowKey.LABOUR_QUERY, CanonicalEventType.LABOUR_QUERY_ASKED)

    await _seed_activity_search(event, decision, service, _Actor(), "Asia/Kolkata")

    assert service.calls == []
    assert "activity_search_results" not in event.fields


async def test_activity_search_is_a_safe_no_op_with_no_service_wired():
    event = _event(CanonicalEventType.ACTIVITY_QUERY_ASKED, {})
    decision = _decision(WorkflowKey.ACTIVITY_QUERY, CanonicalEventType.ACTIVITY_QUERY_ASKED)

    await _seed_activity_search(event, decision, None, _Actor(), "Asia/Kolkata")

    assert "activity_search_results" not in event.fields


async def test_labour_query_seeding_calls_service_and_seeds_results():
    """The wiring bug this session fixed: _seed_labour_query existed and
    worked in isolation but was never called from process_inbound_message's
    gather() list, so every attendance question silently fell through to
    "no attendance recorded" regardless of what was logged. This proves the
    function itself is correct now that it is actually reachable."""
    service = _FakeLabourQueryService(
        {"headcount": 5, "total_cost": "1000", "named": [], "trades": [], "days": 1}
    )
    event = _event(CanonicalEventType.LABOUR_QUERY_ASKED, {})
    decision = _decision(WorkflowKey.LABOUR_QUERY, CanonicalEventType.LABOUR_QUERY_ASKED)

    await _seed_labour_query(event, decision, service, _Actor(), "Asia/Kolkata")

    assert len(service.calls) == 1
    assert event.fields["labour_results"]["headcount"] == 5
    assert event.fields["labour_results"]["date_range_label"] == "today"


def test_start_date_defaults_match_today_for_ist():
    from runtime.labour_query_service import resolve_date_range

    start, end, label = resolve_date_range(None, today=datetime.date(2026, 7, 27))
    assert start == end == datetime.date(2026, 7, 27)
    assert label == "today"
