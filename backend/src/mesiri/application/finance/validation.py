"""Pure structural validation for ManageMoneyAccountCommand — no DB, no I/O.

Duplicate-name (create) / account-not-found (rename, deactivate) checks are
deliberately not here — those need a DB round trip and belong to
resolution.py's PostgresAccountLookupResolver, mirroring
application/expenses/validation.py's split between structural and
DB-backed checks.

Role enforcement lives here too, mirroring transfer_validation.py's
docstring reasoning exactly: this is defense-in-depth, not the only gate --
runtime/inbound_journey.py already refuses to even start the workflow for a
disallowed role (this "should not even be an option" for the WhatsApp UX,
per the explicit ask that reopened this), and
runtime/account_admin_journey.py's deterministic fast path does the same.
This check exists in case either of those is ever bypassed or a future
caller reaches this Command directly.
"""

from __future__ import annotations

from mesiri.authorization.roles import MONEY_MANAGE_ROLES

from .commands import ManageMoneyAccountCommand

_VALID_ACTIONS = {"create", "rename", "deactivate"}
_VALID_ACCOUNT_TYPES = {"cash", "bank", "employee_advance", "other"}

# Deliberately narrower than transfer_validation.py's _TRANSFER_ROLES (no
# PROJECT_MANAGER) -- matches runtime/account_admin_journey.py's
# _ACCOUNT_ADMIN_ROLES exactly. Managing the chart of accounts itself is a
# step further than moving money through it.
# 7 Nov 2026 (SEC-03): read from authorization/roles.py, the same rule as the dashboard's account routes.
_ACCOUNT_ADMIN_ROLES = MONEY_MANAGE_ROLES


def validate(cmd: ManageMoneyAccountCommand) -> list[str]:
    reasons: list[str] = []
    if str(cmd.created_by_role or "").strip().upper() not in _ACCOUNT_ADMIN_ROLES:
        reasons.append("only an admin or finance user can manage accounts")
    if cmd.action not in _VALID_ACTIONS:
        reasons.append(f"unknown action '{cmd.action}'")
        return reasons

    if cmd.action == "create":
        if not (cmd.name or "").strip():
            reasons.append("account name is required")
        if cmd.account_type not in _VALID_ACCOUNT_TYPES:
            reasons.append(f"unknown account type '{cmd.account_type}'")
    elif cmd.action == "rename":
        if not (cmd.target_name or "").strip():
            reasons.append("the account to rename is required")
        if not (cmd.new_name or "").strip():
            reasons.append("the new name is required")
    else:  # deactivate
        if not (cmd.target_name or "").strip():
            reasons.append("the account to deactivate is required")

    return reasons
