"""Finance Module Slice 0: confirming an expense with an account must
actually move money -- expense_payments + money_transactions rows, and the
account's balance reflects it. Covers the three payment_status outcomes
(paid / reimbursable / unpaid) and idempotent replay.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from mesiri.application.expenses.commands import RecordExpenseCommand
from mesiri.application.expenses.handlers import RecordExpenseHandler
from mesiri.bootstrap.settings import Settings
from mesiri.infrastructure.postgres.repositories.expense_execution import (
    PostgresExpenseExecutionRepository,
)
from mesiri.infrastructure.postgres.repositories.finance import PostgresMoneyAccountRepository
from mesiri_contracts.application.results.execution_result import ExecutionStatus

pytestmark = pytest.mark.integration


@pytest.fixture
async def engine():
    settings = Settings()
    eng = create_async_engine(settings.postgres.dsn())
    yield eng
    await eng.dispose()


@pytest.fixture
async def scenario(engine: AsyncEngine):
    """One org/user/project/category and one money account with a starting balance."""
    org_id = uuid.uuid4()
    user_id = uuid.uuid4()
    project_id = uuid.uuid4()
    category_id = uuid.uuid4()
    account_id = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO organizations (id, name, deployment_type, db_route, status, "
                "created_at, updated_at) VALUES (:id, 'Slice0 Test Org', 'local', 'default', "
                "'active', now(), now())"
            ),
            {"id": org_id},
        )
        await conn.execute(
            sa.text(
                "INSERT INTO users (id, organization_id, email, hashed_password, full_name, "
                "role, status, access_policy, created_at, updated_at) "
                "VALUES (:id, :org_id, :email, 'x', 'Test', 'admin', 'active', "
                "CAST(:policy AS jsonb), now(), now())"
            ),
            {
                "id": user_id,
                "org_id": org_id,
                "email": f"{user_id}@example.com",
                "policy": '{"mode": "all_projects", "projects": []}',
            },
        )
        await conn.execute(
            sa.text(
                "INSERT INTO projects (id, organization_id, name, created_at, updated_at) "
                "VALUES (:id, :org_id, 'Slice0 Test Project', now(), now())"
            ),
            {"id": project_id, "org_id": org_id},
        )
        await conn.execute(
            sa.text(
                "INSERT INTO expense_categories (id, organization_id, name, status, created_by) "
                "VALUES (:id, :org_id, 'fuel', 'active', :user_id)"
            ),
            {"id": category_id, "org_id": org_id, "user_id": user_id},
        )
        await conn.execute(
            sa.text(
                "INSERT INTO money_accounts (id, organization_id, name, account_type, "
                "currency, opening_balance, opening_balance_date, status, created_by) "
                "VALUES (:id, :org_id, 'Site Cash', 'cash', 'INR', 5000.00, current_date, "
                "'active', :user_id)"
            ),
            {"id": account_id, "org_id": org_id, "user_id": user_id},
        )
    yield {
        "org_id": org_id,
        "user_id": user_id,
        "project_id": project_id,
        "category_id": category_id,
        "account_id": account_id,
    }
    async with engine.begin() as conn:
        await conn.execute(sa.text("DELETE FROM money_transactions WHERE organization_id = :id"), {"id": org_id})
        await conn.execute(sa.text("DELETE FROM expense_payments WHERE organization_id = :id"), {"id": org_id})
        await conn.execute(
            sa.text(
                "DELETE FROM expense_attachments WHERE expense_id IN "
                "(SELECT id FROM expenses WHERE organization_id = :id)"
            ),
            {"id": org_id},
        )
        await conn.execute(sa.text("DELETE FROM expenses WHERE organization_id = :id"), {"id": org_id})
        await conn.execute(sa.text("DELETE FROM money_accounts WHERE organization_id = :id"), {"id": org_id})
        await conn.execute(sa.text("DELETE FROM expense_categories WHERE organization_id = :id"), {"id": org_id})
        await conn.execute(sa.text("DELETE FROM organizations WHERE id = :id"), {"id": org_id})


def _command(scenario: dict, **overrides) -> RecordExpenseCommand:
    base = dict(
        idempotency_key=f"slice0-{uuid.uuid4()}",
        organization_id=str(scenario["org_id"]),
        project_id=str(scenario["project_id"]),
        category_id=str(scenario["category_id"]),
        amount=Decimal("1200.00"),
        occurred_date=datetime.date.today(),
        created_by=str(scenario["user_id"]),
    )
    base.update(overrides)
    return RecordExpenseCommand(**base)


async def test_expense_with_account_creates_payment_and_ledger_row_and_moves_balance(
    engine: AsyncEngine, scenario: dict
):
    handler = RecordExpenseHandler(PostgresExpenseExecutionRepository())
    cmd = _command(scenario, account_id=str(scenario["account_id"]))

    async with engine.begin() as conn:
        result = await handler.handle(conn, cmd)

    assert result.status == ExecutionStatus.SUCCEEDED
    expense_id = uuid.UUID(result.material_row_id)

    async with engine.connect() as conn:
        payment_count = (
            await conn.execute(
                sa.text("SELECT count(*) FROM expense_payments WHERE expense_id = :id"),
                {"id": expense_id},
            )
        ).scalar_one()
        ledger_count = (
            await conn.execute(
                sa.text(
                    "SELECT count(*) FROM money_transactions "
                    "WHERE source_type = 'expense_payment' AND source_id IN "
                    "(SELECT id FROM expense_payments WHERE expense_id = :id)"
                ),
                {"id": expense_id},
            )
        ).scalar_one()
        payment_status = (
            await conn.execute(
                sa.text("SELECT payment_status FROM expenses WHERE id = :id"), {"id": expense_id}
            )
        ).scalar_one()
        accounts = PostgresMoneyAccountRepository(conn)
        balance = await accounts.get_balance(scenario["org_id"], scenario["account_id"])

    assert payment_count == 1
    assert ledger_count == 1
    assert payment_status == "paid"
    assert balance == Decimal("5000.00") - Decimal("1200.00")


async def test_expense_with_tax_fields_persists_and_round_trips(engine: AsyncEngine, scenario: dict):
    """The gap this closes: RecordExpenseCommand/persist_success never wrote
    tax_rate/tax_amount/is_tax_inclusive at all, so migration 0380's columns
    were unreachable from either the REST or WhatsApp path -- every expense
    came back with NULL tax data regardless of what was sent."""
    handler = RecordExpenseHandler(PostgresExpenseExecutionRepository())
    cmd = _command(
        scenario,
        tax_rate=Decimal("18.00"),
        tax_amount=Decimal("180.00"),
        is_tax_inclusive=False,
    )

    async with engine.begin() as conn:
        result = await handler.handle(conn, cmd)

    assert result.status == ExecutionStatus.SUCCEEDED
    expense_id = uuid.UUID(result.material_row_id)

    async with engine.connect() as conn:
        row = (
            await conn.execute(
                sa.text(
                    "SELECT tax_rate, tax_amount, is_tax_inclusive FROM expenses WHERE id = :id"
                ),
                {"id": expense_id},
            )
        ).mappings().first()

    assert row["tax_rate"] == Decimal("18.00")
    assert row["tax_amount"] == Decimal("180.00")
    assert row["is_tax_inclusive"] is False


async def test_expense_without_tax_fields_stays_null(engine: AsyncEngine, scenario: dict):
    """Most expenses have no stated tax -- must stay NULL, not default to 0,
    and is_tax_inclusive defaults True (matches migration 0380's column
    default)."""
    handler = RecordExpenseHandler(PostgresExpenseExecutionRepository())
    cmd = _command(scenario)

    async with engine.begin() as conn:
        result = await handler.handle(conn, cmd)

    expense_id = uuid.UUID(result.material_row_id)

    async with engine.connect() as conn:
        row = (
            await conn.execute(
                sa.text(
                    "SELECT tax_rate, tax_amount, is_tax_inclusive FROM expenses WHERE id = :id"
                ),
                {"id": expense_id},
            )
        ).mappings().first()

    assert row["tax_rate"] is None
    assert row["tax_amount"] is None
    assert row["is_tax_inclusive"] is True


async def test_own_pocket_expense_has_no_payment_or_ledger_row(
    engine: AsyncEngine, scenario: dict
):
    handler = RecordExpenseHandler(PostgresExpenseExecutionRepository())
    cmd = _command(scenario, paid_from_own_pocket=True)

    async with engine.begin() as conn:
        result = await handler.handle(conn, cmd)

    assert result.status == ExecutionStatus.SUCCEEDED
    expense_id = uuid.UUID(result.material_row_id)

    async with engine.connect() as conn:
        payment_count = (
            await conn.execute(
                sa.text("SELECT count(*) FROM expense_payments WHERE expense_id = :id"),
                {"id": expense_id},
            )
        ).scalar_one()
        payment_status = (
            await conn.execute(
                sa.text("SELECT payment_status FROM expenses WHERE id = :id"), {"id": expense_id}
            )
        ).scalar_one()
        accounts = PostgresMoneyAccountRepository(conn)
        balance = await accounts.get_balance(scenario["org_id"], scenario["account_id"])

    assert payment_count == 0
    assert payment_status == "reimbursable"
    # Own-pocket must not move company money -- the account's balance is untouched.
    assert balance == Decimal("5000.00")


async def test_expense_with_neither_choice_stays_unpaid(engine: AsyncEngine, scenario: dict):
    handler = RecordExpenseHandler(PostgresExpenseExecutionRepository())
    cmd = _command(scenario)

    async with engine.begin() as conn:
        result = await handler.handle(conn, cmd)

    expense_id = uuid.UUID(result.material_row_id)
    async with engine.connect() as conn:
        payment_status = (
            await conn.execute(
                sa.text("SELECT payment_status FROM expenses WHERE id = :id"), {"id": expense_id}
            )
        ).scalar_one()
    assert payment_status == "unpaid"


async def test_replayed_idempotency_key_does_not_double_post_the_ledger(
    engine: AsyncEngine, scenario: dict
):
    """Same Idempotency-Key delivered twice (retry/duplicate webhook) must
    not create a second expense_payments/money_transactions row."""
    handler = RecordExpenseHandler(PostgresExpenseExecutionRepository())
    cmd = _command(scenario, account_id=str(scenario["account_id"]))

    async with engine.begin() as conn:
        first = await handler.handle(conn, cmd)
    async with engine.begin() as conn:
        second = await handler.handle(conn, cmd)

    assert first.status == ExecutionStatus.SUCCEEDED
    assert second.status == ExecutionStatus.ALREADY_EXECUTED
    expense_id = uuid.UUID(first.material_row_id)

    async with engine.connect() as conn:
        payment_count = (
            await conn.execute(
                sa.text("SELECT count(*) FROM expense_payments WHERE expense_id = :id"),
                {"id": expense_id},
            )
        ).scalar_one()
        accounts = PostgresMoneyAccountRepository(conn)
        balance = await accounts.get_balance(scenario["org_id"], scenario["account_id"])

    assert payment_count == 1
    assert balance == Decimal("5000.00") - Decimal("1200.00")


async def test_expense_with_media_object_key_creates_one_receipt_attachment(
    engine: AsyncEngine, scenario: dict
):
    """A WhatsApp image tapped as "Expense" in the image-purpose picker
    (interactions/image_purpose.py) carries media_object_key all the way
    through to confirmation -- this proves the attachment actually gets
    written, not just threaded through as inert data."""
    handler = RecordExpenseHandler(PostgresExpenseExecutionRepository())
    cmd = _command(scenario, media_object_key="media/wamid.1/abc123")

    async with engine.begin() as conn:
        result = await handler.handle(conn, cmd)

    assert result.status == ExecutionStatus.SUCCEEDED
    expense_id = uuid.UUID(result.material_row_id)

    async with engine.connect() as conn:
        row = (
            await conn.execute(
                sa.text(
                    "SELECT media_object_key, attachment_type FROM expense_attachments "
                    "WHERE expense_id = :id"
                ),
                {"id": expense_id},
            )
        ).mappings().one()
    assert row["media_object_key"] == "media/wamid.1/abc123"
    assert row["attachment_type"] == "receipt"


async def test_expense_without_media_object_key_creates_no_attachment(
    engine: AsyncEngine, scenario: dict
):
    handler = RecordExpenseHandler(PostgresExpenseExecutionRepository())
    cmd = _command(scenario)

    async with engine.begin() as conn:
        result = await handler.handle(conn, cmd)

    expense_id = uuid.UUID(result.material_row_id)
    async with engine.connect() as conn:
        count = (
            await conn.execute(
                sa.text("SELECT count(*) FROM expense_attachments WHERE expense_id = :id"),
                {"id": expense_id},
            )
        ).scalar_one()
    assert count == 0


async def test_expense_with_vendor_id_writes_it_to_the_expense_row(
    engine: AsyncEngine, scenario: dict
):
    """Finance Module Slice 4: a vendor_id resolved before persist_success
    (see application/vendors/resolution.py) must actually land on the
    expenses row -- the column previously had no migration and was never
    written at all."""
    org_id = scenario["org_id"]
    user_id = scenario["user_id"]
    vendor_id = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO vendors (id, organization_id, name, status, created_by) "
                "VALUES (:id, :org_id, 'ABC Hardware', 'active', :user_id)"
            ),
            {"id": vendor_id, "org_id": org_id, "user_id": user_id},
        )

    handler = RecordExpenseHandler(PostgresExpenseExecutionRepository())
    cmd = _command(scenario, vendor_id=str(vendor_id))

    async with engine.begin() as conn:
        result = await handler.handle(conn, cmd)

    expense_id = uuid.UUID(result.material_row_id)
    async with engine.connect() as conn:
        stored_vendor_id = (
            await conn.execute(
                sa.text("SELECT vendor_id FROM expenses WHERE id = :id"), {"id": expense_id}
            )
        ).scalar_one()
    assert stored_vendor_id == vendor_id
    # No manual vendor cleanup needed: vendors.organization_id cascades from
    # organizations (migration 0370), and the fixture teardown below deletes
    # this scenario's organization row in the same DELETE statement as its
    # expenses row -- both children vanish together, so the
    # expenses.vendor_id -> vendors FK (no cascade of its own) never sees a
    # dangling reference to violate (see 0361's docstring for why this is
    # safe: a single DELETE statement is checked for FK violations once, at
    # the end, not row-by-row).


async def test_expense_without_vendor_id_leaves_it_null(engine: AsyncEngine, scenario: dict):
    handler = RecordExpenseHandler(PostgresExpenseExecutionRepository())
    cmd = _command(scenario)

    async with engine.begin() as conn:
        result = await handler.handle(conn, cmd)

    expense_id = uuid.UUID(result.material_row_id)
    async with engine.connect() as conn:
        stored_vendor_id = (
            await conn.execute(
                sa.text("SELECT vendor_id FROM expenses WHERE id = :id"), {"id": expense_id}
            )
        ).scalar_one()
    assert stored_vendor_id is None


async def test_expense_with_a_new_vendor_name_creates_the_vendor_and_saves_in_one_transaction(
    engine: AsyncEngine, scenario: dict
):
    """Request 198: "Yes, add new vendor" -- the vendor row and the expense row are
    written together, with the account the sender picked."""
    from mesiri.application.vendors.resolution import PostgresVendorResolver

    handler = RecordExpenseHandler(PostgresExpenseExecutionRepository(), vendor_resolver=PostgresVendorResolver())
    cmd = _command(scenario, account_id=str(scenario["account_id"]), vendor_text="Irani Cafe NIBM")
    async with engine.begin() as conn:
        result = await handler.handle(conn, cmd)
    assert result.status == ExecutionStatus.SUCCEEDED
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                sa.text("SELECT v.name, v.status FROM expenses e JOIN vendors v ON v.id = e.vendor_id WHERE e.id = :id"),
                {"id": uuid.UUID(result.material_row_id)},
            )
        ).first()
    assert row is not None and tuple(row) == ("Irani Cafe NIBM", "active")


async def test_a_new_vendor_whose_name_belongs_to_a_deactivated_vendor_still_saves(
    engine: AsyncEngine, scenario: dict
):
    """Request 198: the unique (organization, name) row of a deactivated vendor must not make
    "add new vendor" blow up (the create used to assert on a row it could not see)."""
    from mesiri.application.vendors.resolution import PostgresVendorResolver

    async with engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO vendors (id, organization_id, name, status, created_by) "
                "VALUES (:id, :org_id, 'Irani Cafe NIBM', 'inactive', :user_id)"
            ),
            {"id": uuid.uuid4(), "org_id": scenario["org_id"], "user_id": scenario["user_id"]},
        )
    handler = RecordExpenseHandler(PostgresExpenseExecutionRepository(), vendor_resolver=PostgresVendorResolver())
    cmd = _command(scenario, vendor_text="Irani Cafe NIBM")
    async with engine.begin() as conn:
        result = await handler.handle(conn, cmd)
    assert result.status == ExecutionStatus.SUCCEEDED
