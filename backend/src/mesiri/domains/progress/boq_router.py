"""REST API for a project's Bill of Quantities (CC-02).

Mounted at /projects/{project_id}/boq:
  GET    ""                       sections with their current lines, money per line and totals
  POST   /sections                add a section ("Concrete work", "Ground floor")
  PATCH  /sections/{section_id}   rename, move to a site, change code or order
  DELETE /sections/{section_id}   remove a section and its lines (not when work is logged against it)
  POST   /sections/{section_id}/lines  add a line
  PATCH  /lines/{line_id}         change a line; a new planned quantity is a new revision
  DELETE /lines/{line_id}         remove a line and its history
  GET    /work                    the project's recorded work quantities and the line each is on (CC-04)
  PUT    /work/{quantity_id}      put a work quantity on a line, or take it off (line_id null)
  PUT    /lines/{line_id}/norms   the materials one unit of the line uses (MP-01), replacing the line's set
  POST   /lines/{line_id}/norms/copy  the same norms onto the project's other lines of the same work and unit
  POST   /from-drawing            DR-06: a drawing's draft quantities added as unpriced lines (never overwrites)

Each line carries ``materials``: its norms (material, quantity per unit of the line, wastage %), read by the
material plan (MP-02, docs/plans/material-plan-plan.md).

Each line also carries the work done against it (CC-04): site work updates put on the line
plus confirmed work-order measurements that did not come from one, each counted once, in the
line's own unit; and the budget that work earned (``boq.line_progress``).

The BOQ carries the company's rates and margins, so it is read and written by the
roles that see the company's spending (``may_view_expenses``: owner, admin, finance,
project manager), each within the projects they can reach. Who else sees rates is
decision D-CC4 (docs/plans/cost-control-plan.md), not settled here.
Plan: docs/plans/cost-control-plan.md section 5.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.authorization.context import AuthorizationContext
from mesiri.authorization.roles import may_view_expenses
from mesiri.domains.progress.boq import line_amounts, line_progress, suggest_line, totals
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


async def _counted_work(
    repo: PostgresBoqRepository, organization_id: uuid.UUID, project_id: uuid.UUID, lines: list[dict]
) -> list[dict]:
    """Every quantity counted on a current line, once each: line, day, site, and the quantity in the line's own
    unit, or None when it was recorded in another unit (never converted; counted as "other unit").

    The one rule for work done per line: ``_done_by_line`` (to date) and cost control's daily variance (CC-07,
    per day) both read it, so the two can never disagree.
    """
    from mesiri.infrastructure.postgres.repositories.materials import UnitsOfMeasureRepository

    current = await repo.current_revision_of(organization_id, project_id)
    unit_of = {ln["id"]: ln["unit_id"] for ln in lines}
    units = UnitsOfMeasureRepository(repo.conn)
    resolved: dict[str, uuid.UUID | None] = {}
    out = []
    for row in await repo.work_done(organization_id, project_id):
        line_id = current.get(row["item_id"], row["item_id"])
        if line_id not in unit_of:
            continue
        unit_id = row["unit_id"]
        if unit_id is None:
            if row["unit_text"] not in resolved:
                found = await units.resolve_alias(row["unit_text"] or "")
                resolved[row["unit_text"]] = found["id"] if found else None
            unit_id = resolved[row["unit_text"]]
        out.append({
            "line_id": line_id, "work_date": row["work_date"], "site_id": row["site_id"],
            "quantity": Decimal(row["quantity"]) if unit_id == unit_of[line_id] else None,
        })
    return out


async def _done_by_line(
    repo: PostgresBoqRepository, organization_id: uuid.UUID, project_id: uuid.UUID, lines: list[dict]
) -> dict[uuid.UUID, dict]:
    """Per current line: the quantity done in its own unit, and how many records were in another unit.

    A record in another unit is never added in (no conversion): it is counted as "other unit"
    so the page can say some work could not be added up.
    """
    out: dict[uuid.UUID, dict] = {ln["id"]: {"done": Decimal(0), "other_unit": 0} for ln in lines}
    for w in await _counted_work(repo, organization_id, project_id, lines):
        if w["quantity"] is None:
            out[w["line_id"]]["other_unit"] += 1
        else:
            out[w["line_id"]]["done"] += w["quantity"]
    return out


#: ST-04: the schedule's progress reads the same "done" as this page (one rule for work done per line).
done_by_line = _done_by_line
#: CC-07: the same count, per line, day and site.
counted_work = _counted_work


def _norm_out(n: dict) -> dict:
    return {
        "material_id": n["material_id"], "material": n["material"], "unit": n["unit"],
        "quantity_per_unit": n["quantity_per_unit"], "wastage_pct": n["wastage_pct"], "note": n["note"],
    }


async def _boq(repo: PostgresBoqRepository, organization_id: uuid.UUID, project_id: uuid.UUID) -> dict:
    from mesiri.infrastructure.postgres.repositories.material_norms import MaterialNormRepository

    sections = await repo.list_sections(organization_id, project_id)
    raw = await repo.list_lines(organization_id, project_id)
    done = await _done_by_line(repo, organization_id, project_id, raw)
    norms = await MaterialNormRepository(repo.conn).for_project(organization_id, project_id)
    lines = [
        {**_line_out(ln), **line_progress(ln, done[ln["id"]]["done"]), "done_in_other_unit": done[ln["id"]]["other_unit"],
         "materials": [_norm_out(n) for n in norms.get(ln["id"], [])]}
        for ln in raw
    ]
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


async def _billed(repo: PostgresBoqRepository, where: str, key: uuid.UUID) -> bool:
    """NXT-02: a BOQ line (any revision of it) that is on an RA bill stays: the bill points at it."""
    from sqlalchemy import text

    rows = await repo.conn.execute(text(
        "WITH RECURSIVE chain(id) AS (SELECT CAST(:id AS uuid) UNION SELECT i.id FROM work_package_planned_items i "
        "JOIN chain c ON i.superseded_by_id = c.id WHERE i.id <> c.id) "
        f"SELECT EXISTS (SELECT 1 FROM ra_bill_lines l WHERE l.planned_item_id IN (SELECT id FROM "  # noqa: S608
        f"work_package_planned_items WHERE {where}))"), {"id": key})
    return bool(rows.scalar())


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
    if await _billed(repo, "work_package_id = :id", section_id):
        raise HTTPException(status_code=409, detail="A line of this section is on an RA bill; it can't be removed")
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
    if await _billed(repo, "id IN (SELECT id FROM chain)", line_id):
        raise HTTPException(status_code=409, detail="This line is on an RA bill; it can't be removed (change it instead)")
    await repo.delete_line(line_id)
    return Response(status_code=204)


class NormIn(BaseModel):
    material_id: uuid.UUID
    quantity_per_unit: Decimal = Field(gt=0, max_digits=14, decimal_places=4,
                                       description="Material used by one unit of the line: 8 (bags per m³)")
    wastage_pct: Decimal = Field(default=Decimal(0), ge=0, le=100, max_digits=5, decimal_places=2)
    note: str | None = Field(default=None, max_length=300)

    _clean_text = field_validator("note")(_clean)


class NormsIn(BaseModel):
    norms: list[NormIn] = Field(default_factory=list, max_length=30)


class NormCopy(BaseModel):
    overwrite: bool = Field(default=False, description="Also replace lines that already have their own norms")


async def _norm_rows(conn: AsyncConnection, organization_id: uuid.UUID, body: NormsIn) -> list[dict]:
    """Check the norms; 422 with a plain reason when one can't be used. A norm is in the material's stock unit."""
    from mesiri.infrastructure.postgres.repositories.material_norms import MaterialNormRepository

    ids = [n.material_id for n in body.norms]
    if len(set(ids)) != len(ids):
        raise HTTPException(status_code=422, detail="A material is listed twice for this line; give it once")
    found = await MaterialNormRepository(conn).materials(organization_id, ids)
    rows = []
    for n in body.norms:
        material = found.get(n.material_id)
        if material is None:
            raise HTTPException(status_code=422, detail="One of the materials is not in your material list")
        if not material["is_active"]:
            raise HTTPException(status_code=422, detail=f"'{material['name']}' is switched off in your material list")
        # Always the material's stock unit, so the plan compares need with stock without converting anything.
        rows.append({**n.model_dump(), "unit_id": material["default_unit_id"]})
    return rows


@router.put("/lines/{line_id}/norms")
async def put_line_norms(
    project_id: uuid.UUID,
    line_id: uuid.UUID,
    body: NormsIn,
    auth: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """MP-01: the materials one unit of this line uses. Replaces the line's whole list; an empty list clears it."""
    from mesiri.infrastructure.postgres.repositories.material_norms import MaterialNormRepository

    repo = await _scope(project_id, auth, conn)
    if await repo.get_line(auth.organization_id, project_id, line_id) is None:
        raise HTTPException(status_code=404, detail="Line not found")
    rows = await _norm_rows(conn, auth.organization_id, body)
    norms = MaterialNormRepository(conn)
    await norms.replace(auth.organization_id, line_id, rows, auth.user_id)
    return _exact({"line_id": line_id, "materials": [_norm_out(n) for n in await norms.for_line(auth.organization_id, line_id)]})


