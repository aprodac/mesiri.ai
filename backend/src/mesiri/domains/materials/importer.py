"""The materials Excel import (PRC-05): a builder's item list, vendors and opening stock in one workbook.

Onboarding a full-project builder means hundreds of items under their categories, the shops they buy from and what
each site holds on day one. Typing them is the work the client said they do today; the import takes their sheet.

One workbook, three sheets (``template_bytes`` writes it, with a "How to fill" sheet):

- **Items**: Main category, Sub-category, Item, Unit, Item code, Other names
- **Vendors**: Vendor, Phone, GSTIN, Address
- **Opening stock**: Project, Site, Item, Quantity, Date

Nothing here has rules of its own: a category, an item, a vendor and an opening stock line are made by the same
code as the dashboard's own buttons (``create_material``, ``record_inflow``, ``vendor_for_name``, the categories
repository), so the import refuses exactly what they refuse. Each row runs in its own savepoint: a refused row is
listed with the reason and the rest go on. ``run`` makes the changes; the preview runs the very same code inside a
savepoint it rolls back, so what the preview says is what the import does.
"""

from __future__ import annotations

import datetime
import io
import uuid
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection

    from mesiri.authorization.context import AuthorizationContext

ITEMS, VENDORS, OPENING = "Items", "Vendors", "Opening stock"
COLUMNS: dict[str, tuple[str, ...]] = {
    ITEMS: ("Main category", "Sub-category", "Item", "Unit", "Item code", "Other names"),
    VENDORS: ("Vendor", "Phone", "GSTIN", "Address"),
    OPENING: ("Project", "Site", "Item", "Quantity", "Date"),
}
#: The column a row cannot do without, per sheet.
_REQUIRED = {ITEMS: ("Item", "Unit"), VENDORS: ("Vendor",), OPENING: ("Site", "Item", "Quantity")}
MAX_ROWS = 5000
MAX_BYTES = 5 * 1024 * 1024
#: Rows listed back one by one (the counts always cover all of them).
MAX_LISTED = 1000

_HOW_TO = (
    "How to fill this workbook (Mesiri materials import)",
    "",
    "Items: one row per item. A size or type is its own item: '2-way switch 6A 1-module', 'PVC pipe 1 inch'.",
    "  Main category: Structural, Electrical, Plumbing & CP, Fire protection, Gas, Lift, Finishing, or your own.",
    "  Sub-category (optional): under the main one, e.g. Switches & sockets, Pipes. New ones are added.",
    "  Unit: how the item is counted in stock: bags, kg, nos, cft, sqft, litres, rolls, load, ...",
    "  Other names (optional): what site people call it, separated by commas (kambi, chakku).",
    "Vendors: the shops you buy from. Phone, GSTIN (15 characters) and address are optional.",
    "Opening stock: what a site holds before you start with Mesiri. Once per site and item.",
    "  Project can be left empty when the site name is only used once.",
    "  Quantity is in the item's unit. Date (optional) defaults to today.",
    "",
    "Upload the file in Materials > Catalogue > Import from Excel. You see what will happen before anything is saved.",
    "Rows already in Mesiri are left as they are; an item that has no category yet is put in the one given here.",
)


class ImportFileError(ValueError):
    """The file can't be read as the import workbook; the message is for the person."""


@dataclass
class SheetRow:
    sheet: str
    row: int
    values: dict[str, Any]

    def text(self, column: str) -> str:
        value = self.values.get(column)
        if value is None:
            return ""
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        return " ".join(str(value).split())


@dataclass
class ImportReport:
    counts: dict[str, dict[str, int]] = field(
        default_factory=lambda: {ITEMS: {}, VENDORS: {}, OPENING: {}, "Categories": {}}
    )
    rows: list[dict[str, Any]] = field(default_factory=list)
    problems: int = 0

    def note(self, row: SheetRow, result: str, name: str, message: str = "") -> None:
        bucket = self.counts[row.sheet]
        bucket[result] = bucket.get(result, 0) + 1
        if result == "problem":
            self.problems += 1
        if len(self.rows) < MAX_LISTED:
            self.rows.append({"sheet": row.sheet, "row": row.row, "name": name, "result": result, "message": message})

    def as_dict(self, *, saved: bool) -> dict[str, Any]:
        return {"saved": saved, "counts": self.counts, "problems": self.problems, "rows": self.rows}


