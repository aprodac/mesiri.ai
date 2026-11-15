"""BOQ-01b (security): only the roles that see the BOQ page are told its lines or may put work on them."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from mesiri.domains.progress.router import WorkBoqLine, boq_seen_by, put_own_work_on_line

PLACED = [{"quantity_id": "q", "work": "plastering", "line": {"id": "l", "work": "Internal plastering"},
           "auto": True, "choices": []}]


@pytest.mark.parametrize("role", ["SITE_SUPERVISOR", "SITE_ENGINEER", None])
def test_a_site_role_is_told_nothing_about_the_boq(role):
    assert boq_seen_by(role, PLACED) == []


@pytest.mark.parametrize("role", ["OWNER", "ADMIN", "PROJECT_MANAGER", "FINANCE"])
def test_the_boq_roles_are_told_where_it_went(role):
    assert boq_seen_by(role, PLACED) == PLACED


async def test_a_site_role_cannot_put_work_on_a_line():
    with pytest.raises(HTTPException) as refused:
        await put_own_work_on_line(uuid.uuid4(), uuid.uuid4(), WorkBoqLine(line_id=None),
                                   auth_context=SimpleNamespace(role="SITE_SUPERVISOR"), conn=None)
    assert refused.value.status_code == 403
