"""WA-07: a company's switched-off modules on WhatsApp.

Covers the registry side (which request needs which module, what the menu
advertises) and the polite reply. The process-level gate is exercised by the
journey tests through the same registry functions.
"""

from __future__ import annotations

import pytest

from channel.replies import render_module_disabled_reply
from mesiri_contracts.assistant.planner_decision import WorkflowKey
from workflows import registry


@pytest.fixture(autouse=True)
def _reset_modules():
    registry.set_enabled_modules(None)
    yield
    registry.set_enabled_modules(None)


@pytest.mark.parametrize(
    ("target", "module"),
    [
        ("expense", "finance"),
        ("transfer", "finance"),
        ("petty_cash", "finance"),
        ("", "finance"),  # falls back to the latest expense/transfer
        ("attendance", "labour"),
        ("activity", None),
    ],
)
def test_reverse_is_judged_by_its_target(target, module):
    fields = {"target_kind": target}
    assert registry.module_for_event(WorkflowKey.REVERSE, fields) == module


def test_ordinary_requests_use_their_workflow_module():
    assert registry.module_for_event(WorkflowKey.EXPENSE_SUBMIT, {}) == "finance"
    assert registry.module_for_event(WorkflowKey.SITE_UPDATE, {}) == "dpr"
    assert registry.module_for_event(None, {}) is None


def test_unknown_company_modules_filter_nothing():
    assert registry.current_enabled_modules() is None
    assert registry.module_is_enabled("finance")


def test_switched_off_module_is_not_enabled_and_always_on_is():
    registry.set_enabled_modules(["dpr", "labour", "materials"])
    assert not registry.module_is_enabled("finance")
    assert registry.module_is_enabled("labour")
    assert registry.module_is_enabled(None)


def test_menu_hides_switched_off_modules():
    everything = {c.category for c in registry.iter_menu_categories()}
    registry.set_enabled_modules(["dpr", "labour", "materials"])
    v1 = {c.category for c in registry.iter_menu_categories()}
    assert registry.WorkflowCategory.FINANCE in everything
    assert registry.WorkflowCategory.FINANCE not in v1
    assert registry.WorkflowCategory.AUTOMATION not in v1
    assert registry.WorkflowCategory.PROGRESS in v1
    assert not any(
        registry.module_for_workflow(d.key) == "finance" for d in registry.iter_user_initiable()
    )


def test_disabled_reply_names_the_module_and_lists_only_what_is_on():
    # Read the finance menu title while nothing is filtered...
    finance_titles = [
        c.title
        for c in registry.iter_menu_categories()
        if c.category is registry.WorkflowCategory.FINANCE
    ]
    assert finance_titles
    # ...then render the reply for a V1 company.
    registry.set_enabled_modules(["dpr", "labour", "materials"])
    reply = render_module_disabled_reply("finance")
    assert "Expenses aren't switched on for your company yet" in reply
    assert "Here's what I can help with" not in reply
    for title in finance_titles:
        assert title not in reply