# ---------------------------------------------------------------------------------------------------------------------
# The workbook
# ---------------------------------------------------------------------------------------------------------------------
def template_bytes() -> bytes:
    """The empty workbook to fill: the three sheets with their headers, and the "How to fill" sheet first."""
    from openpyxl import Workbook
    from openpyxl.styles import Font

    book = Workbook()
    how = book.active
    how.title = "How to fill"
    for line in _HOW_TO:
        how.append([line])
    how["A1"].font = Font(bold=True, size=13)
    how.column_dimensions["A"].width = 110
    for sheet, columns in COLUMNS.items():
        page = book.create_sheet(sheet)
        page.append(list(columns))
        for cell in page[1]:
            cell.font = Font(bold=True)
        for index, column in enumerate(columns):
            page.column_dimensions[chr(ord("A") + index)].width = max(14, len(column) + 6)
        page.freeze_panes = "A2"
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def read_workbook(data: bytes) -> list[SheetRow]:
    """Every filled row of the three sheets, in sheet order. Headers are matched ignoring case and spaces; a sheet that
    is missing is simply empty; a sheet without its required columns is refused (``ImportFileError``)."""
    if len(data) > MAX_BYTES:
        raise ImportFileError("The file is over 5 MB. Split it into smaller files.")
    from openpyxl import load_workbook

    try:
        book = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001 -- any unreadable file is the same answer to the person
        raise ImportFileError("This is not an Excel file (.xlsx). Download the template and fill that.") from exc
    by_key = {_key(name): name for name in book.sheetnames}
    rows: list[SheetRow] = []
    for sheet, columns in COLUMNS.items():
        name = by_key.get(_key(sheet))
        if name is None:
            continue
        cells = book[name].iter_rows(values_only=True)
        header = next(cells, None) or ()
        where = {_key(str(h)): i for i, h in enumerate(header) if h is not None}
        missing = [c for c in _REQUIRED[sheet] if _key(c) not in where]
        if missing:
            raise ImportFileError(f"The '{sheet}' sheet has no {', '.join(missing)} column. Use the template's headers.")
        for number, values in enumerate(cells, start=2):
            row = {c: values[where[_key(c)]] if _key(c) in where and where[_key(c)] < len(values) else None
                   for c in columns}
            if all(v is None or str(v).strip() == "" for v in row.values()):
                continue
            rows.append(SheetRow(sheet, number, row))
            if len(rows) > MAX_ROWS:
                raise ImportFileError(f"The file has more than {MAX_ROWS} rows. Split it into smaller files.")
    if not rows:
        raise ImportFileError("No rows to import: fill the Items, Vendors or Opening stock sheet.")
    return rows


def _key(text: str) -> str:
    return "".join(str(text or "").lower().split())


# ---------------------------------------------------------------------------------------------------------------------
# Running it
# ---------------------------------------------------------------------------------------------------------------------
async def preview(conn: AsyncConnection, auth: AuthorizationContext, rows: list[SheetRow]) -> dict[str, Any]:
    """What ``run`` would do, with nothing kept: the same code in a savepoint that is rolled back."""
    savepoint = await conn.begin_nested()
    try:
        report = await _apply(conn, auth, rows)
    finally:
        await savepoint.rollback()
    return report.as_dict(saved=False)


async def run(conn: AsyncConnection, auth: AuthorizationContext, rows: list[SheetRow]) -> dict[str, Any]:
    return (await _apply(conn, auth, rows)).as_dict(saved=True)


async def _apply(conn: AsyncConnection, auth: AuthorizationContext, rows: list[SheetRow]) -> ImportReport:
    from fastapi import HTTPException
    from sqlalchemy import text

    async def category_count() -> int:
        res = await conn.execute(
            text("SELECT count(*) FROM material_categories WHERE organization_id = :org"), {"org": auth.organization_id}
        )
        return int(res.scalar_one())

    report = ImportReport()
    categories_before = await category_count()
    context = _Context(conn, auth, report)
    handlers = {ITEMS: context.item, VENDORS: context.vendor, OPENING: context.opening}
    for row in rows:
        name = row.text("Item") or row.text("Vendor")
        try:
            async with conn.begin_nested():
                result, message = await handlers[row.sheet](row)
        except HTTPException as exc:
            result, message = "problem", _plain(exc.detail)
        except _RowProblem as exc:
            result, message = "problem", str(exc)
        report.note(row, result, name, message)
    report.counts["Categories"]["added"] = await category_count() - categories_before
    return report


