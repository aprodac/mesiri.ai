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


def test_the_dashboard_lists_the_same_roles():
    """The dashboard hides money pages (Expenses, Rates, Payables...) from the roles the API refuses; its list is
    MONEY_ROLES in lib/module-map.ts (it moved there from the sidebar with the module map, WEB-72). The API is what
    enforces it, but the two must not drift."""
    from pathlib import Path

    module_map = (
        Path(__file__).resolve().parents[3] / "apps" / "dashboard" / "src" / "lib" / "module-map.ts"
    ).read_text(encoding="utf-8")
    line = next(line for line in module_map.splitlines() if line.startswith("export const MONEY_ROLES"))
    assert {role.strip(" '") for role in line.split("[", 1)[1].split("]", 1)[0].split(",")} == set(EXPENSE_VIEW_ROLES)
