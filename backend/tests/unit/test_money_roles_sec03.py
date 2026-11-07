"""SEC-03 (approved in session by the owner, 7 Nov 2026): one rule for who may change where money is kept and move
it, read by the dashboard routes and the WhatsApp journeys alike (three copies disagreed: the owner could not undo a
transfer, manage an account or -- on WhatsApp -- transfer)."""

from __future__ import annotations

import pytest

from mesiri.application.finance import reverse_validation, transfer_validation, validation
from mesiri.authorization.roles import (
    MONEY_MANAGE_ROLES,
    MONEY_TRANSFER_ROLES,
    may_manage_money,
    may_transfer_money,
)


@pytest.mark.parametrize("role", ["owner", "ADMIN", "super_admin", "Finance"])
def test_money_managers(role):
    assert may_manage_money(role) and may_transfer_money(role)


def test_a_project_manager_moves_money_but_does_not_manage_accounts():
    assert may_transfer_money("PROJECT_MANAGER") and not may_manage_money("PROJECT_MANAGER")


@pytest.mark.parametrize("role", ["SITE_ENGINEER", "SUPERVISOR", "", None])
def test_guard_site_roles_never(role):
    assert not may_manage_money(role) and not may_transfer_money(role)


def test_the_journeys_read_the_same_rule():
    assert transfer_validation._TRANSFER_ROLES == MONEY_TRANSFER_ROLES
    assert reverse_validation._REVERSAL_ROLES == MONEY_MANAGE_ROLES
    assert validation._ACCOUNT_ADMIN_ROLES == MONEY_MANAGE_ROLES
    assert "OWNER" in MONEY_MANAGE_ROLES
