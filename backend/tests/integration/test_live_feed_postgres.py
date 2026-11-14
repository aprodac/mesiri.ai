"""WEB-53: the company Live's feed against a real Postgres: every message of
the company in the window (any site, none at all), with the site and project
names and what each turn did, read from its traces. Another company's
messages never show. Each test runs in a transaction that is rolled back."""

from __future__ import annotations

import datetime as dt
import json

import pytest

from mesiri.application.organizations.create_company import NewCompany, create_company
from mesiri.domains.dpr import live_feed
from mesiri.infrastructure.postgres.repositories.fact_reviews import PostgresFactReviewRepository

from .test_live_questions_postgres import (  # noqa: F401 -- the shared fixture
    NOW,
    SENDER,
    _message,
    conn,
)

pytestmark = pytest.mark.integration


async def test_every_message_of_the_company_with_what_it_did(conn) -> None:  # noqa: F811
    created = await create_company(
        conn,
        NewCompany(name="Feed Builders", owner_name="Ravi Kumar", owner_phone="+" + SENDER,
                   project_name="Hospital", site_names=("Tower A",), auto_dpr=False),
        now=NOW,
    )
    org, project, site = created.organization_id, created.project_id, created.sites[0].site_id
    other = await create_company(
        conn,
        NewCompany(name="Someone Else", owner_name="Other", owner_phone="+919800000999",
                   project_name="Mall", site_names=("Block B",), auto_dpr=False),
        now=NOW,
    )
    await _message(conn, org, text_="50 bags cement came", reply="Saved", tools=["search_materials", "record_receipt"],
                   project=project, site=site, v3={"saved": [{"summary": "Cement 50 bags in", "status": 201}], "pending": []})
    await _message(conn, org, text_="stock?", reply="Cement 50 bags", tools=["stock_levels"], project=project, site=site,
                   minutes=1, v3={"saved": [], "pending": []})
    await _message(conn, org, text_="hi", reply="Hi Ravi", tools=[], minutes=2)
    await _message(conn, other.organization_id, text_="not ours", reply="x", tools=[], minutes=3)

    rows = await PostgresFactReviewRepository(conn).live_feed(
        organization_id=org, since=NOW - dt.timedelta(hours=1), until=NOW + dt.timedelta(hours=1)
    )

    assert [r["text"] for r in rows] == ["50 bags cement came", "stock?", "hi"]
    # WEB-65: the test messages carry no status (the default), and are long done: handled.
    assert all(r["handled"] for r in rows)
    # Live plays Mesiri's hello on a person's first message ever, once.
    assert [r["first_message"] for r in rows] == [True, False, False]
    first = rows[0]
    assert (first["site_name"], first["project_name"], first["sender_name"]) == ("Tower A", "Hospital", "Ravi Kumar")
    assert first["project_id"] == project and first["site_id"] == site
    kinds = [(live_feed.classify(r)["kind"], live_feed.classify(r)["state"]) for r in rows]
    assert kinds == [("delivery", "saved"), ("question", "answered"), ("chat", "heard")]
    assert live_feed.classify(first)["summaries"] == ["Cement 50 bags in"]
    assert live_feed.classify(first)["did"] == ["Found the material", "Prepared the delivery"]


async def test_a_transfer_comes_with_its_two_sites(conn) -> None:  # noqa: F811
    created = await create_company(
        conn,
        NewCompany(name="Move Builders", owner_name="Ravi", owner_phone="+" + SENDER,
                   project_name="Hospital", site_names=("Tower A", "Villa 2"), auto_dpr=False),
        now=NOW,
    )
    org, project = created.organization_id, created.project_id
    a, b = created.sites[0].site_id, created.sites[1].site_id
    correlation = await _message(conn, org, text_="30 bags to Villa 2", reply="Ready", tools=[], project=project, site=a)
    from sqlalchemy import text
    await conn.execute(
        text("INSERT INTO journey_traces (id, correlation_id, stage, stage_payload, succeeded)"
             " VALUES (gen_random_uuid(), :c, 'agent_api_turn', CAST(:p AS jsonb), true)"),
        {"c": correlation, "p": json.dumps({"calls": [{"tool": "record_transfer", "arguments": {
            "from_site_id": str(a), "to_site_id": str(b), "quantity": 30}}], "saved": [], "pending": ["30 bags to Villa 2"]})},
    )

    rows = await PostgresFactReviewRepository(conn).live_feed(
        organization_id=org, since=NOW - dt.timedelta(hours=1), until=NOW + dt.timedelta(hours=1)
    )

    what = live_feed.classify(rows[0])
    assert (what["kind"], what["state"]) == ("transfer", "draft")
    assert what["transfer"] == {"from_site_id": str(a), "to_site_id": str(b)}


