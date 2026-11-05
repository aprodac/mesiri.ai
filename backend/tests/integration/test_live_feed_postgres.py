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

from .test_live_questions_postgres import NOW, SENDER, _message, conn  # noqa: F401 -- the shared fixture

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
