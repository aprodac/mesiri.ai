"""The BOQ from Excel (ST-03, part of CC-13): the estimate sheet a contractor already has becomes the BOQ, the budget
and the first schedule.

Typing a 200-line BOQ again is the reason software is not used; the import takes the sheet as it is.

**What it reads.** The first sheet named like "BOQ" (else the first sheet with a header row). The header row is found
in the first 25 rows by its words, in any order and case:

- Work (also Description, Particulars, Item description), Unit (UOM), Quantity (Qty)
- Item no. (S.No, Sl No, Code), Section (Part, Head, Trade): optional
- Client rate (Rate, Unit rate, Quoted rate), Labour rate, Material rate, Subcontract rate: optional
- Start, Finish (End), Starts after: optional, for the schedule

Real estimates have **heading rows** ("A. EARTHWORK", "Ground floor") with no quantity: each one starts a section
for the lines under it, unless a Section column says otherwise. Total and carried-forward rows are skipped. A line
needs work, unit and quantity; everything else is optional.

**What it does.** Each section is found by name or added; each line is added through the same repository as the BOQ
page's own button, so it refuses what the page refuses. A line already in the section (same work and unit) is left
as it is, so the import is safe to run again. Start / Finish on a heading or its lines give the section's dates;
Starts after links two sections. ``preview`` runs the same code in a savepoint it rolls back, so what the preview
says is what the import does.
"""

from __future__ import annotations

import datetime
import io
import re
import uuid
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection

MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 3000
MAX_LISTED = 600
HEADER_SCAN = 25

#: Canonical column -> the words a header may use (compared without case, spaces, dots or brackets).
ALIASES: dict[str, tuple[str, ...]] = {
    "work": ("work", "description", "particulars", "itemdescription", "descriptionofwork", "descriptionofitem",
             "workitem", "nameofwork", "item"),
    "unit": ("unit", "units", "uom", "unitofmeasure"),
    "quantity": ("quantity", "qty", "qnty", "quantities", "boqqty", "boqquantity"),
    "code": ("itemno", "itemnumber", "sno", "slno", "srno", "serialno", "no", "code", "boqcode", "ref", "boqno"),
    "section": ("section", "part", "head", "group", "trade", "chapter", "boqsection"),
    "client_rate": ("clientrate", "rate", "unitrate", "quotedrate", "raters", "rateinrs", "rate₹", "sellingrate"),
    "labour_rate": ("labourrate", "laborrate", "labour", "labor"),
    "material_rate": ("materialrate", "material"),
    "subcontract_rate": ("subcontractrate", "subcontract", "subcontractorrate"),
    "start": ("start", "startdate", "from", "plannedstart"),
    "finish": ("finish", "end", "enddate", "finishdate", "to", "plannedfinish", "plannedend"),
    "after": ("startsafter", "after", "predecessor", "dependson"),
}
TEMPLATE_COLUMNS = ("Section", "Item no.", "Work", "Unit", "Quantity", "Client rate", "Labour rate", "Material rate",
                    "Subcontract rate", "Start", "Finish", "Starts after")
