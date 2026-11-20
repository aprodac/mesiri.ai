"""WEB-24: the site gallery query against a real Postgres (integration).

progress_attachments has no organization/project/site columns; the gallery
takes them from the parent work item. It used to read pa.organization_id
directly and failed on every call. Every test rolls back.
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


async def test_lists_only_this_companys_photos_with_their_work_item(conn) -> None:
    mine = await _company(conn, "Mine")
    other = await _company(conn, "Other")
    photo = await _photo(conn, mine, key="m/a.jpg")
    await _photo(conn, other, key="o/b.jpg")

    items, total = await PostgresProgressReadRepository(conn).list_gallery(organization_id=mine.organization_id)

    assert total == 1
    assert [i["id"] for i in items] == [photo]
    assert items[0]["project_id"] == mine.project_id
    assert items[0]["site_id"] == mine.site_id
    assert items[0]["work_date"] == DAY
    assert items[0]["parent_title"] == "Brickwork"


async def test_project_and_site_filters_and_removed_work_items(conn) -> None:
    mine = await _company(conn, "Mine")
    await _photo(conn, mine, key="m/a.jpg")
    await _photo(conn, mine, key="m/gone.jpg", deleted=True)
    repo = PostgresProgressReadRepository(conn)

    _, total = await repo.list_gallery(organization_id=mine.organization_id)
    assert total == 1  # the removed work item's photo is left out

    _, total = await repo.list_gallery(organization_id=mine.organization_id, project_ids={uuid.uuid4()})
    assert total == 0
    _, total = await repo.list_gallery(organization_id=mine.organization_id, site_id=mine.site_id)
    assert total == 1
    _, total = await repo.list_gallery(organization_id=mine.organization_id, site_id=uuid.uuid4())
    assert total == 0


async def _issue_photo(conn, created, *, key: str, when: dt.date) -> uuid.UUID:
    """A photo hung off a site issue (parent_type SITE_ISSUE), dated `when`."""
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


async def test_kind_and_date_filters(conn) -> None:
    # A work photo on DAY, and an issue photo the day before (WEB-104).
    mine = await _company(conn, "Mine")
    work = await _photo(conn, mine, key="m/work.jpg")
    issue = await _issue_photo(conn, mine, key="m/issue.jpg", when=DAY - dt.timedelta(days=1))
    repo = PostgresProgressReadRepository(conn)

    # Kind filter: ACTIVITY (work) vs SITE_ISSUE (issue).
    items, total = await repo.list_gallery(organization_id=mine.organization_id, parent_type="ACTIVITY")
    assert total == 1 and [i["id"] for i in items] == [work]
    items, total = await repo.list_gallery(organization_id=mine.organization_id, parent_type="SITE_ISSUE")
    assert total == 1 and [i["id"] for i in items] == [issue]

    # Date filter on the work day: DAY keeps the work photo, DAY-1 the issue.
    _, total = await repo.list_gallery(organization_id=mine.organization_id, date_from=DAY)
    assert total == 1  # only the work photo is on or after DAY
    items, total = await repo.list_gallery(
        organization_id=mine.organization_id, date_from=DAY - dt.timedelta(days=1), date_to=DAY - dt.timedelta(days=1)
    )
    assert total == 1 and [i["id"] for i in items] == [issue]
    _, total = await repo.list_gallery(organization_id=mine.organization_id, date_to=DAY)
    assert total == 2  # both days fall on or before DAY
