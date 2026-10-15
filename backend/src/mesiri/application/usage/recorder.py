"""Turn usage reports into priced, company-tagged cost rows (BE-25).

    recorder = install_usage_recorder(db)   # once, at startup

After that, every AI provider response (reported by the adapters through
mesiri_ai.usage) and every WhatsApp message the assistant sends or hears
pricing back for (`record_whatsapp_sent` / `record_whatsapp_pricing`) is
written as one `provider_executions` row with `metered = true`.

Each write runs on its own short transaction, after the call it describes,
and a failure is logged and dropped: cost tracking must never slow down or
break a reply. The INR value is fixed when the row is written, at the
`usage_pricing.usd_inr` platform setting of that moment.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
import time
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from mesiri.domains.organizations.platform_settings import USAGE_PRICING
from mesiri.domains.usage import prices
from mesiri.infrastructure.postgres.repositories.platform_settings import (
    PostgresPlatformSettingsRepository,
)
from mesiri.infrastructure.postgres.repositories.usage_costs import (
    WHATSAPP,
    CostRow,
    PostgresUsageCostRepository,
)

if TYPE_CHECKING:
    from mesiri_ai.usage import ProviderUsage

_log = logging.getLogger(__name__)

# The exchange rate is read at most this often (it changes by hand, rarely).
_FX_TTL_SECONDS = 300.0


def _digits(phone: str | None) -> str | None:
    digits = re.sub(r"\D", "", phone or "")
    return digits or None


def _uuid(value: Any) -> uuid.UUID | None:
    if value is None:
        return None
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except ValueError:
        return None


class UsageRecorder:
    def __init__(self, db: Any, *, now: Any = None) -> None:
        # `db` is a PostgresDatabase (anything with `transaction()`).
        self._db = db
        self._now = now or (lambda: dt.datetime.now(dt.UTC))
        self._fx: tuple[float, Decimal] | None = None

    async def _usd_inr(self, conn: Any) -> Decimal:
        cached = self._fx
        if cached is not None and time.monotonic() - cached[0] < _FX_TTL_SECONDS:
            return cached[1]
        policy = await PostgresPlatformSettingsRepository(conn).get(USAGE_PRICING)
        rate = Decimal(str(policy["usd_inr"]))
        self._fx = (time.monotonic(), rate)
        return rate

    async def record_ai(self, usage: ProviderUsage) -> None:
        """One AI provider response. Never raises."""
        try:
            at = self._now()
            cost = prices.ai_cost(
                provider=usage.provider,
                model=usage.model,
                at=at,
                input_tokens=usage.input_tokens,
                cached_input_tokens=usage.cached_input_tokens,
                audio_input_tokens=usage.audio_input_tokens,
                output_tokens=usage.output_tokens,
                audio_seconds=usage.audio_seconds,
            )
            async with self._db.transaction() as conn:
                repo = PostgresUsageCostRepository(conn)
                org = _uuid(usage.organization_id)
                if org is None and usage.correlation_id:
                    org = await repo.organization_for_message(usage.correlation_id)
                await repo.insert(
                    CostRow(
                        provider=usage.provider,
                        operation=usage.operation,
                        model=usage.model,
                        correlation_id=usage.correlation_id,
                        organization_id=org,
                        purpose=usage.purpose,
                        latency_ms=usage.latency_ms,
                        input_tokens=usage.input_tokens,
                        cached_input_tokens=usage.cached_input_tokens,
                        audio_input_tokens=usage.audio_input_tokens,
                        output_tokens=usage.output_tokens,
                        audio_seconds=usage.audio_seconds,
                        **await self._priced(conn, cost),
                        created_at=at,
                    )
                )
        except Exception:  # noqa: BLE001
            _log.exception(
                "usage.record_ai_failed provider=%s operation=%s",
                usage.provider,
                usage.operation,
            )

    async def record_whatsapp_sent(
        self,
        *,
        wamid: str,
        recipient: str,
        category: str,
        operation: str = "send",
        correlation_id: str | None = None,
    ) -> None:
        """One message the assistant sent. `category` is our estimate:
        the template's category, or "service" for a normal reply. Never raises."""
        try:
            at = self._now()
            digits = _digits(recipient)
            cost = prices.whatsapp_cost(category)
            async with self._db.transaction() as conn:
                repo = PostgresUsageCostRepository(conn)
                await repo.record_whatsapp_sent(
                    CostRow(
                        provider=WHATSAPP,
                        operation=operation,
                        correlation_id=correlation_id,
                        organization_id=await repo.organization_for_phone(digits or ""),
                        category=category.lower(),
                        external_id=wamid,
                        recipient=digits,
                        **await self._priced(conn, cost),
                        created_at=at,
                    )
                )
        except Exception:  # noqa: BLE001
            _log.exception("usage.record_whatsapp_sent_failed wamid=%s", wamid)

    async def record_whatsapp_pricing(
        self,
        *,
        wamid: str,
        recipient: str | None,
        category: str | None,
        billable: bool | None,
    ) -> None:
        """Meta's pricing for a message, from its status webhook: replaces
        our estimate (and is how the free tier shows up). Never raises."""
        try:
            at = self._now()
            digits = _digits(recipient)
            category = (category or "").lower() or None
            cost = prices.whatsapp_cost(category, billable=billable)
            async with self._db.transaction() as conn:
                repo = PostgresUsageCostRepository(conn)
                await repo.record_whatsapp_pricing(
                    CostRow(
                        provider=WHATSAPP,
                        operation="send",
                        organization_id=await repo.organization_for_phone(digits or ""),
                        category=category,
                        billable=billable,
                        external_id=wamid,
                        recipient=digits,
                        **await self._priced(conn, cost),
                        created_at=at,
                    )
                )
        except Exception:  # noqa: BLE001
            _log.exception("usage.record_whatsapp_pricing_failed wamid=%s", wamid)

    async def _priced(self, conn: Any, cost: prices.Cost) -> dict[str, Any]:
        if not cost.priced:
            # Unknown model/category: say "no price" rather than "free".
            return {"cost_currency": cost.currency, "price_ref": prices.PRICE_REF}
        return {
            "cost_native": cost.amount,
            "cost_currency": cost.currency,
            "cost_inr": prices.to_inr(cost, await self._usd_inr(conn)),
            "price_ref": prices.PRICE_REF,
        }


def install_usage_recorder(db: Any) -> UsageRecorder:
    """Create the recorder and route every AI usage report to it."""
    from mesiri_ai import usage

    recorder = UsageRecorder(db)
    usage.set_usage_sink(recorder.record_ai)
    return recorder