_EXAMPLE = (
    ("Earthwork", "1.1", "Excavation in ordinary soil up to 1.5 m depth", "cum", 420, 260, 140, None, None,
     "2026-12-01", "2026-12-08", None),
    ("Earthwork", "1.2", "Backfilling with excavated earth in 15 cm layers", "cum", 180, 120, 70, None, None, None,
     None, None),
    ("Foundation", "2.1", "PCC 1:4:8 below footings", "cum", 38, 5600, 900, 3900, None, "2026-12-09", "2026-12-20",
     "Earthwork"),
    ("Foundation", "2.2", "RCC M25 in footings including shuttering", "cum", 96, 9200, 1600, 6100, None, None, None,
     None),
    ("Superstructure", "3.1", "Brickwork in CM 1:6, 230 mm walls", "cum", 310, 6800, 1900, 3800, None,
     "2026-12-21", "2027-02-10", "Foundation"),
    ("Finishing", "4.1", "Internal plastering 12 mm in CM 1:4", "sqft", 18000, 42, 14, 22, None, "2027-02-11",
     "2027-03-20", "Superstructure"),
)
_HOW_TO = (
    "How to fill this sheet (Mesiri BOQ import)",
    "",
    "Use your own estimate sheet if you like: Mesiri finds the columns by their names (Description, Qty, Unit, Rate...).",
    "One row per BOQ item: what is built (Work), its Unit (cum, sqft, sqm, rft, nos, kg) and the Quantity.",
    "Section groups the items (Earthwork, Ground floor, Electrical). Instead of a Section column you may put a heading",
    "  row with no quantity above the items ('A. EARTHWORK'): the items under it go into that section.",
    "Client rate: what the client pays per unit. Labour / Material / Subcontract rate: what it should cost you per unit.",
    "  Leave a rate empty if you don't have it yet; it is 'not priced', never zero.",
    "Start / Finish (optional): the section's planned days, for the schedule. Starts after: the section before it.",
    "Rows already in the BOQ (same section, work and unit) are left as they are, so you can import again safely.",
    "Upload it in Planning > BOQ & budget > Import from Excel, or on the Project start page. You see a preview first.",
)
_SKIP = re.compile(r"^(sub\s*-?\s*total|total|grand\s*total|carried\s*(forward|over)|c/?f|b/?f|brought\s*forward)\b",
                   re.IGNORECASE)


class ImportFileError(ValueError):
    """The file can't be read as a BOQ sheet; the message is for the person."""


def heading_name(text: str) -> str:
    """A heading as people read it: "SITE PREPARATION & EARTHWORK" -> "Site Preparation & Earthwork". Mixed case is
    left as typed; short joining words stay small."""
    if not text.isupper():
        return text
    small = {"and", "of", "to", "in", "for", "the", "on", "at", "with"}
    words = text.lower().split()
    return " ".join(w if (i and w in small) else w[:1].upper() + w[1:] for i, w in enumerate(words))


def _key(value: Any) -> str:
    return re.sub(r"[\s.\-_/()\[\]:#]", "", str(value or "").lower())


@dataclass
class BoqRow:
    row: int
    section: str | None
    code: str | None
    work: str | None
    unit: str | None
    quantity: Any
    rates: dict[str, Any]
    start: Any
    finish: Any
    after: str | None
    heading: bool = False


@dataclass
class Sheet:
    name: str
    columns: dict[str, str]
    rows: list[BoqRow] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    out = " ".join(str(value).split())
    return out or None


def _match(header: Any) -> str | None:
    k = _key(header)
    if not k:
        return None
    for canon, words in ALIASES.items():
        if k in words:
            return canon
    return None


def read_sheet(data: bytes) -> Sheet:
    """The BOQ rows of the workbook, with headings marked; ``ImportFileError`` when there is nothing to read."""
    if len(data) > MAX_BYTES:
        raise ImportFileError("The file is over 5 MB. Split it into smaller files.")
    from openpyxl import load_workbook

    try:
        book = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001 -- any unreadable file is the same answer to the person
        raise ImportFileError("This is not an Excel file (.xlsx). Save it as .xlsx, or download the template.") from exc
    names = sorted(book.sheetnames, key=lambda n: 0 if "boq" in _key(n) or "billofquantit" in _key(n) else 1)
    for name in names:
        if _key(name) in ("howtofill",):
            continue
        rows = list(book[name].iter_rows(values_only=True, max_row=MAX_ROWS + HEADER_SCAN))
        for at, header in enumerate(rows[:HEADER_SCAN]):
            where: dict[str, int] = {}
            unknown: list[str] = []
            for i, h in enumerate(header or ()):
                canon = _match(h)
                if canon and canon not in where:
                    where[canon] = i
                elif h is not None and str(h).strip():
                    unknown.append(str(h).strip())
            if "work" in where and ("quantity" in where or "unit" in where):
                sheet = Sheet(name, {k: str(header[i]).strip() for k, i in where.items()}, unknown=unknown)
                sheet.rows = _rows(rows[at + 1:], where, first=at + 2)
                if not sheet.rows:
                    raise ImportFileError(f"The '{name}' sheet has the headers but no rows under them.")
                return sheet
    raise ImportFileError("No BOQ found: the sheet needs a header row with Work (or Description), Unit and Quantity.")


