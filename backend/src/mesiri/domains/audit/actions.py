"""What a superadmin audit entry is (BE-05). Pure definitions, no I/O.

Every change a Mesiri operator makes to a company, its people or the
platform is recorded once: who did it, what they did, to which company,
when, and the before/after values. The store is
infrastructure/postgres/repositories/admin_audit.py; the one function that
writes an entry is application/audit/record.py.

Action names are a closed list, so a typo is refused at the call rather than
saved as a row nobody's filter ever finds.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

# Who acted.
ACTOR_PLATFORM_ADMIN = "platform_admin"
# The owner signing themselves up (WhatsApp or web self-serve).
ACTOR_SELF_SIGNUP = "self_signup"
# Code with no person behind it (API scripts, scheduled jobs).
ACTOR_SYSTEM = "system"
ACTOR_KINDS = (ACTOR_PLATFORM_ADMIN, ACTOR_SELF_SIGNUP, ACTOR_SYSTEM)

# Companies
COMPANY_CREATED = "company.created"
COMPANY_DELETED = "company.deleted"
COMPANY_FINANCE_SEEDED = "company.finance_seeded"
COMPANY_SETTING_CHANGED = "company.setting_changed"
# Name or primary contact changed in the control panel (SA-03).
COMPANY_UPDATED = "company.updated"
# Trial controls (SS-10); listed now so its routes only need the call.
COMPANY_TRIAL_EXTENDED = "company.trial_extended"
COMPANY_CONVERTED = "company.converted"
COMPANY_SUSPENDED = "company.suspended"
COMPANY_REACTIVATED = "company.reactivated"
COMPANY_STATUS_CHANGED = "company.status_changed"

# People in a company
COMPANY_USER_CREATED = "company_user.created"
COMPANY_USER_UPDATED = "company_user.updated"
COMPANY_USER_STATUS_CHANGED = "company_user.status_changed"
COMPANY_USER_ACCESS_CHANGED = "company_user.access_changed"
COMPANY_USER_DELETED = "company_user.deleted"

# Mesiri operators and platform-wide configuration
PLATFORM_ADMIN_CREATED = "platform_admin.created"
PLATFORM_ADMIN_UPDATED = "platform_admin.updated"
PLATFORM_SETTING_CHANGED = "platform_setting.changed"
AI_CONFIG_CHANGED = "ai_config.changed"

# Database page (SA-15): a SQL read, and a write that changed rows.
DATABASE_QUERY_READ = "database.query_read"
DATABASE_ROWS_CHANGED = "database.rows_changed"

ACTIONS = frozenset(
    {
        COMPANY_CREATED,
        COMPANY_DELETED,
        COMPANY_FINANCE_SEEDED,
        COMPANY_SETTING_CHANGED,
        COMPANY_UPDATED,
        COMPANY_TRIAL_EXTENDED,
        COMPANY_CONVERTED,
        COMPANY_SUSPENDED,
        COMPANY_REACTIVATED,
        COMPANY_STATUS_CHANGED,
        COMPANY_USER_CREATED,
        COMPANY_USER_UPDATED,
        COMPANY_USER_STATUS_CHANGED,
        COMPANY_USER_ACCESS_CHANGED,
        COMPANY_USER_DELETED,
        PLATFORM_ADMIN_CREATED,
        PLATFORM_ADMIN_UPDATED,
        PLATFORM_SETTING_CHANGED,
        AI_CONFIG_CHANGED,
        DATABASE_QUERY_READ,
        DATABASE_ROWS_CHANGED,
    }
)

# Never stored, at any depth: the entry says the field changed, not its value.
_SECRET_KEYS = frozenset(
    {"password", "new_password", "admin_password", "owner_password", "hashed_password", "api_key"}
)
REDACTED = "[changed]"

_LABEL_MAX = 200
_SUMMARY_MAX = 500


@dataclass(frozen=True, slots=True)
class AuditActor:
    kind: str
    user_id: uuid.UUID | None = None
    # A name or phone as it was at the time, so the entry still reads right
    # after the person is renamed or removed.
    label: str | None = None


SYSTEM = AuditActor(kind=ACTOR_SYSTEM)


def actor_from_admin(payload: dict[str, Any] | None) -> AuditActor:
    """The platform admin behind a request, from the JWT payload that
    `require_platform_admin` returns (`sub` = user id, `name`)."""
    payload = payload or {}
    user_id: uuid.UUID | None
    try:
        user_id = uuid.UUID(str(payload.get("sub")))
    except ValueError:
        user_id = None
    label = str(payload.get("name") or "").strip() or None
    return AuditActor(kind=ACTOR_PLATFORM_ADMIN, user_id=user_id, label=label)


def redact(value: Any) -> Any:
    """`value` with every secret field replaced by REDACTED, recursively."""
    if isinstance(value, dict):
        return {
            k: (REDACTED if str(k).lower() in _SECRET_KEYS and v is not None else redact(v))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    if isinstance(value, uuid.UUID):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def validate_entry(action: str, actor: AuditActor) -> None:
    """Raises ValueError for an unknown action or actor kind."""
    if action not in ACTIONS:
        raise ValueError(f"unknown audit action: {action}")
    if actor.kind not in ACTOR_KINDS:
        raise ValueError(f"unknown audit actor kind: {actor.kind}")


def clip_label(label: str | None) -> str | None:
    return label[:_LABEL_MAX] if label else None


def clip_summary(summary: str | None) -> str | None:
    return summary[:_SUMMARY_MAX] if summary else None
