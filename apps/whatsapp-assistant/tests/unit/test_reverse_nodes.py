"""Reverse workflow nodes — unit tests (pure functions, no LangGraph needed)."""

from __future__ import annotations

from mesiri_contracts.assistant.draft_action import DraftActionType
from mesiri_contracts.assistant.planner_decision import WorkflowKey
from workflows.reverse.nodes import build_draft, request_confirmation

ORG = "11111111-1111-4111-8111-111111111111"
USR = "22222222-2222-4222-8222-222222222222"
EXPENSE_ID = "55555555-5555-4555-8555-555555555555"
TRANSACTION_ID = "66666666-6666-4666-8666-666666666666"
ACTIVITY_ID = "77777777-7777-4777-8777-777777777777"


def _base_state(fields: dict) -> dict:
    return {
        "workflow_instance_id": "wf_1",
        "workflow_key": WorkflowKey.REVERSE.value,
        "correlation_id": "cor_1",
        "organization_id": ORG,
        "user_id": USR,
        "project_id": None,
        "site_id": None,
        "collected_fields": fields,
    }


def test_expense_target_builds_a_draft():
    state = _base_state(
        {
            "target_kind": "expense",
            "expense_id": EXPENSE_ID,
            "created_by_role": "ADMIN",
            "reversal_amount": "700.00",
            "reversal_description": "diesel refill",
            "reversal_occurred_date": "2026-07-25",
        }
    )
    update = build_draft(state)
    draft = update["draft_action"]
    assert draft.action_type is DraftActionType.REVERSE_TRANSACTION
    assert draft.fields["expense_id"] == EXPENSE_ID
    assert draft.fields["target_kind"] == "expense"
    assert draft.fields["created_by_role"] == "ADMIN"
    # Display-only, but kept (unlike other finance workflows' plumbing) --
    # these come from a real DB read (runtime/reversal_query.py), never an
    # unresolved AI hint, so channel/receipt/data.py's build_receipt_data
    # can show a real reversal receipt with them.
    assert draft.fields["reversal_amount"] == "700.00"
    assert draft.fields["reversal_description"] == "diesel refill"


def test_transfer_target_builds_a_draft():
    state = _base_state(
        {
            "target_kind": "transfer",
            "money_transaction_id": TRANSACTION_ID,
            "created_by_role": "FINANCE",
            "reversal_amount": "5000.00",
            "reversal_from_account_name": "Company Bank",
            "reversal_to_account_name": "Site Cash",
        }
    )
    update = build_draft(state)
    draft = update["draft_action"]
    assert draft.fields["money_transaction_id"] == TRANSACTION_ID
    assert draft.fields["target_kind"] == "transfer"
    assert draft.fields["reversal_from_account_name"] == "Company Bank"
    assert draft.fields["reversal_to_account_name"] == "Site Cash"


def test_no_expense_found_completes_without_a_draft():
    state = _base_state({"target_kind": "expense", "created_by_role": "ADMIN"})
    update = build_draft(state)
    assert "draft_action" not in update
    assert "no confirmed expenses" in update["pending_prompt"]


def test_no_transfer_found_completes_without_a_draft():
    state = _base_state({"target_kind": "transfer", "created_by_role": "ADMIN"})
    update = build_draft(state)
    assert "draft_action" not in update
    assert "no transfers" in update["pending_prompt"]


def test_request_confirmation_expense_phrasing():
    state = _base_state(
        {
            "target_kind": "expense",
            "expense_id": EXPENSE_ID,
            "created_by_role": "ADMIN",
            "reversal_amount": "700.00",
            "reversal_description": "diesel refill",
            "reversal_occurred_date": "2026-07-25",
        }
    )
    state.update(build_draft(state))
    prompt = request_confirmation(state)["pending_prompt"]
    assert "Reverse expense" in prompt
    assert "700.00" in prompt
    assert "diesel refill" in prompt
    assert "YES" in prompt


def test_request_confirmation_transfer_phrasing():
    state = _base_state(
        {
            "target_kind": "transfer",
            "money_transaction_id": TRANSACTION_ID,
            "created_by_role": "FINANCE",
            "reversal_amount": "5000.00",
            "reversal_from_account_name": "Company Bank",
            "reversal_to_account_name": "Site Cash",
        }
    )
    state.update(build_draft(state))
    prompt = request_confirmation(state)["pending_prompt"]
    assert "Reverse transfer" in prompt
    assert "Company Bank" in prompt
    assert "Site Cash" in prompt
    assert "5000.00" in prompt


def test_activity_target_builds_a_draft():
    """ADR-D15: undoing an Activity the reporter just created."""
    state = _base_state(
        {
            "target_kind": "activity",
            "activity_id": ACTIVITY_ID,
            "reversal_activity_summary": "plastering — 2nd floor",
            "reversal_occurred_date": "2026-07-28",
        }
    )
    update = build_draft(state)
    draft = update["draft_action"]
    assert draft.action_type is DraftActionType.REVERSE_TRANSACTION
    assert draft.fields["activity_id"] == ACTIVITY_ID
    assert draft.fields["target_kind"] == "activity"