def _rows(cells: list[tuple], where: dict[str, int], first: int) -> list[BoqRow]:
    def get(values: tuple, canon: str) -> Any:
        i = where.get(canon)
        return values[i] if i is not None and i < len(values) else None

    out: list[BoqRow] = []
    for number, values in enumerate(cells, start=first):
        values = values or ()
        if all(v is None or str(v).strip() == "" for v in values):
            continue
        work = _text(get(values, "work"))
        unit = _text(get(values, "unit"))
        qty = get(values, "quantity")
        code = _text(get(values, "code"))
        section = _text(get(values, "section"))
        if work and _SKIP.match(work):
            continue
        has_qty = qty is not None and str(qty).strip() not in ("", "-")
        heading = bool(work) and not unit and not has_qty
        if not work and not unit and not has_qty:
            continue
        rates = {k: get(values, k) for k in ("client_rate", "labour_rate", "material_rate", "subcontract_rate")}
        out.append(BoqRow(number, section, code, work, unit, qty, rates, get(values, "start"), get(values, "finish"),
                          _text(get(values, "after")), heading))
    return out


def template_bytes() -> bytes:
    """The sheet to fill, with six example rows and a "How to fill" sheet."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    book = Workbook()
    sheet = book.active
    sheet.title = "BOQ"
    sheet.append(list(TEMPLATE_COLUMNS))
    for cell in sheet[1]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="FFE08A")
    for row in _EXAMPLE:
        sheet.append(list(row))
    for i, width in enumerate((16, 9, 52, 8, 11, 12, 12, 13, 15, 12, 12, 16)):
        sheet.column_dimensions[chr(ord("A") + i)].width = width
    sheet.freeze_panes = "A2"
    how = book.create_sheet("How to fill")
    for line in _HOW_TO:
        how.append([line])
    how["A1"].font = Font(bold=True, size=13)
    how.column_dimensions["A"].width = 115
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


# ---------------------------------------------------------------------------------------------------------------------
# Running it
# ---------------------------------------------------------------------------------------------------------------------

class _RowProblem(Exception):
    """A row that can't go in; the message is for the person."""


def _number(value: Any, what: str, *, positive: bool) -> Decimal | None:
    if value is None or str(value).strip() in ("", "-"):
        return None
    if isinstance(value, bool):
        raise _RowProblem(f"{what} is not a number")
    cleaned = str(value).replace(",", "").replace("₹", "").replace("Rs.", "").replace("Rs", "").strip()
    try:
        number = Decimal(cleaned)
    except InvalidOperation as exc:
        raise _RowProblem(f"{what} '{value}' is not a number") from exc
    if positive and number <= 0:
        raise _RowProblem(f"{what} must be more than 0")
    if number < 0:
        raise _RowProblem(f"{what} can't be negative")
    return number


def _date(value: Any, what: str) -> datetime.date | None:
    if value is None or str(value).strip() == "":
        return None
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    text_value = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%d %b %Y", "%d-%b-%Y", "%d %B %Y"):
        try:
            return datetime.datetime.strptime(text_value, fmt).date()
        except ValueError:
            continue
    raise _RowProblem(f"{what} '{value}' is not a date (use 2026-12-01 or 01/12/2026)")


