"""Company lifecycle: trial, active, expired, suspended (SS-02).

Pure rules, no I/O. The single answer to "may this company use Mesiri right
now?", so the WhatsApp identity gate, the automatic DPR, the scheduled
scripts and the context projection can't each decide differently (BE-07 was
two of them disagreeing about "Active" vs "active").

    trial      a free trial; operational until `trial_ends_at`
    active     a paying (or manually activated) customer
    expired    a trial that ended; not operational, data kept for a while
    suspended  switched off by Mesiri; not operational

A trial whose `trial_ends_at` has passed is treated as `expired` even while
its stored status still says `trial`. Nothing has to run at midnight to
flip it, so expiry can never be late or skipped.
"""

from __future__ import annotations

import datetime as dt

ACTIVE = "active"
TRIAL = "trial"
EXPIRED = "expired"
SUSPENDED = "suspended"

STATUSES: tuple[str, ...] = (ACTIVE, TRIAL, EXPIRED, SUSPENDED)
OPERATIONAL_STATUSES: frozenset[str] = frozenset({ACTIVE, TRIAL})

# How a company was created, for the trials funnel (SS-11).
SIGNUP_SOURCES: tuple[str, ...] = ("superadmin", "whatsapp", "web", "api")


def normalize(status: object) -> str:
    """Stored statuses are lowercase (migration 0463), but rows written
    earlier or by an older build may differ in case or whitespace."""
    return str(status or "").strip().lower()


def effective_status(status: object, trial_ends_at: dt.datetime | None, now: dt.datetime) -> str:
    """The status that applies at `now`. A trial past its end is expired;
    a trial with no end date (set by hand) stays a trial. An unknown value
    is treated as suspended: fail closed, never grant access by accident."""
    value = normalize(status)
    if value == TRIAL and trial_ends_at is not None and trial_ends_at <= now:
        return EXPIRED
    if value not in STATUSES:
        return SUSPENDED
    return value


def is_operational(status: object, trial_ends_at: dt.datetime | None, now: dt.datetime) -> bool:
    """May the company use Mesiri right now (send updates, get DPRs)?"""
    return effective_status(status, trial_ends_at, now) in OPERATIONAL_STATUSES


def operational_sql(alias: str = "o") -> str:
    """The same rule as `is_operational`, as a SQL condition on the
    `organizations` table (aliased `alias`; pass "" for no alias)."""
    p = f"{alias}." if alias else ""
    return (
        f"(lower({p}status) = '{ACTIVE}'"
        f" OR (lower({p}status) = '{TRIAL}'"
        f" AND ({p}trial_ends_at IS NULL OR {p}trial_ends_at > now())))"
    )


def trial_window(start: dt.datetime, trial_days: int) -> tuple[dt.datetime, dt.datetime]:
    """Start and end of a trial of `trial_days` days beginning at `start`."""
    if trial_days < 1:
        raise ValueError("trial_days must be at least 1")
    return start, start + dt.timedelta(days=trial_days)


def trial_days_left(trial_ends_at: dt.datetime | None, now: dt.datetime) -> int | None:
    """Whole days left in the trial (0 once it has ended), or None when the
    trial has no end date."""
    if trial_ends_at is None:
        return None
    remaining = trial_ends_at - now
    if remaining.total_seconds() <= 0:
        return 0
    return remaining.days + (1 if remaining.seconds or remaining.microseconds else 0)
