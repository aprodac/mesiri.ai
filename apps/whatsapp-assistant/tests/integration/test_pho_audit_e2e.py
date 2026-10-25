"""Photos (audit 07) against a real database: a "Site Update" photo reaches
the work it shows with its caption (PHO-01), and the day's DPR payload carries
the photos for the document to print (PHO-02)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import text
from tests.integration.test_wrk_audit_e2e import (  # noqa: F401 -- the fixture
    DAY1,
    DAY2,
    _day,
    _send,
    world,
)

from runtime.activity_query import ActivityQueryService
from runtime.evidence_query import EvidenceAttachService
from runtime.site_photos import attach_site_update_photos

pytestmark = pytest.mark.integration


def _photo(key: str, caption: str | None = None):
    return SimpleNamespace(media=SimpleNamespace(object_key=key), text=caption)


async def _tap_site_update(world, photos):  # noqa: F811 -- pytest fixture imported from the shared e2e module
    ctx = SimpleNamespace(
        organization_id=str(world.org), user_id=world.user,
        sites=[SimpleNamespace(id=str(world.site), name="Green Villa", project_id=str(world.project))],
    )
    return await attach_site_update_photos(
        photos, ctx=ctx, work_site=None, activity_query=ActivityQueryService(world.db),
        evidence_query=EvidenceAttachService(world.db), correlation_id="cor_photos",
    )


async def test_pho01_site_update_photos_reach_the_work_with_their_captions(world):  # noqa: F811 -- pytest fixture imported from the shared e2e module
    saved = await _send(world, "ph1", narrative="Started plastering 2nd floor", work_type="plastering",
                        occurred_on=DAY2.isoformat())
    assert saved is not None and saved.execution_result is not None

    reply = await _tap_site_update(
        world, [_photo("media/a/1", "2nd floor plastering"), _photo("media/a/2"), _photo("media/a/3")]
    )
    assert reply.startswith("📷 3 photos attached to plastering"), reply
    async with world.db.transaction() as conn:
        rows = (await conn.execute(text(
            "SELECT media_object_key, caption FROM progress_attachments pa JOIN activities a"
            " ON a.id = pa.parent_id WHERE a.organization_id = :o ORDER BY media_object_key"),
            {"o": world.org})).all()
    assert rows == [("media/a/1", "2nd floor plastering"), ("media/a/2", None), ("media/a/3", None)]

    payload, _ = await _day(world, DAY2)
    work = payload["activities"][0]
    assert work["evidence_count"] == 3 and payload["evidence_count"] == 3
    assert [p["object_key"] for p in work["photos"]] == ["media/a/1", "media/a/2", "media/a/3"]
    assert work["photos"][0]["caption"] == "2nd floor plastering"


async def test_pho01_finished_work_still_takes_its_photos(world):  # noqa: F811 -- pytest fixture imported from the shared e2e module
    await _send(world, "ph2", narrative="plastering 2nd floor finished", work_type="plastering",
                status="completed", occurred_on=DAY2.isoformat())
    reply = await _tap_site_update(world, [_photo("media/b/1")])
    assert reply.startswith("📷 1 photo attached"), reply


async def test_pho01_nothing_reported_says_so_instead_of_losing_the_photos(world):  # noqa: F811 -- pytest fixture imported from the shared e2e module
    reply = await _tap_site_update(world, [_photo("media/c/1")])
    assert "no activity" in reply


async def test_pho02_photos_added_today_to_earlier_work_are_on_todays_report(world):  # noqa: F811 -- pytest fixture imported from the shared e2e module
    await _send(world, "ph3", narrative="started brickwork", work_type="brickwork", occurred_on=DAY1.isoformat())
    await _send(world, "ph4", narrative="brickwork 60%", work_type="brickwork", progress_percent=60,
                occurred_on=DAY2.isoformat(), continues="brickwork")
    await _tap_site_update(world, [_photo("media/d/1", "brickwork today")])
    payload, _ = await _day(world, DAY2)
    work = payload["activities"][0]
    assert work["continued"] and work["evidence_count"] == 1 and work["photos"][0]["caption"] == "brickwork today"
