"""Petty cash workflow nodes — unit tests (pure functions, no LangGraph needed)."""

from __future__ import annotations

from mesiri_contracts.assistant.draft_action import DraftActionType
from mesiri_contracts.assistant.planner_decision import WorkflowKey
from workflows.petty_cash.nodes import build_draft, request_confirmation, resolve_other_account

ORG = "11111111-1111-4111-8111-111111111111"
USR = "22222222-2222-4222-8222-222222222222"
ACC_A = "aaaaaaaa-1111-4111-8111-111111111111"
ACC_B = "bbbbbbbb-2222-4222-8222-222222222222"
RECIPIENT_ACC = "cccccccc-3333-4333-8333-333333333333"

_CANDIDATES = [{"id": ACC_A, "name": "Company Bank"}, {"id": ACC_B, "name": "Site Cash"}]


def _base_state(fields: dict, awaiting_slot: str | None = None) -> dict:
    state = {
        "workflow_instance_id": "wf_1",
        "workflow_key": WorkflowKey.PETTY_CASH.value,
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


def test_issue_prefills_to_account_from_recipient_and_asks_for_from_account():
    state = _base_state(
        {
            "amount": 20000,
            "direction": "issue",
            "recipient_name": "Alan",
            "recipient_account_id": RECIPIENT_ACC,
            "account_candidates": _CANDIDATES,
        }
    )
    update = resolve_other_account(state)
    assert update["collected_fields"]["to_account_id"] == RECIPIENT_ACC
    assert update["awaiting_slot"] == "from_account_id"
    # Real WhatsApp interactive list, not just numbered text -- see
    # workflows/slots.py's slot_options.
    assert update["awaiting_slot_options"] == [
        {"value": ACC_A, "label": "Company Bank"},
        {"value": ACC_B, "label": "Site Cash"},
    ]


def test_issue_autofills_from_account_on_single_candidate():
    state = _base_state(
        {
            "amount": 20000,
            "direction": "issue",
            "recipient_account_id": RECIPIENT_ACC,
            "account_candidates": [_CANDIDATES[0]],
        }
    )
    update = resolve_other_account(state)
    assert update["collected_fields"]["to_account_id"] == RECIPIENT_ACC
    assert update["collected_fields"]["from_account_id"] == ACC_A
    assert "awaiting_slot" not in update


def test_return_prefills_from_account_and_asks_for_to_account():
    state = _base_state(
        {
            "amount": 3000,
            "direction": "return",
            "recipient_account_id": RECIPIENT_ACC,
            "account_candidates": _CANDIDATES,
        }
    )
    update = resolve_other_account(state)
    assert update["collected_fields"]["from_account_id"] == RECIPIENT_ACC
    assert update["awaiting_slot"] == "to_account_id"


def test_unresolved_recipient_still_lets_the_other_slot_resolve():
    """No matching user for `recipient_name` -> recipient_account_id was
    never seeded -- the recipient leg stays None, but the other leg still
    resolves normally (the backend's transfer validation catches the
    missing leg, not this node)."""
    state = _base_state(
        {"amount": 20000, "direction": "issue", "account_candidates": [_CANDIDATES[0]]}
    )
    update = resolve_other_account(state)
    assert update["collected_fields"]["to_account_id"] is None
    assert update["collected_fields"]["from_account_id"] == ACC_A


def test_answer_resolves_the_awaited_slot():
    state = _base_state(
        {
            "amount": 20000,
            "direction": "issue",
            "recipient_account_id": RECIPIENT_ACC,
            "account_candidates": _CANDIDATES,
            "_slot_answer_text": "1",
        },
        awaiting_slot="from_account_id",
    )
    update = resolve_other_account(state)
    assert update["collected_fields"]["from_account_id"] == ACC_A
    assert update["awaiting_slot"] is None
    assert "_slot_answer_text" not in update["collected_fields"]


def test_unmatched_answer_reasks():
    state = _base_state(
        {
            "amount": 20000,
            "direction": "issue",
            "recipient_account_id": RECIPIENT_ACC,
            "account_candidates": _CANDIDATES,
            "_slot_answer_text": "purple monkey dishwasher",
        },
        awaiting_slot="from_account_id",
    )
    update = resolve_other_account(state)
    assert update["awaiting_slot"] == "from_account_id"
    assert "couldn't tell which one" in update["pending_prompt"]


def test_build_draft_emits_transfer_money_and_excludes_plumbing_fields():
    """account_candidates/recipient_name/recipient_account_id are pure
    plumbing. direction and recipient_account_name are deliberately kept
    (both already canonical, never an unresolved AI hint) so
    channel/receipt/data.py's build_receipt_data can tell a petty cash
    receipt apart from a plain transfer and show who it involved -- and
    other_account_name is added, the org-side account's real name, for the
    same reason transfer/nodes.py's build_draft now adds it."""
    state = _base_state(
        {
            "amount": 20000,
            "direction": "issue",
            "recipient_name": "Alan",
            "recipient_account_id": RECIPIENT_ACC,
            "recipient_account_name": "Alan — Petty Cash",
            "to_account_id": RECIPIENT_ACC,
            "from_account_id": ACC_A,
            "account_candidates": _CANDIDATES,
        }
    )
    draft = build_draft(state)["draft_action"]
    assert draft.action_type is DraftActionType.TRANSFER_MONEY
    assert "account_candidates" not in draft.fields
    assert "recipient_name" not in draft.fields
    assert "recipient_account_id" not in draft.fields
    assert draft.fields["from_account_id"] == ACC_A
    assert draft.fields["to_account_id"] == RECIPIENT_ACC
    assert draft.fields["direction"] == "issue"
    assert draft.fields["recipient_account_name"] == "Alan — Petty Cash"
    assert draft.fields["other_account_name"] == "Company Bank"


def test_request_confirmation_issue_phrasing():
    state = _base_state(
        {
            "amount": 20000,
            "direction": "issue",
            "recipient_name": "Alan",
            "recipient_account_id": RECIPIENT_ACC,
            "recipient_account_name": "Alan — Petty Cash",
            "to_account_id": RECIPIENT_ACC,
            "from_account_id": ACC_A,
            "account_candidates": _CANDIDATES,
        }
    )
    state.update(build_draft(state))
    prompt = request_confirmation(state)["pending_prompt"]
    assert "issuance" in prompt
    assert "Alan — Petty Cash" in prompt
    assert "Company Bank" in prompt
    assert "20000" in prompt


def test_request_confirmation_return_phrasing():
    state = _base_state(
        {
            "amount": 3000,
            "direction": "return",
            "recipient_name": "Alan",
            "recipient_account_id": RECIPIENT_ACC,
            "recipient_account_name": "Alan — Petty Cash",
            "from_account_id": RECIPIENT_ACC,
            "to_account_id": ACC_B,
            "account_candidates": _CANDIDATES,
        }
    )
    state.update(build_draft(state))
    prompt = request_confirmation(state)["pending_prompt"]
    assert "return" in prompt
    assert "Alan — Petty Cash" in prompt
    assert "Site Cash" in prompt
