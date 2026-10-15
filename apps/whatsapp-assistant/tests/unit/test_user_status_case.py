"""User status casing — reactivating someone must not lock them out.

Real incident: an admin deactivated a user in the control panel and then
reactivated them. Afterwards the assistant no longer recognized their
number and replied as though they were a stranger.

Cause: the control panel wrote `body.status.capitalize()` -> "Active", but
users are stored lowercase ("active"); only organizations use the
capitalized form. The assistant's lookup was `WHERE u.status = 'active'`, a
case-sensitive comparison, so the row was never found. Deactivation
"worked" by accident ("Inactive" isn't "active" either) -- only
reactivation was broken.

Fixed on three sides, each covered here: reads are case-insensitive (so
already-broken rows recover), writes are normalized lowercase (so it stops
recurring), and migration 0368 repairs existing rows.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from context.main_table_repositories import _status_is

_APP_SRC = pathlib.Path(__file__).resolve().parents[2] / "src"


# ---------------------------------------------------------------------------
# The comparison helper
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["active", "Active", "ACTIVE", " Active ", "aCtIvE"])
def test_any_casing_of_active_counts_as_active(value):
    """The load-bearing assertion: "Active" must not read as inactive.
    That single mismatch is what locked a real user out."""
    assert _status_is(value, "active") is True


@pytest.mark.parametrize("value", ["inactive", "Inactive", "suspended", "", None])
def test_non_active_values_are_not_active(value):
    assert _status_is(value, "active") is False


def test_organizations_capitalized_convention_still_works():
    """Organizations are stored "Active"; the shared helper must accept that
    too, or fixing users would suspend every tenant."""
    assert _status_is("Active", "active") is True
    assert _status_is("Suspended", "active") is False


def test_project_on_track_status_unaffected():
    assert _status_is("on_track", "on_track") is True
    assert _status_is("at_risk", "on_track") is False


# ---------------------------------------------------------------------------
# The lookup and the writers
# ---------------------------------------------------------------------------


def test_actor_lookup_is_case_insensitive():
    """The assistant resolves an inbound number against users.status. A
    case-sensitive match here is exactly what produced the lockout."""
    sql = (_APP_SRC / "backend" / "postgres" / "actor.py").read_text(encoding="utf-8")
    assert "lower(u.status) = 'active'" in sql, (
        "the actor lookup must compare status case-insensitively"
    )
    assert "AND u.status = 'active'" not in sql, "the case-sensitive comparison must be gone"


def test_no_writer_capitalizes_user_status():
    """`.capitalize()` on a user status is the original bug. Every status
    is stored lowercase (migration 0463)."""
    offenders = []
    for path in _APP_SRC.rglob("*.py"):
        if "__pycache__" in path.as_posix():
            continue
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"status.{0,20}\.capitalize\(\)", text):
            offenders.append(f"{path.name}: {match.group(0)}")
    assert not offenders, f"user status must be written lowercase, found: {offenders}"


def test_migration_0368_lowercases_only_users():
    """Rewriting organizations.status would break the capitalized
    convention it legitimately uses."""
    migration = (
        _APP_SRC.parents[2]  # repo root: src -> whatsapp-assistant -> apps -> root
        / "backend"
        / "migrations"
        / "versions"
        / "0368_normalize_user_status_case.py"
    ).read_text(encoding="utf-8")
    assert "UPDATE users SET status = lower(status)" in migration
    assert "UPDATE organizations" not in migration


def test_no_writer_stores_capitalized_org_status():
    """BE-07: organizations were written "Active" while every reader of the
    automatic DPR compared against 'active', so it matched no company.
    Statuses are lowercase everywhere now; nothing may write "Active" again."""
    offenders = []
    for path in _APP_SRC.rglob("*.py"):
        if "__pycache__" in path.as_posix():
            continue
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r'status\s*=\s*"(Active|Suspended)"', text):
            offenders.append(f"{path.name}: {match.group(0)}")
    assert not offenders, f"statuses must be written lowercase, found: {offenders}"
