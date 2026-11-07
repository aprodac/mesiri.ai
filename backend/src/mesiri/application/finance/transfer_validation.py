"""Pure structural validation for TransferMoneyCommand — no DB, no I/O.

Account existence/active-status is a DB-backed check and belongs to
transfer_resolution.py's PostgresTransferAccountResolver, mirroring the
structural-vs-DB-backed split used everywhere else in this codebase (see
application/expenses/validation.py's docstring).

Role enforcement lives here rather than earlier in the WhatsApp pipeline: a
disallowed role can still complete slot-fill, but the transfer is rejected
before any money moves, consistent with every other business rule in this
codebase being enforced in the Domain/Application layer, not the
interaction layer.
"""

from __future__ import annotations

from mesiri.authorization.roles import MONEY_TRANSFER_ROLES

from .transfer_commands import TransferMoneyCommand

# PROJECT_MANAGER may transfer (within their project scope, enforced by the
# existing project/site authorization already applied upstream); ADMIN and
# FINANCE always may. SITE_ENGINEER never may -- matches the permission
# table in docs/execution/FINANCE_MODULE_PLAN.md.
# 7 Nov 2026 (SEC-03): read from authorization/roles.py; the owner was missing from this copy.
_TRANSFER_ROLES = MONEY_TRANSFER_ROLES


def validate(cmd: TransferMoneyCommand) -> list[str]:
    reasons: list[str] = []
    if cmd.amount <= 0:
        reasons.append("amount must be greater than zero")
    if not cmd.from_account_id or not cmd.to_account_id:
        reasons.append("both accounts are required")
    elif cmd.from_account_id == cmd.to_account_id:
        reasons.append("cannot transfer to the same account")
    if str(cmd.created_by_role or "").strip().upper() not in _TRANSFER_ROLES:
        reasons.append("only an admin, finance user, or project manager can transfer money")
    return reasons
