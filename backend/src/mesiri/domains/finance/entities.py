"""Domain entities for money accounts and money transactions.

Plain dataclasses — no SQLAlchemy. Mesiri Daily is not an accounting system:
there is no chart of accounts, no journal entries, no debit/credit
terminology. An account's balance is always derived (opening_balance + sum
of its money_transactions), never stored as a mutable column.
"""

from __future__ import annotations

import datetime
import enum
import uuid
from dataclasses import dataclass
from decimal import Decimal


class AccountType(str, enum.Enum):
    CASH = "cash"
    BANK = "bank"
    EMPLOYEE_ADVANCE = "employee_advance"
    OTHER = "other"


class AccountStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class TransactionType(str, enum.Enum):
    FUND_RECEIVED = "fund_received"
    TRANSFER = "transfer"
    EXPENSE_PAYMENT = "expense_payment"
    ADJUSTMENT = "adjustment"
    REVERSAL = "reversal"


@dataclass(frozen=True, slots=True)
class MoneyAccount:
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    account_type: AccountType
    currency: str
    opening_balance: Decimal
    opening_balance_date: datetime.date
    status: AccountStatus
    code: str | None = None
    project_id: uuid.UUID | None = None
    site_id: uuid.UUID | None = None
    owner_user_id: uuid.UUID | None = None
    #: WEB-66: a bank account's bank, IFSC and the account number's last 4 digits (never the full number).
    bank_name: str | None = None
    ifsc_code: str | None = None
    account_last4: str | None = None


@dataclass(frozen=True, slots=True)
class MoneyTransaction:
    id: uuid.UUID
    organization_id: uuid.UUID
    transaction_type: TransactionType
    amount: Decimal
    occurred_date: datetime.date
    created_by: uuid.UUID
    from_account_id: uuid.UUID | None = None
    to_account_id: uuid.UUID | None = None
    source_type: str | None = None
    source_id: uuid.UUID | None = None
    occurred_time: datetime.time | None = None
    description: str | None = None
    correlation_id: str | None = None