def test_no_activity_found_completes_without_a_draft():
    """No same-session activity to undo (see runtime/reversal_query.py's
    find_latest_activity docstring) -- a friendly reply, not a dead end."""
    state = _base_state({"target_kind": "activity", "created_by_role": "SITE_ENGINEER"})
    update = build_draft(state)
    assert "draft_action" not in update
    assert "don't see anything you just logged" in update["pending_prompt"]


def test_request_confirmation_activity_phrasing():
    state = _base_state(
        {
            "target_kind": "activity",
            "activity_id": ACTIVITY_ID,
            "reversal_activity_summary": "plastering — 2nd floor",
            "reversal_occurred_date": "2026-07-28",
        }
    )
    state.update(build_draft(state))
    prompt = request_confirmation(state)["pending_prompt"]
    assert "Remove activity" in prompt
    assert "plastering — 2nd floor" in prompt
    assert "2026-07-28" in prompt
    assert "YES" in prompt


ATTENDANCE_REPORT_ID = "99999999-9999-4999-8999-999999999999"


def _attendance_state(**overrides):
    return _base_state(
        {
            "target_kind": "attendance",
            "attendance_report_id": ATTENDANCE_REPORT_ID,
            "created_by_role": "SITE_ENGINEER",
            "reversal_occurred_date": "2026-07-30",
            "reversal_attendance_headcount": 18,
            "reversal_amount": "12600.00",
            "reversal_attendance_site": "Block A",
            **overrides,
        }
    )


def test_attendance_target_builds_a_draft():
    state = _attendance_state()
    draft = build_draft(state)["draft_action"]
    assert draft.action_type is DraftActionType.REVERSE_TRANSACTION
    assert draft.fields["attendance_report_id"] == ATTENDANCE_REPORT_ID
    assert draft.fields["target_kind"] == "attendance"


def test_no_attendance_found_points_at_replace_instead():
    """The reply has to distinguish the two repairs: replace fixes a
    headcount on the right site, withdraw is for the wrong site entirely."""
    state = _base_state({"target_kind": "attendance", "created_by_role": "SITE_ENGINEER"})
    update = build_draft(state)
    assert "draft_action" not in update
    assert "don't see an attendance report you filed" in update["pending_prompt"]
    assert "Replace it" in update["pending_prompt"]


def test_request_confirmation_attendance_names_the_site_and_day():
    """The mistake this exists to fix is a report on the wrong site, so the
    site and date are what the user must be able to check before saying
    YES."""
    state = _attendance_state()
    state.update(build_draft(state))
    prompt = request_confirmation(state)["pending_prompt"]
    assert "Withdraw attendance report" in prompt
    assert "Block A" in prompt
    assert "2026-07-30" in prompt
    assert "18 workers" in prompt
    assert "12600.00" in prompt
    assert "stays on record" in prompt
    assert "YES" in prompt


def test_request_confirmation_attendance_singular_worker():
    state = _attendance_state(reversal_attendance_headcount=1)
    state.update(build_draft(state))
    assert "1 worker," in request_confirmation(state)["pending_prompt"]


def _petty_cash_state(**overrides):
    return _base_state(
        {
            "target_kind": "petty_cash",
            "money_transaction_id": TRANSACTION_ID,
            "created_by_role": "FINANCE",
            "reversal_amount": "20000.00",
            "reversal_from_account_name": "Company Account",
            "reversal_to_account_name": "Alan Usman — Petty Cash",
            "reversal_petty_cash_direction": "issue",
            "reversal_petty_cash_holder": "Alan Usman",
            **overrides,
        }
    )


def test_petty_cash_target_builds_a_draft():
    state = _petty_cash_state()
    draft = build_draft(state)["draft_action"]
    assert draft.action_type is DraftActionType.REVERSE_TRANSACTION
    # Same row, same execution path as a transfer -- only the labelling
    # differs (see find_latest_reversible_petty_cash).
    assert draft.fields["money_transaction_id"] == TRANSACTION_ID
    assert draft.fields["target_kind"] == "petty_cash"


def test_no_petty_cash_found_completes_without_a_draft():
    state = _base_state({"target_kind": "petty_cash", "created_by_role": "FINANCE"})
    update = build_draft(state)
    assert "draft_action" not in update
    assert "no petty cash issues or returns to reverse" in update["pending_prompt"]


def test_request_confirmation_petty_cash_names_the_person_not_the_accounts():
    """A confirmation the user cannot recognise is not a confirmation (P2):
    nobody thinks of "₹20,000 to Alan" as an account pair."""
    state = _petty_cash_state()
    state.update(build_draft(state))
    prompt = request_confirmation(state)["pending_prompt"]
    assert "Reverse petty cash" in prompt
    assert "issued to Alan Usman" in prompt
    assert "20000.00" in prompt
    assert "Alan Usman — Petty Cash" not in prompt
    assert "YES" in prompt


def test_request_confirmation_petty_cash_return_phrasing():
    state = _petty_cash_state(reversal_petty_cash_direction="return")
    state.update(build_draft(state))
    prompt = request_confirmation(state)["pending_prompt"]
    assert "returned by Alan Usman" in prompt
