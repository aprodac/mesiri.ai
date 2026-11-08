"""REST API for the end of a project (END-01 snag list, END-03 handover checklist).

  GET    /snags?project_id=&status=&site_id=     snags in scope; status open / fixed / closed / pending (not closed)
  POST   /projects/{project_id}/snags            raise a snag: what, where, which trade or subcontractor, by when
  PATCH  /snags/{snag_id}                        change an open snag's details
  POST   /snags/{snag_id}/fixed                  the site says it is put right (a note: what was done)
  POST   /snags/{snag_id}/close                  a manager checked the fix: closed
  POST   /snags/{snag_id}/reopen                 the fix is not good: open again, with the reason
  DELETE /snags/{snag_id}                        remove a snag raised by mistake (open only)

  GET    /projects/{project_id}/handover         the handover checklist: work, snags, subcontracts, final bill,
                                                 client paid, handover day, defect period, retention
  PATCH  /projects/{project_id}/handover         set the handover day (moves the stage to the defect period)

Who: anyone on the project raises a snag and says it is fixed (the site engineer walks the rooms); closing,
reopening, deleting and the handover day are for the roles that run the project (owner, admin, finance, PM:
``may_view_expenses``, the same as the schedule). The checklist's money steps show only to the owner, an admin or
finance (``may_manage_money``, D-N3 default). Plan: docs/plans/project-end-plan.md.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.authorization.context import AuthorizationContext
from mesiri.authorization.roles import may_manage_money, may_view_expenses
from mesiri.domains.closeout import handover, snags
from mesiri.domains.projects.router import get_auth_context
from mesiri.domains.shared.modules import require_module
from mesiri.infrastructure.postgres.dependency import get_db_conn

router = APIRouter(tags=["closeout"], dependencies=[Depends(require_module("dpr"))])


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = " ".join(value.split())
    return value or None


class SnagIn(BaseModel):
    description: str | None = Field(default=None, min_length=1, max_length=500,
                                    description="What is wrong: 'tile chipped near the door'")
    place: str | None = Field(default=None, max_length=120, description="Where, in words: 'Bedroom 2', 'First floor "
                                                                         "toilet'")
    site_id: uuid.UUID | None = None
    trade: str | None = Field(default=None, max_length=60, description="Who fixes it: plumber, electrician, tiler...")
    vendor_id: uuid.UUID | None = Field(default=None, description="The subcontractor who fixes it, when known")
    found_by: str | None = Field(default=None, description="us (our walk-round) or client")
    due_on: datetime.date | None = None

    _clean_text = field_validator("description", "place", "trade")(_clean)

    @field_validator("found_by")
    @classmethod
    def _found_by(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip().lower()
        if v not in ("us", "client"):
            raise ValueError("found_by is us or client")
        return v


class FixedIn(BaseModel):
    note: str | None = Field(default=None, max_length=500, description="What was done")

    _clean_text = field_validator("note")(_clean)


class ReopenIn(BaseModel):
    reason: str = Field(min_length=1, max_length=500)

    _clean_text = field_validator("reason")(_clean)


class HandoverIn(BaseModel):
    handed_over_on: datetime.date | None = None
    clear: bool = Field(default=False, description="Remove the handover day (set by mistake)")


def _out(value: Any) -> Any:
    if isinstance(value, datetime.date | datetime.datetime):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dict):
        return {k: _out(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_out(v) for v in value]
    if hasattr(value, "as_tuple"):  # Decimal: exact string
        return str(value)
    return value


def _in_scope(auth: AuthorizationContext, project_id: uuid.UUID) -> None:
    if not auth.project_scope.grants_all_org_projects and project_id not in auth.project_scope.project_ids:
        raise HTTPException(status_code=403, detail="Not authorized for this project")


def _manager(auth: AuthorizationContext) -> None:
    if not may_view_expenses(auth.role):
        raise HTTPException(status_code=403, detail="Only the owner, an admin, finance or a project manager can do "
                                                    "this")


async def _project(conn: AsyncConnection, auth: AuthorizationContext, project_id: uuid.UUID) -> dict[str, Any]:
    _in_scope(auth, project_id)
    row = (await conn.execute(text(
        "SELECT id, name, stage, handed_over_on FROM projects WHERE id = :p AND organization_id = :org"),
        {"p": project_id, "org": auth.organization_id})).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return dict(row)


async def _snag(conn: AsyncConnection, auth: AuthorizationContext, snag_id: uuid.UUID) -> dict[str, Any]:
    snag = await snags.get(conn, auth.organization_id, snag_id)
    if snag is None:
        raise HTTPException(status_code=404, detail="Snag not found")
    _in_scope(auth, snag["project_id"])
    return snag


async def _check_refs(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID, body: SnagIn) -> None:
    if body.site_id is not None and not (await conn.execute(text(
            "SELECT 1 FROM sites WHERE id = :s AND project_id = :p AND organization_id = :org"),
            {"s": body.site_id, "p": project_id, "org": org})).scalar():
        raise HTTPException(status_code=422, detail="That site is not on this project")
    if body.vendor_id is not None and not (await conn.execute(text(
            "SELECT 1 FROM vendors WHERE id = :v AND organization_id = :org"),
            {"v": body.vendor_id, "org": org})).scalar():
        raise HTTPException(status_code=422, detail="That subcontractor is not in your supplier list")


async def _today(conn: AsyncConnection, org: uuid.UUID) -> datetime.date:
    from mesiri.application.dpr.project_day import company_today

    return await company_today(conn, org)


# -- snags (END-01) --------------------------------------------------------------------------------------------------

@router.get("/snags")
async def list_snags(project_id: uuid.UUID | None = None, status: str | None = None, site_id: uuid.UUID | None = None,
                     auth: AuthorizationContext = Depends(get_auth_context),
                     conn: AsyncConnection = Depends(get_db_conn)):
    """Snags, open first (oldest due first), then fixed and waiting for a check, then closed. ``status=pending``:
    everything not closed. ``counts`` per status for the same projects."""
    if status is not None and status not in (*snags.STATUSES, "pending"):
        raise HTTPException(status_code=422, detail="status is open, fixed, closed or pending")
    scope = None if auth.project_scope.grants_all_org_projects else set(auth.project_scope.project_ids)
    if project_id is not None:
        await _project(conn, auth, project_id)
        scope = {project_id}
    rows = await snags.list_snags(conn, auth.organization_id, scope, status=status, site_id=site_id)
    every = rows if status is None else await snags.list_snags(conn, auth.organization_id, scope, site_id=site_id)
    counts = {k: sum(1 for r in every if r["status"] == k) for k in snags.STATUSES}
    return _out({"snags": rows, "counts": counts, "can_manage": may_view_expenses(auth.role)})


@router.post("/projects/{project_id}/snags", status_code=201)
async def raise_snag(project_id: uuid.UUID, body: SnagIn, auth: AuthorizationContext = Depends(get_auth_context),
                     conn: AsyncConnection = Depends(get_db_conn)):
    proj = await _project(conn, auth, project_id)
    if not body.description:
        raise HTTPException(status_code=422, detail="Say what is wrong")
    await _check_refs(conn, auth.organization_id, project_id, body)
    values = body.model_dump(exclude_unset=True)
    snag_id = await snags.create(conn, auth.organization_id, project_id, proj["stage"], values, auth.user_id)
    return _out(await snags.get(conn, auth.organization_id, snag_id))


@router.patch("/snags/{snag_id}")
async def update_snag(snag_id: uuid.UUID, body: SnagIn, auth: AuthorizationContext = Depends(get_auth_context),
                      conn: AsyncConnection = Depends(get_db_conn)):
    snag = await _snag(conn, auth, snag_id)
    if snag["status"] == "closed":
        raise HTTPException(status_code=409, detail=f"{snag['ref']} is closed; a new problem is a new snag")
    values = body.model_dump(exclude_unset=True)
    if "description" in values and not values["description"]:
        raise HTTPException(status_code=422, detail="Say what is wrong")
    await _check_refs(conn, auth.organization_id, snag["project_id"], body)
    await snags.update(conn, snag_id, values)
    return _out(await snags.get(conn, auth.organization_id, snag_id))


@router.post("/snags/{snag_id}/fixed")
async def snag_fixed(snag_id: uuid.UUID, body: FixedIn | None = None,
                     auth: AuthorizationContext = Depends(get_auth_context),
                     conn: AsyncConnection = Depends(get_db_conn)):
    snag = await _snag(conn, auth, snag_id)
    if snag["status"] != "open":
        raise HTTPException(status_code=409, detail=f"{snag['ref']} is already {snag['status_label'].lower()}")
    await snags.mark_fixed(conn, snag_id, body.note if body else None, auth.user_id)
    return _out(await snags.get(conn, auth.organization_id, snag_id))


@router.post("/snags/{snag_id}/close")
async def close_snag(snag_id: uuid.UUID, auth: AuthorizationContext = Depends(get_auth_context),
                     conn: AsyncConnection = Depends(get_db_conn)):
    """A manager checked it. An open snag may be closed directly (fixed on the spot during the walk-round)."""
    _manager(auth)
    snag = await _snag(conn, auth, snag_id)
    if snag["status"] == "closed":
        raise HTTPException(status_code=409, detail=f"{snag['ref']} is already closed")
    await snags.close(conn, snag_id, auth.user_id)
    return _out(await snags.get(conn, auth.organization_id, snag_id))


@router.post("/snags/{snag_id}/reopen")
async def reopen_snag(snag_id: uuid.UUID, body: ReopenIn, auth: AuthorizationContext = Depends(get_auth_context),
                      conn: AsyncConnection = Depends(get_db_conn)):
    _manager(auth)
    snag = await _snag(conn, auth, snag_id)
    if snag["status"] != "fixed":
        raise HTTPException(status_code=409, detail=f"Only a fixed snag goes back to open ({snag['ref']} is "
                                                    f"{snag['status_label'].lower()})")
    await snags.reopen(conn, snag_id, body.reason)
    return _out(await snags.get(conn, auth.organization_id, snag_id))


@router.delete("/snags/{snag_id}", status_code=204)
async def delete_snag(snag_id: uuid.UUID, auth: AuthorizationContext = Depends(get_auth_context),
                      conn: AsyncConnection = Depends(get_db_conn)):
    _manager(auth)
    snag = await _snag(conn, auth, snag_id)
    if snag["status"] != "open":
        raise HTTPException(status_code=409, detail=f"{snag['ref']} is {snag['status_label'].lower()}: only an open "
                                                    "snag raised by mistake is removed")
    await snags.delete(conn, snag_id)
    return Response(status_code=204)


# -- handover checklist (END-03) -------------------------------------------------------------------------------------

@router.get("/projects/{project_id}/handover")
async def project_handover(project_id: uuid.UUID, auth: AuthorizationContext = Depends(get_auth_context),
                           conn: AsyncConnection = Depends(get_db_conn)):
    from mesiri.domains.schedule.router import STAGE_WORDS

    proj = await _project(conn, auth, project_id)
    today = await _today(conn, auth.organization_id)
    money = may_manage_money(auth.role)
    f = await handover.facts(conn, auth.organization_id, project_id, today, money)
    steps = handover.steps(f, today, money)
    required = [s for s in steps if not s.get("optional")]
    nxt = next((s["key"] for s in required if not s["done"]), None) or next(
        (s["key"] for s in steps if not s["done"]), None)
    return _out({"project": {"id": proj["id"], "name": proj["name"], "stage": proj["stage"],
                             "stage_label": STAGE_WORDS.get(proj["stage"], proj["stage"])},
                 "today": today, "steps": steps, "next": nxt, "done": sum(1 for s in steps if s["done"]),
                 "total": len(steps), "ready_to_close": all(s["done"] for s in required),
                 "handed_over_on": f["handed_over_on"], "defects_end": f["defects_end"],
                 "defect_liability_months": f["defect_liability_months"], "snags": f["snags"],
                 "money": f.get("money"), "can_edit": may_view_expenses(auth.role), "can_see_money": money})


@router.patch("/projects/{project_id}/handover")
async def set_handover(project_id: uuid.UUID, body: HandoverIn, auth: AuthorizationContext = Depends(get_auth_context),
                       conn: AsyncConnection = Depends(get_db_conn)):
    """The day the client took the project over. Setting it moves a project that is not past it yet (tender, won,
    running, handover) to the defect period; clearing it moves a project in the defect period back to handover. A
    closed project keeps its stage."""
    _manager(auth)
    proj = await _project(conn, auth, project_id)
    today = await _today(conn, auth.organization_id)
    if body.clear:
        stage = "handover" if proj["stage"] == "defects" else proj["stage"]
        day = None
    else:
        day = body.handed_over_on or today
        if day > today:
            raise HTTPException(status_code=422, detail="That day has not come yet: set it when the client takes over")
        stage = proj["stage"] if proj["stage"] in ("defects", "closed") else "defects"
    await conn.execute(text(
        "UPDATE projects SET handed_over_on = :d, stage = :s, updated_at = now() WHERE id = :p"),
        {"d": day, "s": stage, "p": project_id})
    return await project_handover(project_id, auth, conn)
