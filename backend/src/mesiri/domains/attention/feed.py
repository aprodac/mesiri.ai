"""GM-04: gather the attention feed for one person.

Each signal is read through its module's **own route function, as the caller**: a route that refuses (403 / 404:
their role, their project) is skipped, so who sees what stays each module's rule (SEC-01, D-CC4 included). The rules
that turn answers into alerts are ``rules.py``. Snoozes: ``attention_snoozes`` (migration 0533).
"""

from __future__ import annotations

import datetime
import logging
import uuid
from collections.abc import Awaitable
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.authorization.context import AuthorizationContext
from mesiri.domains.attention import rules

_log = logging.getLogger(__name__)


async def _quiet(call: Awaitable[Any]) -> Any:
    """The route's answer, or None when it refuses this person (their role or project)."""
    try:
        return await call
    except HTTPException as exc:
        if exc.status_code in (401, 403, 404, 422):
            return None
        raise


async def _projects(conn: AsyncConnection, auth: AuthorizationContext, project_id: uuid.UUID | None) -> list[dict]:
    """The caller's live projects (not archived), each with whether it has a BOQ (cost and material plan need one)."""
    rows = (await conn.execute(text(
        "SELECT p.id, p.name, EXISTS (SELECT 1 FROM work_package_planned_items i JOIN work_packages w "
        "ON w.id = i.work_package_id WHERE w.project_id = p.id AND i.superseded_by_id IS NULL) AS has_boq "
        "FROM projects p WHERE p.organization_id = :org AND COALESCE(p.status, '') <> 'archived' ORDER BY p.name"),
        {"org": auth.organization_id})).mappings().all()
    scope = None if auth.project_scope.grants_all_org_projects else set(auth.project_scope.project_ids)
    return [dict(r) for r in rows
            if (scope is None or r["id"] in scope) and (project_id is None or r["id"] == project_id)]


async def local_now(conn: AsyncConnection, org: uuid.UUID) -> datetime.datetime:
    """The company's wall clock (its zone), for the reporting cut-off."""
    from mesiri.application.dpr.project_day import zone_sql

    return (await conn.execute(text(f"SELECT CAST(now() AT TIME ZONE {zone_sql(':org_id')} AS timestamp)"),
                               {"org_id": org})).scalar_one()


async def collect(conn: AsyncConnection, auth: AuthorizationContext, *, enabled: set[str],
                  project_id: uuid.UUID | None = None) -> list[dict[str, Any]]:
    """Every alert for this person, unordered and unfiltered by snoozes."""
    from mesiri.domains.costing.router import portfolio, project_variance
    from mesiri.domains.dpr.router import list_site_days
    from mesiri.domains.equipment.router import hire_check
    from mesiri.domains.materials.plan_router import material_plan
    from mesiri.domains.progress.router import list_issues
    from mesiri.domains.schedule.router import get_schedule

    now = await local_now(conn, auth.organization_id)
    today = now.date()
    alerts: list[dict[str, Any]] = []
    projects = await _projects(conn, auth, project_id)
    for p in projects:
        project = {"id": p["id"], "name": p["name"]}
        schedule = await _quiet(get_schedule(p["id"], auth=auth, conn=conn))
        if schedule:
            alerts += rules.schedule_alerts(project, schedule)
        if not p["has_boq"]:
            continue
        if "cost" in enabled:
            variance = await _quiet(project_variance(p["id"], date_from=None, date_to=None, site_id=None,
                                                     auth=auth, conn=conn))
            if variance:
                alerts += rules.cost_alerts(project, variance)
        plan = await _quiet(material_plan(p["id"], weeks=8, site_id=None, auth=auth, conn=conn))
        if plan:
            alerts += rules.order_alerts(project, plan, today)

    if projects:
        days = await _quiet(list_site_days(report_date=today, project_id=project_id, auth_context=auth, conn=conn))
        if days:
            alerts += rules.report_alerts(days, now)
        issues: list[dict] = []
        for status in ("OPEN", "ACKNOWLEDGED"):
            page = await _quiet(list_issues(project_id=project_id, site_id=None, status=status, severity=None,
                                            limit=100, offset=0, auth_context=auth, conn=conn))
            issues += (page or {}).get("items", [])
        if issues:
            alerts += rules.issue_alerts(issues, datetime.datetime.now(datetime.UTC),
                                         await _names(conn, auth.organization_id, issues), today)
    if "cost" in enabled and any(p["has_boq"] for p in projects):
        book = await _quiet(portfolio(auth=auth, conn=conn))
        if book:
            ids = {str(p["id"]) for p in projects}
            alerts += rules.budget_alerts({"projects": [x for x in book["projects"] if x["project_id"] in ids]})
    if "equipment" in enabled and project_id is None:
        hire = await _quiet(hire_check(date_from=None, date_to=None, vendor_id=None, auth_context=auth, conn=conn))
        if hire:
            alerts += rules.hire_alerts(hire)
    return alerts


async def _names(conn: AsyncConnection, org: uuid.UUID, issues: list[dict]) -> dict[str, str]:
    ids = {i["project_id"] for i in issues} | {i["site_id"] for i in issues}
    rows = (await conn.execute(text(
        "SELECT id, name FROM projects WHERE organization_id = :org AND id = ANY(:ids) UNION ALL "
        "SELECT id, name FROM sites WHERE organization_id = :org AND id = ANY(:ids)"),
        {"org": org, "ids": [uuid.UUID(str(x)) for x in ids]})).all()
    return {str(r.id): r.name for r in rows}


# --- snoozes ---------------------------------------------------------------------------------------------------------


async def snoozed(conn: AsyncConnection, auth: AuthorizationContext, today: datetime.date) -> set[str]:
    rows = await conn.execute(text(
        "SELECT key FROM attention_snoozes WHERE organization_id = :org AND user_id = :u AND until >= :today"),
        {"org": auth.organization_id, "u": auth.user_id, "today": today})
    return {r.key for r in rows}


async def snooze(conn: AsyncConnection, auth: AuthorizationContext, key: str, until: datetime.date) -> None:
    await conn.execute(text(
        "INSERT INTO attention_snoozes (organization_id, user_id, key, until) VALUES (:org, :u, :k, :until) "
        "ON CONFLICT (user_id, key) DO UPDATE SET until = EXCLUDED.until, created_at = now()"),
        {"org": auth.organization_id, "u": auth.user_id, "k": key, "until": until})


async def unsnooze(conn: AsyncConnection, auth: AuthorizationContext, key: str) -> None:
    await conn.execute(text("DELETE FROM attention_snoozes WHERE organization_id = :org AND user_id = :u AND key = :k"),
                       {"org": auth.organization_id, "u": auth.user_id, "k": key})
