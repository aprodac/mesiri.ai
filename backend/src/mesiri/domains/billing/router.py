"""REST API for client billing (NXT-01, NXT-02).

  GET   /billing/clients                       the company's clients, each with its projects and contract value
  POST  /billing/clients                       add a client
  PATCH /billing/clients/{client_id}           change a client's details
  GET   /projects/{project_id}/contract        the project's client and contract terms (null when not set)
  PUT   /projects/{project_id}/contract        set them: an existing client_id, or a new client by name

  GET   /billing/ra-bills?project_id=          RA bills, newest first per project
  POST  /projects/{project_id}/ra-bills        a new draft from the measured work not billed yet
  GET   /billing/ra-bills/{bill_id}            one bill with its lines and money
  PATCH /billing/ra-bills/{bill_id}            a draft's date, period and notes
  PUT   /billing/ra-bills/{bill_id}/lines/{line_id}   a draft line's quantity (the suggested one is kept)
  POST  /billing/ra-bills/{bill_id}/submit     freeze it: the money is stored, it is sent to the client
  POST  /billing/ra-bills/{bill_id}/certify    what the client's engineer certified (may differ), and when
  POST  /billing/ra-bills/{bill_id}/cancel     a submitted bill withdrawn (its quantities go back to "not billed")
  DELETE /billing/ra-bills/{bill_id}           remove a draft

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


# -- RA bills (NXT-02) ---------------------------------------------------------------------------------------------

class BillCreate(BaseModel):
    bill_date: datetime.date | None = None
    period_to: datetime.date | None = None


class BillUpdate(BaseModel):
    bill_date: datetime.date | None = None
    period_to: datetime.date | None = None
    notes: str | None = Field(default=None, max_length=1000)

    _clean_text = field_validator("notes")(_clean)


class LineQuantity(BaseModel):
    quantity: Decimal = Field(ge=0, max_digits=14, decimal_places=3)


class Certify(BaseModel):
    certified_amount: Decimal = Field(ge=0, max_digits=16, decimal_places=2)
    certified_on: datetime.date | None = None


async def _bill(conn: AsyncConnection, auth: AuthorizationContext, bill_id: uuid.UUID) -> dict[str, Any]:
    from mesiri.domains.billing import bills

    _require(auth)
    bill = await bills.get(conn, auth.organization_id, bill_id)
    if bill is None:
        raise HTTPException(status_code=404, detail="Bill not found")
    _require(auth, bill["project_id"])
    return bill


def _draft(bill: dict[str, Any]) -> None:
    if bill["status"] != "draft":
        raise HTTPException(status_code=409, detail=f"{bill['ref']} is {bill['status']}; only a draft can change")


async def _today(conn: AsyncConnection, org: uuid.UUID) -> datetime.date:
    from mesiri.application.dpr.project_day import company_today

    return await company_today(conn, org)


@router.get("/billing/ra-bills")
async def list_ra_bills(project_id: uuid.UUID | None = None, auth: AuthorizationContext = Depends(get_auth_context),
                        conn: AsyncConnection = Depends(get_db_conn)):
    from mesiri.domains.billing import bills

    _require(auth, project_id)
    scope = None if auth.project_scope.grants_all_org_projects else set(auth.project_scope.project_ids)
    if project_id is not None:
        scope = {project_id}
    return _out(await bills.list_bills(conn, auth.organization_id, scope))


@router.post("/projects/{project_id}/ra-bills", status_code=201)
async def create_ra_bill(project_id: uuid.UUID, body: BillCreate,
                         auth: AuthorizationContext = Depends(get_auth_context),
                         conn: AsyncConnection = Depends(get_db_conn)):
    from sqlalchemy import text

    from mesiri.domains.billing import bills

    _require(auth, project_id)
    org = auth.organization_id
    await _project_name(conn, org, project_id)
    draft = (await conn.execute(text(
        "SELECT number FROM ra_bills WHERE organization_id = :org AND project_id = :p AND status = 'draft'"),
        {"org": org, "p": project_id})).scalar()
    if draft is not None:
        raise HTTPException(status_code=409, detail=f"{bills.ref(draft)} is still a draft: submit or remove it first")
    today = await _today(conn, org)
    bill_id, added = await bills.create_draft(conn, org, project_id, body.bill_date or today,
                                              body.period_to or today, auth.user_id)
    if added == 0:
        raise HTTPException(status_code=422, detail="No measured work to bill: every priced BOQ line's measured "
                                                    "quantity is already on a bill (or no line has a client rate)")
    return _out(await bills.get(conn, org, bill_id))


@router.get("/billing/ra-bills/{bill_id}")
async def get_ra_bill(bill_id: uuid.UUID, auth: AuthorizationContext = Depends(get_auth_context),
                      conn: AsyncConnection = Depends(get_db_conn)):
    return _out(await _bill(conn, auth, bill_id))


@router.patch("/billing/ra-bills/{bill_id}")
async def update_ra_bill(bill_id: uuid.UUID, body: BillUpdate, auth: AuthorizationContext = Depends(get_auth_context),
                         conn: AsyncConnection = Depends(get_db_conn)):
    from mesiri.domains.billing import bills

    bill = await _bill(conn, auth, bill_id)
    _draft(bill)
    values = body.model_dump(exclude_unset=True)
    if "bill_date" in values and values["bill_date"] is None:
        raise HTTPException(status_code=422, detail="A bill needs a date")
    await bills.update_details(conn, bill_id, values)
    return _out(await bills.get(conn, auth.organization_id, bill_id))


@router.put("/billing/ra-bills/{bill_id}/lines/{line_id}")
async def set_ra_bill_line(bill_id: uuid.UUID, line_id: uuid.UUID, body: LineQuantity,
                           auth: AuthorizationContext = Depends(get_auth_context),
                           conn: AsyncConnection = Depends(get_db_conn)):
    """The office's quantity for one line of a draft (D-N1: measured by default, editable before submitting; the
    suggested quantity stays on the line, so the change shows)."""
    from mesiri.domains.billing import bills

    bill = await _bill(conn, auth, bill_id)
    _draft(bill)
    if not await bills.set_quantity(conn, bill_id, line_id, body.quantity):
        raise HTTPException(status_code=404, detail="Line not found on this bill")
    return _out(await bills.get(conn, auth.organization_id, bill_id))


@router.post("/billing/ra-bills/{bill_id}/submit")
async def submit_ra_bill(bill_id: uuid.UUID, auth: AuthorizationContext = Depends(get_auth_context),
                         conn: AsyncConnection = Depends(get_db_conn)):
    from mesiri.domains.billing import bills

    bill = await _bill(conn, auth, bill_id)
    _draft(bill)
    if not any(Decimal(ln["quantity"]) > 0 for ln in bill["lines"]):
        raise HTTPException(status_code=422, detail="Every line is 0: nothing to bill")
    await bills.submit(conn, bill, auth.user_id)
    return _out(await bills.get(conn, auth.organization_id, bill_id))


@router.post("/billing/ra-bills/{bill_id}/certify")
async def certify_ra_bill(bill_id: uuid.UUID, body: Certify, auth: AuthorizationContext = Depends(get_auth_context),
                          conn: AsyncConnection = Depends(get_db_conn)):
    from mesiri.domains.billing import bills

    bill = await _bill(conn, auth, bill_id)
    if bill["status"] not in ("submitted", "certified"):
        raise HTTPException(status_code=409, detail="Only a submitted bill can be certified")
    await bills.set_status(conn, bill_id, "certified", certified_amount=body.certified_amount,
                           certified_on=body.certified_on or await _today(conn, auth.organization_id))
    return _out(await bills.get(conn, auth.organization_id, bill_id))


@router.post("/billing/ra-bills/{bill_id}/cancel")
async def cancel_ra_bill(bill_id: uuid.UUID, auth: AuthorizationContext = Depends(get_auth_context),
                         conn: AsyncConnection = Depends(get_db_conn)):
    from mesiri.domains.billing import bills

    bill = await _bill(conn, auth, bill_id)
    if bill["status"] != "submitted":
        raise HTTPException(status_code=409, detail="Only a submitted bill can be withdrawn (a draft is removed, a "
                                                    "certified one stays)")
    await bills.set_status(conn, bill_id, "cancelled")
    return _out(await bills.get(conn, auth.organization_id, bill_id))


@router.delete("/billing/ra-bills/{bill_id}", status_code=204)
async def delete_ra_bill(bill_id: uuid.UUID, auth: AuthorizationContext = Depends(get_auth_context),
                         conn: AsyncConnection = Depends(get_db_conn)):
    from fastapi import Response

    from mesiri.domains.billing import bills

    bill = await _bill(conn, auth, bill_id)
    _draft(bill)
    await bills.delete_draft(conn, bill_id)
    return Response(status_code=204)
