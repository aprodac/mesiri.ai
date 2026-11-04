"""Deleting a company whose records point at each other, against a real Postgres (integration).

Reported from the control panel (4 Nov 2026): "Failed to delete organization ... violates foreign key constraint
material_usage_reverses_movement_id_fkey". The delete step cleared the rows that block the cascade one level deep, but
those rows can be pointed at too: a reversed receipt by its reversal (and the reversal of that reversal), an expense by
its payments, a category by its sub-categories. Guard: a transfer between two accounts keeps both accounts (its CHECK
refuses a half-empty transfer), so the step deletes pointing rows rather than emptying their links.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration


@pytest.fixture
async def engine():
    from sqlalchemy.ext.asyncio import create_async_engine

    from mesiri.bootstrap.settings import Settings

    engine = create_async_engine(Settings().postgres.dsn())
    yield engine
    await engine.dispose()


async def _company(engine) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    from mesiri.application.organizations.create_company import NewCompany, create_company

    tag = uuid.uuid4().hex[:6]
    async with engine.begin() as conn:
        created = await create_company(conn, NewCompany(name=f"Linked Builders {tag}", owner_name="Anil",
                                                        owner_email=f"anil-{tag}@linked.test", project_name="Tower"))
    assert created.project_id is not None
    return created.organization_id, created.project_id, created.owner_user_id


async def _materials_reversed_twice(conn, org: uuid.UUID, project: uuid.UUID, user: uuid.UUID) -> None:
    """A receipt, its reversal (usage) and the reversal of that (receipt): the reported failure."""
    unit = (await conn.execute(text("SELECT id FROM units_of_measure WHERE code = 'bags'"))).scalar_one()
    material, receipt, usage, back = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await conn.execute(text(
        "INSERT INTO materials_catalog (id, organization_id, name, created_by, default_unit_id) "
        "VALUES (:id, :o, :n, :u, :unit)"), {"id": material, "o": org, "n": f"Cement {material.hex[:6]}", "u": user,
                                               "unit": unit})
    row = ("organization_id, project_id, material_name, quantity, unit, occurred_date, created_by, material_id, unit_id, "
           "movement_reason, reverses_movement_id")
    vals = ":o, :p, 'Cement', 50, 'bags', :d, :u, :m, :unit, :reason, :rev"
    common = {"o": org, "p": project, "d": dt.date(2026, 11, 3), "u": user, "m": material, "unit": unit}
    await conn.execute(text(f"INSERT INTO material_receipts (id, {row}) VALUES (:id, {vals})"),
                       {**common, "id": receipt, "reason": "RECEIVED", "rev": None})
    await conn.execute(text(f"INSERT INTO material_usage (id, {row}) VALUES (:id, {vals})"),
                       {**common, "id": usage, "reason": "ADJUSTMENT_OUT", "rev": receipt})
    await conn.execute(text(f"INSERT INTO material_receipts (id, {row}) VALUES (:id, {vals})"),
                       {**common, "id": back, "reason": "ADJUSTMENT_IN", "rev": usage})


async def _paid_expense_in_a_sub_category(conn, org: uuid.UUID, project: uuid.UUID, user: uuid.UUID) -> None:
    """Siblings: a category tree, an expense paid from a project account, a transfer between two accounts."""
    parent, child, expense = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    site_cash, office = uuid.uuid4(), uuid.uuid4()
    for cat, up in ((parent, None), (child, parent)):
        await conn.execute(text(
            "INSERT INTO expense_categories (id, organization_id, name, created_by, parent_category_id) "
            "VALUES (:id, :o, :n, :u, :up)"), {"id": cat, "o": org, "n": f"Cat {cat.hex[:6]}", "u": user, "up": up})
    for acc, proj in ((site_cash, project), (office, None)):
        await conn.execute(text(
            "INSERT INTO money_accounts (id, organization_id, account_type, name, opening_balance, opening_balance_date, "
            "created_by, project_id) VALUES (:id, :o, 'cash', :n, 0, :d, :u, :p)"),
            {"id": acc, "o": org, "n": f"Acc {acc.hex[:6]}", "d": dt.date(2026, 11, 1), "u": user, "p": proj})
    await conn.execute(text(
        "INSERT INTO expenses (id, organization_id, project_id, amount, occurred_date, created_by, category_id) "
        "VALUES (:id, :o, :p, 900, :d, :u, :c)"), {"id": expense, "o": org, "p": project, "d": dt.date(2026, 11, 3),
                                                   "u": user, "c": child})
    await conn.execute(text(
        "INSERT INTO expense_payments (id, organization_id, expense_id, account_id, amount, paid_date, created_by) "
        "VALUES (gen_random_uuid(), :o, :e, :a, 900, :d, :u)"),
        {"o": org, "e": expense, "a": site_cash, "d": dt.date(2026, 11, 3), "u": user})
    await conn.execute(text(
        "INSERT INTO money_transactions (id, amount, occurred_date, created_by, organization_id, transaction_type, "
        "from_account_id, to_account_id) VALUES (gen_random_uuid(), 5000, :d, :u, :o, 'transfer', :f, :t)"),
        {"d": dt.date(2026, 11, 2), "u": user, "o": org, "f": office, "t": site_cash})


async def _gone(engine, org: uuid.UUID) -> None:
    async with engine.connect() as conn:
        for table in ("organizations", "users", "material_receipts", "material_usage", "expenses", "money_accounts"):
            column = "id" if table == "organizations" else "organization_id"
            left = (await conn.execute(text(f"SELECT count(*) FROM {table} WHERE {column} = :o"), {"o": org})).scalar()
            assert left == 0, (table, left)


async def test_a_company_with_a_reversed_reversal_deletes(engine) -> None:
    from mesiri.application.organizations.delete_company import delete_company

    org, project, user = await _company(engine)
    async with engine.begin() as conn:
        await _materials_reversed_twice(conn, org, project, user)
    async with engine.begin() as conn:
        await delete_company(conn, org)
    await _gone(engine, org)


async def test_a_company_with_paid_expenses_categories_and_transfers_deletes(engine) -> None:
    from mesiri.application.organizations.delete_company import delete_company

    org, project, user = await _company(engine)
    async with engine.begin() as conn:
        await _materials_reversed_twice(conn, org, project, user)
        await _paid_expense_in_a_sub_category(conn, org, project, user)
    async with engine.begin() as conn:
        await delete_company(conn, org)
    await _gone(engine, org)


async def test_guard_another_company_is_untouched(engine) -> None:
    from mesiri.application.organizations.delete_company import delete_company

    org, project, user = await _company(engine)
    other, other_project, other_user = await _company(engine)
    async with engine.begin() as conn:
        await _materials_reversed_twice(conn, org, project, user)
        await _materials_reversed_twice(conn, other, other_project, other_user)
        await _paid_expense_in_a_sub_category(conn, other, other_project, other_user)
    async with engine.begin() as conn:
        await delete_company(conn, org)
    try:
        async with engine.connect() as conn:
            counts = [(await conn.execute(text(f"SELECT count(*) FROM {t} WHERE organization_id = :o"),
                                          {"o": other})).scalar()
                      for t in ("material_receipts", "material_usage", "expense_payments", "money_transactions")]
            assert counts == [2, 1, 1, 1]
            reversal = (await conn.execute(text(
                "SELECT count(*) FROM material_receipts WHERE organization_id = :o AND reverses_movement_id IS NOT NULL"),
                {"o": other})).scalar()
            assert reversal == 1  # its reversal links are kept
    finally:
        async with engine.begin() as conn:
            await delete_company(conn, other)
