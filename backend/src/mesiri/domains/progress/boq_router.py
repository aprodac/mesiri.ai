"""REST API for a project's Bill of Quantities (CC-02).

Mounted at /projects/{project_id}/boq:
  GET    ""                       sections with their current lines, money per line and totals
  POST   /sections                add a section ("Concrete work", "Ground floor")
  PATCH  /sections/{section_id}   rename, move to a site, change code or order
  DELETE /sections/{section_id}   remove a section and its lines (not when work is logged against it)
  POST   /sections/{section_id}/lines  add a line
  PATCH  /lines/{line_id}         change a line; a new planned quantity is a new revision
  DELETE /lines/{line_id}         remove a line and its history

The BOQ carries the company's rates and margins, so it is read and written by the
roles that see the company's spending (``may_view_expenses``: owner, admin, finance,
project manager), each within the projects they can reach. Who else sees rates is
decision D-CC4 (docs/plans/cost-control-plan.md), not settled here.
Plan: docs/plans/cost-control-plan.md section 5.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.authorization.context import AuthorizationContext
from mesiri.authorization.roles import may_view_expenses
from mesiri.domains.progress.boq import line_amounts, totals
from mesiri.domains.projects.router import get_auth_context
from mesiri.domains.shared.modules import require_module
from mesiri.infrastructure.postgres.dependency import get_db_conn
from mesiri.infrastructure.postgres.repositories.boq import PostgresBoqRepository

router = APIRouter(
    prefix="/projects/{project_id}/boq",
    tags=["boq"],
    dependencies=[Depends(require_module("dpr"))],
)

_Rate = Field(default=None, ge=0, max_digits=14, decimal_places=2)


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = " ".join(value.split())
    return value or None


class SectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    site_id: uuid.UUID | None = None
    code: str | None = Field(default=None, max_length=40)

    _clean_text = field_validator("name", "code")(_clean)


class SectionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    site_id: uuid.UUID | None = None
    code: str | None = Field(default=None, max_length=40)
    sort_order: int | None = None

    _clean_text = field_validator("name", "code")(_clean)


class LineCreate(BaseModel):
    work: str = Field(min_length=1, max_length=300, description="What is built: 'M20 concrete in columns'")
    unit: str = Field(min_length=1, max_length=40, description="cum, sqft, sqm, rft, nos, kg ...")
    planned_quantity: Decimal = Field(gt=0, max_digits=14, decimal_places=3)
    boq_code: str | None = Field(default=None, max_length=40)
    client_rate: Decimal | None = _Rate
    labour_rate: Decimal | None = _Rate
    material_rate: Decimal | None = _Rate
    subcontract_rate: Decimal | None = _Rate

    _clean_text = field_validator("work", "unit", "boq_code")(_clean)


class LineUpdate(BaseModel):
    """Only the fields sent change; a rate sent as null becomes "not priced"."""

    work: str | None = Field(default=None, min_length=1, max_length=300)
    unit: str | None = Field(default=None, min_length=1, max_length=40)
    planned_quantity: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=3)
    revision_reason: str | None = Field(default=None, max_length=300)
    boq_code: str | None = Field(default=None, max_length=40)
    client_rate: Decimal | None = _Rate
    labour_rate: Decimal | None = _Rate
    material_rate: Decimal | None = _Rate
    subcontract_rate: Decimal | None = _Rate
    sort_order: int | None = None

    _clean_text = field_validator("work", "unit", "boq_code", "revision_reason")(_clean)


async def _scope(
    project_id: uuid.UUID, auth: AuthorizationContext, conn: AsyncConnection
) -> PostgresBoqRepository:
    """The BOQ repository, once the caller may see this project's money and the project is theirs."""
    if not may_view_expenses(auth.role):
        raise HTTPException(status_code=403, detail="Not authorized to see the BOQ and its rates")
    if not auth.project_scope.grants_all_org_projects and project_id not in auth.project_scope.project_ids:
        raise HTTPException(status_code=403, detail="Not authorized for this project")
    repo = PostgresBoqRepository(conn)
    if not await repo.project_exists(auth.organization_id, project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    return repo


async def _unit_id(conn: AsyncConnection, unit: str) -> uuid.UUID:
    from mesiri.infrastructure.postgres.repositories.materials import UnitsOfMeasureRepository

    row = await UnitsOfMeasureRepository(conn).resolve_alias(unit)
    if row is None or not row["is_active"]:
        raise HTTPException(status_code=422, detail=f"'{unit}' is not a unit Mesiri knows (try cum, sqft, rft, nos, kg)")
    return row["id"]


async def _check_site(repo: PostgresBoqRepository, project_id: uuid.UUID, site_id: uuid.UUID | None) -> None:
    if site_id is not None and not await repo.site_in_project(project_id, site_id):
        raise HTTPException(status_code=422, detail="site_id is not a site of this project")


def _exact(value):
    """Money and quantities as exact strings ("756000.00"), as the other money APIs send them; never floats."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {k: _exact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_exact(v) for v in value]
    return value


def _line_out(line: dict) -> dict:
    return {
        "id": line["id"],
        "section_id": line["work_package_id"],
        "boq_code": line["boq_code"],
        "work": line["work_type"],
        "unit": line["unit"],
        "unit_name": line["unit_name"],
        "planned_quantity": line["planned_quantity"],
        "client_rate": line["client_rate"],
        "labour_rate": line["labour_rate"],
        "material_rate": line["material_rate"],
        "subcontract_rate": line["subcontract_rate"],
        "revision_no": line["revision_no"],
        "sort_order": line["sort_order"],
        **line_amounts(line),
    }


async def _boq(repo: PostgresBoqRepository, organization_id: uuid.UUID, project_id: uuid.UUID) -> dict:
    sections = await repo.list_sections(organization_id, project_id)
    lines = [_line_out(ln) for ln in await repo.list_lines(organization_id, project_id)]
    out = []
    for section in sections:
        own = [ln for ln in lines if ln["section_id"] == section["id"]]
        out.append({**section, "lines": own, "totals": totals(own)})
    return _exact({"project_id": project_id, "sections": out, "totals": totals(lines)})


async def _check_code(
    repo: PostgresBoqRepository, project_id: uuid.UUID, code: str | None, exclude: uuid.UUID | None = None
) -> None:
    if code is not None and await repo.code_taken(project_id, code, exclude):
        raise HTTPException(status_code=409, detail=f"Another section of this project already has the code '{code}'")


async def _duplicate_check(
    repo: PostgresBoqRepository, section_id: uuid.UUID, work: str, unit_id: uuid.UUID, exclude: uuid.UUID | None = None
) -> None:
    if await repo.current_line_with(section_id, work, unit_id, exclude):
        raise HTTPException(status_code=409, detail=f"'{work}' in this unit is already a line in this section")


@router.get("")
async def get_boq(
    project_id: uuid.UUID,
    auth: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    repo = await _scope(project_id, auth, conn)
    return await _boq(repo, auth.organization_id, project_id)


@router.post("/sections", status_code=201)
async def create_section(
    project_id: uuid.UUID,
    body: SectionCreate,
    auth: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    repo = await _scope(project_id, auth, conn)
    await _check_site(repo, project_id, body.site_id)
    await _check_code(repo, project_id, body.code)
    section_id = await repo.create_section(
        auth.organization_id, project_id, body.name, body.site_id, body.code, auth.user_id
    )
    return await repo.get_section(auth.organization_id, project_id, section_id)


@router.patch("/sections/{section_id}")
async def update_section(
    project_id: uuid.UUID,
    section_id: uuid.UUID,
    body: SectionUpdate,
    auth: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    repo = await _scope(project_id, auth, conn)
    if await repo.get_section(auth.organization_id, project_id, section_id) is None:
        raise HTTPException(status_code=404, detail="Section not found")
    changes = body.model_dump(exclude_unset=True)
    if "name" in changes and changes["name"] is None:
        raise HTTPException(status_code=422, detail="A section needs a name")
    await _check_site(repo, project_id, changes.get("site_id"))
    await _check_code(repo, project_id, changes.get("code"), exclude=section_id)
    await repo.update_section(section_id, changes)
    return await repo.get_section(auth.organization_id, project_id, section_id)


@router.delete("/sections/{section_id}", status_code=204)
async def delete_section(
    project_id: uuid.UUID,
    section_id: uuid.UUID,
    auth: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    repo = await _scope(project_id, auth, conn)
    if await repo.get_section(auth.organization_id, project_id, section_id) is None:
        raise HTTPException(status_code=404, detail="Section not found")
    if await repo.section_has_activities(section_id):
        raise HTTPException(status_code=409, detail="Work has been logged against this section; it can't be removed")
    await repo.delete_section(section_id)
    return Response(status_code=204)


@router.post("/sections/{section_id}/lines", status_code=201)
async def create_line(
    project_id: uuid.UUID,
    section_id: uuid.UUID,
    body: LineCreate,
    auth: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    repo = await _scope(project_id, auth, conn)
    if await repo.get_section(auth.organization_id, project_id, section_id) is None:
        raise HTTPException(status_code=404, detail="Section not found")
    unit_id = await _unit_id(conn, body.unit)
    await _duplicate_check(repo, section_id, body.work, unit_id)
    values = body.model_dump()
    values.update(work_type=values.pop("work"), unit_id=unit_id)
    line_id = await repo.create_line(auth.organization_id, section_id, values, auth.user_id)
    return _exact(_line_out(await repo.get_line(auth.organization_id, project_id, line_id)))


@router.patch("/lines/{line_id}")
async def update_line(
    project_id: uuid.UUID,
    line_id: uuid.UUID,
    body: LineUpdate,
    auth: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    repo = await _scope(project_id, auth, conn)
    line = await repo.get_line(auth.organization_id, project_id, line_id)
    if line is None:
        raise HTTPException(status_code=404, detail="Line not found")
    changes = body.model_dump(exclude_unset=True)
    quantity = changes.pop("planned_quantity", None)
    reason = changes.pop("revision_reason", None)
    for required in ("work", "unit", "sort_order"):
        if required in changes and changes[required] is None:
            raise HTTPException(status_code=422, detail=f"{required} can't be empty")
    if "work" in changes:
        changes["work_type"] = changes.pop("work")
    if "unit" in changes:
        changes["unit_id"] = await _unit_id(conn, changes.pop("unit"))
    if "work_type" in changes or "unit_id" in changes:
        await _duplicate_check(
            repo,
            line["work_package_id"],
            changes.get("work_type", line["work_type"]),
            changes.get("unit_id", line["unit_id"]),
            exclude=line["id"],
        )
    await repo.update_line(line["id"], changes)
    if quantity is not None and Decimal(quantity) != Decimal(line["planned_quantity"]):
        line_id = await repo.revise_quantity(auth.organization_id, line, quantity, reason, auth.user_id)
    return _exact(_line_out(await repo.get_line(auth.organization_id, project_id, line_id)))


@router.delete("/lines/{line_id}", status_code=204)
async def delete_line(
    project_id: uuid.UUID,
    line_id: uuid.UUID,
    auth: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    repo = await _scope(project_id, auth, conn)
    if await repo.get_line(auth.organization_id, project_id, line_id) is None:
        raise HTTPException(status_code=404, detail="Line not found")
    await repo.delete_line(line_id)
    return Response(status_code=204)


# -- import from Excel (ST-03) ------------------------------------------------------------------------------------------

class BoqImportFile(BaseModel):
    file_base64: str = Field(min_length=1, description="The .xlsx file, base64-encoded")
    file_name: str | None = None


def _sheet(body: BoqImportFile):
    import base64
    import binascii

    from mesiri.domains.progress.boq_import import ImportFileError, read_sheet

    try:
        data = base64.b64decode(body.file_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=422, detail="The file could not be read. Choose it again.") from exc
    try:
        return read_sheet(data)
    except ImportFileError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/import/template")
async def boq_import_template(project_id: uuid.UUID, auth: AuthorizationContext = Depends(get_auth_context),
                              conn: AsyncConnection = Depends(get_db_conn)):
    """The BOQ sheet to fill, with example rows; any estimate sheet with Work / Unit / Quantity columns also works."""
    from mesiri.domains.progress.boq_import import template_bytes

    await _scope(project_id, auth, conn)
    return Response(content=template_bytes(),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="mesiri-boq-import.xlsx"'})


@router.post("/import/preview")
async def boq_import_preview(project_id: uuid.UUID, body: BoqImportFile,
                             auth: AuthorizationContext = Depends(get_auth_context),
                             conn: AsyncConnection = Depends(get_db_conn)):
    """What importing this sheet would add, row by row, with nothing saved."""
    from mesiri.domains.progress.boq_import import preview

    await _scope(project_id, auth, conn)
    return await preview(conn, auth.organization_id, project_id, auth.user_id, _sheet(body))


@router.post("/import")
async def boq_import(project_id: uuid.UUID, body: BoqImportFile,
                     auth: AuthorizationContext = Depends(get_auth_context),
                     conn: AsyncConnection = Depends(get_db_conn)):
    """Import the sheet: sections, lines with their rates, and the sections' dates and links for the schedule.
    Lines already in the BOQ are left as they are, so it is safe to run again."""
    from mesiri.domains.progress.boq_import import run

    await _scope(project_id, auth, conn)
    return await run(conn, auth.organization_id, project_id, auth.user_id, _sheet(body))
