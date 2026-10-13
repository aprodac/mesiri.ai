"""ReverseTransactionCommand validation — unit tests (pure, no DB, no I/O)."""

from __future__ import annotations

from mesiri.application.finance.reverse_commands import ReverseTransactionCommand
from mesiri.application.finance.reverse_validation import validate

ORG = "11111111-1111-4111-8111-111111111111"
USR = "22222222-2222-4222-8222-222222222222"
EXPENSE_ID = "55555555-5555-4555-8555-555555555555"
TRANSACTION_ID = "66666666-6666-4666-8666-666666666666"
ACTIVITY_ID = "77777777-7777-4777-8777-777777777777"
ATTENDANCE_REPORT_ID = "88888888-8888-4888-8888-888888888888"


def _command(**overrides) -> ReverseTransactionCommand:
    base = dict(
        idempotency_key="idem_1",
        organization_id=ORG,
        created_by=USR,
        created_by_role="ADMIN",
        target_kind="expense",
        expense_id=EXPENSE_ID,
    )
    base.update(overrides)
    return ReverseTransactionCommand(**base)


def test_valid_expense_reversal_has_no_reasons():
    assert validate(_command()) == []


def test_valid_transfer_reversal_has_no_reasons():
    reasons = validate(
        _command(target_kind="transfer", expense_id=None, money_transaction_id=TRANSACTION_ID)
    )
    assert reasons == []


def test_unknown_target_kind_is_rejected():
    reasons = validate(_command(target_kind="petty_cash"))
    assert "unknown target_kind 'petty_cash'" in reasons


def test_expense_target_without_expense_id_is_rejected():
    reasons = validate(_command(expense_id=None))
    assert "no expense to reverse" in reasons


def test_transfer_target_without_transaction_id_is_rejected():
    reasons = validate(_command(target_kind="transfer", expense_id=None))
    assert "no transfer to reverse" in reasons


def test_finance_role_is_allowed():
    assert validate(_command(created_by_role="FINANCE")) == []


def test_project_manager_role_is_rejected():
    """Unlike transfer, reversal is ADMIN/FINANCE only -- a PROJECT_MANAGER
    who may transfer money may not undo a confirmed record."""
    reasons = validate(_command(created_by_role="PROJECT_MANAGER"))
    assert "only an admin or finance user can reverse a transaction" in reasons


def test_site_engineer_role_is_rejected():
    reasons = validate(_command(created_by_role="SITE_ENGINEER"))
    assert "only an admin or finance user can reverse a transaction" in reasons


def test_missing_role_is_rejected():
    reasons = validate(_command(created_by_role=None))
    assert "only an admin or finance user can reverse a transaction" in reasons


def test_role_check_is_case_insensitive():
    assert validate(_command(created_by_role="admin")) == []


def test_valid_activity_undo_has_no_reasons():
    reasons = validate(
        _command(
            target_kind="activity",
            expense_id=None,
            activity_id=ACTIVITY_ID,
            created_by_role="SITE_ENGINEER",
        )
    )
    assert reasons == []


def test_activity_target_without_activity_id_is_rejected():
    reasons = validate(_command(target_kind="activity", expense_id=None))
    assert "no activity to undo" in reasons


def test_activity_undo_is_not_gated_by_finance_role():
    """ADR-D15: unlike expense/transfer, undoing an Activity is authorized
    by same-session scoping (only the reporter's own just-created activity
    is ever resolved -- see runtime/reversal_query.py), not by role. A
    site engineer -- who could never reverse a transfer -- can undo their
    own activity."""
    reasons = validate(
        _command(
            target_kind="activity",
            expense_id=None,
            activity_id=ACTIVITY_ID,
            created_by_role="SITE_ENGINEER",
        )
    )
    assert "only an admin or finance user can reverse a transaction" not in reasons


def test_activity_undo_with_no_role_at_all_still_has_no_reasons():
    reasons = validate(
        _command(target_kind="activity", expense_id=None, activity_id=ACTIVITY_ID, created_by_role=None)
    )
    assert reasons == []


def test_valid_attendance_withdrawal_has_no_reasons():
    assert (
        validate(
            _command(
                target_kind="attendance",
                expense_id=None,
                attendance_report_id=ATTENDANCE_REPORT_ID,
            )
        )
        == []
    )


def test_attendance_target_without_report_id_is_rejected():
    reasons = validate(_command(target_kind="attendance", expense_id=None))
    assert "no attendance report to withdraw" in reasons


def test_attendance_withdrawal_is_not_gated_by_finance_role():
    """Attendance is operational, like an activity: the gate is ownership
    (reverse_resolution.py refuses a report you did not file), not role. A
    site engineer must be able to withdraw their own mis-filed day without
    finding an admin -- otherwise the wrong-site report just stays."""
    reasons = validate(
        _command(
            target_kind="attendance",
            expense_id=None,
            attendance_report_id=ATTENDANCE_REPORT_ID,
            created_by_role="SITE_ENGINEER",
        )
    )
    assert reasons == []