@dataclass
class Report:
    sections_added: int = 0
    sections_found: int = 0
    lines_added: int = 0
    lines_kept: int = 0
    problems: int = 0
    contract_value: Decimal = Decimal(0)
    budget_cost: Decimal = Decimal(0)
    dated_sections: int = 0
    links: int = 0
    rows: list[dict] = field(default_factory=list)
    sections: list[dict] = field(default_factory=list)

    def note(self, row: int, result: str, what: str, message: str | None = None, section: str | None = None) -> None:
        if result == "problem":
            self.problems += 1
        if len(self.rows) < MAX_LISTED:
            self.rows.append({"row": row, "result": result, "what": what, "section": section, "message": message})


async def preview(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID, user_id: uuid.UUID,
                  sheet: Sheet) -> dict[str, Any]:
    """What ``run`` would do, nothing kept: the same code in a savepoint that is rolled back."""
    savepoint = await conn.begin_nested()
    try:
        report = await _apply(conn, org, project_id, user_id, sheet)
    finally:
        await savepoint.rollback()
    return _out(report, sheet, saved=False)


async def run(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID, user_id: uuid.UUID,
              sheet: Sheet) -> dict[str, Any]:
    return _out(await _apply(conn, org, project_id, user_id, sheet), sheet, saved=True)


def _out(report: Report, sheet: Sheet, *, saved: bool) -> dict[str, Any]:
    return {
        "saved": saved, "sheet": sheet.name, "columns": sheet.columns, "ignored_columns": sheet.unknown,
        "sections_added": report.sections_added, "sections_found": report.sections_found,
        "lines_added": report.lines_added, "lines_kept": report.lines_kept, "problems": report.problems,
        "contract_value": str(report.contract_value), "budget_cost": str(report.budget_cost),
        "dated_sections": report.dated_sections, "links": report.links,
        "sections": report.sections, "rows": report.rows,
    }


