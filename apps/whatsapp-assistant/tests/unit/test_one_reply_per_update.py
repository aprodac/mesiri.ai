"""Request [63]: one reply per site update -- no stray Labour / Cement summary.

A query segment the splitter adds to a plain site update is dropped unless the
message carries a question signal; a kept one is folded into the saved reply.
"""

from __future__ import annotations

import pytest
from tests.unit.test_worker_promotion_wiring import _block_after, _dependencies_source

from canonicalization.question_signal import drop_unasked_queries, has_question_signal
from mesiri_contracts.assistant.canonical_event import CanonicalEventType, IntentCompleteness
from mesiri_contracts.assistant.v2.canonical_event import CanonicalEventV2

ORG = "11111111-1111-4111-8111-111111111111"
USR = "22222222-2222-4222-8222-222222222222"


def _event(event_type: CanonicalEventType) -> CanonicalEventV2:
    return CanonicalEventV2(
        event_id=f"evt_{event_type.value}",
        correlation_id="cor",
        source_message_id="msg",
        event_type=event_type,
        completeness=IntentCompleteness.ACTIONABLE,
        organization_id=ORG,
        user_id=USR,
    )


def test_site_update_with_spurious_labour_query_keeps_only_the_update():
    events = [
        _event(CanonicalEventType.ACTIVITY_CONTINUATION_REQUESTED),
        _event(CanonicalEventType.LABOUR_QUERY_ASKED),
    ]
    kept = drop_unasked_queries(events, "Plastering 2nd floor 40% aayi")
    assert [e.event_type for e in kept] == [CanonicalEventType.ACTIVITY_CONTINUATION_REQUESTED]


def test_site_update_with_spurious_stock_query_keeps_only_the_update():
    events = [
        _event(CanonicalEventType.ACTIVITY_CONTINUATION_REQUESTED),
        _event(CanonicalEventType.INVENTORY_QUERY_ASKED),
    ]
    assert len(drop_unasked_queries(events, "plastering finished 2nd floor")) == 1


def test_a_real_question_keeps_its_query_segment():
    events = [
        _event(CanonicalEventType.LABOUR_ATTENDANCE_REQUESTED),
        _event(CanonicalEventType.INVENTORY_QUERY_ASKED),
    ]
    assert drop_unasked_queries(events, "6 mason vannu. ethra cement stock?") == events


@pytest.mark.parametrize(
    "text", ["how many bags left", "Cement ethra und", "send dpr", "balance entha", "stock?"]
)
def test_question_signals(text):
    assert has_question_signal(text)


@pytest.mark.parametrize("text", ["Plastering 2nd floor 40% aayi", "", None, "mason 5 vannu"])
def test_no_question_signal(text):
    assert not has_question_signal(text)


def test_the_first_segment_and_non_query_segments_are_never_dropped():
    events = [
        _event(CanonicalEventType.LABOUR_QUERY_ASKED),
        _event(CanonicalEventType.ACTIVITY_CONTINUATION_REQUESTED),
    ]
    assert drop_unasked_queries(events, "plain text") == events


def test_save_first_folds_the_plan_reply_into_the_saved_reply():
    block = _block_after(_dependencies_source(), "async def _deliver_handled(", "def _succeeded(")
    assert "fold_plan_reply" in block
    assert "reply_text = f\"{reply_text}" in block
