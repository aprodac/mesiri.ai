"""The unified media gallery query against a real Postgres (integration).

WEB-24 started it (work/issue photos joined to their parent); WEB-105 unified
it so one paged query returns every image kind — work and issue photos,
attendance sheets, supplier deliveries and receipts — newest first, with the
money kinds (material, expense) gated by `include_money`. Every test rolls back.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from sqlalchemy import text

from mesiri.application.organizations.create_company import NewCompany, create_company
from mesiri.infrastructure.postgres.repositories.progress import PostgresProgressReadRepository

pytestmark = pytest.mark.integration

DAY = dt.date(2026, 10, 20)


@pytest.fixture
async def conn():
    from sqlalchemy.ext.asyncio import create_async_engine

    from mesiri.bootstrap.settings import Settings

    engine = create_async_engine(Settings().postgres.dsn())
    async with engine.connect() as connection:
        tx = await connection.begin()
        yield connection
        await tx.rollback()
    await engine.dispose()


async def _company(conn, name: str):
    return await create_company(
        conn,
        NewCompany(name=name, owner_name="Owner", owner_phone=f"+91 9{uuid.uuid4().int % 10**9:09d}", project_name="P", site_name="S"),
    )


async def _photo(conn, created, *, key: str, deleted: bool = False) -> uuid.UUID:
    """A work photo (progress_attachments on an activity) → kind 'work'."""
    activity_id = uuid.uuid4()
    await conn.execute(
        text(
            "INSERT INTO activities (id, organization_id, project_id, site_id, activity_date, work_type, deleted_at)"
            " VALUES (:id, :org, :project, :site, :day, 'Brickwork', :deleted)"
        ),
        {
            "id": activity_id,
            "org": created.organization_id,
            "project": created.project_id,
            "site": created.site_id,
            "day": DAY,
            "deleted": dt.datetime.now(dt.UTC) if deleted else None,
        },
    )
    photo_id = uuid.uuid4()
    await conn.execute(
        text(
            "INSERT INTO progress_attachments (id, parent_type, parent_id, media_object_key, attachment_type)"
            " VALUES (:id, 'ACTIVITY', :parent, :key, 'site_photo')"
        ),
        {"id": photo_id, "parent": activity_id, "key": key},
    )
    return photo_id


async def _issue_photo(conn, created, *, key: str, when: dt.date = DAY) -> uuid.UUID:
    """A photo on a site issue (parent_type SITE_ISSUE) → kind 'issue'."""
    issue_id = uuid.uuid4()
    await conn.execute(
        text(
            "INSERT INTO site_issues (id, organization_id, project_id, site_id, occurred_at, narrative, issue_type, severity, status)"
            " VALUES (:id, :org, :project, :site, :occurred_at, 'Water logging', 'WEATHER', 'MEDIUM', 'OPEN')"
        ),
        {
            "id": issue_id,
            "org": created.organization_id,
            "project": created.project_id,
            "site": created.site_id,
            "occurred_at": dt.datetime.combine(when, dt.time(9, 0), tzinfo=dt.UTC),
        },
    )
    photo_id = uuid.uuid4()
    await conn.execute(
        text(
            "INSERT INTO progress_attachments (id, parent_type, parent_id, media_object_key, attachment_type)"
            " VALUES (:id, 'SITE_ISSUE', :parent, :key, 'site_photo')"
        ),
        {"id": photo_id, "parent": issue_id, "key": key},
    )
    return photo_id


async def _attendance_photo(conn, created, *, key: str, when: dt.date = DAY) -> uuid.UUID:
    """An attendance sheet photo (labour_attendance_attachments) → 'attendance'."""
    report_id = uuid.uuid4()
    await conn.execute(
        text(
            "INSERT INTO labour_attendance_reports (id, organization_id, project_id, site_id, occurred_date, recorded_via, created_by)"
            " VALUES (:id, :org, :project, :site, :day, 'whatsapp_image', :user)"
        ),
        {"id": report_id, "org": created.organization_id, "project": created.project_id, "site": created.site_id, "day": when, "user": created.owner_user_id},
    )
    photo_id = uuid.uuid4()
    await conn.execute(
        text(
            "INSERT INTO labour_attendance_attachments (id, report_id, media_object_key, attachment_type, created_by)"
            " VALUES (:id, :report, :key, 'attendance_sheet', :user)"
        ),
        {"id": photo_id, "report": report_id, "key": key, "user": created.owner_user_id},
    )
    return photo_id


async def _material_photo(conn, created, *, key: str, when: dt.date = DAY) -> uuid.UUID:
    """A supplier delivery/invoice photo (material_invoice_attachments) → 'material'."""
    invoice_id = uuid.uuid4()
    await conn.execute(
        text(
            "INSERT INTO material_invoices (id, organization_id, project_id, site_id, supplier_name, invoice_date, invoice_total, created_by)"
            " VALUES (:id, :org, :project, :site, 'Malabar Traders', :day, 25000, :user)"
        ),
        {"id": invoice_id, "org": created.organization_id, "project": created.project_id, "site": created.site_id, "day": when, "user": created.owner_user_id},
    )
    photo_id = uuid.uuid4()
    await conn.execute(
        text(
            "INSERT INTO material_invoice_attachments (id, invoice_id, media_object_key, attachment_type, created_by)"
            " VALUES (:id, :invoice, :key, 'bill', :user)"
        ),
        {"id": photo_id, "invoice": invoice_id, "key": key, "user": created.owner_user_id},
    )
    return photo_id


async def _expense_photo(conn, created, *, key: str, when: dt.date = DAY) -> uuid.UUID:
    """A receipt (expense_attachments) → kind 'expense'."""
    category_id = uuid.uuid4()
    await conn.execute(
        text(
            "INSERT INTO expense_categories (id, organization_id, name, status, created_by)"
            " VALUES (:id, :org, 'fuel', 'active', :user)"
        ),
        {"id": category_id, "org": created.organization_id, "user": created.owner_user_id},
    )
    expense_id = uuid.uuid4()
    await conn.execute(
        text(
            "INSERT INTO expenses (id, organization_id, project_id, category_id, amount, currency, description, occurred_date,"
            " workflow_status, payment_status, source, created_by)"
            " VALUES (:id, :org, :project, :category, 700.00, 'INR', 'Diesel', :day, 'confirmed', 'unpaid', 'whatsapp', :user)"
        ),
        {"id": expense_id, "org": created.organization_id, "project": created.project_id, "category": category_id, "day": when, "user": created.owner_user_id},
    )
    photo_id = uuid.uuid4()
    await conn.execute(
        text(
            "INSERT INTO expense_attachments (id, expense_id, media_object_key, attachment_type, created_by)"
            " VALUES (:id, :expense, :key, 'receipt', :user)"
        ),
        {"id": photo_id, "expense": expense_id, "key": key, "user": created.owner_user_id},
    )
    return photo_id


async def _gallery(conn, org, **kw):
    return await PostgresProgressReadRepository(conn).list_media_gallery(organization_id=org, **kw)


async def test_lists_only_this_companys_photos_with_their_work_item(conn) -> None:
    mine = await _company(conn, "Mine")
    other = await _company(conn, "Other")
    photo = await _photo(conn, mine, key="m/a.jpg")
    await _photo(conn, other, key="o/b.jpg")

    items, total = await _gallery(conn, mine.organization_id)

    assert total == 1
    assert [i["id"] for i in items] == [photo]
    assert items[0]["kind"] == "work"
    assert items[0]["project_id"] == mine.project_id
    assert items[0]["site_id"] == mine.site_id
    assert items[0]["work_date"] == DAY
    assert items[0]["title"] == "Brickwork"


async def test_project_and_site_filters_and_removed_work_items(conn) -> None:
    mine = await _company(conn, "Mine")
    await _photo(conn, mine, key="m/a.jpg")
    await _photo(conn, mine, key="m/gone.jpg", deleted=True)

    _, total = await _gallery(conn, mine.organization_id)
    assert total == 1  # the removed work item's photo is left out

    _, total = await _gallery(conn, mine.organization_id, project_ids={uuid.uuid4()})
    assert total == 0
    _, total = await _gallery(conn, mine.organization_id, site_id=mine.site_id)
    assert total == 1
    _, total = await _gallery(conn, mine.organization_id, site_id=uuid.uuid4())
    assert total == 0


async def test_all_five_kinds_and_money_gating(conn) -> None:
    mine = await _company(conn, "Mine")
    await _photo(conn, mine, key="m/work.jpg")
    await _issue_photo(conn, mine, key="m/issue.jpg")
    await _attendance_photo(conn, mine, key="m/att.jpg")
    mat = await _material_photo(conn, mine, key="m/bill.jpg")
    exp = await _expense_photo(conn, mine, key="m/receipt.jpg")

    # Without money rights: only the three operational kinds.
    items, total = await _gallery(conn, mine.organization_id, include_money=False)
    kinds = {i["kind"] for i in items}
    assert total == 3 and kinds == {"work", "issue", "attendance"}
    assert mat not in {i["id"] for i in items} and exp not in {i["id"] for i in items}

    # With money rights: all five.
    items, total = await _gallery(conn, mine.organization_id, include_money=True)
    assert total == 5 and {i["kind"] for i in items} == {"work", "issue", "attendance", "material", "expense"}
    by_kind = {i["kind"]: i for i in items}
    assert by_kind["material"]["title"] == "Malabar Traders"
    assert by_kind["material"]["amount"] == 25000
    assert by_kind["expense"]["amount"] == 700
    assert by_kind["attendance"]["title"] == "Attendance sheet"

    # Kind filter: a receipt only for a money-capable caller.
    _, total = await _gallery(conn, mine.organization_id, kinds={"expense"}, include_money=True)
    assert total == 1
    _, total = await _gallery(conn, mine.organization_id, kinds={"expense"}, include_money=False)
    assert total == 0  # a site engineer asking for receipts gets an empty page, not a leak
    items, _ = await _gallery(conn, mine.organization_id, kinds={"attendance"}, include_money=False)
    assert [i["kind"] for i in items] == ["attendance"]


async def test_money_kinds_are_tenant_scoped(conn) -> None:
    mine = await _company(conn, "Mine")
    other = await _company(conn, "Other")
    await _expense_photo(conn, other, key="o/receipt.jpg")
    await _material_photo(conn, other, key="o/bill.jpg")

    _, total = await _gallery(conn, mine.organization_id, include_money=True)
    assert total == 0  # another company's receipts and bills never show here


async def test_date_filter_across_kinds(conn) -> None:
    mine = await _company(conn, "Mine")
    await _photo(conn, mine, key="m/work.jpg")  # DAY
    await _expense_photo(conn, mine, key="m/receipt.jpg", when=DAY - dt.timedelta(days=5))

    items, total = await _gallery(conn, mine.organization_id, include_money=True, date_from=DAY)
    assert total == 1 and items[0]["kind"] == "work"
    items, total = await _gallery(conn, mine.organization_id, include_money=True, date_to=DAY - dt.timedelta(days=1))
    assert total == 1 and items[0]["kind"] == "expense"
    _, total = await _gallery(conn, mine.organization_id, include_money=True)
    assert total == 2  # newest first overall
