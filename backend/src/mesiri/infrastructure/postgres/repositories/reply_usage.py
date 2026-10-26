"""Read-only: how fast each WhatsApp message was answered and what AI it
used, for the control panel's Reply Insights page (SA-17).

Joins two things that are already recorded, adding no table:
- reply time: `inbound_messages.received_at -> processed_at`, the same
  number the Performance page summarises. A held photo's time includes how
  long the sender took to answer "what is this photo for?".
- AI usage: the metered `provider_executions` rows (BE-25, migration 0478),
  one per AI provider response, tied to a message by `correlation_id`:
  tokens (`input_tokens` includes its `cached_input_tokens` part), latency
  and cost in INR. WhatsApp send rows are left out (they carry no tokens and
  no message id).

Every read is scoped by `_SCOPE`: messages received in [since, until),
optionally for one company and one message type. Takes an externally
supplied connection and never commits.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa

from mesiri.infrastructure.postgres.repositories.usage_costs import WHATSAPP

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection

#: Reply-time bands shown as the speed distribution, in ms (upper bounds).
BANDS_MS = (5_000, 15_000, 30_000, 60_000)

#: How the message feed can be ordered.
SORTS = {
    "newest": "m.received_at DESC",
    "slowest": "m.reply_ms DESC NULLS LAST, m.received_at DESC",
    "tokens": "total_tokens DESC NULLS LAST, m.received_at DESC",
    "cost": "u.ai_cost_inr DESC NULLS LAST, m.received_at DESC",
}

# The messages in scope, with their reply time.
_SCOPE = (
    "m AS ("
    " SELECT im.id, im.correlation_id, im.received_at, im.processed_at,"
    "  im.message_type, im.processing_status, im.organization_id, im.sender_wa_id,"
    "  EXTRACT(EPOCH FROM (im.processed_at - im.received_at)) * 1000 AS reply_ms"
    " FROM inbound_messages im"
    " WHERE im.received_at >= :since AND im.received_at < :until"
    "  AND (CAST(:org AS uuid) IS NULL OR im.organization_id = CAST(:org AS uuid))"
    "  AND (CAST(:mtype AS text) IS NULL OR im.message_type = CAST(:mtype AS text))"
    ")"
)

# The AI calls made for messages in scope, as rows.
_CALLS = (
    "c AS ("
    " SELECT pe.* FROM provider_executions pe"
    " WHERE pe.metered AND pe.provider <> :wa"
    "  AND pe.correlation_id IN (SELECT correlation_id FROM m)"
    ")"
)

# The same, summed per message.
_USAGE = (
    "u AS ("
    " SELECT c.correlation_id, count(*) AS ai_calls,"
    "  sum(c.latency_ms) AS ai_ms,"
    "  COALESCE(sum(c.input_tokens), 0) AS input_tokens,"
    "  COALESCE(sum(c.cached_input_tokens), 0) AS cached_input_tokens,"
    "  COALESCE(sum(c.output_tokens), 0) AS output_tokens,"
    "  COALESCE(sum(c.cost_inr), 0) AS ai_cost_inr,"
    "  count(*) FILTER (WHERE c.cost_inr IS NULL) AS unpriced"
    " FROM c GROUP BY c.correlation_id"
    ")"
)

_WITH = f"WITH {_SCOPE}, {_CALLS}, {_USAGE} "

_TOKEN_SUMS = (
    "COALESCE(sum(u.ai_calls), 0) AS ai_calls, "
    "COALESCE(sum(u.input_tokens), 0) AS input_tokens, "
    "COALESCE(sum(u.cached_input_tokens), 0) AS cached_input_tokens, "
    "COALESCE(sum(u.output_tokens), 0) AS output_tokens, "
    "COALESCE(sum(u.ai_cost_inr), 0) AS ai_cost_inr, "
    "COALESCE(sum(u.unpriced), 0) AS unpriced "
)


def _pct(fraction: float, column: str) -> str:
    return f"percentile_cont({fraction}) WITHIN GROUP (ORDER BY {column})"


def _bands() -> str:
    """`band_0 .. band_N`: replied messages per reply-time band."""
    parts, lower = [], None
    for i, upper in enumerate(BANDS_MS):
        cond = f"m.reply_ms < {upper}" + (f" AND m.reply_ms >= {lower}" if lower else "")
        parts.append(f"count(*) FILTER (WHERE {cond}) AS band_{i}")
        lower = upper
    parts.append(f"count(*) FILTER (WHERE m.reply_ms >= {lower}) AS band_{len(BANDS_MS)}")
    return ", ".join(parts) + ", "


class PostgresReplyUsageRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    @staticmethod
    def _params(
        since: dt.datetime,
        until: dt.datetime,
        organization_id: uuid.UUID | None,
        message_type: str | None,
        **extra: Any,
    ) -> dict[str, Any]:
        return {
            "since": since,
            "until": until,
            "org": organization_id,
            "mtype": message_type,
            "wa": WHATSAPP,
            **extra,
        }

    async def _all(self, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        rows = (await self._conn.execute(sa.text(sql), params)).mappings().all()
        return [dict(r) for r in rows]

    async def summary(
        self,
        *,
        since: dt.datetime,
        until: dt.datetime,
        organization_id: uuid.UUID | None = None,
        message_type: str | None = None,
    ) -> dict[str, Any]:
        """Messages in scope: how many were answered, reply time (avg,
        p50/p90/p95, max), the reply-time bands, how many were answered with
        no AI at all (`no_ai`) and how many used it (`with_ai`),
        and the tokens and AI cost of handling them."""
        sql = (
            _WITH + "SELECT count(*) AS messages, "
            "count(m.reply_ms) AS replied, "
            "count(*) FILTER (WHERE m.processing_status = 'failed') AS failed, "
            "count(*) FILTER (WHERE m.reply_ms IS NOT NULL AND u.ai_calls IS NULL) AS no_ai, "
            "count(u.correlation_id) AS with_ai, "
            "avg(m.reply_ms) AS avg_ms, "
            f"{_pct(0.5, 'm.reply_ms')} AS p50_ms, "
            f"{_pct(0.9, 'm.reply_ms')} AS p90_ms, "
            f"{_pct(0.95, 'm.reply_ms')} AS p95_ms, "
            "max(m.reply_ms) AS max_ms, " + _bands() + _TOKEN_SUMS + "FROM m "
            "LEFT JOIN u ON u.correlation_id = m.correlation_id"
        )
        rows = await self._all(sql, self._params(since, until, organization_id, message_type))
        return rows[0]

    async def timeline(
        self,
        *,
        since: dt.datetime,
        until: dt.datetime,
        step: dt.timedelta,
        organization_id: uuid.UUID | None = None,
        message_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Per time bucket of `step` (Indian time, empty buckets included,
        oldest first): messages, reply time p50/p95, tokens and AI cost."""
        bucket = (
            "date_bin(CAST(:step AS interval), ({col}) AT TIME ZONE 'Asia/Kolkata', "
            "TIMESTAMP '2000-01-01')"
        )
        first = bucket.format(col="CAST(:since AS timestamptz)")
        last = bucket.format(col="CAST(:until AS timestamptz) - interval '1 microsecond'")
        sql = (
            _WITH + ", agg AS ("
            f" SELECT {bucket.format(col='m.received_at')} AS bucket, count(*) AS messages,"
            f"  {_pct(0.5, 'm.reply_ms')} AS p50_ms, {_pct(0.95, 'm.reply_ms')} AS p95_ms, "
            + _TOKEN_SUMS
            + " FROM m LEFT JOIN u ON u.correlation_id = m.correlation_id GROUP BY 1"
            ") "
            "SELECT b.bucket, COALESCE(agg.messages, 0) AS messages, agg.p50_ms, agg.p95_ms,"
            " COALESCE(agg.input_tokens, 0) AS input_tokens,"
            " COALESCE(agg.cached_input_tokens, 0) AS cached_input_tokens,"
            " COALESCE(agg.output_tokens, 0) AS output_tokens,"
            " COALESCE(agg.ai_cost_inr, 0) AS ai_cost_inr "
            f"FROM generate_series({first}, {last}, CAST(:step AS interval)) AS b(bucket) "
            "LEFT JOIN agg ON agg.bucket = b.bucket ORDER BY b.bucket"
        )
        return await self._all(
            sql, self._params(since, until, organization_id, message_type, step=step)
        )

    async def by_model(
        self,
        *,
        since: dt.datetime,
        until: dt.datetime,
        organization_id: uuid.UUID | None = None,
        message_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """The AI calls for messages in scope per provider and model, most
        tokens first: calls, latency (avg, p95), tokens and cost."""
        sql = (
            _WITH + "SELECT c.provider, c.model, count(*) AS calls, "
            "avg(c.latency_ms) AS avg_ms, "
            f"{_pct(0.95, 'c.latency_ms')} AS p95_ms, "
            "COALESCE(sum(c.input_tokens), 0) AS input_tokens, "
            "COALESCE(sum(c.cached_input_tokens), 0) AS cached_input_tokens, "
            "COALESCE(sum(c.output_tokens), 0) AS output_tokens, "
            "COALESCE(sum(c.cost_inr), 0) AS ai_cost_inr, "
            "count(*) FILTER (WHERE c.cost_inr IS NULL) AS unpriced "
            "FROM c GROUP BY c.provider, c.model "
            "ORDER BY COALESCE(sum(c.input_tokens), 0) + COALESCE(sum(c.output_tokens), 0) DESC, "
            "calls DESC"
        )
        return await self._all(sql, self._params(since, until, organization_id, message_type))

    async def by_step(
        self,
        *,
        since: dt.datetime,
        until: dt.datetime,
        organization_id: uuid.UUID | None = None,
        message_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """The same per step of handling a message (the call's purpose,
        else its operation): where the tokens go."""
        sql = (
            _WITH + "SELECT COALESCE(c.purpose, c.operation) AS step, count(*) AS calls, "
            "avg(c.latency_ms) AS avg_ms, "
            "COALESCE(sum(c.input_tokens), 0) AS input_tokens, "
            "COALESCE(sum(c.output_tokens), 0) AS output_tokens, "
            "COALESCE(sum(c.cost_inr), 0) AS ai_cost_inr "
            "FROM c GROUP BY 1 "
            "ORDER BY COALESCE(sum(c.input_tokens), 0) + COALESCE(sum(c.output_tokens), 0) DESC, "
            "calls DESC"
        )
        return await self._all(sql, self._params(since, until, organization_id, message_type))

    async def messages(
        self,
        *,
        since: dt.datetime,
        until: dt.datetime,
        organization_id: uuid.UUID | None = None,
        message_type: str | None = None,
        sort: str = "newest",
        slower_than_ms: int | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Each message in scope with its reply time and AI usage, ordered by
        `sort` (a key of SORTS). `total` on every row is the count before
        the page was cut. The sender's name is matched by WhatsApp number
        within the message's company, as the Logs screen does."""
        sql = (
            _WITH + "SELECT m.correlation_id, m.received_at, m.processed_at, m.reply_ms, "
            "m.message_type, m.processing_status, m.organization_id, "
            "o.name AS organization_name, m.sender_wa_id, su.full_name AS sender_name, "
            "left(im.body_text, 200) AS text, left(im.assistant_reply, 400) AS reply, "
            "COALESCE(u.ai_calls, 0) AS ai_calls, u.ai_ms, "
            "COALESCE(u.input_tokens, 0) AS input_tokens, "
            "COALESCE(u.cached_input_tokens, 0) AS cached_input_tokens, "
            "COALESCE(u.output_tokens, 0) AS output_tokens, "
            "u.input_tokens + u.output_tokens AS total_tokens, "
            "COALESCE(u.ai_cost_inr, 0) AS ai_cost_inr, COALESCE(u.unpriced, 0) AS unpriced, "
            "count(*) OVER () AS total "
            "FROM m JOIN inbound_messages im ON im.id = m.id "
            "LEFT JOIN u ON u.correlation_id = m.correlation_id "
            "LEFT JOIN organizations o ON o.id = m.organization_id "
            "LEFT JOIN LATERAL (SELECT us.full_name FROM users us "
            " WHERE us.organization_id = m.organization_id "
            " AND regexp_replace(us.whatsapp_number, '\\D', '', 'g') "
            " = regexp_replace(m.sender_wa_id, '\\D', '', 'g') LIMIT 1) su ON true "
            "WHERE (CAST(:slower AS float) IS NULL OR m.reply_ms >= CAST(:slower AS float)) "
            f"ORDER BY {SORTS[sort]} LIMIT :limit OFFSET :offset"
        )
        return await self._all(
            sql,
            self._params(
                since,
                until,
                organization_id,
                message_type,
                slower=slower_than_ms,
                limit=limit,
                offset=offset,
            ),
        )

    async def message_calls(self, correlation_id: str) -> list[dict[str, Any]]:
        """The AI calls made for one message, in the order they were made."""
        return await self._all(
            "SELECT pe.created_at, pe.provider, pe.model, pe.operation, pe.purpose, "
            "pe.latency_ms, pe.input_tokens, pe.cached_input_tokens, pe.audio_input_tokens, "
            "pe.output_tokens, pe.cost_inr AS ai_cost_inr "
            "FROM provider_executions pe "
            "WHERE pe.correlation_id = :corr AND pe.metered AND pe.provider <> :wa "
            "ORDER BY pe.created_at",
            {"corr": correlation_id, "wa": WHATSAPP},
        )
