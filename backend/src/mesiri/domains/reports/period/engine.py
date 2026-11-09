"""The period-report engine (PRC-19): a period × a scope × the person's role → sections, headline, "Needs you".

One read, three outputs: the page (JSON), the PDF and the Excel all render what ``build`` returns, so they never
disagree. Each section runs in its own savepoint (the approvals inbox's way): a section that fails is named in
``unavailable`` and the rest still show; a section the person may not see (403 / 404 from its module) or whose
module is switched off is left out without a word.
"""

from __future__ import annotations

import datetime
import logging
import uuid
from collections.abc import Callable
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.authorization.context import AuthorizationContext
from mesiri.authorization.roles import may_manage_money, may_view_expenses
from mesiri.domains.reports.period import headline as rules
from mesiri.domains.reports.period import periods
from mesiri.domains.reports.period.sections import MODULE_OF, SECTIONS, Ctx

logger = logging.getLogger(__name__)

#: Sections in the order the page, the PDF and the Excel show them.
ORDER = ("work", "schedule", "labour", "materials", "money", "issues", "photos", "completeness")
NOUN = {"week": "week", "month": "month", "custom": "period"}


async def _site_names(conn: AsyncConnection, auth: AuthorizationContext, project_id: uuid.UUID) -> dict[str, str]:
    """The project's sites this person reaches: the project's own sites list, as the caller."""
    from mesiri.domains.projects.router import list_sites

    out = {}
    for s in await list_sites(project_id=project_id, auth_context=auth, conn=conn):
        sid = s["id"] if isinstance(s, dict) else s.id
        name = s["name"] if isinstance(s, dict) else s.name
        out[str(sid)] = name
    return out


async def build(conn: AsyncConnection, auth: AuthorizationContext, *, project_id: uuid.UUID,
                site_id: uuid.UUID | None, period: periods.Period, enabled: Callable[[str], bool],
                storage: Any = None, today: datetime.date | None = None) -> dict[str, Any]:
    from mesiri.application.dpr.project_day import company_today
    from mesiri.domains.schedule.router import _project

    project = await _project(conn, auth, project_id)  # 403 / 404 outside the person's projects
    today = today or await company_today(conn, auth.organization_id)
    sites = await _site_names(conn, auth, project_id)
    if site_id is not None and str(site_id) not in sites:
        raise HTTPException(status_code=404, detail="Site not found in this project")
    ctx = Ctx(conn=conn, auth=auth, project=project, site_id=site_id, period=period, prev=periods.previous(period),
              today=today, money=may_view_expenses(auth.role), bills=may_manage_money(auth.role), enabled=enabled,
              storage=storage, sites=sites)

    sections: dict[str, dict] = {}
    unavailable: list[str] = []
    for key in ORDER:
        module = MODULE_OF[key]
        if module is not None and not enabled(module):
            continue
        if key == "money" and not ctx.money:
            continue
        try:
            async with conn.begin_nested():  # one section failing must not abort the others' reads
                sections[key] = await SECTIONS[key](ctx)
        except HTTPException as exc:
            if exc.status_code not in (403, 404):
                unavailable.append(key)
        except Exception:  # noqa: BLE001 -- the rest of the report still shows
            logger.exception("period_report.section_failed key=%s project=%s", key, project_id)
            unavailable.append(key)

    waiting = await _waiting(conn, auth, enabled, project_id, site_id)
    noun = NOUN[period.kind]
    return {
        "audience": "internal",
        "project": {"id": str(project["id"]), "name": project["name"], "client": project.get("client")},
        "site": {"id": str(site_id), "name": sites[str(site_id)]} if site_id else None,
        "period": period.as_dict(), "previous": ctx.prev.as_dict(),
        "next": periods.following(period).as_dict() if periods.following(period).start <= today else None,
        "today": today.isoformat(), "running": period.end >= today,
        "generated_at": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        "headline": rules.headline(sections, noun), "kpis": rules.kpis(sections), "areas": rules.areas(sections),
        "needs_you": rules.needs_you(sections, waiting),
        "sections": sections, "order": [k for k in ORDER if k in sections], "unavailable": unavailable,
        "sees_money": ctx.money,
    }


async def _waiting(conn: AsyncConnection, auth: AuthorizationContext, enabled: Callable[[str], bool],
                   project_id: uuid.UUID, site_id: uuid.UUID | None) -> list[dict[str, Any]]:
    """What the approvals inbox has waiting for this person in this project (and site)."""
    from mesiri.domains.approvals import inbox

    try:
        async with conn.begin_nested():
            got = await inbox.waiting(conn, auth, enabled)
    except Exception:  # noqa: BLE001 -- the report shows without it
        logger.exception("period_report.waiting_failed project=%s", project_id)
        return []
    return [i for i in got["items"] if i.get("project_id") == str(project_id)
            and (site_id is None or i.get("site_id") in (None, str(site_id)))]


def public(report: dict[str, Any]) -> dict[str, Any]:
    """The report as the page gets it: photo storage keys stay on the server."""
    photos = report["sections"].get("photos")
    if not photos:
        return report
    clean = {**photos, "rows": [{k: v for k, v in r.items() if not k.startswith("_")} for r in photos["rows"]]}
    return {**report, "sections": {**report["sections"], "photos": clean}}
