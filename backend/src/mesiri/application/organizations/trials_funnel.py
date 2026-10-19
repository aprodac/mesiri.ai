"""The trials funnel for the control panel (SS-11).

Of the trials started in a period: how many sent a first update, sent a
first DPR, and converted to a paying company, and what each cost while on
trial (AI and WhatsApp, BE-25). Built on the companies overview (SA-02), the
one read that already knows each company's trial start, first update, first
DPR sent and conversion, so the funnel and the companies list cannot
disagree about a company.

A trial deleted after it ended is not in `organizations` any more, so it is
not counted here (its costs stay in the cost rows, under no company name).
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.application.organizations.companies_overview import CompanyOverview, list_companies
from mesiri.domains.organizations import lifecycle
from mesiri.infrastructure.postgres.repositories.usage_costs import PostgresUsageCostRepository

#: The funnel's steps, in order; each counts trials that reached it.
STEPS = (
    ("started", "Started a trial"),
    ("first_update", "Sent a first update"),
    ("first_dpr", "First DPR sent"),
    ("converted", "Converted"),
)


def _reached(company: CompanyOverview) -> dict[str, bool]:
    return {
        "started": True,
        "first_update": company.setup.first_update_at is not None,
        "first_dpr": company.setup.first_dpr_sent_at is not None,
        "converted": company.converted_at is not None,
    }


def _hours(start: dt.datetime | None, end: dt.datetime | None) -> float | None:
    if start is None or end is None:
        return None
    return round((end - start).total_seconds() / 3600, 1)


def build_funnel(
    trials: list[CompanyOverview], costs: dict[Any, dict[str, Any]]
) -> dict[str, Any]:
    """The funnel from trials already chosen and their costs. Pure, so it is
    testable without a database."""
    counts = {key: 0 for key, _ in STEPS}
    rows = []
    total = Decimal("0")
    unpriced = 0
    for company in trials:
        reached = _reached(company)
        for key, done in reached.items():
            counts[key] += int(done)
        cost = costs.get(company.id) or {}
        cost_inr = Decimal(str(cost.get("total_cost_inr") or 0))
        total += cost_inr
        unpriced += int(cost.get("unpriced") or 0)
        rows.append(
            {
                "organization_id": str(company.id),
                "name": company.name,
                "signup_source": company.signup_source,
                "effective_status": company.effective_status,
                "trial_started_at": company.trial_started_at,
                "trial_ends_at": company.trial_ends_at,
                "first_update_at": company.setup.first_update_at,
                "first_dpr_sent_at": company.setup.first_dpr_sent_at,
                "converted_at": company.converted_at,
                "hours_to_first_update": _hours(
                    company.trial_started_at, company.setup.first_update_at
                ),
                "reached": [key for key, _ in STEPS if reached[key]],
                "ai_calls": int(cost.get("ai_calls") or 0),
                "whatsapp_messages": int(cost.get("whatsapp_messages") or 0),
                "cost_inr": str(cost_inr),
            }
        )
    started = counts["started"]
    return {
        "steps": [
            {
                "key": key,
                "label": label,
                "count": counts[key],
                "percent": round(100 * counts[key] / started) if started else None,
            }
            for key, label in STEPS
        ],
        "still_on_trial": sum(1 for c in trials if c.effective_status == lifecycle.TRIAL),
        "cost": {
            "total_inr": str(total),
            "per_trial_inr": str((total / started).quantize(Decimal("0.01"))) if started else None,
            "per_conversion_inr": (
                str((total / counts["converted"]).quantize(Decimal("0.01")))
                if counts["converted"]
                else None
            ),
            "unpriced": unpriced,
        },
        "trials": rows,
    }


async def trials_funnel(
    conn: AsyncConnection, *, since: dt.datetime, until: dt.datetime
) -> dict[str, Any]:
    """Trials started in [since, until), newest first, as a funnel."""
    trials = [
        company
        for company in await list_companies(conn)
        if company.trial_started_at is not None and since <= company.trial_started_at < until
    ]
    trials.sort(key=lambda c: c.trial_started_at, reverse=True)
    costs = await PostgresUsageCostRepository(conn).trial_costs([c.id for c in trials])
    return build_funnel(trials, costs)
