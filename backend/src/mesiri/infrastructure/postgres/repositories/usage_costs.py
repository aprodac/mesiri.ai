"""PostgreSQL store for per-call costs (migration 0478, BE-25).

Cost rows live in `provider_executions` with `metered = true`: one per AI
provider response and one per outbound WhatsApp message (keyed by its wamid,
so Meta's status webhook can correct it). Takes an externally-supplied
connection and never commits.

Company attribution: a row carries `organization_id` when it was known at
write time; otherwise a row written while handling an inbound message is
attributed through `correlation_id` -> inbound_messages.organization_id.
`_ORG` below is that one rule, used by every read.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

import sqlalchemy as sa

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection

STAGE = "metered"
WHATSAPP = "whatsapp"


@dataclass(frozen=True, slots=True)
class CostRow:
    provider: str
    operation: str
    model: str | None = None
    correlation_id: str | None = None
    organization_id: uuid.UUID | None = None
    purpose: str | None = None
    latency_ms: float | None = None
    input_tokens: int | None = None
    cached_input_tokens: int | None = None
    audio_input_tokens: int | None = None
    output_tokens: int | None = None
    audio_seconds: float | None = None
    category: str | None = None
    billable: bool | None = None
    external_id: str | None = None
    recipient: str | None = None
    cost_native: Decimal | None = None
    cost_currency: str | None = None
    cost_inr: Decimal | None = None
    price_ref: str | None = None
    created_at: dt.datetime | None = None


@dataclass(frozen=True, slots=True)
class UsageSummary:
    ai_calls: int
    input_tokens: int
    output_tokens: int
    ai_cost_inr: Decimal
    whatsapp_messages: int
    whatsapp_cost_inr: Decimal

    @property
    def total_cost_inr(self) -> Decimal:
        return self.ai_cost_inr + self.whatsapp_cost_inr


_INSERT_COLUMNS = (
    "id, correlation_id, stage, provider, operation, model, latency_ms, succeeded, "
    "metered, organization_id, purpose, input_tokens, cached_input_tokens, "
    "audio_input_tokens, output_tokens, audio_seconds, category, billable, "
    "external_id, recipient, cost_native, cost_currency, cost_inr, price_ref, created_at"
)
_INSERT_VALUES = (
    ":id, :correlation_id, :stage, :provider, :operation, :model, :latency_ms, true, "
    "true, :organization_id, :purpose, :input_tokens, :cached_input_tokens, "
    ":audio_input_tokens, :output_tokens, :audio_seconds, :category, :billable, "
    ":external_id, :recipient, :cost_native, :cost_currency, :cost_inr, :price_ref, "
    "COALESCE(:created_at, now())"
)

# The company a cost row belongs to (see module docstring).
_ORG = (
    "COALESCE(pe.organization_id, "
    "(SELECT im.organization_id FROM inbound_messages im "
    " WHERE im.correlation_id = pe.correlation_id LIMIT 1))"
)


def _params(row: CostRow) -> dict[str, object]:
    return {
        "id": uuid.uuid4(),
        "stage": STAGE,
        **{name: getattr(row, name) for name in CostRow.__slots__},
    }


class PostgresUsageCostRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def insert(self, row: CostRow) -> None:
        """One AI call's cost row."""
        await self._conn.execute(
            sa.text(f"INSERT INTO provider_executions ({_INSERT_COLUMNS}) VALUES ({_INSERT_VALUES})"),
            _params(row),
        )

    async def record_whatsapp_sent(self, row: CostRow) -> None:
        """The send side of a WhatsApp message (our estimate). If Meta's
        status webhook got there first, its category/billable/cost stand and
        only the fields it couldn't know are filled in."""
        await self._conn.execute(
            sa.text(
                f"INSERT INTO provider_executions ({_INSERT_COLUMNS}) VALUES ({_INSERT_VALUES}) "
                "ON CONFLICT (external_id) WHERE external_id IS NOT NULL DO UPDATE SET "
                "correlation_id = COALESCE(provider_executions.correlation_id, "
                "EXCLUDED.correlation_id), "
                "organization_id = COALESCE(provider_executions.organization_id, "
                "EXCLUDED.organization_id), "
                "recipient = COALESCE(provider_executions.recipient, EXCLUDED.recipient), "
                "purpose = COALESCE(provider_executions.purpose, EXCLUDED.purpose), "
                "latency_ms = COALESCE(provider_executions.latency_ms, EXCLUDED.latency_ms), "
                "operation = EXCLUDED.operation, "
                "created_at = LEAST(provider_executions.created_at, EXCLUDED.created_at)"
            ),
            _params(row),
        )

    async def record_whatsapp_pricing(self, row: CostRow) -> None:
        """Meta's verdict on a message (status webhook `pricing`): category,
        billable and the cost they imply replace our estimate."""
        await self._conn.execute(
            sa.text(
                f"INSERT INTO provider_executions ({_INSERT_COLUMNS}) VALUES ({_INSERT_VALUES}) "
                "ON CONFLICT (external_id) WHERE external_id IS NOT NULL DO UPDATE SET "
                "category = EXCLUDED.category, billable = EXCLUDED.billable, "
                "cost_native = EXCLUDED.cost_native, cost_currency = EXCLUDED.cost_currency, "
                "cost_inr = EXCLUDED.cost_inr, price_ref = EXCLUDED.price_ref, "
                "recipient = COALESCE(provider_executions.recipient, EXCLUDED.recipient), "
                "organization_id = COALESCE(provider_executions.organization_id, "
                "EXCLUDED.organization_id)"
            ),
            _params(row),
        )

    async def organization_for_message(self, correlation_id: str) -> uuid.UUID | None:
        """The company an inbound message was resolved to, if it is known yet."""
        if not correlation_id:
            return None
        return (
            await self._conn.execute(
                sa.text(
                    "SELECT organization_id FROM inbound_messages "
                    "WHERE correlation_id = :cid AND organization_id IS NOT NULL LIMIT 1"
                ),
                {"cid": correlation_id},
            )
        ).scalar_one_or_none()

    async def organization_for_phone(self, digits: str) -> uuid.UUID | None:
        """The company of the user with this WhatsApp number (compared as
        digits; one number belongs to one user, BE-04)."""
        if not digits:
            return None
        return (
            await self._conn.execute(
                sa.text(
                    "SELECT organization_id FROM users "
                    "WHERE regexp_replace(whatsapp_number, '\\D', '', 'g') = :digits "
                    "AND organization_id IS NOT NULL LIMIT 1"
                ),
                {"digits": digits},
            )
        ).scalar_one_or_none()

    async def usage_summary(
        self,
        organization_id: uuid.UUID,
        *,
        since: dt.datetime,
        until: dt.datetime | None = None,
    ) -> UsageSummary:
        """What one company used and cost in [since, until)."""
        return await self._summary(
            f"{_ORG} = :org", {"org": organization_id}, since=since, until=until
        )

    async def usage_for_phone(
        self, digits: str, *, since: dt.datetime, until: dt.datetime | None = None
    ) -> UsageSummary:
        """WhatsApp messages sent to one number, plus the AI calls made while
        handling that number's own messages -- for signups, which have no
        company yet (SS-09)."""
        return await self._summary(
            "(pe.recipient = :digits OR pe.correlation_id IN ("
            " SELECT im.correlation_id FROM inbound_messages im"
            " WHERE regexp_replace(im.sender_wa_id, '\\D', '', 'g') = :digits"
            " AND im.received_at >= :since))",
            {"digits": digits},
            since=since,
            until=until,
        )

    async def _summary(
        self,
        where: str,
        params: dict[str, object],
        *,
        since: dt.datetime,
        until: dt.datetime | None,
    ) -> UsageSummary:
        row = (
            await self._conn.execute(
                sa.text(
                    "SELECT "
                    "count(*) FILTER (WHERE pe.provider <> :wa) AS ai_calls, "
                    "COALESCE(sum(pe.input_tokens) FILTER (WHERE pe.provider <> :wa), 0) "
                    "AS input_tokens, "
                    "COALESCE(sum(pe.output_tokens) FILTER (WHERE pe.provider <> :wa), 0) "
                    "AS output_tokens, "
                    "COALESCE(sum(pe.cost_inr) FILTER (WHERE pe.provider <> :wa), 0) "
                    "AS ai_cost_inr, "
                    "count(*) FILTER (WHERE pe.provider = :wa) AS whatsapp_messages, "
                    "COALESCE(sum(pe.cost_inr) FILTER (WHERE pe.provider = :wa), 0) "
                    "AS whatsapp_cost_inr "
                    "FROM provider_executions pe "
                    "WHERE pe.metered AND pe.created_at >= :since "
                    "AND (CAST(:until AS timestamptz) IS NULL OR pe.created_at < :until) "
                    f"AND {where}"
                ),
                {**params, "wa": WHATSAPP, "since": since, "until": until},
            )
        ).mappings().one()
        return UsageSummary(
            ai_calls=int(row["ai_calls"]),
            input_tokens=int(row["input_tokens"]),
            output_tokens=int(row["output_tokens"]),
            ai_cost_inr=Decimal(row["ai_cost_inr"]),
            whatsapp_messages=int(row["whatsapp_messages"]),
            whatsapp_cost_inr=Decimal(row["whatsapp_cost_inr"]),
        )
