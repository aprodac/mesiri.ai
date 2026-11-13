"""WEB-83: the owner's board against a real Postgres: every read is the module's own route function, run for a
real company, so a route whose signature or SQL changed fails here and not on Live. An owner's board reads all of
it; a site engineer's board is refused every money read by the modules themselves. Rolled back after each test."""

from __future__ import annotations

import datetime as dt
import logging
import types
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from mesiri.application.organizations.create_company import NewCompany, create_company
from mesiri.authorization.context import AuthorizationContext, ProjectAccessScope
from mesiri.domains.dpr import board

from .test_live_questions_postgres import NOW, conn  # noqa: F401 -- the shared fixture

pytestmark = pytest.mark.integration

REQUEST = types.SimpleNamespace(app=types.SimpleNamespace(state=types.SimpleNamespace()))
MONEY_READS = {"costs", "budget", "rates", "wages", "suppliers", "clients", "to_bill"}


def _auth(org: uuid.UUID, user: uuid.UUID, role: str) -> AuthorizationContext:
    return AuthorizationContext(user_id=user, organization_id=org, role=role, status="active",
                                access_policy={},  # type: ignore[arg-type]
                                project_scope=ProjectAccessScope(mode="all_projects", project_ids=set()))


async def _company(conn):  # noqa: F811
    return await create_company(
        conn, NewCompany(name="Board Builders", owner_name="Ravi Kumar", owner_phone="+919876500083",
                         project_name="Hospital", site_names=("Tower A", "Main block"), auto_dpr=False), now=NOW)


@pytest.mark.parametrize("name", sorted(board.READS))
async def test_every_read_runs_for_an_owner(conn, name) -> None:  # noqa: F811
    made = await _company(conn)
    ctx = board.Ctx(conn=conn, auth=_auth(made.organization_id, made.owner_user_id, "OWNER"), request=REQUEST,
                    today=dt.date(2026, 10, 26))
    data = await board.READS[name](ctx)
    part = next(p for q in board.QUESTIONS for p in q.parts if p.read == name)
    # A new company has nothing to say yet, and the sentence is made from the route's real answer without failing.
    assert part.say(data) is None or isinstance(part.say(data), str)


@pytest.mark.parametrize("name", sorted(MONEY_READS))
async def test_the_modules_refuse_a_site_engineer_every_money_read(conn, name) -> None:  # noqa: F811
    made = await _company(conn)
    ctx = board.Ctx(conn=conn, auth=_auth(made.organization_id, uuid.uuid4(), "SITE_ENGINEER"), request=REQUEST,
                    today=dt.date(2026, 10, 26))
    with pytest.raises(HTTPException) as refused:
        await board.READS[name](ctx)
    assert refused.value.status_code == 403


async def test_the_board_of_a_day_with_an_open_issue(conn, caplog) -> None:  # noqa: F811
    made = await _company(conn)
    org, site = made.organization_id, made.sites[0].site_id
    today = dt.date(2026, 10, 26)
    await conn.execute(text(
        "INSERT INTO site_issues (id, organization_id, project_id, site_id, issue_type, narrative, occurred_at) "
        "VALUES (:id, :org, :p, :s, 'WEATHER', 'Water leaking in the basement', :at)"),
        {"id": uuid.uuid4(), "org": org, "p": made.project_id, "s": site, "at": NOW})

    with caplog.at_level(logging.ERROR, logger=board.__name__):
        owner = await board.build(conn, _auth(org, made.owner_user_id, "OWNER"), REQUEST, today, lambda m: True)
        engineer = await board.build(conn, _auth(org, uuid.uuid4(), "SITE_ENGINEER"), REQUEST, today, lambda m: True)
    assert not caplog.records  # no read failed

    by = {q["key"]: q for q in owner["questions"]}
    assert [q["key"] for q in owner["questions"]] == [q.key for q in board.QUESTIONS]
    assert {"text": "1 issue open on 1 site.", "opens": "/issues", "read": "days"} in by["stops"]["lines"]
    assert not any(q["hidden"] for q in by.values())
    # Nothing spent, nothing owed: said as such only because every part was read.
    assert by["money"]["quiet"] == "Nothing spent in the last 7 days." and by["owed"]["quiet"] == "Nothing owed either way."

    theirs = {q["key"]: q for q in engineer["questions"]}
    assert theirs["money"]["hidden"] and theirs["owed"]["hidden"]
    assert theirs["money"]["lines"] == [] and theirs["money"]["quiet"] is None
    assert {"text": "1 issue open on 1 site.", "opens": "/issues", "read": "days"} in theirs["stops"]["lines"]
