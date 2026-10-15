"""BE-25: cost rows against a real Postgres (integration).

The recorder normally opens its own transaction per row; here it is handed
the test's connection, so everything is rolled back at the end.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text

from mesiri.application.organizations.create_company import NewCompany, create_company
from mesiri.application.usage.recorder import UsageRecorder
from mesiri.infrastructure.postgres.repositories.usage_costs import PostgresUsageCostRepository
from mesiri_ai.usage import ProviderUsage

pytestmark = pytest.mark.integration

# Thursday, DeepSeek off-peak.
_NOW = dt.datetime(2026, 10, 15, 12, 0, tzinfo=dt.UTC)


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


class _SameConnection:
    def __init__(self, conn) -> None:
        self._conn = conn

    @contextlib.asynccontextmanager
    async def transaction(self):
        yield self._conn


@pytest.fixture
def recorder(conn) -> UsageRecorder:
    return UsageRecorder(_SameConnection(conn), now=lambda: _NOW)


async def _company(conn) -> tuple[uuid.UUID, str]:
    phone = "9" + str(uuid.uuid4().int)[:9]
    created = await create_company(
        conn, NewCompany(name="Cost Co", owner_name="C", owner_phone=phone), now=_NOW
    )
    return created.organization_id, created.owner_whatsapp_number


async def _inbound(conn, *, correlation_id: str, sender: str, org: uuid.UUID | None) -> None:
    await conn.execute(
        text(
            "INSERT INTO inbound_messages (id, correlation_id, sender_wa_id, message_type, "
            "raw_payload, dedup_key, organization_id, received_at) VALUES (:id, :cid, :s, "
            "'text', '{}', :cid, :org, :at)"
        ),
        {"id": uuid.uuid4(), "cid": correlation_id, "s": sender, "org": org, "at": _NOW},
    )


async def _row(conn, where: str, **params):
    return (
        await conn.execute(text(f"SELECT * FROM provider_executions WHERE {where}"), params)
    ).mappings().one()


async def test_ai_call_is_priced_and_attributed_through_its_message(conn, recorder) -> None:
    org, phone = await _company(conn)
    cid = f"cor_{uuid.uuid4().hex}"
    await _inbound(conn, correlation_id=cid, sender=phone, org=org)

    await recorder.record_ai(
        ProviderUsage(
            provider="deepseek",
            operation="extract",
            model="deepseek-flash",
            correlation_id=cid,
            input_tokens=1_000_000,
            cached_input_tokens=0,
            output_tokens=1_000_000,
        )
    )

    row = await _row(conn, "correlation_id = :cid AND metered", cid=cid)
    assert row["organization_id"] == org
    assert row["stage"] == "metered"
    # Off-peak: (0.30 + 1.20) / 2 = 0.75 USD, at the default 96.29.
    assert row["cost_native"] == Decimal("0.75")
    assert row["cost_currency"] == "USD"
    assert row["cost_inr"] == Decimal("0.75") * Decimal("96.29")
    assert row["price_ref"] == "2026-10-15"


async def test_unknown_model_is_stored_without_a_cost(conn, recorder) -> None:
    await recorder.record_ai(
        ProviderUsage(provider="gemini", operation="extract", model="mystery", input_tokens=5)
    )
    row = await _row(conn, "model = 'mystery' AND metered")
    assert row["cost_inr"] is None
    assert row["input_tokens"] == 5


@pytest.mark.parametrize("webhook_first", [False, True])
async def test_whatsapp_send_and_meta_pricing_merge(conn, recorder, webhook_first) -> None:
    org, phone = await _company(conn)
    wamid = f"wamid.{uuid.uuid4().hex}"

    async def sent():
        await recorder.record_whatsapp_sent(
            wamid=wamid, recipient=f"+{phone}", category="service", operation="send_text"
        )

    async def priced():
        # Inside Meta's monthly free tier.
        await recorder.record_whatsapp_pricing(
            wamid=wamid, recipient=phone, category="service", billable=False
        )

    for step in (priced, sent) if webhook_first else (sent, priced):
        await step()

    row = await _row(conn, "external_id = :w", w=wamid)
    assert row["organization_id"] == org
    assert row["recipient"] == phone
    assert row["operation"] == "send_text"
    assert row["billable"] is False
    assert row["cost_inr"] == 0


async def test_template_estimate_stands_until_meta_says_otherwise(conn, recorder) -> None:
    _, phone = await _company(conn)
    wamid = f"wamid.{uuid.uuid4().hex}"
    await recorder.record_whatsapp_sent(wamid=wamid, recipient=phone, category="UTILITY")
    row = await _row(conn, "external_id = :w", w=wamid)
    assert (row["category"], row["billable"], row["cost_inr"]) == (
        "utility",
        None,
        Decimal("0.1150"),
    )


async def test_usage_summary_and_per_phone(conn, recorder) -> None:
    org, phone = await _company(conn)
    cid = f"cor_{uuid.uuid4().hex}"
    await _inbound(conn, correlation_id=cid, sender=phone, org=None)  # org not known yet
    await recorder.record_ai(
        ProviderUsage(
            provider="gemini",
            operation="extract",
            model="gemini-2.5-flash",
            correlation_id=cid,
            input_tokens=1000,
            output_tokens=100,
        )
    )
    # The message is resolved to the company afterwards: the read still finds it.
    await conn.execute(
        text("UPDATE inbound_messages SET organization_id = :o WHERE correlation_id = :c"),
        {"o": org, "c": cid},
    )
    await recorder.record_whatsapp_sent(
        wamid=f"wamid.{uuid.uuid4().hex}", recipient=phone, category="utility"
    )

    repo = PostgresUsageCostRepository(conn)
    summary = await repo.usage_summary(org, since=_NOW - dt.timedelta(days=1))
    assert (summary.ai_calls, summary.input_tokens, summary.output_tokens) == (1, 1000, 100)
    assert summary.whatsapp_messages == 1
    assert summary.whatsapp_cost_inr == Decimal("0.1150")
    # (1000 * 0.30 + 100 * 2.50) / 1M USD
    assert summary.ai_cost_inr == Decimal("0.00055") * Decimal("96.29")
    assert summary.total_cost_inr == summary.ai_cost_inr + summary.whatsapp_cost_inr

    by_phone = await repo.usage_for_phone(phone, since=_NOW - dt.timedelta(days=1))
    assert (by_phone.ai_calls, by_phone.whatsapp_messages) == (1, 1)

    later = await repo.usage_summary(org, since=_NOW + dt.timedelta(minutes=1))
    assert later.ai_calls == later.whatsapp_messages == 0
