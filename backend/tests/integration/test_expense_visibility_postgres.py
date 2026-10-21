"""SEC-01 against a real database: the dashboard's expense reads follow
mesiri.authorization.roles -- owner/admin, finance and project managers, each
within the projects they reach; everyone else gets a 403 (and can still pick a
category to record an expense, without the spending per category)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from mesiri.application.organizations.create_company import NewCompany, create_company
from mesiri.authorization.context import AccessPolicy, AuthorizationContext, ProjectAccessScope
from mesiri.bootstrap.settings import Settings
from mesiri.domains.expenses import router as expenses
from mesiri.infrastructure.postgres.database import PostgresDatabase

pytestmark = pytest.mark.integration


def _ctx(world, role: str, projects: set[uuid.UUID] | None) -> AuthorizationContext:
    scope = (
        ProjectAccessScope(mode="all_projects", project_ids=set())
        if projects is None
        else ProjectAccessScope(mode="custom_projects", project_ids=projects)
    )
    return AuthorizationContext(
        user_id=world.owner,
        organization_id=world.org,
        role=role,
        status="active",
        access_policy=AccessPolicy(mode=scope.mode, projects=[]),
        project_scope=scope,
    )


@pytest.fixture
async def world():
    db = PostgresDatabase(Settings().postgres)
    await db.connect()
    async with db.transaction() as conn:
        created = await create_company(
            conn,
            NewCompany(
                name=f"Expense rule {uuid.uuid4().hex[:6]}",
                owner_name="Owner",
                owner_phone=f"9195{uuid.uuid4().int % 10**8:08d}",
                project_name="Green Villa",
                site_names=("Kakkanad",),
            ),
            now=dt.datetime(2026, 10, 21, 6, tzinfo=dt.UTC),
        )
        other = uuid.uuid4()
        await conn.execute(
            text("INSERT INTO projects (id, organization_id, name) VALUES (:id, :o, 'Blue Hills')"),
            {"id": other, "o": created.organization_id},
        )
        category = uuid.uuid4()
        await conn.execute(
            text(
                "INSERT INTO expense_categories (id, organization_id, name, status, created_by)"
                " VALUES (:id, :o, 'transport', 'active', :u)"
            ),
            {"id": category, "o": created.organization_id, "u": created.owner_user_id},
        )
        ids = {}
        for project, amount in ((created.project_id, 1500), (other, 900)):
            ids[project] = uuid.uuid4()
            await conn.execute(
                text(
                    "INSERT INTO expenses (id, organization_id, project_id, amount, occurred_date,"
                    " created_by, category_id, workflow_status)"
                    " VALUES (:id, :o, :p, :a, :d, :u, :c, 'confirmed')"
                ),
                {
                    "id": ids[project], "o": created.organization_id, "p": project, "a": amount,
                    "d": dt.date(2026, 10, 21), "u": created.owner_user_id, "c": category,
                },
            )
    from types import SimpleNamespace

    yield SimpleNamespace(
        db=db, org=created.organization_id, owner=created.owner_user_id,
        mine=created.project_id, other=other, expenses=ids,
    )
    async with db.transaction() as conn:
        await conn.execute(text("DELETE FROM expenses WHERE organization_id = :o"), {"o": created.organization_id})
        await conn.execute(text("DELETE FROM organizations WHERE id = :o"), {"o": created.organization_id})
    await db.disconnect()


async def _listed(world, ctx) -> set[uuid.UUID]:
    async with world.db.transaction() as conn:
        return {e.id for e in await expenses.list_expenses(auth_context=ctx, conn=conn)}


async def test_admin_and_finance_with_every_project_read_every_expense(world):
    for role in ("ADMIN", "FINANCE"):
        assert await _listed(world, _ctx(world, role, None)) == set(world.expenses.values())


async def test_a_project_manager_reads_only_their_own_projects(world):
    ctx = _ctx(world, "PROJECT_MANAGER", {world.mine})
    assert await _listed(world, ctx) == {world.expenses[world.mine]}
    async with world.db.transaction() as conn:
        mine = await expenses.get_expense(expense_id=world.expenses[world.mine], auth_context=ctx, conn=conn)
        assert mine.id == world.expenses[world.mine]
        with pytest.raises(HTTPException) as other:
            await expenses.get_expense(expense_id=world.expenses[world.other], auth_context=ctx, conn=conn)
    assert other.value.status_code == 404  # not even told it exists


@pytest.mark.parametrize("role", ["SITE_ENGINEER", "SUPERVISOR"])
async def test_a_site_engineer_or_supervisor_reads_no_expenses(world, role):
    ctx = _ctx(world, role, {world.mine})
    async with world.db.transaction() as conn:
        for read in (
            lambda: expenses.list_expenses(auth_context=ctx, conn=conn),
            lambda: expenses.get_expense(expense_id=world.expenses[world.mine], auth_context=ctx, conn=conn),
        ):
            with pytest.raises(HTTPException) as denied:
                await read()
            assert denied.value.status_code == 403


async def test_the_category_list_stays_for_recording_but_without_the_spending(world):
    async with world.db.transaction() as conn:
        engineer = await expenses.list_expense_categories(
            auth_context=_ctx(world, "SITE_ENGINEER", {world.mine}), conn=conn
        )
        admin = await expenses.list_expense_categories(auth_context=_ctx(world, "ADMIN", None), conn=conn)
    by_name = {c.name: c for c in engineer}
    assert by_name["transport"].total_amount_spent == Decimal("0")
    assert {c.name: c.total_amount_spent for c in admin}["transport"] == Decimal("2400")
