"""UX-26 on a real Postgres: a sample company's sender id finds its person (and the company counts as active for a
message); the same encoding for a person in a real company finds nobody, so the id can never reach a real company.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from backend.postgres.actor import PostgresActorReader
from context.main_table_repositories import MainExternalIdentityRepository
from mesiri.application.learn import sandbox
from mesiri.application.organizations.create_company import NewCompany, create_company
from mesiri.application.organizations.delete_company import delete_company
from mesiri.bootstrap.settings import Settings
from mesiri.domains.shared.sandbox_gate import sample_sender_id

pytestmark = pytest.mark.integration


@pytest.fixture
async def world(monkeypatch):
    async def no_seed(app, info, real_org, today):  # noqa: ANN001, ARG001
        return {}, []

    monkeypatch.setattr(sandbox, "_seed_in_fresh_context", no_seed)
    engine = create_async_engine(Settings().postgres.dsn())
    async with engine.begin() as conn:
        made = await create_company(conn, NewCompany(
            name="Acme Real Builders", owner_name="Asha Menon", owner_email=f"asha.{uuid.uuid4().hex}@acme.test",
            project_name="Real Tower", site_names=("Block 1",)))
    person = sandbox.RealPerson(made.owner_user_id, made.organization_id, "Asha Menon")
    opened = await sandbox.open_sandbox(engine, None, person, role="SITE_ENGINEER")
    yield engine, made, opened
    async with engine.begin() as conn:
        await delete_company(conn, opened.organization_id)
        await delete_company(conn, made.organization_id)
    await engine.dispose()


async def test_a_sample_id_finds_its_person_and_a_real_one_finds_nobody(world) -> None:
    engine, made, opened = world
    async with engine.connect() as conn:
        ravi = (await conn.execute(text("SELECT id FROM users WHERE organization_id = :o AND role = 'SITE_ENGINEER'"),
                                   {"o": opened.organization_id})).scalar_one()
    reader = PostgresActorReader()
    found = await reader.resolve_by_whatsapp_id(sample_sender_id(ravi))
    assert found is not None and str(found.organization_id) == str(opened.organization_id)
    assert found.org_active  # a sample company may talk to Mesiri, though no scheduled job reaches it
    assert await reader.resolve_by_whatsapp_id(sample_sender_id(made.owner_user_id)) is None  # a real company's person

    identities = MainExternalIdentityRepository(engine)
    assert await identities.find_identity(provider="whatsapp", external_subject=sample_sender_id(ravi)) is not None
    assert await identities.find_identity(provider="whatsapp", external_subject=sample_sender_id(made.owner_user_id)) is None
