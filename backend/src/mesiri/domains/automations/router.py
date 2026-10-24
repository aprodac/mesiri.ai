"""REST API for user-defined recurring automations.

Mounted at /automations so:
  GET    /automations                list this org's automations
  POST   /automations                create one
  PATCH  /automations/{id}           update fields (including enabled)
  DELETE /automations/{id}           delete
  GET    /automations/{id}/runs      run history (reads the `notifications`
                                      queue by rule_key -- no separate
                                      history table, see the migration's
                                      module docstring)

An automation whose audience is anyone other than SELF (USERS/ROLE/
NON_REPORTERS) requires ADMIN/PROJECT_MANAGER -- same role set and same
"refuse before anything is created" reasoning as
apps/whatsapp-assistant/src/projects/router.py's `_CREATE_ROLES` for
Project/Site creation. A SELF digest (nudging only yourself) is open to any
authenticated user -- it can't be used to message anyone else.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, model_validator
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.application.automations.scheduling import parse_time_of_day
from mesiri.authorization.context import AuthorizationContext
from mesiri.domains.projects.router import get_auth_context
from mesiri.domains.shared.modules import require_module
from mesiri.domains.shared.timezones import TimezoneName
from mesiri.infrastructure.postgres.dependency import get_db_conn
from mesiri.infrastructure.postgres.repositories.automations import PostgresAutomationRepository

router = APIRouter(
    prefix="/automations",
    tags=["automations"],
    dependencies=[Depends(require_module("automations"))],
)

_VALID_ACTIONS = {"SEND_DPR", "COMPLIANCE_SUMMARY", "REMINDER"}
_VALID_AUDIENCES = {"SELF", "USERS", "ROLE", "NON_REPORTERS"}
_VALID_FREQUENCIES = {"DAILY", "WEEKDAYS", "WEEKLY"}
# Matches projects/router.py's _CREATE_ROLES exactly -- same roles that may
# create a Project/Site may target an automation at someone else.
_TARGET_OTHERS_ROLES = {"ADMIN", "PROJECT_MANAGER"}


class AutomationRequest(BaseModel):
    project_id: uuid.UUID | None = None
    site_id: uuid.UUID | None = None
    action: Literal["SEND_DPR", "COMPLIANCE_SUMMARY", "REMINDER"]
    audience: Literal["SELF", "USERS", "ROLE", "NON_REPORTERS"]
    audience_user_ids: list[uuid.UUID] | None = None
    audience_role: str | None = None
    message: str | None = None
    frequency: Literal["DAILY", "WEEKDAYS", "WEEKLY"] = "DAILY"
    day_of_week: int | None = None
    time_of_day: str
    timezone: TimezoneName = "UTC"

    @model_validator(mode="after")
    def _check_shape(self) -> AutomationRequest:
        if self.audience == "USERS" and not self.audience_user_ids:
            raise ValueError("audience_user_ids is required when audience is USERS")
        if self.audience == "ROLE" and not self.audience_role:
            raise ValueError("audience_role is required when audience is ROLE")
        if self.action == "REMINDER" and not (self.message or "").strip():
            raise ValueError("message is required when action is REMINDER")
        if self.action == "SEND_DPR" and self.site_id is None:
            raise ValueError("site_id is required when action is SEND_DPR (a DPR is site-scoped)")
        if self.frequency == "WEEKLY" and self.day_of_week is None:
            raise ValueError("day_of_week is required when frequency is WEEKLY")
        if self.day_of_week is not None and not (0 <= self.day_of_week <= 6):
            raise ValueError("day_of_week must be 0 (Monday) through 6 (Sunday)")
        try:
            parse_time_of_day(self.time_of_day)
        except (ValueError, IndexError) as exc:
            raise ValueError('time_of_day must be "HH:MM"') from exc
        return self


class AutomationUpdateRequest(BaseModel):
    """Every field optional -- only what's set is changed (PATCH semantics),
    mirroring domains/dpr's ReviseDprRequest-adjacent update shapes."""

    project_id: uuid.UUID | None = None
    site_id: uuid.UUID | None = None
    action: Literal["SEND_DPR", "COMPLIANCE_SUMMARY", "REMINDER"] | None = None
    audience: Literal["SELF", "USERS", "ROLE", "NON_REPORTERS"] | None = None
    audience_user_ids: list[uuid.UUID] | None = None
    audience_role: str | None = None
    message: str | None = None
    frequency: Literal["DAILY", "WEEKDAYS", "WEEKLY"] | None = None
    day_of_week: int | None = None
    time_of_day: str | None = None
    timezone: TimezoneName | None = None
    enabled: bool | None = None


def _requires_admin_or_pm(audience: str) -> bool:
    return audience != "SELF"


