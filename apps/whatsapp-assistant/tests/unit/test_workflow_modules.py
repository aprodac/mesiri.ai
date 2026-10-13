"""Workflow -> module mapping and /auth/me's enabled_modules (V1 tracker BE-06).

The registry names modules as plain strings to keep depending on contracts
only; these tests are what stop those strings drifting from the backend
catalogue.
"""

from __future__ import annotations

import pytest

from auth import router as auth_router
from mesiri.domains.organizations import settings
from mesiri_contracts.assistant.planner_decision import WorkflowKey
from workflows import registry


def test_every_mapped_module_exists_in_the_backend_catalogue():
    for definition in registry.iter_definitions():
        module = registry.module_for_workflow(definition.key)
        assert module is None or module in settings.MODULES, definition.key


@pytest.mark.parametrize(
    "key",
    [
        WorkflowKey.EXPENSE_SUBMIT,
        WorkflowKey.PETTY_CASH,
        WorkflowKey.TRANSFER,
        WorkflowKey.ACCOUNT_BALANCE_QUERY,
    ],
)
def test_money_workflows_need_finance(key):
    assert registry.module_for_workflow(key) == "finance"


def test_v1_capture_workflows_map_to_v1_modules():
    assert registry.module_for_workflow(WorkflowKey.SITE_UPDATE) == "dpr"
    assert registry.module_for_workflow(WorkflowKey.LABOUR_ATTENDANCE) == "labour"
    assert registry.module_for_workflow(WorkflowKey.MATERIAL_RECEIPT) == "materials"


def test_reverse_is_always_available():
    """REVERSE is filed under finance but also undoes attendance and
    activities; gating it on finance would block V1 corrections."""
    assert registry.module_for_workflow(WorkflowKey.REVERSE) is None


def test_identity_and_project_workflows_are_always_available():
    assert registry.module_for_workflow(WorkflowKey.WHO_AM_I) is None
    assert registry.module_for_workflow(WorkflowKey.PROJECT_CREATE) is None


async def test_me_gives_platform_admin_every_module():
    assert await auth_router._enabled_modules_for("") == list(settings.MODULES)


async def test_me_falls_back_to_default_when_lookup_fails(monkeypatch):
    """/auth/me gates every dashboard page load; a settings failure must not
    log anyone out."""

    def broken_engine():
        raise RuntimeError("database down")

    monkeypatch.setattr(auth_router, "get_engine", broken_engine)
    org = "11111111-1111-1111-1111-111111111111"
    assert await auth_router._enabled_modules_for(org) == settings.DEFAULT_ENABLED_MODULES
