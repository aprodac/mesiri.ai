"""Pure structural validation for ReverseTransactionCommand — no DB, no I/O.

Existence/already-reversed checks are DB-backed and belong to
reverse_resolution.py's PostgresReverseTargetResolver, mirroring the
structural-vs-DB-backed split used everywhere else in this codebase (see
application/expenses/validation.py's docstring).

Role enforcement lives here rather than earlier in the WhatsApp pipeline,
same reasoning as transfer_validation.py: a disallowed role can still reach
this point, but the reversal is rejected before anything is undone. The
ADMIN/FINANCE gate below is specifically a *money-movement* control
(docs/execution/FINANCE_MODULE_PLAN.md's permission table) and does not
apply to `target_kind == "activity"` -- ADR-D15 governs that case instead:
undo is authorized by the same-session scoping in runtime/
reversal_query.py's find_latest_activity (only the reporter's own
just-created Activity is ever resolved), not by role.
"""

from __future__ import annotations

from .reverse_commands import ReverseTransactionCommand

# Reversal is a stricter gate than transfer's ADMIN/FINANCE/PROJECT_MANAGER --
# undoing a confirmed record is ADMIN/FINANCE only, per
# docs/execution/FINANCE_MODULE_PLAN.md's permission table.
_REVERSAL_ROLES = frozenset({"ADMIN", "FINANCE"})
_FINANCIAL_TARGET_KINDS = frozenset({"expense", "transfer"})
# `activity` and `attendance` are operational, not financial: both are
# scoped to the person who filed the record (checked in reverse_resolution
# .py), which is the gate that matters for them -- a site engineer must be
# able to withdraw their own mis-filed report without an admin, and must
# never be able to touch anyone else's.
_VALID_TARGET_KINDS = frozenset({"expense", "transfer", "activity", "attendance"})


def validate(cmd: ReverseTransactionCommand) -> list[str]:
    reasons: list[str] = []
    if cmd.target_kind not in _VALID_TARGET_KINDS:
        reasons.append(f"unknown target_kind '{cmd.target_kind}'")
        return reasons
    if cmd.target_kind == "expense" and not cmd.expense_id:
        reasons.append("no expense to reverse")
    if cmd.target_kind == "transfer" and not cmd.money_transaction_id:
        reasons.append("no transfer to reverse")
    if cmd.target_kind == "activity" and not cmd.activity_id:
        reasons.append("no activity to undo")
    if cmd.target_kind == "attendance" and not cmd.attendance_report_id:
        reasons.append("no attendance report to withdraw")
    if (
        cmd.target_kind in _FINANCIAL_TARGET_KINDS
        and str(cmd.created_by_role or "").strip().upper() not in _REVERSAL_ROLES
    ):
        reasons.append("only an admin or finance user can reverse a transaction")
    return reasons
