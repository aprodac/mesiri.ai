"""Superadmin trial controls: extend, convert to paid, suspend, reactivate (SS-10).

Both admin routers call `apply_trial_action`, so a company's plan changes the
same way whichever serves the request. Each action runs in the caller's
transaction: lock the company row, check the action fits its status, update
it, and record it in the audit log (BE-05) -- the change is saved if and only
if its audit entry is.

The rules are pure (`plan_change`), keyed on the effective status
(domains/organizations/lifecycle), so a trial past its end counts as expired
even while its stored status still says `trial`:

    extend      trial or expired   end = later of (old end, now) + N days;
                                   back to `trial`
    convert     trial or expired   `active`, converted_at = now; trial dates
                                   kept as history
    suspend     anything but       `suspended`; WhatsApp refuses the company
                suspended          from its next message
    reactivate  suspended          `active` if it was converted or never on a
                                   trial, else back to `trial` (and expired
                                   at once if its end has passed)
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa

from mesiri.application.audit.record import record_admin_action
from mesiri.domains.audit import actions as audit
from mesiri.domains.organizations import lifecycle

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection

    from mesiri.domains.audit.actions import AuditActor

EXTEND = "extend"
CONVERT = "convert"
SUSPEND = "suspend"
REACTIVATE = "reactivate"
ACTIONS = (EXTEND, CONVERT, SUSPEND, REACTIVATE)

EXTEND_DAYS_RANGE = (1, 90)
_REASON_MAX = 300

_AUDIT_ACTION = {
    EXTEND: audit.COMPANY_TRIAL_EXTENDED,
    CONVERT: audit.COMPANY_CONVERTED,
    SUSPEND: audit.COMPANY_SUSPENDED,
    REACTIVATE: audit.COMPANY_REACTIVATED,
}


class TrialControlError(ValueError):
    """An action that can't be done; the message says why. `status_code` is
    what a route answers: 404 no such company, 409 doesn't fit the company's
    status, 400 a bad request."""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class PlanState:
    status: str
    trial_started_at: dt.datetime | None
    trial_ends_at: dt.datetime | None
    converted_at: dt.datetime | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "trial_started_at": _iso(self.trial_started_at),
            "trial_ends_at": _iso(self.trial_ends_at),
            "converted_at": _iso(self.converted_at),
        }


def _iso(value: dt.datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _refuse(message: str) -> TrialControlError:
    return TrialControlError(message, status_code=409)


def plan_change(
    action: str, current: PlanState, now: dt.datetime, *, days: int | None = None
) -> tuple[PlanState, str]:
    """The company's plan after `action`, and a one-line summary for the
    audit log. Pure; raises TrialControlError."""
    effective = lifecycle.effective_status(current.status, current.trial_ends_at, now)

    if action == EXTEND:
        low, high = EXTEND_DAYS_RANGE
        if isinstance(days, bool) or not isinstance(days, int) or not low <= days <= high:
            raise TrialControlError(f"Extend by a whole number of days from {low} to {high}")
        if effective not in (lifecycle.TRIAL, lifecycle.EXPIRED):
            raise _refuse(f"Only a trial can be extended; this company is {effective}")
        base = max(current.trial_ends_at or now, now)
        after = PlanState(
            status=lifecycle.TRIAL,
            trial_started_at=current.trial_started_at or now,
            trial_ends_at=base + dt.timedelta(days=days),
            converted_at=current.converted_at,
        )
        return after, f"Trial extended by {days} day{'s' if days != 1 else ''}"

    if action == CONVERT:
        if effective == lifecycle.ACTIVE:
            raise _refuse("This company is already active")
        if effective == lifecycle.SUSPENDED:
            raise _refuse("This company is suspended; reactivate it first")
        after = PlanState(
            status=lifecycle.ACTIVE,
            trial_started_at=current.trial_started_at,
            trial_ends_at=current.trial_ends_at,
            converted_at=now,
        )
        return after, "Converted to paid"

    if action == SUSPEND:
        if effective == lifecycle.SUSPENDED:
            raise _refuse("This company is already suspended")
        after = PlanState(
            status=lifecycle.SUSPENDED,
            trial_started_at=current.trial_started_at,
            trial_ends_at=current.trial_ends_at,
            converted_at=current.converted_at,
        )
        return after, "Suspended"

    if action == REACTIVATE:
        if effective != lifecycle.SUSPENDED:
            raise _refuse(f"Only a suspended company can be reactivated; this one is {effective}")
        was_trial = current.converted_at is None and current.trial_ends_at is not None
        after = PlanState(
            status=lifecycle.TRIAL if was_trial else lifecycle.ACTIVE,
            trial_started_at=current.trial_started_at,
            trial_ends_at=current.trial_ends_at,
            converted_at=current.converted_at,
        )
        return after, f"Reactivated as {after.status}"

    raise TrialControlError(f"action must be one of {list(ACTIONS)}")


_SELECT_FOR_UPDATE = sa.text(
    "SELECT name, status, trial_started_at, trial_ends_at, converted_at "
    "FROM organizations WHERE id = :id FOR UPDATE"
)
_UPDATE = sa.text(
    "UPDATE organizations SET status = :status, trial_started_at = :trial_started_at, "
    "trial_ends_at = :trial_ends_at, converted_at = :converted_at, updated_at = :now "
    "WHERE id = :id"
)


async def apply_trial_action(
    conn: AsyncConnection,
    organization_id: uuid.UUID,
    action: str,
    *,
    actor: AuditActor,
    days: int | None = None,
    reason: str | None = None,
    now: dt.datetime | None = None,
) -> PlanState:
    """Change the company's plan and record it, in the caller's transaction.
    Returns the plan after the change. Raises TrialControlError."""
    if action not in ACTIONS:
        raise TrialControlError(f"action must be one of {list(ACTIONS)}")
    now = now or dt.datetime.now(dt.UTC)
    reason = " ".join((reason or "").split())[:_REASON_MAX] or None

    row = (await conn.execute(_SELECT_FOR_UPDATE, {"id": organization_id})).mappings().first()
    if row is None:
        raise TrialControlError("Company not found", status_code=404)
    before = PlanState(
        status=lifecycle.normalize(row["status"]),
        trial_started_at=row["trial_started_at"],
        trial_ends_at=row["trial_ends_at"],
        converted_at=row["converted_at"],
    )
    after, summary = plan_change(action, before, now, days=days)

    await conn.execute(
        _UPDATE,
        {
            "id": organization_id,
            "status": after.status,
            "trial_started_at": after.trial_started_at,
            "trial_ends_at": after.trial_ends_at,
            "converted_at": after.converted_at,
            "now": now,
        },
    )
    details: dict[str, Any] = {"before": before.as_dict(), "after": after.as_dict()}
    if days is not None and action == EXTEND:
        details["days"] = days
    if reason:
        details["reason"] = reason
    await record_admin_action(
        conn,
        actor=actor,
        action=_AUDIT_ACTION[action],
        organization_id=organization_id,
        target_type="organization",
        target_id=organization_id,
        summary=f"{row['name']}: {summary}" + (f" ({reason})" if reason else ""),
        details=details,
        now=now,
    )
    return after
