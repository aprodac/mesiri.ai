"""WEB-46: the Live report's questions, against a real Postgres. The agent
answers a lookup without leaving a workflow row, so a question is told by the
turn's traced tool calls (journey_traces 'agent_tools'). A message with no
project or site recorded counts when its sender wrote about the site that day.
Each test runs in a transaction that is rolled back."""

from __future__ import annotations

import datetime as dt
import json
import uuid

import pytest
from sqlalchemy import text

from mesiri.application.organizations.create_company import NewCompany, create_company
from mesiri.domains.dpr.router import QUESTION_KINDS, QUESTION_TOOLS
from mesiri.infrastructure.postgres.repositories.fact_reviews import PostgresFactReviewRepository

pytestmark = pytest.mark.integration

NOW = dt.datetime(2026, 10, 26, 3, 0, tzinfo=dt.UTC)
SENDER = "919876500061"


@pytest.fixture
async def conn():
    from sqlalchemy.ext.asyncio import create_async_engine

    from mesiri.bootstrap.settings import Settings

    engine = create_async_engine(Settings().postgres.dsn())
    async with engine.connect() as connection:
        tx = await connection.begin()
        yield connection
        await tx.rollback()
    await engine.dispose()


async def _message(conn, org, *, text_, reply, tools, project=None, site=None, minutes=0, v3=None) -> str:
    correlation = f"cor_{uuid.uuid4().hex[:10]}"
    await conn.execute(
        text(
            "INSERT INTO inbound_messages (id, correlation_id, sender_wa_id, message_type, raw_payload,"
            " body_text, dedup_key, raw_payload_captured, organization_id, project_id, site_id,"
            " assistant_reply, received_at)"
            " VALUES (:id, :c, :s, 'text', '{}'::jsonb, :b, :c, true, :o, :p, :site, :r, :at)"
        ),
        {"id": uuid.uuid4(), "c": correlation, "s": SENDER, "b": text_, "o": org, "p": project,
         "site": site, "r": reply, "at": NOW + dt.timedelta(minutes=minutes)},
    )
    if v3 is not None:
        # TM-41: a v3 turn (stage agent_api_turn): its calls, and what it saved or prepared.
        await conn.execute(
            text(
                "INSERT INTO journey_traces (id, correlation_id, stage, stage_payload, succeeded)"
                " VALUES (:id, :c, 'agent_api_turn', CAST(:p AS jsonb), true)"
            ),
            {"id": uuid.uuid4(), "c": correlation, "p": json.dumps({
                "calls": [{"tool": t, "arguments": {}, "result": {"status": 200}} for t in tools], **v3})},
        )
        return correlation
    if tools:
        await conn.execute(
            text(
                "INSERT INTO journey_traces (id, correlation_id, stage, stage_payload, succeeded)"
                " VALUES (:id, :c, 'agent_tools', CAST(:p AS jsonb), true)"
            ),
            {"id": uuid.uuid4(), "c": correlation, "p": json.dumps({"calls": [{"tool": t, "args": [], "status": "ok"} for t in tools]})},
        )
    return correlation


async def test_a_question_answered_by_a_lookup_is_listed(conn) -> None:
    created = await create_company(
        conn,
        NewCompany(name="Ask Builders", owner_name="Owner", owner_phone="+" + SENDER,
                   project_name="Hospital", site_names=("Tower A",), auto_dpr=False),
        now=NOW,
    )
    org, project, site = created.organization_id, created.project_id, created.sites[0].site_id
    # An entry about the site, then a question with no project/site recorded (as before WEB-46).
    await _message(conn, org, text_="innu 4 per", reply="Saved", tools=["save_labour"], project=project, site=site)
    await _message(conn, org, text_="ആരൊക്കെ വന്നു?", reply="ഇന്ന് 4 പേർ", tools=["query_labour"], minutes=5)
    # A money question is never listed; a message that asked nothing either.
    await _message(conn, org, text_="expenses?", reply="₹ 500", tools=["query_expenses"], project=project, site=site, minutes=6)

    rows = await PostgresFactReviewRepository(conn).questions(
        organization_id=org, project_id=project, site_id=site,
        since=NOW - dt.timedelta(hours=1), until=NOW + dt.timedelta(hours=1),
        workflow_keys=list(QUESTION_KINDS), tool_names=list(QUESTION_TOOLS),
    )

    assert [(r["text"], r["reply"], r["tools"]) for r in rows] == [("ആരൊക്കെ വന്നു?", "ഇന്ന് 4 പേർ", ["query_labour"])]


async def test_v3_a_lookup_only_turn_is_a_question_and_an_entry_is_not(conn) -> None:
    """TM-41 (2 Nov): v3 traces its turns as agent_api_turn, so v3 companies' questions never reached Live."""
    created = await create_company(
        conn,
        NewCompany(name="Ask Builders v3", owner_name="Owner", owner_phone="+" + SENDER,
                   project_name="Hospital", site_names=("Tower A",), auto_dpr=False),
        now=NOW,
    )
    org, project, site = created.organization_id, created.project_id, created.sites[0].site_id
    await _message(conn, org, text_="how many came today?", reply="4 masons", tools=["labour_attendance"],
                   project=project, site=site, v3={"saved": [], "pending": []})
    # An entry also looks things up (the material's id) but prepares a save: not a question.
    await _message(conn, org, text_="50 bags cement came", reply="Ready to save", tools=["search_materials", "stock_check"],
                   project=project, site=site, minutes=2, v3={"saved": [], "pending": ["50 bags cement received"]})

    rows = await PostgresFactReviewRepository(conn).questions(
        organization_id=org, project_id=project, site_id=site,
        since=NOW - dt.timedelta(hours=1), until=NOW + dt.timedelta(hours=1),
        workflow_keys=list(QUESTION_KINDS), tool_names=list(QUESTION_TOOLS),
    )

    assert [(r["text"], r["tools"]) for r in rows] == [("how many came today?", ["labour_attendance"])]
