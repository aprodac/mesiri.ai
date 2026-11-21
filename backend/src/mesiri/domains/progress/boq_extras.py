"""The BOQ the way construction ERPs keep it (PS phase 2b, migration 0566). Every function takes the request's
connection and never commits.

- **Quantities per site** (``boq_line_sites``): "plastering 1,450 sqm" split into Villa 1..4. A line with no split is for
  the whole project. A split always adds up to the line's quantity (refused otherwise), and each site's work done comes
  from the same counted work as the line's (``boq_router.counted_work``), so per-site and whole-line progress agree.
- **The approved budget** (``boq_baselines``): the BOQ as it stood when locked, lines and totals copied. Later changes
  are read against it, line by line (matched on item no., work and unit) and in total.
- **The rate library** (``boq_library_items``): a line saved once with its rates and materials per unit, added to any
  project's BOQ later.
- **Export**: the BOQ as an .xlsx the client can read and the import can read back.
"""

from __future__ import annotations

import io
import json
import uuid
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text

RATES = ("client_rate", "labour_rate", "material_rate", "subcontract_rate", "machinery_rate", "other_rate")


# -- quantities per site ------------------------------------------------------------------------------------------

async def sites_by_line(conn: Any, org: uuid.UUID, project_id: uuid.UUID) -> dict[uuid.UUID, list[dict]]:
    """Each current line's split by site, in site-name order."""
    rows = (await conn.execute(text(
        "SELECT ls.planned_item_id AS line_id, ls.site_id, s.name AS site, ls.quantity "
        "FROM boq_line_sites ls JOIN sites s ON s.id = ls.site_id "
        "JOIN work_package_planned_items i ON i.id = ls.planned_item_id JOIN work_packages w ON w.id = i.work_package_id "
        "WHERE ls.organization_id = :org AND w.project_id = :p AND i.superseded_by_id IS NULL ORDER BY lower(s.name)"),
        {"org": org, "p": project_id})).mappings().all()
    out: dict[uuid.UUID, list[dict]] = {}
    for r in rows:
        out.setdefault(r["line_id"], []).append({"site_id": r["site_id"], "site": r["site"], "quantity": r["quantity"]})
    return out


async def set_line_sites(conn: Any, org: uuid.UUID, project_id: uuid.UUID, line_id: uuid.UUID,
                         planned: Decimal, split: list[dict]) -> None:
    """The line's split becomes ``split`` ({site_id, quantity}); an empty list makes it a whole-project line again.

    Refused: a site of another project, a site twice, or a split that does not add up to the line's quantity.
    """
    ids = [uuid.UUID(str(s["site_id"])) for s in split]
    if len(set(ids)) != len(ids):
        raise HTTPException(status_code=422, detail="A site is in the split twice")
    if ids:
        found = set((await conn.execute(text(
            "SELECT id FROM sites WHERE organization_id = :org AND project_id = :p AND id = ANY(:ids)"),
            {"org": org, "p": project_id, "ids": ids})).scalars().all())
        if found != set(ids):
            raise HTTPException(status_code=422, detail="One of the sites is not a site of this project")
        total = sum((Decimal(str(s["quantity"])) for s in split), Decimal(0))
        if abs(total - Decimal(planned)) > Decimal("0.001"):
            raise HTTPException(status_code=422, detail=(
                f"The sites add up to {_plain(total)}, the line is {_plain(Decimal(planned))}: they must match"))
    await conn.execute(text("DELETE FROM boq_line_sites WHERE organization_id = :org AND planned_item_id = :l"),
                       {"org": org, "l": line_id})
    for s in split:
        await conn.execute(text(
            "INSERT INTO boq_line_sites (organization_id, planned_item_id, site_id, quantity) VALUES (:org, :l, :s, :q)"),
            {"org": org, "l": line_id, "s": uuid.UUID(str(s["site_id"])), "q": Decimal(str(s["quantity"]))})


def _plain(value: Decimal) -> str:
    return format(value.normalize(), "f")


def done_by_line_site(work: list[dict]) -> dict[tuple[uuid.UUID, uuid.UUID], Decimal]:
    """Work done per (line, site), from the counted work; work in another unit is left out, as for the line."""
    out: dict[tuple[uuid.UUID, uuid.UUID], Decimal] = {}
    for w in work:
        if w["quantity"] is None or w["site_id"] is None:
            continue
        key = (w["line_id"], w["site_id"])
        out[key] = out.get(key, Decimal(0)) + w["quantity"]
    return out


# -- the approved budget --------------------------------------------------------------------------------------------

def line_key(line: dict) -> str:
    """How a line is found again in a baseline: item no., work and unit (ids change with each quantity revision)."""
    return f"{(line.get('boq_code') or '').strip().lower()}|{' '.join(str(line.get('work') or '').lower().split())}|" \
           f"{line.get('unit') or ''}"


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    return value