class _RowProblem(Exception):
    """A row that can't go in; the message is for the person."""


def _plain(detail: Any) -> str:
    if isinstance(detail, dict):
        return str(detail.get("message") or detail.get("detail") or detail)
    return str(detail)


class _Context:
    """What the rows share: the company's categories, units, sites, as they grow during the import."""

    def __init__(self, conn: AsyncConnection, auth: AuthorizationContext, report: ImportReport) -> None:
        self.conn, self.auth, self.report = conn, auth, report
        self._sites: list[dict] | None = None

    # -- Items ---------------------------------------------------------------------------------------------------------
    async def item(self, row: SheetRow) -> tuple[str, str]:
        from mesiri.domains.materials.router import MaterialCatalogCreate, create_material
        from mesiri.infrastructure.postgres.repositories.materials import (
            PostgresMaterialCatalogRepository,
            UnitsOfMeasureRepository,
        )

        name, unit_text = row.text("Item"), row.text("Unit")
        if not name or not unit_text:
            raise _RowProblem("Item and Unit are both needed.")
        category_id = await self._category(row.text("Main category"), row.text("Sub-category"))
        catalog = PostgresMaterialCatalogRepository(self.conn)
        existing = await catalog.get_by_name(self.auth.organization_id, name)
        if existing is not None:
            message = await self._aliases(existing, row)
            if existing.get("category_id") is None and category_id is not None:
                await catalog.update(
                    self.auth.organization_id, existing["id"], updated_by=self.auth.user_id,
                    set_category_id=True, category_id=category_id,
                )
                return "placed", "Already in Mesiri; put in the category given." + message
            return "existing", "Already in Mesiri." + message
        unit = await UnitsOfMeasureRepository(self.conn).resolve_alias(unit_text)
        if unit is None:
            raise _RowProblem(f"Unit '{unit_text}' is not known. Use bags, kg, nos, cft, sqft, litres, rolls, load, ...")
        created = await create_material(
            MaterialCatalogCreate(
                name=name, default_unit_id=unit["id"], category_id=category_id, sku=row.text("Item code") or None
            ),
            auth_context=self.auth,
            conn=self.conn,
        )
        return "added", await self._aliases(created, row)

    async def _category(self, main: str, sub: str) -> uuid.UUID | None:
        from mesiri.domains.materials.categories import clean_category_name
        from mesiri.infrastructure.postgres.repositories.material_categories import (
            PostgresMaterialCategoryRepository,
        )

        main, sub = clean_category_name(main), clean_category_name(sub)
        if sub and not main:
            raise _RowProblem("A sub-category needs its main category.")
        if not main:
            return None
        repo = PostgresMaterialCategoryRepository(self.conn)
        org = self.auth.organization_id
        top = await repo.find(org, None, main)
        if top is None:
            top = await repo.create(
                org, name=main, parent_id=None, sort_order=await repo.next_sort_order(org, None),
                created_by=self.auth.user_id,
            )
        if not sub:
            return top["id"]
        child = await repo.find(org, top["id"], sub)
        if child is None:
            child = await repo.create(
                org, name=sub, parent_id=top["id"], sort_order=await repo.next_sort_order(org, top["id"]),
                created_by=self.auth.user_id,
            )
        return child["id"]

    async def _aliases(self, material: dict, row: SheetRow) -> str:
        """Add the other names that no other material already has; say which were skipped."""
        from mesiri.infrastructure.postgres.repositories.materials import (
            PostgresMaterialCatalogRepository,
        )

        repo = PostgresMaterialCatalogRepository(self.conn)
        taken = []
        for alias in [a.strip() for a in row.text("Other names").split(",") if a.strip()]:
            other = await repo.find_by_alias(self.auth.organization_id, alias)
            if other is not None and str(other["id"]) != str(material["id"]):
                taken.append(f"'{alias}' is already {other['name']}")
                continue
            if other is None:
                await repo.add_alias(self.auth.organization_id, material["id"], alias, self.auth.user_id)
        return f" Other names skipped: {'; '.join(taken)}." if taken else ""

    # -- Vendors -------------------------------------------------------------------------------------------------------
    async def vendor(self, row: SheetRow) -> tuple[str, str]:
        from mesiri.application.vendors.resolution import vendor_for_name
        from mesiri.domains.vendors.details import (
            VendorDetailError,
            clean_address,
            clean_gstin,
            clean_phone,
        )
        from mesiri.infrastructure.postgres.repositories.vendors import PostgresVendorRepository

        name = row.text("Vendor")
        try:
            details = {
                key: value
                for key, value in (
                    ("phone", clean_phone(row.text("Phone"))),
                    ("gstin", clean_gstin(row.text("GSTIN"))),
                    ("address", clean_address(row.text("Address"))),
                )
                if value is not None
            }
        except VendorDetailError as exc:
            raise _RowProblem(str(exc)) from exc
        repo = PostgresVendorRepository(self.conn)
        existing = await repo.find_by_name_exact_active(self.auth.organization_id, name)
        vendor_id = existing.id if existing else await vendor_for_name(
            self.conn, self.auth.organization_id, name, created_by=self.auth.user_id
        )
        changed = existing is not None and any(getattr(existing, k) != v for k, v in details.items())
        if details and (existing is None or changed):
            await repo.update(self.auth.organization_id, vendor_id, updated_by=self.auth.user_id, details=details)
        if existing is None:
            return "added", ""
        return ("updated", "Phone / GSTIN / address updated.") if changed else ("existing", "Already in Mesiri.")

    # -- Opening stock -------------------------------------------------------------------------------------------------
    async def opening(self, row: SheetRow) -> tuple[str, str]:
        from mesiri.domains.materials.router import MaterialInflowCreate, record_inflow
        from mesiri.domains.materials.validation import OPENING_STOCK
        from mesiri.infrastructure.postgres.repositories.materials import (
            PostgresMaterialCatalogRepository,
        )

        project_id, site_id = await self._site(row.text("Project"), row.text("Site"))
        catalog = PostgresMaterialCatalogRepository(self.conn)
        item = row.text("Item")
        material = await catalog.get_by_name(self.auth.organization_id, item) or await catalog.find_by_alias(
            self.auth.organization_id, item
        )
        if material is None:
            raise _RowProblem(f"'{item}' is not an item yet: add it on the Items sheet.")
        try:
            quantity = Decimal(str(row.values.get("Quantity")).replace(",", "").strip())
        except (InvalidOperation, ValueError) as exc:
            raise _RowProblem(f"Quantity '{row.text('Quantity')}' is not a number.") from exc
        result = await record_inflow(
            self.conn,
            self.auth,
            MaterialInflowCreate(
                project_id=project_id,
                site_id=site_id,
                material_id=material["id"],
                unit_id=material["default_unit_id"],
                quantity=quantity,
                movement_reason=OPENING_STOCK,
                occurred_date=await self._date(row.values.get("Date")),
            ),
        )
        return "added", "" if not result.get("converted") else str(result["converted"])

    async def _site(self, project: str, site: str) -> tuple[uuid.UUID, uuid.UUID]:
        from sqlalchemy import text

        if self._sites is None:
            res = await self.conn.execute(
                text(
                    "SELECT s.id AS site_id, s.name AS site, p.id AS project_id, p.name AS project FROM sites s "
                    "JOIN projects p ON p.id = s.project_id WHERE s.organization_id = :org"
                ),
                {"org": self.auth.organization_id},
            )
            self._sites = [dict(r) for r in res.mappings().all()]
        hits = [s for s in self._sites if _key(s["site"]) == _key(site)
                and (not project or _key(s["project"]) == _key(project))]
        if not hits:
            raise _RowProblem(f"No site '{site}'" + (f" in project '{project}'." if project else "."))
        if len(hits) > 1:
            raise _RowProblem(f"Site '{site}' is in several projects: fill the Project column.")
        return hits[0]["project_id"], hits[0]["site_id"]

    async def _date(self, value: Any) -> datetime.date:
        if isinstance(value, datetime.datetime):
            return value.date()
        if isinstance(value, datetime.date):
            return value
        text_value = str(value or "").strip()
        if not text_value:
            from mesiri.application.dpr import project_day

            return await project_day.company_today(self.conn, self.auth.organization_id)
        for pattern in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d.%m.%Y"):
            try:
                return datetime.datetime.strptime(text_value, pattern).date()
            except ValueError:
                continue
        raise _RowProblem(f"Date '{text_value}' is not a date: use 01-11-2026.")
