"""SEC-01: one rule for who may read expenses, used by the dashboard API and
the WhatsApp assistant."""

from __future__ import annotations

import pytest

from mesiri.authorization.roles import EXPENSE_VIEW_ROLES, may_view_expenses


@pytest.mark.parametrize("role", ["ADMIN", "admin", "OWNER", "FINANCE", "PROJECT_MANAGER", " project_manager "])
def test_owner_admin_finance_and_project_managers_may_read_expenses(role):
    assert may_view_expenses(role)


@pytest.mark.parametrize("role", ["SITE_ENGINEER", "SUPERVISOR", "USER", "", None])
def test_everyone_else_may_not(role):
    assert not may_view_expenses(role)


def test_the_dashboard_sidebar_lists_the_same_roles():
    """apps/dashboard's sidebar mirrors the rule to hide the Expenses link;
    the API is what enforces it, but the two must not drift."""
    from pathlib import Path

    sidebar = (
        Path(__file__).resolve().parents[3] / "apps" / "dashboard" / "src" / "components" / "app-sidebar.tsx"
    ).read_text(encoding="utf-8")
    line = next(line for line in sidebar.splitlines() if line.startswith("const EXPENSE_VIEW_ROLES"))
    assert {role.strip(" '") for role in line.split("[", 1)[1].split("]", 1)[0].split(",")} == set(EXPENSE_VIEW_ROLES)