async def lock_baseline(conn: Any, org: uuid.UUID, project_id: uuid.UUID, user_id: uuid.UUID, boq: dict,
                        name: str | None, note: str | None) -> dict:
    """Copy the BOQ as it is now as the approved budget ("Budget v1", "v2" ...)."""
    count = (await conn.execute(text("SELECT count(*) FROM boq_baselines WHERE organization_id = :org AND project_id = :p"),
                                {"org": org, "p": project_id})).scalar() or 0
    lines = [{"key": line_key(ln), "boq_code": ln.get("boq_code"), "work": ln["work"], "unit": ln["unit"],
              "planned_quantity": ln["planned_quantity"], "client_rate": ln["client_rate"],
              "budget_rate": ln["budget_rate"], "contract_value": ln["contract_value"], "budget_cost": ln["budget_cost"]}
             for sec in boq["sections"] for ln in sec["lines"]]
    totals = {k: boq["totals"].get(k) for k in ("contract_value", "budget_cost", "margin", "priced_margin", "line_count")}
    row = (await conn.execute(text(
        "INSERT INTO boq_baselines (organization_id, project_id, name, note, totals, lines, locked_by) "
        "VALUES (:org, :p, :n, :note, CAST(:t AS jsonb), CAST(:l AS jsonb), :by) RETURNING id, name, locked_at"),
        {"org": org, "p": project_id, "n": (name or "").strip() or f"Budget v{count + 1}", "note": note,
         "t": json.dumps(_jsonable(totals)), "l": json.dumps(_jsonable(lines)), "by": user_id})).mappings().one()
    return dict(row)


async def latest_baseline(conn: Any, org: uuid.UUID, project_id: uuid.UUID) -> dict | None:
    row = (await conn.execute(text(
        "SELECT b.id, b.name, b.note, b.totals, b.lines, b.locked_at, u.full_name AS locked_by "
        "FROM boq_baselines b LEFT JOIN users u ON u.id = b.locked_by "
        "WHERE b.organization_id = :org AND b.project_id = :p ORDER BY b.locked_at DESC LIMIT 1"),
        {"org": org, "p": project_id})).mappings().first()
    return dict(row) if row else None


def compare_with_baseline(boq: dict, baseline: dict | None) -> dict | None:
    """Each line gets ``baseline`` ({planned_quantity, client_rate, budget_rate, budget_cost, contract_value}, or None
    for a line added since); the result says the approved and current totals and how many lines changed."""
    if baseline is None:
        return None
    lines = baseline["lines"] if isinstance(baseline["lines"], list) else json.loads(baseline["lines"])
    totals = baseline["totals"] if isinstance(baseline["totals"], dict) else json.loads(baseline["totals"])
    by_key = {b["key"]: b for b in lines}
    seen: set[str] = set()
    changed = added = 0
    for sec in boq["sections"]:
        for ln in sec["lines"]:
            key = line_key(ln)
            was = by_key.get(key)
            ln["baseline"] = {k: was.get(k) for k in ("planned_quantity", "client_rate", "budget_rate", "budget_cost",
                                                     "contract_value")} if was else None
            if was is None:
                added += 1
            else:
                seen.add(key)
                if any(str(Decimal(str(was.get(k) or 0))) != str(Decimal(str(ln.get(k) or 0)))
                       for k in ("planned_quantity", "client_rate", "budget_rate")):
                    changed += 1
    removed = len([k for k in by_key if k not in seen])
    return {"id": baseline["id"], "name": baseline["name"], "note": baseline.get("note"),
            "locked_at": baseline["locked_at"], "locked_by": baseline.get("locked_by"),
            "contract_value": totals.get("contract_value"), "budget_cost": totals.get("budget_cost"),
            "lines_changed": changed, "lines_added": added, "lines_removed": removed}


# -- the rate library -----------------------------------------------------------------------------------------------

async def library(conn: Any, org: uuid.UUID) -> list[dict]:
    rows = (await conn.execute(text(
        f"SELECT l.id, l.work, l.unit_id, u.code AS unit, {', '.join('l.' + r for r in RATES)}, l.materials "  # noqa: S608
        "FROM boq_library_items l JOIN units_of_measure u ON u.id = l.unit_id "
        "WHERE l.organization_id = :org ORDER BY lower(l.work)"), {"org": org})).mappings().all()
    return [dict(r) for r in rows]


