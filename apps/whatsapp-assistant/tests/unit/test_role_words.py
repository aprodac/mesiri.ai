"""WA-67: one role vocabulary for every add-a-person flow on WhatsApp, and a
project manager can't make an admin (audit SET-01, SET-05)."""

from __future__ import annotations

import pytest

from mesiri_contracts.assistant.planner_decision import WorkflowKey
from workflows.add_project_member.nodes import build_draft as build_member_draft
from workflows.create_user.nodes import build_draft as build_user_draft
from workflows.role_words import normalize_role


@pytest.mark.parametrize(
    ("hint", "role"),
    [
        ("accountant", "FINANCE"),
        ("as PM", "PROJECT_MANAGER"),
        ("project manager", "PROJECT_MANAGER"),
        ("owner", "ADMIN"),
        ("Director", "ADMIN"),
        ("site engineer", "SITE_ENGINEER"),
        ("supervisor", "SITE_ENGINEER"),
        ("SITE_ENGINEER", "SITE_ENGINEER"),
        ("equipment operator", "SITE_ENGINEER"),  # "pm" inside a word is not PM
        ("", "SITE_ENGINEER"),
        (None, "SITE_ENGINEER"),
    ],
)
def test_role_words(hint, role):
    assert normalize_role(hint) == role


def _state(key: WorkflowKey, fields: dict) -> dict:
    return {
        "workflow_instance_id": "wf_1",
        "workflow_key": key.value,
        "correlation_id": "cor_1",
        "organization_id": "11111111-1111-4111-8111-111111111111",
        "user_id": "22222222-2222-4222-8222-222222222222",
        "project_id": "33333333-3333-4333-8333-333333333333",
        "site_id": None,
        "collected_fields": fields,
    }


@pytest.mark.parametrize("role_hint", ["admin", "owner", "accountant"])
def test_a_project_manager_is_told_only_an_admin_can_give_that_role(role_hint):
    member = build_member_draft(
        _state(WorkflowKey.ADD_PROJECT_MEMBER, {"member_name": "Ravi", "role": role_hint, "created_by_role": "PROJECT_MANAGER"})
    )
    user = build_user_draft(
        _state(
            WorkflowKey.CREATE_USER,
            {"full_name": "Ravi", "whatsapp_number": "919876511122", "role": role_hint, "created_by_role": "PROJECT_MANAGER"},
        )
    )
    for result in (member, user):
        assert "draft_action" not in result
        assert result["pending_prompt"].startswith("Only an admin can add someone as")


def test_a_project_manager_may_add_project_managers_and_engineers():
    for hint, role in (("pm", "PROJECT_MANAGER"), ("engineer", "SITE_ENGINEER")):
        result = build_member_draft(
            _state(WorkflowKey.ADD_PROJECT_MEMBER, {"member_name": "Ravi", "role": hint, "created_by_role": "PROJECT_MANAGER"})
        )
        assert result["draft_action"].fields["role"] == role


def test_an_admin_may_add_an_admin():
    result = build_member_draft(
        _state(WorkflowKey.ADD_PROJECT_MEMBER, {"member_name": "Ravi", "role": "owner", "created_by_role": "ADMIN"})
    )
    assert result["draft_action"].fields["role"] == "ADMIN"
