"""SA-05: the control panel's costs view, against a real Postgres
(integration): totals, per Indian day, per company, per message a company
sent, and the WhatsApp messages sent to it. Each test runs in a transaction
that is rolled back.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from mesiri.domains.admin import costs_router
from mesiri.infrastructure.postgres.repositories.usage_costs import (
    CostRow,
    PostgresUsageCostRepository,
)

pytestmark = pytest.mark.integration

FROM, TO = dt.date(2026, 10, 18), dt.date(2026, 10, 19)


def _utc(day: int, hour: int, minute: int = 0) -> dt.datetime:
    return dt.datetime(2026, 10, day, hour, minute, tzinfo=dt.UTC)


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


async def _org(conn, name: str) -> uuid.UUID:
    org = uuid.uuid4()
    await conn.execute(
        text(
            "INSERT INTO organizations (id, name, deployment_type, db_route, status, created_at)"
            " VALUES (:id, :name, 'local', 'default', 'active', now())"
        ),
        {"id": org, "name": name},
    )
    return org


async def _costs(conn):
    """Acme: one message (two AI calls, one unpriced) and two WhatsApp
    replies, one sent late on the 18th UTC, which is the 19th in India.
    Bharat: one AI call. A signup with no company yet: one AI call. And a
    row from before the range that must not count."""
    acme, bharat = await _org(conn, "Acme Builders"), await _org(conn, "Bharat Infra")
    corr = f"corr-{uuid.uuid4()}"
    await conn.execute(
        text(
            "INSERT INTO inbound_messages (id, correlation_id, sender_wa_id, message_type,"
            " raw_payload, dedup_key, body_text, organization_id, received_at)"
            " VALUES (gen_random_uuid(), :corr, '919876500061', 'text', '{}', :dedup,"
            " '12 masons today, plastering 3rd floor', :org, :at)"
        ),
        {"corr": corr, "dedup": f"wamid-{corr}", "org": acme, "at": _utc(18, 6)},
    )
    repo = PostgresUsageCostRepository(conn)
    for row in (
        # Attributed through the message, not its own column.
        CostRow(provider="gemini", operation="extract", model="gemini-2.5-flash",
                correlation_id=corr, input_tokens=1200, output_tokens=300,
                cost_inr=Decimal("0.0900"), created_at=_utc(18, 6, 1)),
        CostRow(provider="deepseek", operation="plan", model="unknown-model",
                correlation_id=corr, input_tokens=500, output_tokens=50,
                cost_inr=None, created_at=_utc(18, 6, 2)),
        CostRow(provider="gemini", operation="extract", organization_id=bharat,
                cost_inr=Decimal("0.0400"), created_at=_utc(19, 5)),
        CostRow(provider="gemini", operation="signup", cost_inr=Decimal("0.0100"),
                created_at=_utc(19, 7)),
        CostRow(provider="gemini", operation="old", organization_id=acme,
                cost_inr=Decimal("9.0000"), created_at=_utc(17, 6)),
    ):
        await repo.insert(row)
    for wamid, at in ((f"wamid.a-{corr}", _utc(18, 6, 3)), (f"wamid.b-{corr}", _utc(18, 20))):
        await repo.record_whatsapp_sent(
            CostRow(provider="whatsapp", operation="send_text", organization_id=acme,
                    category="service", billable=True, external_id=wamid,
                    recipient="919876500061", cost_inr=Decimal("0.1150"), created_at=at)
        )
    return acme, bharat


async def test_totals_days_and_companies(conn) -> None:
    acme, bharat = await _costs(conn)

    costs = await costs_router.get_costs(
        date_from=FROM, date_to=TO, organization_id=None, _admin={}, conn=conn
    )

    totals = costs["totals"]
    # Other companies in a shared database may add rows: check ours.
    companies = {c["organization_name"]: c for c in costs["by_company"]}
    assert Decimal(companies["Acme Builders"]["total_cost_inr"]) == Decimal("0.3200")
    assert companies["Acme Builders"]["ai_calls"] == 2
    assert companies["Acme Builders"]["whatsapp_messages"] == 2
    assert companies["Acme Builders"]["unpriced"] == 1  # not counted as free
    assert Decimal(companies["Bharat Infra"]["ai_cost_inr"]) == Decimal("0.0400")
    no_company = next(c for c in costs["by_company"] if c["organization_id"] is None)
    assert no_company["ai_calls"] >= 1
    assert Decimal(totals["total_cost_inr"]) >= Decimal("0.3700")

    acme_days = await costs_router.get_costs(
        date_from=FROM, date_to=TO, organization_id=acme, _admin={}, conn=conn
    )
    days = {d["day"]: d for d in acme_days["by_day"]}
    # 20:00 UTC on the 18th is 01:30 on the 19th in India.
    assert days["2026-10-19"]["whatsapp_messages"] == 1
    assert days["2026-10-18"]["ai_calls"] == 2
    assert Decimal(acme_days["totals"]["total_cost_inr"]) == Decimal("0.3200")


async def test_one_company_lists_its_messages_and_whatsapp_sent(conn) -> None:
    acme, _ = await _costs(conn)

    costs = await costs_router.get_costs(
        date_from=FROM, date_to=TO, organization_id=acme, _admin={}, conn=conn
    )

    assert "by_company" not in costs
    [message] = costs["messages"]
    assert message["text"] == "12 masons today, plastering 3rd floor"
    assert (message["ai_calls"], message["input_tokens"], message["unpriced"]) == (2, 1700, 1)
    assert Decimal(message["ai_cost_inr"]) == Decimal("0.0900")
    assert [s["category"] for s in costs["sent"]] == ["service", "service"]
    assert costs["sent"][0]["sent_at"] > costs["sent"][1]["sent_at"]  # newest first


async def test_a_bad_range_is_refused(conn) -> None:
    with pytest.raises(HTTPException) as backwards:
        await costs_router.get_costs(
            date_from=TO, date_to=FROM, organization_id=None, _admin={}, conn=conn
        )
    with pytest.raises(HTTPException) as too_long:
        await costs_router.get_costs(
            date_from=dt.date(2025, 1, 1), date_to=TO, organization_id=None, _admin={}, conn=conn
        )
    assert backwards.value.status_code == too_long.value.status_code == 422


def test_only_platform_admins_can_read_costs() -> None:
    from mesiri.domains.shared.auth import require_platform_admin

    [route] = [r for r in costs_router.router.routes if r.path == "/admin/costs"]
    assert require_platform_admin in [d.call for d in route.dependant.dependencies]


# --- SS-11: the trials funnel ----------------------------------------------


async def _trial(conn, phone: str, name: str, started: dt.datetime):
    from mesiri.application.organizations.create_company import (
        START_TRIAL,
        NewCompany,
        create_company,
    )

    created = await create_company(
        conn,
        NewCompany(
            name=name,
            owner_name="Owner",
            owner_phone=phone,
            project_name="P1",
            site_names=("S1",),
            start_as=START_TRIAL,
            signup_source="whatsapp",
        ),
        now=started,
    )
    return created


async def test_trials_funnel_counts_each_step_and_trial_costs(conn) -> None:
    # Three trials started on the 18th/19th (India), one before the range.
    await _trial(conn, "9876500071", "Quiet Trial", _utc(18, 4))
    active = await _trial(conn, "9876500072", "Active Trial", _utc(18, 5))
    paying = await _trial(conn, "9876500073", "Paying Trial", _utc(19, 4))
    await _trial(conn, "9876500074", "Old Trial", _utc(10, 4))

    for created in (active, paying):  # a first update
        await conn.execute(
            text(
                "INSERT INTO activities (id, organization_id, project_id, site_id, activity_date,"
                " work_type, narrative, created_at) VALUES (gen_random_uuid(), :org, :p, :s,"
                " '2026-10-19', 'plastering', 'walls', :at)"
            ),
            {"org": created.organization_id, "p": created.project_id, "s": created.site_id,
             "at": _utc(19, 6)},
        )
    await conn.execute(  # a first DPR sent
        text(
            "INSERT INTO daily_reports (id, organization_id, project_id, site_id, level,"
            " report_date, status, updated_at) VALUES (gen_random_uuid(), :org, :p, :s, 'SITE',"
            " '2026-10-19', 'PUBLISHED', :at)"
        ),
        {"org": paying.organization_id, "p": paying.project_id, "s": paying.site_id,
         "at": _utc(19, 15)},
    )
    await conn.execute(  # converted the next day
        text("UPDATE organizations SET status = 'active', converted_at = :at WHERE id = :id"),
        {"id": paying.organization_id, "at": _utc(20, 6)},
    )
    repo = PostgresUsageCostRepository(conn)
    for org, cost, at in (
        (paying.organization_id, "0.5000", _utc(19, 6)),
        (paying.organization_id, "9.0000", _utc(21, 6)),  # after converting: not trial cost
        (active.organization_id, "0.2500", _utc(18, 6)),
    ):
        await repo.insert(CostRow(provider="gemini", operation="extract", organization_id=org,
                                  cost_inr=Decimal(cost), created_at=at))

    funnel = await costs_router.get_trials_funnel(
        date_from=FROM, date_to=TO, _admin={}, conn=conn
    )

    ours = {t["name"]: t for t in funnel["trials"] if t["name"].endswith(" Trial")}
    assert set(ours) == {"Quiet Trial", "Active Trial", "Paying Trial"}  # not "Old Trial"
    assert ours["Quiet Trial"]["reached"] == ["started"]
    assert ours["Active Trial"]["reached"] == ["started", "first_update"]
    assert ours["Paying Trial"]["reached"] == ["started", "first_update", "first_dpr", "converted"]
    assert Decimal(ours["Paying Trial"]["cost_inr"]) == Decimal("0.5000")
    assert Decimal(ours["Active Trial"]["cost_inr"]) == Decimal("0.2500")
    assert ours["Active Trial"]["hours_to_first_update"] == 25.0
    steps = {s["key"]: s for s in funnel["steps"]}
    assert steps["started"]["count"] >= 3 and steps["converted"]["count"] >= 1


def test_funnel_percentages_and_cost_per_trial() -> None:
    from types import SimpleNamespace

    from mesiri.application.organizations.trials_funnel import build_funnel

    def company(i, update=None, dpr=None, converted=None, status="trial"):
        return SimpleNamespace(
            id=i, name=f"T{i}", signup_source="web", effective_status=status,
            trial_started_at=_utc(18, 4), trial_ends_at=None, converted_at=converted,
            setup=SimpleNamespace(first_update_at=update, first_dpr_sent_at=dpr),
        )

    trials = [
        company(1),
        company(2, update=_utc(18, 6)),
        company(3, update=_utc(18, 6), dpr=_utc(18, 15), converted=_utc(19, 4), status="active"),
        company(4, update=_utc(18, 6), dpr=_utc(18, 15)),
    ]
    funnel = build_funnel(trials, {3: {"total_cost_inr": "3.00"}, 4: {"total_cost_inr": "1.00", "unpriced": 2}})

    assert [(s["key"], s["count"], s["percent"]) for s in funnel["steps"]] == [
        ("started", 4, 100), ("first_update", 3, 75), ("first_dpr", 2, 50), ("converted", 1, 25),
    ]
    assert funnel["still_on_trial"] == 3
    assert funnel["cost"] == {
        "total_inr": "4.00", "per_trial_inr": "1.00", "per_conversion_inr": "4.00", "unpriced": 2,
    }
    assert build_funnel([], {})["cost"]["per_trial_inr"] is None
