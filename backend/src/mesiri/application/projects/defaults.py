"""[259]: the report settings a new project starts with, in one place.

Before this, only sign-up set them (the company's zone, DPR on). A project made later, from the
dashboard or from WhatsApp, took the column defaults: UTC and no daily report, so it never got its
evening report and its times read in UTC (5 Nov: every one of the 8 projects created after sign-up in
production, all in Asia/Kolkata companies).

A new project now takes the company's own choice: the company's time zone; the daily report on when
any of its projects has it on (with that project's cut-off and send times), or when it has no project
yet (what sign-up gives); off only when every project it has is off. The old defaults (UTC, off) were
never anyone's choice, so they are not copied. Anything the caller sets explicitly still wins.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import sqlalchemy as sa

#: No company zone known (or not a real zone): the one every customer so far uses.
FALLBACK_ZONE = "Asia/Kolkata"
CUTOFF = "18:00"
SEND_DEADLINE = "21:00"

#: The company's newest project with the report on first; any project at all tells "has projects".
_REPORTING_PROJECT = sa.text(
    "SELECT reporting_timezone, auto_generate_dpr, reporting_cutoff_time, dpr_send_deadline "
    "FROM projects WHERE organization_id = :org AND status IS DISTINCT FROM 'archived' "
    "ORDER BY auto_generate_dpr DESC, created_at DESC LIMIT 1"
)
_COMPANY_ZONE = sa.text("SELECT timezone FROM organizations WHERE id = :org")


@dataclass(frozen=True)
class ReportSettings:
    reporting_timezone: str
    auto_generate_dpr: bool
    reporting_cutoff_time: str
    dpr_send_deadline: str


def _zone(value: Any) -> str | None:
    if not value:
        return None
    try:
        ZoneInfo(str(value))
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return None
    return str(value)


def _clock(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    return text[:5] if len(text) >= 5 and text[2] == ":" else fallback


async def new_project_settings(conn: Any, organization_id: Any) -> ReportSettings:
    """The company's report settings for a project it is creating now."""
    row = (await conn.execute(_REPORTING_PROJECT, {"org": organization_id})).mappings().first()
    company_zone = _zone((await conn.execute(_COMPANY_ZONE, {"org": organization_id})).scalar())
    if row is None:  # the company's first project: as sign-up sets it
        return ReportSettings(company_zone or FALLBACK_ZONE, True, CUTOFF, SEND_DEADLINE)
    reporting = bool(row["auto_generate_dpr"])
    zone = _zone(row["reporting_timezone"]) if reporting else None
    if zone in (None, "UTC"):  # UTC was the column default, never a choice
        zone = company_zone or zone
    return ReportSettings(
        reporting_timezone=zone or FALLBACK_ZONE,
        auto_generate_dpr=reporting,
        reporting_cutoff_time=_clock(row["reporting_cutoff_time"], CUTOFF) if reporting else CUTOFF,
        dpr_send_deadline=_clock(row["dpr_send_deadline"], SEND_DEADLINE) if reporting else SEND_DEADLINE,
    )