async def _apply(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID, user_id: uuid.UUID,
                 sheet: Sheet) -> Report:
    from fastapi import HTTPException
    from sqlalchemy import text

    from mesiri.domains.progress.boq import line_amounts
    from mesiri.domains.schedule import logic
    from mesiri.infrastructure.postgres.repositories.boq import PostgresBoqRepository
    from mesiri.infrastructure.postgres.repositories.materials import UnitsOfMeasureRepository

    repo = PostgresBoqRepository(conn)
    units = UnitsOfMeasureRepository(conn)
    report = Report()
    existing = {s["name"].lower(): s["id"] for s in await repo.list_sections(org, project_id)}
    plan: dict[str, dict[str, Any]] = {}  # section name (lower) -> {id, name, start, finish, after, lines}
    current: str | None = None

    async def section_for(name: str, row: int, code: str | None = None) -> dict[str, Any]:
        k = name.lower()
        if k in plan:
            return plan[k]
        if k in existing:
            report.sections_found += 1
            sid = existing[k]
        else:
            code = code[:40] if code and not await repo.code_taken(project_id, code[:40]) else None
            sid = await repo.create_section(org, project_id, name[:200], None, code, user_id)
            existing[k] = sid
            report.sections_added += 1
        plan[k] = {"id": sid, "name": name, "start": None, "finish": None, "after": None, "lines": 0,
                   "value": Decimal(0), "row": row}
        return plan[k]

    def take_dates(entry: dict[str, Any], r: BoqRow) -> None:
        s, f = _date(r.start, "Start"), _date(r.finish, "Finish")
        if s and (entry["start"] is None or s < entry["start"]):
            entry["start"] = s
        if f and (entry["finish"] is None or f > entry["finish"]):
            entry["finish"] = f
        if r.after:
            entry["after"] = r.after

    for r in sheet.rows:
        label = r.work or r.code or ""
        try:
            if r.heading:
                name = r.section or heading_name(r.work or r.code or "")
                current = name
                async with conn.begin_nested():
                    entry = await section_for(name, r.row, None if r.section else r.code)
                    take_dates(entry, r)
                report.note(r.row, "section", name, None, name)
                continue
            name = r.section or current or "BOQ"
            if not r.work:
                raise _RowProblem("No work / description")
            if not r.unit:
                raise _RowProblem("No unit (cum, sqft, nos ...)")
            quantity = _number(r.quantity, "Quantity", positive=True)
            if quantity is None:
                raise _RowProblem("No quantity")
            rates = {k: _number(v, k.replace("_", " ").capitalize(), positive=False) for k, v in r.rates.items()}
            unit = await units.resolve_alias(r.unit)
            if unit is None or not unit["is_active"]:
                raise _RowProblem(f"'{r.unit}' is not a unit Mesiri knows (try cum, sqft, rft, nos, kg)")
            async with conn.begin_nested():
                entry = await section_for(name, r.row)
                take_dates(entry, r)
                work = r.work[:300]
                if await repo.current_line_with(entry["id"], work, unit["id"]):
                    report.lines_kept += 1
                    report.note(r.row, "kept", work, "Already in the BOQ: left as it is", entry["name"])
                    continue
                await repo.create_line(org, entry["id"], {
                    "work_type": work, "unit_id": unit["id"], "planned_quantity": quantity,
                    "boq_code": (r.code or None) and r.code[:40], **rates}, user_id)
            money = line_amounts({"planned_quantity": quantity, **rates})
            report.lines_added += 1
            entry["lines"] += 1
            if money["contract_value"] is not None:
                report.contract_value += money["contract_value"]
                entry["value"] += money["contract_value"]
            if money["budget_cost"] is not None:
                report.budget_cost += money["budget_cost"]
            report.note(r.row, "added", work, None, entry["name"])
        except HTTPException as exc:
            report.note(r.row, "problem", label, str(exc.detail), r.section or current)
        except _RowProblem as exc:
            report.note(r.row, "problem", label, str(exc), r.section or current)

    # The schedule: each section's dates and "starts after", once every section exists.
    for entry in plan.values():
        changes = {}
        if entry["start"] and entry["finish"]:
            if entry["finish"] < entry["start"]:
                report.note(entry["row"], "problem", entry["name"], "Finish is before Start: dates not set",
                            entry["name"])
            else:
                changes = {"planned_start": entry["start"], "planned_end": entry["finish"]}
        elif entry["start"] or entry["finish"]:
            day = entry["start"] or entry["finish"]
            changes = {"planned_start": day, "planned_end": day}
        if changes:
            await conn.execute(text("UPDATE work_packages SET planned_start = :planned_start, "
                                    "planned_end = :planned_end, updated_at = now() WHERE id = :id"),
                               {**changes, "id": entry["id"]})
            report.dated_sections += 1
        if entry["after"]:
            pred = existing.get(entry["after"].lower())
            current_links = [{"predecessor": r[0], "successor": r[1]} for r in (await conn.execute(text(
                "SELECT predecessor_id, successor_id FROM work_package_links WHERE organization_id = :org"),
                {"org": org})).all()]
            if pred is None or pred == entry["id"]:
                report.note(entry["row"], "problem", entry["name"], f"Starts after '{entry['after']}': no such section",
                            entry["name"])
            elif logic.makes_cycle(current_links, pred, entry["id"]):
                report.note(entry["row"], "problem", entry["name"],
                            f"Starts after '{entry['after']}' would go round in a circle: not linked", entry["name"])
            else:
                await conn.execute(text(
                    "INSERT INTO work_package_links (organization_id, predecessor_id, successor_id) "
                    "VALUES (:org, :p, :s) ON CONFLICT DO NOTHING"), {"org": org, "p": pred, "s": entry["id"]})
                report.links += 1
        report.sections.append({"id": str(entry["id"]), "name": entry["name"], "lines": entry["lines"],
                                "contract_value": str(entry["value"]),
                                "start": entry["start"].isoformat() if entry["start"] else None,
                                "finish": entry["finish"].isoformat() if entry["finish"] else None})
    return report
