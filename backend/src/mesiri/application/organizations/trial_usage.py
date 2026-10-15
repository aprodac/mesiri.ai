"""Is a trial company over today's usage caps? (SS-09)

    verdict = await TrialUsageGuard(db).check(organization_id)
    if verdict.over_cap: reply guardrails.TRIAL_LIMIT_MESSAGE and stop

Only companies on a `trial` are capped; an active (paying) company always
passes. Today's usage is BE-25's cost rows since midnight India time, and
the caps are the `trial_guardrails` platform setting. The answer is cached
for a minute per company, so asking on every inbound message costs at most
one query a minute per company. Fails open: if the check itself fails, the
message goes through (a cost guard must never take the assistant down).
"""

from __future__ import annotations

import datetime as dt
import logging
import time
import uuid
from typing import Any

import sqlalchemy as sa

from mesiri.domains.organizations import guardrails, lifecycle
from mesiri.domains.organizations.platform_settings import TRIAL_GUARDRAILS
from mesiri.infrastructure.postgres.repositories.platform_settings import (
    PostgresPlatformSettingsRepository,
)
from mesiri.infrastructure.postgres.repositories.usage_costs import (
    PostgresUsageCostRepository,
)

_log = logging.getLogger(__name__)

_CACHE_SECONDS = 60.0


async def check_trial_usage(
    conn: Any, organization_id: uuid.UUID, *, now: dt.datetime | None = None
) -> guardrails.TrialUsageVerdict:
    """The verdict for one company, uncached, in the caller's connection."""
    now = now or dt.datetime.now(dt.UTC)
    status = (
        await conn.execute(
            sa.text("SELECT status FROM organizations WHERE id = :id"), {"id": organization_id}
        )
    ).scalar_one_or_none()
    if lifecycle.normalize(status) != lifecycle.TRIAL:
        return guardrails.NOT_OVER
    rules = await PostgresPlatformSettingsRepository(conn).get(TRIAL_GUARDRAILS)
    usage = await PostgresUsageCostRepository(conn).usage_summary(
        organization_id, since=guardrails.cap_day_start(now)
    )
    return guardrails.evaluate_trial_usage(
        ai_cost_inr=usage.ai_cost_inr,
        whatsapp_messages=usage.whatsapp_messages,
        rules=rules,
    )


class TrialUsageGuard:
    def __init__(self, db: Any, *, clock: Any = time.monotonic) -> None:
        # `db` is a PostgresDatabase (anything with `transaction()`).
        self._db = db
        self._clock = clock
        self._cache: dict[uuid.UUID, tuple[float, guardrails.TrialUsageVerdict]] = {}

    async def check(self, organization_id: uuid.UUID | str) -> guardrails.TrialUsageVerdict:
        try:
            org = (
                organization_id
                if isinstance(organization_id, uuid.UUID)
                else uuid.UUID(str(organization_id))
            )
            cached = self._cache.get(org)
            if cached is not None and self._clock() - cached[0] < _CACHE_SECONDS:
                return cached[1]
            async with self._db.transaction() as conn:
                verdict = await check_trial_usage(conn, org)
            self._cache[org] = (self._clock(), verdict)
            if verdict.over_cap:
                _log.warning("trial.over_cap org=%s reason=%s", org, verdict.reason)
            return verdict
        except Exception:  # noqa: BLE001
            _log.exception("trial.usage_check_failed org=%s", organization_id)
            return guardrails.NOT_OVER