async def save_to_library(conn: Any, org: uuid.UUID, line: dict, norms: list[dict], user_id: uuid.UUID) -> dict:
    """Save (or refresh) the line in the company's library: same work and unit replaces the saved rates."""
    materials = [{"material_id": str(n["material_id"]), "unit_id": str(n["unit_id"]),
                  "quantity_per_unit": str(n["quantity_per_unit"]), "wastage_pct": str(n.get("wastage_pct") or 0)}
                 for n in norms]
    row = (await conn.execute(text(
        f"INSERT INTO boq_library_items (organization_id, work, unit_id, {', '.join(RATES)}, materials, created_by) "  # noqa: S608
        f"VALUES (:org, :work, :unit, {', '.join(':' + r for r in RATES)}, CAST(:m AS jsonb), :by) "
        "ON CONFLICT (organization_id, lower(work), unit_id) DO UPDATE SET "
        f"{', '.join(f'{r} = EXCLUDED.{r}' for r in RATES)}, materials = EXCLUDED.materials, updated_at = now() "
        "RETURNING id, work"),
        {"org": org, "work": line["work_type"], "unit": line["unit_id"], **{r: line.get(r) for r in RATES},
         "m": json.dumps(materials), "by": user_id})).mappings().one()
    return dict(row)


async def library_item(conn: Any, org: uuid.UUID, item_id: uuid.UUID) -> dict:
    row = (await conn.execute(text(
        f"SELECT id, work, unit_id, {', '.join(RATES)}, materials FROM boq_library_items "  # noqa: S608
        "WHERE organization_id = :org AND id = :id"), {"org": org, "id": item_id})).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="That item is not in your rate library")
    return dict(row)


async def delete_library_item(conn: Any, org: uuid.UUID, item_id: uuid.UUID) -> None:
    await conn.execute(text("DELETE FROM boq_library_items WHERE organization_id = :org AND id = :id"),
                       {"org": org, "id": item_id})


# -- export ---------------------------------------------------------------------------------------------------------

def export_xlsx(boq: dict, project: str, client: str | None, gst_pct: Decimal | None, with_costs: bool) -> bytes:
    """The BOQ as the client reads it (item no., description, unit, quantity, rate, amount, GST), and with
    ``with_costs`` our own cost split and margin too. Headers the import knows, so the file can be read back."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    book = Workbook()
    sheet = book.active
    sheet.title = "BOQ"
    bold = Font(bold=True)
    fill = PatternFill("solid", fgColor="EEEAE0")
    sheet.append([f"{project}: Bill of Quantities"])
    sheet["A1"].font = Font(bold=True, size=13)
    if client:
        sheet.append([f"Client: {client}"])
    sheet.append([])
    head = ["Item no.", "Description", "Unit", "Qty", "Rate", "Amount"]
    if with_costs:
        head += ["Labour rate", "Material rate", "Subcontract rate", "Machinery rate", "Other rate", "Cost per unit",
                 "Budget cost", "Margin"]
    sheet.append(head)
    for cell in sheet[sheet.max_row]:
        cell.font = bold
        cell.fill = fill

    def n(value: Any) -> float | None:
        return float(value) if value not in (None, "") else None

    for sec in boq["sections"]:
        if not sec["lines"]:
            continue
        sheet.append([sec.get("code") or "", sec["name"]])
        sheet.cell(sheet.max_row, 2).font = bold
        for ln in sec["lines"]:
            row = [ln.get("boq_code") or "", ln["work"] + (" (provisional sum)" if ln.get("is_provisional") else ""),
                   ln["unit"], n(ln["planned_quantity"]), n(ln["client_rate"]), n(ln["contract_value"])]
            if with_costs:
                row += [n(ln.get(r)) for r in RATES[1:]] + [n(ln["budget_rate"]), n(ln["budget_cost"]), n(ln["margin"])]
            sheet.append(row)
        total = [""] * len(head)
        total[1] = f"Total {sec['name']}"
        total[5] = n(sec["totals"]["contract_value"])
        if with_costs:
            total[-2] = n(sec["totals"]["budget_cost"])
            total[-1] = n(sec["totals"].get("margin") if sec["totals"].get("margin") is not None
                          else sec["totals"].get("priced_margin"))
        sheet.append(total)
        for cell in sheet[sheet.max_row]:
            cell.font = bold
    sheet.append([])
    grand = Decimal(str(boq["totals"]["contract_value"] or 0))
    sheet.append(["", "Total (before GST)", "", "", "", float(grand)])
    if gst_pct:
        gst = (grand * Decimal(gst_pct) / 100).quantize(Decimal("0.01"))
        sheet.append(["", f"GST {Decimal(gst_pct).normalize()}%", "", "", "", float(gst)])
        sheet.append(["", "Total with GST", "", "", "", float(grand + gst)])
    for row in sheet.iter_rows(min_row=sheet.max_row - 2):
        for cell in row:
            cell.font = bold
    widths = {"A": 9, "B": 46, "C": 8, "D": 11, "E": 12, "F": 15}
    for col, w in widths.items():
        sheet.column_dimensions[col].width = w
    for col in "GHIJKLMN":
        sheet.column_dimensions[col].width = 14
    for row in sheet.iter_rows(min_row=4):
        for cell in row[3:]:
            if isinstance(cell.value, float):
                cell.number_format = "#,##,##0.00"
                cell.alignment = Alignment(horizontal="right")
    buf = io.BytesIO()
    book.save(buf)
    return buf.getvalue()