@router.post("/lines/{line_id}/norms/copy")
async def copy_line_norms(
    project_id: uuid.UUID,
    line_id: uuid.UUID,
    body: NormCopy,
    auth: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """MP-01: the same norms onto the project's other current lines of the same work and unit ("M20 in columns" on
    every floor). Lines with their own norms are left alone unless ``overwrite``."""
    from mesiri.infrastructure.postgres.repositories.material_norms import MaterialNormRepository

    repo = await _scope(project_id, auth, conn)
    line = await repo.get_line(auth.organization_id, project_id, line_id)
    if line is None:
        raise HTTPException(status_code=404, detail="Line not found")
    norms = MaterialNormRepository(conn)
    source = await norms.for_line(auth.organization_id, line_id)
    if not source:
        raise HTTPException(status_code=422, detail="This line has no materials to copy yet")
    copied, kept = [], []
    for other in await norms.lines_like(auth.organization_id, project_id, line):
        if other["has_norms"] and not body.overwrite:
            kept.append(other["id"])
            continue
        await norms.replace(auth.organization_id, other["id"], source, auth.user_id)
        copied.append(other["id"])
    return {"copied_to": [str(i) for i in copied], "kept": [str(i) for i in kept]}


class WorkLine(BaseModel):
    line_id: uuid.UUID | None = Field(description="The BOQ line this work is on; null takes it off")


@router.get("/work")
async def list_work(
    project_id: uuid.UUID,
    unlinked: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
    auth: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Recorded work quantities, newest first; each with its line, or a suggested one to confirm.

    The suggestion is only offered, never saved: a person puts the work on a line.
    """
    repo = await _scope(project_id, auth, conn)
    lines = await repo.list_lines(auth.organization_id, project_id)
    current = await repo.current_revision_of(auth.organization_id, project_id)
    out = []
    for w in await repo.work_updates(auth.organization_id, project_id, unlinked_only=unlinked, limit=limit):
        line_id = current.get(w["line_id"], w["line_id"]) if w["line_id"] else None
        out.append({
            "id": w["id"], "date": w["activity_date"], "site_id": w["site_id"], "site_name": w["site_name"],
            "work": w["work"] or w["narrative"], "quantity": w["quantity"], "unit": w["unit"],
            "line_id": line_id, "on_work_order": w["work_order_line_id"] is not None,
            "suggested_line_id": None if line_id else suggest_line(w["work"] or w["narrative"], w["unit_id"], w["section_id"], lines),
        })
    return _exact({"project_id": project_id, "work": out})


@router.put("/work/{quantity_id}", status_code=204)
async def put_work_on_line(
    project_id: uuid.UUID,
    quantity_id: uuid.UUID,
    body: WorkLine,
    auth: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """Count a recorded work quantity on a BOQ line (or take it off). One line per quantity, so never twice.

    Refused when the line is in another unit (no conversion), and when the work is counted
    through a work order (it is changed there, so the two never disagree).
    """
    repo = await _scope(project_id, auth, conn)
    work = await repo.get_work_update(auth.organization_id, project_id, quantity_id)
    if work is None:
        raise HTTPException(status_code=404, detail="Work update not found")
    if work["work_order_line_id"] is not None:
        raise HTTPException(status_code=409, detail="This work is counted on a work order; change it on the work order.")
    if body.line_id is not None:
        line = await repo.get_line(auth.organization_id, project_id, body.line_id)
        if line is None:
            raise HTTPException(status_code=422, detail="That BOQ line is not in this project.")
        if line["unit_id"] != work["unit_id"]:
            raise HTTPException(
                status_code=422,
                detail=f"That line is measured in {line['unit']}; this work is in another unit, so it can't be added to it.",
            )
    await repo.set_work_line(quantity_id, body.line_id)
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


class DraftLine(BaseModel):
    work: str = Field(min_length=1, max_length=300)
    unit: str = Field(min_length=1, max_length=40)
    quantity: Decimal = Field(gt=0, max_digits=14, decimal_places=3)

    _clean_text = field_validator("work", "unit")(_clean)


class DraftSection(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    lines: list[DraftLine] = Field(default_factory=list, max_length=200)

    _clean_text = field_validator("name")(_clean)


class FromDrawing(BaseModel):
    sections: list[DraftSection] = Field(min_length=1, max_length=50)


@router.post("/from-drawing")
async def boq_from_drawing(
    project_id: uuid.UUID,
    body: FromDrawing,
    auth: AuthorizationContext = Depends(get_auth_context),
    conn: AsyncConnection = Depends(get_db_conn),
):
    """DR-06: quantities drafted from a drawing set (Planning > Drawing check), as edited, added to the BOQ: a
    section per floor (the existing one when the name matches), each line unpriced. A line whose work and unit the
    section already has is left as it is and reported as skipped (D-DR2: never overwrites)."""
    from sqlalchemy import text

    repo = await _scope(project_id, auth, conn)
    org = auth.organization_id
    added = skipped = 0
    for sec in body.sections:
        section_id = (await conn.execute(text(
            "SELECT id FROM work_packages WHERE organization_id = :org AND project_id = :p AND lower(name) = lower(:n) "
            "ORDER BY created_at LIMIT 1"), {"org": org, "p": project_id, "n": sec.name})).scalar()
        if section_id is None:
            section_id = await repo.create_section(org, project_id, sec.name, None, None, auth.user_id)
            # Dated like the floor's finishing work in the schedule (DR-05's "<floor>: masonry / plastering /
            # flooring"), so it sits on the Gantt with them and the material plan can spread its need. DR-09: the
            # "Foundation" section (a structural set's footings) takes the excavation and footings' dates.
            span = (await conn.execute(text(
                "SELECT min(planned_start), max(planned_end) FROM work_packages WHERE organization_id = :org "
                "AND project_id = :p AND (lower(name) IN (lower(:n) || ': masonry', lower(:n) || ': plastering', "
                "lower(:n) || ': flooring') OR (lower(:n) = 'foundation' AND lower(name) IN ('excavation', "
                "'footings and columns up to plinth'))) AND planned_start IS NOT NULL"),
                {"org": org, "p": project_id, "n": sec.name})).one()
            if span[0] is not None:
                await conn.execute(text("UPDATE work_packages SET planned_start = :s, planned_end = :e WHERE id = :id"),
                                   {"s": span[0], "e": span[1], "id": section_id})
        for ln in sec.lines:
            unit_id = await _unit_id(conn, ln.unit)
            if await repo.current_line_with(section_id, ln.work, unit_id):
                skipped += 1
                continue
            await repo.create_line(org, section_id, {"work_type": ln.work, "unit_id": unit_id,
                                                     "planned_quantity": ln.quantity}, auth.user_id)
            added += 1
    return {"added": added, "skipped": skipped, **_exact(await _boq(repo, org, project_id))}