async def test_a_voice_note_shows_the_words_mesiri_heard(conn) -> None:  # noqa: F811
    """5 Nov: most real messages are Malayalam voice notes, whose words live only in the turn's trace."""
    from sqlalchemy import text

    created = await create_company(
        conn,
        NewCompany(name="Voice Builders", owner_name="Ravi", owner_phone="+" + SENDER,
                   project_name="Hospital", site_names=("Tower A",), auto_dpr=False),
        now=NOW,
    )
    org, project, site = created.organization_id, created.project_id, created.sites[0].site_id
    correlation = await _message(conn, org, text_=None, reply="Ready", tools=[], project=project, site=site)
    await conn.execute(text("UPDATE inbound_messages SET message_type = 'voice' WHERE correlation_id = :c"), {"c": correlation})
    await conn.execute(
        text("INSERT INTO journey_traces (id, correlation_id, stage, stage_payload, succeeded)"
             " VALUES (gen_random_uuid(), :c, 'agent_api_turn', CAST(:p AS jsonb), true)"),
        {"c": correlation, "p": json.dumps({"text": "ഇന്ന് 50 ചാക്ക് സിമന്റ് വന്നു", "calls": [], "saved": [], "pending": []})},
    )
    # The guard: a typed message keeps its own words, and a tap's trace text ("(tapped Save)") never shows.
    await _message(conn, org, text_="hi", reply="Hi", tools=[], minutes=1)

    rows = await PostgresFactReviewRepository(conn).live_feed(
        organization_id=org, since=NOW - dt.timedelta(hours=1), until=NOW + dt.timedelta(hours=1)
    )

    assert [r["text"] for r in rows] == ["ഇന്ന് 50 ചാക്ക് സിമന്റ് വന്നു", "hi"]


async def test_a_message_mesiri_is_still_working_on_is_not_handled(conn) -> None:  # noqa: F811
    """WEB-65: a message just in, still 'pending', is not handled yet; Live waits for it."""
    from sqlalchemy import text

    created = await create_company(
        conn,
        NewCompany(name="Busy Builders", owner_name="Ravi", owner_phone="+" + SENDER,
                   project_name="Hospital", site_names=("Tower A",), auto_dpr=False),
        now=NOW,
    )
    org = created.organization_id
    correlation = await _message(conn, org, text_="bill", reply=None, tools=[])
    now = dt.datetime.now(dt.UTC)
    await conn.execute(text("UPDATE inbound_messages SET processing_status = 'pending', received_at = :at WHERE correlation_id = :c"),
                       {"c": correlation, "at": now})
    rows = await PostgresFactReviewRepository(conn).live_feed(
        organization_id=org, since=now - dt.timedelta(hours=1), until=now + dt.timedelta(hours=1)
    )
    assert [r["handled"] for r in rows] == [False]


async def test_the_stamp_changes_when_a_message_comes_and_when_mesiri_is_done(conn) -> None:  # noqa: F811
    """WEB-69: Live asks for the stamp every second and reads the feed only when it changed."""
    from sqlalchemy import text

    created = await create_company(
        conn,
        NewCompany(name="Stamp Builders", owner_name="Ravi", owner_phone="+" + SENDER,
                   project_name="Hospital", site_names=("Tower A",), auto_dpr=False),
        now=NOW,
    )
    org = created.organization_id
    repo = PostgresFactReviewRepository(conn)
    window = {"organization_id": org, "since": NOW - dt.timedelta(hours=1), "until": NOW + dt.timedelta(hours=1)}
    empty = await repo.live_stamp(**window)
    correlation = await _message(conn, org, text_="cement vannu", reply=None, tools=[])
    came = await repo.live_stamp(**window)
    await conn.execute(text("UPDATE inbound_messages SET assistant_reply = 'Ready', processing_status = 'completed' "
                            "WHERE correlation_id = :c"), {"c": correlation})
    done = await repo.live_stamp(**window)
    assert len({empty, came, done}) == 3


