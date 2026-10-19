"""Transfer workflow nodes — unit tests (pure functions, no LangGraph needed)."""

from __future__ import annotations

from mesiri_contracts.assistant.draft_action import DraftActionType
from mesiri_contracts.assistant.planner_decision import WorkflowKey
from workflows.transfer.nodes import (
    build_draft,
    request_confirmation,
    resolve_from_account,
    resolve_to_account,
)

ORG = "11111111-1111-4111-8111-111111111111"
USR = "22222222-2222-4222-8222-222222222222"
ACC_A = "aaaaaaaa-1111-4111-8111-111111111111"
ACC_B = "bbbbbbbb-2222-4222-8222-222222222222"


def _base_state(fields: dict, awaiting_slot: str | None = None) -> dict:
    state = {
        "workflow_instance_id": "wf_1",
        "workflow_key": WorkflowKey.TRANSFER.value,
        "correlation_id": "cor_1",
        "organization_id": ORG,
        "user_id": USR,
        "project_id": None,
        "site_id": None,
        "collected_fields": fields,
    }
    if awaiting_slot is not None:
        state["awaiting_slot"] = awaiting_slot
    return state


_CANDIDATES = [{"id": ACC_A, "name": "Company Bank"}, {"id": ACC_B, "name": "Site Cash"}]


def test_resolve_from_account_already_resolved_is_a_no_op():
    state = _base_state({"amount": 500, "from_account_id": ACC_A})
    assert resolve_from_account(state) == {}


def test_resolve_from_account_matches_extracted_name():
    state = _base_state({"amount": 500, "from_account_name": "company bank", "account_candidates": _CANDIDATES})
    update = resolve_from_account(state)
    assert update["collected_fields"]["from_account_id"] == ACC_A
    assert "awaiting_slot" not in update


def test_resolve_from_account_unmatched_name_asks():
    state = _base_state({"amount": 500, "from_account_name": "nonexistent", "account_candidates": _CANDIDATES})
    update = resolve_from_account(state)
    assert update["awaiting_slot"] == "from_account_id"
    assert "Company Bank" in update["pending_prompt"]
    assert "Site Cash" in update["pending_prompt"]
    # Real WhatsApp interactive list, not just numbered text -- see
    # workflows/slots.py's slot_options.
    assert update["awaiting_slot_options"] == [
        {"value": ACC_A, "label": "Company Bank"},
        {"value": ACC_B, "label": "Site Cash"},
    ]


def test_resolve_from_account_no_name_asks_when_multiple_candidates():
    state = _base_state({"amount": 500, "account_candidates": _CANDIDATES})
    update = resolve_from_account(state)
    assert update["awaiting_slot"] == "from_account_id"


def test_resolve_from_account_autofills_on_single_candidate():
    state = _base_state({"amount": 500, "account_candidates": [_CANDIDATES[0]]})
    update = resolve_from_account(state)
    assert update["collected_fields"]["from_account_id"] == ACC_A
    assert "awaiting_slot" not in update


def test_resolve_from_account_answer_resolves_the_slot():
    state = _base_state(
        {"amount": 500, "account_candidates": _CANDIDATES, "_slot_answer_text": "1"},
        awaiting_slot="from_account_id",
    )
    update = resolve_from_account(state)
    assert update["collected_fields"]["from_account_id"] == ACC_A
    assert update["awaiting_slot"] is None
    assert "_slot_answer_text" not in update["collected_fields"]


def test_resolve_from_account_unmatched_answer_reasks():
    state = _base_state(
        {"amount": 500, "account_candidates": _CANDIDATES, "_slot_answer_text": "purple monkey dishwasher"},
        awaiting_slot="from_account_id",
    )
    update = resolve_from_account(state)
    assert update["awaiting_slot"] == "from_account_id"
    assert "couldn't tell which one" in update["pending_prompt"]


def test_resolve_to_account_excludes_the_already_resolved_from_account():
    state = _base_state(
        {"amount": 500, "from_account_id": ACC_A, "account_candidates": _CANDIDATES}
    )
    update = resolve_to_account(state)
    # Only one real candidate left (Site Cash) -> auto-fills.
    assert update["collected_fields"]["to_account_id"] == ACC_B


def test_resolve_to_account_ignores_an_answer_meant_for_the_from_slot():
    """A slot answer only applies to the node whose slot is currently awaited."""
    state = _base_state(
        {
            "amount": 500,
            "from_account_id": ACC_A,
            "account_candidates": _CANDIDATES,
            "_slot_answer_text": "1",
        },
        awaiting_slot="from_account_id",
    )
    update = resolve_to_account(state)
    # to_account_id auto-fills from the one remaining candidate regardless
    # of the stray answer text (which belongs to the from-slot, not this one).
    assert update["collected_fields"]["to_account_id"] == ACC_B


def test_build_draft_excludes_plumbing_fields():
    """account_candidates is pure plumbing and must not survive. The raw
    AI-extracted from_account_name/to_account_name hint text must not
    survive either -- but the key is reused (not dropped) to carry the
    real resolved account name instead, so channel/receipt/data.py's
    build_receipt_data can show it without any I/O of its own."""
    state = _base_state(
        {
            "amount": 500,
            "from_account_id": ACC_A,
            "to_account_id": ACC_B,
            "from_account_name": "company acc",  # raw AI hint, discarded
            "to_account_name": "site cash pls",  # raw AI hint, discarded
            "account_candidates": _CANDIDATES,
        }
    )
    draft = build_draft(state)["draft_action"]
    assert draft.action_type is DraftActionType.TRANSFER_MONEY
    assert "account_candidates" not in draft.fields
    assert draft.fields["from_account_id"] == ACC_A
    assert draft.fields["to_account_id"] == ACC_B
    # Overwritten with the real resolved names, not the raw hint text above.
    assert draft.fields["from_account_name"] == "Company Bank"
    assert draft.fields["to_account_name"] == "Site Cash"


def test_request_confirmation_shows_account_names_not_ids():
    state = _base_state(
        {
            "amount": 500,
            "from_account_id": ACC_A,
            "to_account_id": ACC_B,
            "account_candidates": _CANDIDATES,
        }
    )
    state.update(build_draft(state))
    prompt = request_confirmation(state)["pending_prompt"]
    assert "Company Bank" in prompt
    assert "Site Cash" in prompt
    assert ACC_A not in prompt
    assert "500" in prompt
    assert "YES" in prompt
