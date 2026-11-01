"""WA-119 test kit: a stand-in for the dashboard API (the pilot's routes, answering
like the real ones, behind the real ``get_current_user``) and a scripted model
that sends a two-receipt message through it."""

from __future__ import annotations

import uuid

from fastapi import Depends, FastAPI, Header
from pydantic import BaseModel

from agent_api.client import Actor
from agent_api.tools import ALLOWED, CONFIRM_ARG, build_tools
from mesiri.domains.shared.auth import get_current_user
from mesiri_ai.fakes import FakeToolCallingProvider

ORG = str(uuid.uuid4())
USER = str(uuid.uuid4())
PROJECT = str(uuid.uuid4())
SITE = str(uuid.uuid4())
CEMENT = str(uuid.uuid4())
TMT = str(uuid.uuid4())
BAG = str(uuid.uuid4())
NOS = str(uuid.uuid4())

ACTOR = Actor(user_id=USER, organization_id=ORG, role="SITE_SUPERVISOR", name="Ravi")
MESSAGE = "50 bag cement and 50 TMT came today at Green Villa"
STAND_IN_TOOLS = {"list_projects", "list_sites", "search_materials", "list_units", "record_receipt"}


class Inflow(BaseModel):
    project_id: uuid.UUID
    site_id: uuid.UUID | None = None
    material_id: uuid.UUID
    unit_id: uuid.UUID
    quantity: float
    occurred_date: str
    supplier: str | None = None


def stand_in_api(seen: list[tuple[str, str, dict, str | None]], *, refuse_tmt: bool = False) -> FastAPI:
    app = FastAPI()

    def note(method: str, path: str, jwt: dict, key: str | None = None) -> None:
        seen.append((method, path, jwt, key))

    @app.get("/projects")
    async def projects(jwt: dict = Depends(get_current_user)):
        note("GET", "/projects", jwt)
        return [{"id": PROJECT, "name": "Green Villa"}]

    @app.get("/projects/{project_id}/sites")
    async def sites(project_id: str, jwt: dict = Depends(get_current_user)):
        note("GET", f"/projects/{project_id}/sites", jwt)
        return [{"id": SITE, "name": "Green Villa main"}]

    @app.get("/materials")
    async def materials(search: str | None = None, jwt: dict = Depends(get_current_user)):
        note("GET", f"/materials?search={search}", jwt)
        catalog = {"cement": (CEMENT, "Cement OPC 53"), "tmt": (TMT, "TMT bar 12mm")}
        hit = catalog.get((search or "").lower())
        return {"items": [{"id": hit[0], "name": hit[1]}] if hit else [], "total": 1 if hit else 0}

    @app.get("/materials/units-of-measure")
    async def units(jwt: dict = Depends(get_current_user)):
        note("GET", "/materials/units-of-measure", jwt)
        return [{"id": BAG, "code": "bag"}, {"id": NOS, "code": "nos"}]

    @app.post("/materials/inflows", status_code=201)
    async def inflow(body: Inflow, jwt: dict = Depends(get_current_user),
                     idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
        note("POST", "/materials/inflows", jwt, idempotency_key)
        if refuse_tmt and str(body.material_id) == TMT:
            from fastapi import HTTPException

            raise HTTPException(status_code=403, detail="Not authorized for this site")
        return {"id": str(uuid.uuid4()), "status": "created", "quantity": body.quantity}

    return app


def stand_in_tools(app: FastAPI):  # noqa: ANN201
    return build_tools(app.openapi(), tuple(a for a in ALLOWED if a.name in STAND_IN_TOOLS))


def receipt_call(material: str, unit: str, line: str) -> tuple[str, dict]:
    return ("record_receipt", {
        "project_id": PROJECT, "site_id": SITE, "material_id": material, "unit_id": unit,
        "quantity": 50, "occurred_date": "2026-11-01", CONFIRM_ARG: line,
    })


def two_receipts_model() -> FakeToolCallingProvider:
    return FakeToolCallingProvider([
        [("list_projects", {}), ("search_materials", {"search": "cement"}),
         ("search_materials", {"search": "TMT"}), ("list_units", {})],
        [("list_sites", {"project_id": PROJECT})],
        [receipt_call(CEMENT, BAG, "50 bags cement, Green Villa"), receipt_call(TMT, NOS, "50 TMT bars, Green Villa")],
        "Ready: 50 bags cement and 50 TMT bars at Green Villa. Confirm to save.",
    ])