async def test_a_questions_ripple_reads_what_it_looked_up_and_todays_messages_before_it(conn) -> None:  # noqa: F811
    """WEB-87 on a real Postgres: the read calls' arguments come through the feed, the day starts in the company's
    zone, and the messages behind the answer are today's saved ones at the site it read, before the question."""
    import uuid

    from sqlalchemy import text

    from mesiri.authorization.context import (
        AuthorizationContext,
        ProjectAccessScope,
        SiteAccessScope,
    )
    from mesiri.domains.dpr import effects

    created = await create_company(
        conn,
        NewCompany(name="Answer Builders", owner_name="Ravi Kumar", owner_phone="+" + SENDER,
                   project_name="Hospital", site_names=("Tower A", "Villa 2"), auto_dpr=False),
        now=NOW,
    )
    org, project = created.organization_id, created.project_id
    a, b = created.sites[0].site_id, created.sites[1].site_id

    async def turn(correlation, payload):
        await conn.execute(
            text("INSERT INTO journey_traces (id, correlation_id, stage, stage_payload, succeeded)"
                 " VALUES (gen_random_uuid(), :c, 'agent_api_turn', CAST(:p AS jsonb), true)"),
            {"c": correlation, "p": json.dumps(payload)})

    def saved(summary):
        return {"calls": [{"tool": "record_receipt", "arguments": {}}],
                "saved": [{"tool": "record_receipt", "status": 201, "summary": summary, "id": str(uuid.uuid4())}]}

    await turn(await _message(conn, org, text_="50 bags cement came", reply="Saved", tools=[], project=project,
                              site=a), saved("Cement 50 bags in"))
    await turn(await _message(conn, org, text_="20 bags at Villa", reply="Saved", tools=[], project=project, site=b,
                              minutes=1), saved("Cement 20 bags in"))
    asked = await _message(conn, org, text_="how much cement at Tower A?", reply="Tower A has 50 bags.", tools=[],
                           project=project, site=a, minutes=2)
    await turn(asked, {"calls": [{"tool": "stock_summary", "arguments": {"site_id": str(a)}, "result": "{}"}],
                       "saved": [], "pending": []})
    await turn(await _message(conn, org, text_="10 more came", reply="Saved", tools=[], project=project, site=a,
                              minutes=3), saved("Cement 10 bags in"))
    message_id = (await conn.execute(text("SELECT id FROM inbound_messages WHERE correlation_id = :c"),
                                     {"c": asked})).scalar_one()

    rows = await PostgresFactReviewRepository(conn).live_feed(
        organization_id=org, since=NOW - dt.timedelta(hours=1), until=NOW + dt.timedelta(hours=1))
    question = live_feed.classify(next(r for r in rows if r["id"] == str(message_id)))
    assert question["records"] == [{"kind": "answer", "id": str(message_id)}]
    assert question["looked"] == [{"tool": "stock_summary", "site_id": str(a), "material_id": None}]

    auth = AuthorizationContext(user_id=created.owner_user_id, organization_id=org, role="OWNER", status="active",
                                access_policy={},  # type: ignore[arg-type]
                                project_scope=ProjectAccessScope(mode="all_projects", project_ids=set()),
                                site_scopes={project: SiteAccessScope(mode="all_sites", site_ids=set())})
    today = (NOW + dt.timedelta(hours=5, minutes=30)).date()  # the company's day (India)
    facts = await effects.read_answer(conn, org, message_id, today, True, auth=auth)
    assert facts["read"] == "Read the stock at Tower A" and facts["answer"] == "Tower A has 50 bags."
    assert facts["from"] == [{"sender": "Ravi Kumar", "site": "Tower A", "summary": "Cement 50 bags in"}]
    # With a material named, a delivery with no record of that material is left out, never guessed.
    await conn.execute(text(
        "UPDATE journey_traces SET stage_payload = jsonb_set(stage_payload::jsonb, '{calls,0,arguments,material_id}',"
        " to_jsonb(CAST(:m AS text))) WHERE correlation_id = :c"), {"m": str(uuid.uuid4()), "c": asked})
    facts = await effects.read_answer(conn, org, message_id, today, True, auth=auth)
    assert facts["from"] == []
    cards = effects.cards(effects.ANSWER, facts, True)["cards"]
    assert [c["key"] for c in cards] == ["answer", "answer_read", "answer_from"]
    # The guard: a viewer given only the other site sees none of Tower A's messages behind the answer.
    only_b = AuthorizationContext(user_id=created.owner_user_id, organization_id=org, role="SITE_ENGINEER",
                                  status="active", access_policy={},  # type: ignore[arg-type]
                                  project_scope=ProjectAccessScope(mode="all_projects", project_ids=set()),
                                  site_scopes={project: SiteAccessScope(mode="custom_sites", site_ids={b})})
    await conn.execute(text(
        "UPDATE journey_traces SET stage_payload = stage_payload::jsonb #- '{calls,0,arguments,material_id}'"
        " WHERE correlation_id = :c"), {"c": asked})
    assert (await effects.read_answer(conn, org, message_id, today, True, auth=auth))["from"]
    assert (await effects.read_answer(conn, org, message_id, today, True, auth=only_b))["from"] == []
