"""PRC-18 (decision D3): how an expense was paid, from the account it was paid from -- the one rule every total that
splits petty cash from direct spending reads.

- ``petty_cash``: paid from a site's cash box or a person's advance (``cash``, ``employee_advance`` accounts).
- ``direct``: paid from a bank or any other company account.
- ``own_pocket``: someone paid it themselves and is owed it back (``payment_status = 'reimbursable'``).
- ``unpaid``: no payment recorded yet.

An expense paid from both kinds counts by the larger part (a rare split payment stays one row in every total).
"""

from __future__ import annotations

from decimal import Decimal

PETTY_CASH_ACCOUNTS = frozenset({"cash", "employee_advance"})

PETTY_CASH = "petty_cash"
DIRECT = "direct"
OWN_POCKET = "own_pocket"
UNPAID = "unpaid"


def paid_via(payment_status: str | None, paid_by_account_type: dict[str, Decimal] | None) -> str:
    """``paid_by_account_type``: confirmed payment amounts per account type, e.g. ``{"cash": Decimal("500")}``."""
    if paid_by_account_type:
        petty = sum((v for k, v in paid_by_account_type.items() if k in PETTY_CASH_ACCOUNTS), Decimal(0))
        other = sum((v for k, v in paid_by_account_type.items() if k not in PETTY_CASH_ACCOUNTS), Decimal(0))
        if petty or other:
            return PETTY_CASH if petty >= other else DIRECT
    if (payment_status or "").lower() == "reimbursable":
        return OWN_POCKET
    return UNPAID
