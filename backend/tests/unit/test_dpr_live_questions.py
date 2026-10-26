"""WEB-37: the Live report's questions (GET /dpr/site-days/{id}/questions):
the site rule is the site day's, one day at a time, and finance questions
are never listed (their answers are for some roles only, SEC-01)."""

from __future__ import annotations

import datetime
import uuid

import pytest
from fastapi import HTTPException

from mesiri.authorization.context import (
    AccessPolicy,
    AuthorizationContext,
    ProjectAccessScope,
    SiteAccessScope,
)
from mesiri.domains.dpr import router as dpr_router

ORG = uuid.uuid4()
P1 = uuid.uuid4()
S1, S2 = uuid.uuid4(), uuid.uuid4()
SINCE = datetime.datetime(2026, 10, 25, tzinfo=datetime.UTC)
UNTIL = SINCE + datetime.timedelta(days=1)

ONLY_S1 = AuthorizationContext(
    user_id=uuid.uuid4(),
    organization_id=ORG,
    role="SITE_ENGINEER",
    status="active",
    access_policy=AccessPolicy(mode="custom_projects", projects=[]),
    project_scope=ProjectAccessScope(mode="custom_projects", project_ids={P1}),
    site_scopes={P1: SiteAccessScope(mode="custom_sites", site_ids={S1})},
)


class _Sites:
    def __init__(self, conn):
        pass

    async def find_site(self, *, organization_id, site_id):
        return {"id": site_id, "project_id": P1}


class _Questions:
    asked: dict = {}

    def __init__(self, conn):
        pass

    async def questions(self, **kw):
        _Questions.asked = kw
        return [
            {"id": "m1", "text": "stock at tower a?", "reply": "Cement 40 bags", "workflow_key": "material.inventory_query"},
            {"id": "m2", "text": "how many came?", "reply": "5 workers", "workflow_key": "labour.query"},
            # WEB-46: the agent's lookups leave no workflow row; the traced tool tells.
            {"id": "m3", "text": "ആരൊക്കെ വന്നു?", "reply": "ഇന്ന് 4 പേർ", "workflow_key": None, "tools": ["query_labour"]},
            {"id": "m4", "text": "expenses?", "reply": "500", "workflow_key": None, "tools": ["query_expenses"]},
        ]


@pytest.fixture(autouse=True)
def _fakes(monkeypatch):
    monkeypatch.setattr(dpr_router, "PostgresDprRepository", _Sites)
    monkeypatch.setattr(dpr_router, "PostgresFactReviewRepository", _Questions)


async def test_questions_come_with_what_they_were_about():
    res = await dpr_router.list_site_day_questions(S1, SINCE, UNTIL, auth_context=ONLY_S1, conn=None)

    assert [(q["id"], q["kind"]) for q in res["items"]] == [("m1", "stock"), ("m2", "manpower"), ("m3", "manpower")]
    assert all("workflow_key" not in q and "tools" not in q for q in res["items"])
    assert _Questions.asked["site_id"] == S1 and _Questions.asked["project_id"] == P1


async def test_finance_questions_are_never_asked_for():
    await dpr_router.list_site_day_questions(S1, SINCE, UNTIL, auth_context=ONLY_S1, conn=None)

    keys = set(_Questions.asked["workflow_keys"])
    assert "expense.query" not in keys and "finance.account_query" not in keys
    assert "query_expenses" not in _Questions.asked["tool_names"]
    assert "material.inventory_query" in keys


async def test_a_site_outside_the_viewers_sites_is_not_found():
    with pytest.raises(HTTPException) as err:
        await dpr_router.list_site_day_questions(S2, SINCE, UNTIL, auth_context=ONLY_S1, conn=None)
    assert err.value.status_code == 404


@pytest.mark.parametrize(
    "since, until",
    [(UNTIL, SINCE), (SINCE, SINCE + datetime.timedelta(days=3))],
)
async def test_one_day_at_a_time(since, until):
    with pytest.raises(HTTPException) as err:
        await dpr_router.list_site_day_questions(S1, since, until, auth_context=ONLY_S1, conn=None)
    assert err.value.status_code == 422
