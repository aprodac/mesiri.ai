"""WA-67 (audit SET-01): who may give which role, checked again when a
WhatsApp add-person change is saved."""

from __future__ import annotations

import pytest

from mesiri.application.identity.create_user_commands import CreateUserCommand
from mesiri.application.identity.create_user_validation import validate as validate_user
from mesiri.application.projects.add_member_commands import AddProjectMemberCommand
from mesiri.application.projects.add_member_validation import validate as validate_member
from mesiri.authorization.roles import may_grant_role

REFUSED = "only an admin can give someone the admin or finance role"


@pytest.mark.parametrize(
    ("creator", "role", "allowed"),
    [
        ("ADMIN", "ADMIN", True),
        ("ADMIN", "FINANCE", True),
        ("PROJECT_MANAGER", "PROJECT_MANAGER", True),
        ("PROJECT_MANAGER", "SITE_ENGINEER", True),
        ("PROJECT_MANAGER", "ADMIN", False),
        ("PROJECT_MANAGER", "FINANCE", False),
        ("SITE_ENGINEER", "SITE_ENGINEER", False),
        (None, "SITE_ENGINEER", False),
        ("project_manager", "site_engineer", True),
    ],
)
def test_may_grant_role(creator, role, allowed):
    assert may_grant_role(creator, role) is allowed


def _user(creator, role):
    return CreateUserCommand(
        idempotency_key="k", organization_id="o", created_by="u", created_by_role=creator,
        full_name="Ravi", whatsapp_number="919876511122", role=role,
    )


def _member(creator, role):
    return AddProjectMemberCommand(
        idempotency_key="k", organization_id="o", project_id="p", created_by="u",
        created_by_role=creator, member_name="Ravi", member_user_id="m", role=role,
    )


@pytest.mark.parametrize("build", [_user, _member])
def test_a_project_manager_making_an_admin_is_refused_when_saved(build):
    validate = validate_user if build is _user else validate_member
    assert REFUSED in validate(build("PROJECT_MANAGER", "ADMIN"))
    assert validate(build("PROJECT_MANAGER", "SITE_ENGINEER")) == []
    assert validate(build("ADMIN", "ADMIN")) == []
