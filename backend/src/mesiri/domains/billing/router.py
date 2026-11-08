"""REST API for client billing (NXT-01, NXT-02).

  GET   /billing/clients                       the company's clients, each with its projects and contract value
  POST  /billing/clients                       add a client
  PATCH /billing/clients/{client_id}           change a client's details
  GET   /projects/{project_id}/contract        the project's client and contract terms (null when not set)
  PUT   /projects/{project_id}/contract        set them: an existing client_id, or a new client by name

Who: the owner, an admin and finance (``may_manage_money``), within the projects they can reach: the plan's default
for decision D-N3 (docs/plans/next-modules-plan.md), the narrowest existing money rule, until Ilan decides otherwise.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.authorization.context import AuthorizationContext
from mesiri.authorization.roles import may_manage_money
from mesiri.domains.billing import contracts
from mesiri.domains.projects.router import get_auth_context
from mesiri.domains.shared.modules import require_module
from mesiri.infrastructure.postgres.dependency import get_db_conn

router = APIRouter(tags=["billing"], dependencies=[Depends(require_module("dpr"))])

_Pct = Field(default=None, ge=0, le=100, max_digits=5, decimal_places=2)
_Money = Field(default=None, ge=0, max_digits=16, decimal_places=2)


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = " ".join(value.split())
    return value or None


class ClientIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    contact_person: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=200)
    gstin: str | None = Field(default=None, max_length=20)
    address: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=1000)

    _clean_text = field_validator("name", "contact_person", "phone", "email", "gstin", "address", "notes")(_clean)

    @field_validator("gstin")
    @classmethod
    def _gstin(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.upper().replace(" ", "")
        if len(v) != 15 or not v.isalnum():
            raise ValueError("a GSTIN is 15 letters and digits (e.g. 32ABCDE1234F1Z5)")
        return v


class ContractIn(BaseModel):
    client_id: uuid.UUID | None = None
    new_client: ClientIn | None = Field(default=None, description="A client not saved yet (name at least)")
    contract_no: str | None = Field(default=None, max_length=80)
    contract_value: Decimal | None = _Money
    signed_on: datetime.date | None = None
    retention_pct: Decimal | None = _Pct
    mobilisation_advance: Decimal | None = _Money
    advance_recovery_pct: Decimal | None = _Pct
    gst_pct: Decimal | None = _Pct
    tds_pct: Decimal | None = _Pct
    defect_liability_months: int | None = Field(default=None, ge=0, le=120)
    payment_terms: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=1000)

    _clean_text = field_validator("contract_no", "payment_terms", "notes")(_clean)


def _require(auth: AuthorizationContext, project_id: uuid.UUID | None = None) -> None:
    if not may_manage_money(auth.role):
        raise HTTPException(status_code=403, detail="Only the owner, an admin or finance can see client contracts "
                                                    "and bills")
    if project_id is not None and not auth.project_scope.grants_all_org_projects \
            and project_id not in auth.project_scope.project_ids:
        raise HTTPException(status_code=403, detail="Not authorized for this project")


def _out(value: Any) -> Any:
    """Dates as ISO strings, ids as strings, money as exact strings ("756000.00"), never floats."""
    if isinstance(value, datetime.date | datetime.datetime):
        return value.isoformat()
    if isinstance(value, uuid.UUID | Decimal):
        return str(value)
    if isinstance(value, dict):
        return {k: _out(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_out(v) for v in value]
    return value


async def _project_name(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID) -> str:
    from sqlalchemy import text

    name = (await conn.execute(text("SELECT name FROM projects WHERE id = :p AND organization_id = :org"),
                               {"p": project_id, "org": org})).scalar()
    if name is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return name


async def _new_client(conn: AsyncConnection, auth: AuthorizationContext, body: ClientIn) -> Any:
    if not body.name:
        raise HTTPException(status_code=422, detail="A client needs a name")
    if await contracts.client_named(conn, auth.organization_id, body.name):
        raise HTTPException(status_code=409, detail=f"A client called '{body.name}' is already saved: pick them")
    return await contracts.create_client(conn, auth.organization_id, body.model_dump(exclude_unset=True), auth.user_id)


@router.get("/billing/clients")
async def list_clients(auth: AuthorizationContext = Depends(get_auth_context),
                       conn: AsyncConnection = Depends(get_db_conn)):
    _require(auth)
    clients = await contracts.list_clients(conn, auth.organization_id)
    if not auth.project_scope.grants_all_org_projects:
        allowed = auth.project_scope.project_ids
        for c in clients:
            c["projects"] = [p for p in c["projects"] if p["id"] in allowed]
    return _out(clients)


@router.post("/billing/clients", status_code=201)
async def create_client(body: ClientIn, auth: AuthorizationContext = Depends(get_auth_context),
                        conn: AsyncConnection = Depends(get_db_conn)):
    _require(auth)
    client_id = await _new_client(conn, auth, body)
    return _out(await contracts.get_client(conn, auth.organization_id, client_id))


@router.patch("/billing/clients/{client_id}")
async def update_client(client_id: uuid.UUID, body: ClientIn, auth: AuthorizationContext = Depends(get_auth_context),
                        conn: AsyncConnection = Depends(get_db_conn)):
    _require(auth)
    if await contracts.get_client(conn, auth.organization_id, client_id) is None:
        raise HTTPException(status_code=404, detail="Client not found")
    values = body.model_dump(exclude_unset=True)
    if "name" in values:
        if not values["name"]:
            raise HTTPException(status_code=422, detail="A client needs a name")
        if await contracts.client_named(conn, auth.organization_id, values["name"], exclude=client_id):
            raise HTTPException(status_code=409, detail=f"Another client is already called '{values['name']}'")
    await contracts.update_client(conn, auth.organization_id, client_id, values)
    return _out(await contracts.get_client(conn, auth.organization_id, client_id))


@router.get("/projects/{project_id}/contract")
async def get_contract(project_id: uuid.UUID, auth: AuthorizationContext = Depends(get_auth_context),
                       conn: AsyncConnection = Depends(get_db_conn)):
    _require(auth, project_id)
    name = await _project_name(conn, auth.organization_id, project_id)
    contract = await contracts.get_contract(conn, auth.organization_id, project_id)
    return _out({"project": {"id": project_id, "name": name}, "contract": contract})


@router.put("/projects/{project_id}/contract")
async def put_contract(project_id: uuid.UUID, body: ContractIn,
                       auth: AuthorizationContext = Depends(get_auth_context),
                       conn: AsyncConnection = Depends(get_db_conn)):
    """Set the project's client and contract terms. Every term is written: one left out becomes empty."""
    _require(auth, project_id)
    org = auth.organization_id
    name = await _project_name(conn, org, project_id)
    if body.client_id and body.new_client:
        raise HTTPException(status_code=422, detail="Pick a saved client or add a new one, not both")
    if body.mobilisation_advance and body.contract_value and body.mobilisation_advance > body.contract_value:
        raise HTTPException(status_code=422, detail="The advance is more than the contract value")
    before = await contracts.get_contract(conn, org, project_id)
    client_id = body.client_id
    if client_id is not None and await contracts.get_client(conn, org, client_id) is None:
        raise HTTPException(status_code=422, detail="That client is not in your client list")
    if body.new_client is not None:
        client_id = await _new_client(conn, auth, body.new_client)
    await contracts.put_contract(conn, org, project_id, client_id,
                                 body.model_dump(exclude={"client_id", "new_client"}), auth.user_id)
    after = await contracts.get_contract(conn, org, project_id)
    if after and after["client_name"]:
        await contracts.name_project_client(conn, org, project_id, after["client_name"],
                                            before["client_name"] if before else None)
    return _out({"project": {"id": project_id, "name": name}, "contract": after})