def _to_response(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "project_id": str(row["project_id"]) if row.get("project_id") else None,
        "site_id": str(row["site_id"]) if row.get("site_id") else None,
        "action": row["action"],
        "audience": row["audience"],
        "audience_user_ids": row.get("audience_user_ids") or [],
        "audience_role": row.get("audience_role"),
        "message": row.get("message"),
        "frequency": row["frequency"],
        "day_of_week": row.get("day_of_week"),
        "time_of_day": row["time_of_day"],
        "timezone": row["timezone"],
        "enabled": row["enabled"],
        "last_run_on": row["last_run_on"].isoformat() if row.get("last_run_on") else None,
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
    }


@router.get("")
async def list_automations(
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    repo = PostgresAutomationRepository(conn)
    rows = await repo.list_for_org(organization_id=auth_context.organization_id)
    return {"items": [_to_response(r) for r in rows]}


@router.post("")
async def create_automation(
    req: AutomationRequest,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    if _requires_admin_or_pm(req.audience) and auth_context.role.upper() not in _TARGET_OTHERS_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Only an admin or project manager can create an automation that targets other people",
        )
    repo = PostgresAutomationRepository(conn)
    row = await repo.create(
        organization_id=auth_context.organization_id,
        project_id=req.project_id,
        site_id=req.site_id,
        action=req.action,
        audience=req.audience,
        audience_user_ids=[str(u) for u in req.audience_user_ids] if req.audience_user_ids else None,
        audience_role=req.audience_role,
        message=req.message,
        frequency=req.frequency,
        day_of_week=req.day_of_week,
        time_of_day=req.time_of_day,
        timezone=req.timezone,
        created_by=auth_context.user_id,
    )
    return _to_response(row)


@router.patch("/{automation_id}")
async def update_automation(
    automation_id: uuid.UUID,
    req: AutomationUpdateRequest,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    repo = PostgresAutomationRepository(conn)
    existing = await repo.get(organization_id=auth_context.organization_id, automation_id=automation_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Automation not found")

    fields = req.model_dump(exclude_unset=True)
    new_audience = fields.get("audience", existing["audience"])
    if _requires_admin_or_pm(new_audience) and auth_context.role.upper() not in _TARGET_OTHERS_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Only an admin or project manager can target an automation at other people",
        )
    if "audience_user_ids" in fields and fields["audience_user_ids"]:
        fields["audience_user_ids"] = [str(u) for u in fields["audience_user_ids"]]
    if "time_of_day" in fields and fields["time_of_day"] is not None:
        try:
            parse_time_of_day(fields["time_of_day"])
        except (ValueError, IndexError) as exc:
            raise HTTPException(status_code=400, detail='time_of_day must be "HH:MM"') from exc

    await repo.update(
        organization_id=auth_context.organization_id, automation_id=automation_id, fields=fields
    )
    updated = await repo.get(organization_id=auth_context.organization_id, automation_id=automation_id)
    assert updated is not None
    return _to_response(updated)


@router.delete("/{automation_id}")
async def delete_automation(
    automation_id: uuid.UUID,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    repo = PostgresAutomationRepository(conn)
    deleted = await repo.delete(organization_id=auth_context.organization_id, automation_id=automation_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Automation not found")
    return {"status": "success"}


@router.get("/{automation_id}/runs")
async def list_automation_runs(
    automation_id: uuid.UUID,
    limit: int = 50,
    auth_context: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Run history straight from the `notifications` queue -- no separate
    history table (see migration 0455's module docstring). One row per
    recipient per day the automation fired, including *why* a recipient
    was skipped (e.g. outside the WhatsApp 24h session window)."""
    from sqlalchemy import text

    repo = PostgresAutomationRepository(conn)
    automation = await repo.get(organization_id=auth_context.organization_id, automation_id=automation_id)
    if automation is None:
        raise HTTPException(status_code=404, detail="Automation not found")

    rows = (
        await conn.execute(
            text(
                """
                SELECT n.id, n.subject_id, n.recipient_user_id, n.occurred_on,
                       n.status, n.skip_reason, n.sent_at, n.created_at,
                       u.full_name AS recipient_name
                FROM notifications n
                LEFT JOIN users u ON u.id = n.recipient_user_id
                WHERE n.organization_id = :org_id AND n.rule_key = :rule_key
                ORDER BY n.occurred_on DESC, n.created_at DESC
                LIMIT :limit
                """
            ),
            {
                "org_id": auth_context.organization_id,
                "rule_key": f"automation:{automation_id}",
                "limit": limit,
            },
        )
    ).mappings().all()
    return {
        "items": [
            {
                "id": str(r["id"]),
                "recipient_name": r["recipient_name"],
                "occurred_on": r["occurred_on"].isoformat(),
                "status": r["status"],
                "skip_reason": r["skip_reason"],
                "sent_at": r["sent_at"].isoformat() if r["sent_at"] else None,
                "created_at": r["created_at"].isoformat(),
            }
            for r in rows
        ]
    }
