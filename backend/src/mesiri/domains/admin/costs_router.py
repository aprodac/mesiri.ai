"""What Mesiri costs to run, and what trials turn into, for the control
panel (SA-05, SS-11).

Reads the per-call cost rows BE-25 records (`provider_executions`, metered):
totals, per day and per company for a date range, and for one company, each
message it sent with the AI cost of handling it, and each WhatsApp message
sent to its people. And the trials funnel: of the trials started in a period,
how many reached a first update, a first DPR and conversion, and what each
cost while on trial. Read-only.

One router, mounted by both apps (backend http/app.py and the assistant's
runtime/lifecycle.py), like the branding router. Gated by
require_platform_admin: costs are across every company.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.application.organizations.trials_funnel import trials_funnel
from mesiri.domains.shared.auth import require_platform_admin
from mesiri.infrastructure.postgres.dependency import get_db_conn
from mesiri.infrastructure.postgres.repositories.usage_costs import (
    PostgresUsageCostRepository,
)

router = APIRouter(prefix="/admin", tags=["admin"])

#: Days are Indian calendar days, the same as the cost rows' `day`.
_INDIA = ZoneInfo("Asia/Kolkata")
_MAX_DAYS = 366


def _start_of(day: dt.date) -> dt.datetime:
    return dt.datetime.combine(day, dt.time.min, tzinfo=_INDIA)


def _plain(row: dict[str, Any]) -> dict[str, Any]:
    """JSON-safe: money as strings (exact), ids and times as text."""
    out: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, uuid.UUID):
            out[key] = str(value)
        elif isinstance(value, dt.datetime | dt.date):
            out[key] = value.isoformat()
        elif key.endswith("_inr") and value is not None:
            out[key] = str(value)
        else:
            out[key] = value
    return out


@router.get("/costs")
async def get_costs(
    date_from: dt.date = Query(alias="from"),
    date_to: dt.date = Query(alias="to"),
    organization_id: uuid.UUID | None = None,
    _admin: dict = Depends(require_platform_admin),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Costs for [from, to] (Indian days, both included). Without a company:
    totals, per day, per company and per person across companies (SA-23,
    the most expensive 500). With one: totals and per day for it,
    plus its messages (`messages`: AI cost per message it sent), the
    WhatsApp messages sent to its people (`sent`), newest 200 of each, and
    what each person cost (`by_person`, SA-22)."""
    if date_to < date_from:
        raise HTTPException(status_code=422, detail="'to' is before 'from'")
    if (date_to - date_from).days >= _MAX_DAYS:
        raise HTTPException(status_code=422, detail=f"Pick at most {_MAX_DAYS} days")
    since, until = _start_of(date_from), _start_of(date_to + dt.timedelta(days=1))

    repo = PostgresUsageCostRepository(conn)
    scope = {"since": since, "until": until, "organization_id": organization_id}
    result: dict[str, Any] = {
        "from": date_from.isoformat(),
        "to": date_to.isoformat(),
        "organization_id": str(organization_id) if organization_id else None,
        "totals": _plain(await repo.cost_totals(**scope)),
        "by_day": [_plain(r) for r in await repo.costs_by_day(**scope)],
    }
    if organization_id is None:
        result["by_company"] = [
            _plain(r) for r in await repo.costs_by_company(since=since, until=until)
        ]
        result["by_person"] = [
            _plain(r)
            for r in await repo.costs_by_person(organization_id=None, since=since, until=until)
        ]
    else:
        result["messages"] = [
            _plain(r)
            for r in await repo.costs_by_inbound_message(
                organization_id=organization_id, since=since, until=until
            )
        ]
        result["sent"] = [
            _plain(r)
            for r in await repo.whatsapp_messages_sent(
                organization_id=organization_id, since=since, until=until
            )
        ]
        result["by_person"] = [
            _plain(r)
            for r in await repo.costs_by_person(
                organization_id=organization_id, since=since, until=until
            )
        ]
    return result


@router.get("/trials/funnel")
async def get_trials_funnel(
    date_from: dt.date = Query(alias="from"),
    date_to: dt.date = Query(alias="to"),
    _admin: dict = Depends(require_platform_admin),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Trials started on [from, to] (Indian days, both included): the funnel
    started -> first update -> first DPR -> converted, the cost per trial
    and per conversion, and each trial with its milestones and cost."""
    if date_to < date_from:
        raise HTTPException(status_code=422, detail="'to' is before 'from'")
    funnel = await trials_funnel(
        conn, since=_start_of(date_from), until=_start_of(date_to + dt.timedelta(days=1))
    )
    return {
        "from": date_from.isoformat(),
        "to": date_to.isoformat(),
        **funnel,
        "trials": [_plain(t) for t in funnel["trials"]],
    }
