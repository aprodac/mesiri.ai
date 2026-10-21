"""WA-35 against a real database: the Save / Cancel tap on the agent's reply
confirms or rejects exactly the sender's own drafts (BE-09), and nobody
else's."""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from mesiri.application.organizations.create_company import NewCompany, create_company
from mesiri.bootstrap.settings import Settings
from mesiri.infrastructure.postgres.database import PostgresDatabase
from mesiri.infrastructure.postgres.repositories.fact_reviews import PostgresFactReviewRepository
from runtime.agent import save_button
from runtime.save_first import SaveFirstService

pytestmark = pytest.mark.integration

DAY = dt.date(2026, 10, 21)


@pytest.fixture
async def world():
    db = PostgresDatabase(Settings().postgres)
    await db.connect()
    engineer_id = uuid.uuid4()
    activities = [uuid.uuid4() for _ in range(3)]
    async with db.transaction() as conn:
        created = await create_company(
            conn,
            NewCompany(
                name=f"Save button E2E {uuid.uuid4().hex[:6]}",
                owner_name="Owner",
                owner_phone=f"9197{uuid.uuid4().int % 10**8:08d}",
                project_name="Green Villa",
                site_names=("Kakkanad",),
            ),
            now=dt.datetime(2026, 10, 21, 6, tzinfo=dt.UTC),
        )
        await conn.execute(
            text(
                "INSERT INTO users (id, organization_id, hashed_password, full_name, role, status)"
                " VALUES (:id, :org, 'x', 'Ravi', 'SITE_ENGINEER', 'active')"
            ),
            {"id": engineer_id, "org": created.organization_id},
        )
        reviews = PostgresFactReviewRepository(conn)
        # Two drafts the engineer sent, one the owner sent.
        for activity_id, actor in zip(
            activities, (engineer_id, engineer_id, created.owner_user_id), strict=True
        ):
            await conn.execute(
                text(
                    "INSERT INTO activities (id, organization_id, project_id, site_id, activity_date)"
                    " VALUES (:id, :org, :p, :s, :d)"
                ),
                {
                    "id": activity_id,
                    "org": created.organization_id,
                    "p": created.project_id,
                    "s": created.sites[0].site_id,
                    "d": DAY,
                },
            )
            await reviews.mark_draft(
                organization_id=created.organization_id,
                fact_type="activity",
                fact_id=activity_id,
                actor_user_id=actor,
            )

    yield SimpleNamespace(db=db, created=created, engineer_id=engineer_id, activities=activities)

    async with db.transaction() as conn:
        org = created.organization_id
        await conn.execute(text("DELETE FROM fact_reviews WHERE organization_id = :o"), {"o": org})
        await conn.execute(
            text(
                "DELETE FROM activity_corrections WHERE activity_id IN"
                " (SELECT id FROM activities WHERE organization_id = :o)"
            ),
            {"o": org},
        )
        await conn.execute(text("DELETE FROM organizations WHERE id = :o"), {"o": org})
    await db.disconnect()


async def _states(world) -> list[str]:
    async with world.db.transaction() as conn:
        states = await PostgresFactReviewRepository(conn).states_for("activity", world.activities)
    return [states[a] for a in world.activities]


class _Handler:
    """InteractionHandler.settle_drafts over the real save-first service."""

    def __init__(self, db):
        self._service = SaveFirstService(db)

    async def settle_drafts(self, *, organization_id, user_id, facts, keep):
        return await self._service.settle_drafts(
            organization_id=organization_id, actor_user_id=user_id, facts=facts, keep=keep
        )


def _tap(action, activity_ids):
    tap = save_button.tap_id(action, [("activity", a) for a in activity_ids])
    return SimpleNamespace(metadata={"interactive_reply_id": tap})


def _actor(world, user_id):
    return SimpleNamespace(organization_id=world.created.organization_id, user_id=f"ctx_user_{user_id}")


async def test_save_confirms_the_drafts_on_the_card_and_nothing_else(world):
    engineer = _actor(world, world.engineer_id)
    reply = await save_button.handle_tap(
        _tap(save_button.SAVE, world.activities[:1]), engineer, _Handler(world.db)
    )
    assert reply.text == save_button.SAVED_DONE
    assert await _states(world) == ["confirmed", "draft", "draft"]

    again = await save_button.handle_tap(
        _tap(save_button.SAVE, world.activities[:1]), engineer, _Handler(world.db)
    )
    assert again.text == save_button.ALREADY_DONE


async def test_cancel_rejects_them_through_the_modules_own_undo(world):
    engineer = _actor(world, world.engineer_id)
    reply = await save_button.handle_tap(
        _tap(save_button.CANCEL, world.activities[1:2]), engineer, _Handler(world.db)
    )
    assert reply.text == save_button.CANCELLED_DONE
    assert await _states(world) == ["draft", "rejected", "draft"]


async def test_nobody_settles_someone_elses_draft(world):
    engineer = _actor(world, world.engineer_id)
    reply = await save_button.handle_tap(
        _tap(save_button.CANCEL, world.activities[2:]), engineer, _Handler(world.db)
    )
    assert "not your entry" in reply.text
    assert await _states(world) == ["draft", "draft", "draft"]


async def test_another_company_cannot_touch_these_drafts(world):
    stranger = SimpleNamespace(organization_id=str(uuid.uuid4()), user_id=str(world.engineer_id))
    reply = await save_button.handle_tap(
        _tap(save_button.SAVE, world.activities), stranger, _Handler(world.db)
    )
    assert reply.text == save_button.ALREADY_DONE  # nothing of theirs: nothing said about it
    assert await _states(world) == ["draft", "draft", "draft"]
