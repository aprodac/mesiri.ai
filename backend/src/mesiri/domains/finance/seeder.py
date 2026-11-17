from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.domains.shared import clock

_expense_categories = sa.Table(
    "expense_categories",
    sa.MetaData(),
    sa.Column("id", sa.UUID(as_uuid=True)),
    sa.Column("organization_id", sa.UUID(as_uuid=True)),
    sa.Column("name", sa.String),
    sa.Column("code", sa.String),
    sa.Column("status", sa.String),
    sa.Column("created_at", sa.DateTime(timezone=True)),
    sa.Column("created_by", sa.UUID(as_uuid=True)),
)

_money_accounts = sa.Table(
    "money_accounts",
    sa.MetaData(),
    sa.Column("id", sa.UUID(as_uuid=True)),
    sa.Column("organization_id", sa.UUID(as_uuid=True)),
    sa.Column("name", sa.String),
    sa.Column("account_type", sa.String),
    sa.Column("currency", sa.String),
    sa.Column("opening_balance", sa.Numeric),
    sa.Column("opening_balance_date", sa.Date),
    sa.Column("status", sa.String),
    sa.Column("created_at", sa.DateTime(timezone=True)),
    sa.Column("created_by", sa.UUID(as_uuid=True)),
)

_vendors = sa.Table(
    "vendors",
    sa.MetaData(),
    sa.Column("id", sa.UUID(as_uuid=True)),
    sa.Column("organization_id", sa.UUID(as_uuid=True)),
    sa.Column("name", sa.String),
    sa.Column("status", sa.String),
    sa.Column("created_at", sa.DateTime(timezone=True)),
    sa.Column("created_by", sa.UUID(as_uuid=True)),
)

_expenses = sa.Table(
    "expenses",
    sa.MetaData(),
    sa.Column("id", sa.UUID(as_uuid=True)),
    sa.Column("organization_id", sa.UUID(as_uuid=True)),
    sa.Column("project_id", sa.UUID(as_uuid=True)),
    sa.Column("category_id", sa.UUID(as_uuid=True)),
    sa.Column("vendor_id", sa.UUID(as_uuid=True)),
    sa.Column("expense_number", sa.String),
    sa.Column("amount", sa.Numeric),
    sa.Column("currency", sa.String),
    sa.Column("description", sa.String),
    sa.Column("occurred_date", sa.Date),
    sa.Column("workflow_status", sa.String),
    sa.Column("payment_status", sa.String),
    sa.Column("source", sa.String),
    sa.Column("created_at", sa.DateTime(timezone=True)),
    sa.Column("created_by", sa.UUID(as_uuid=True)),
)

_money_transactions = sa.Table(
    "money_transactions",
    sa.MetaData(),
    sa.Column("id", sa.UUID(as_uuid=True)),
    sa.Column("organization_id", sa.UUID(as_uuid=True)),
    sa.Column("transaction_type", sa.String),
    sa.Column("from_account_id", sa.UUID(as_uuid=True)),
    sa.Column("to_account_id", sa.UUID(as_uuid=True)),
    sa.Column("amount", sa.Numeric),
    sa.Column("source_type", sa.String),
    sa.Column("source_id", sa.UUID(as_uuid=True)),
    sa.Column("occurred_date", sa.Date),
    sa.Column("description", sa.String),
    sa.Column("created_at", sa.DateTime(timezone=True)),
    sa.Column("created_by", sa.UUID(as_uuid=True)),
)

_organization_settings = sa.Table(
    "organization_settings",
    sa.MetaData(),
    sa.Column("id", sa.UUID(as_uuid=True)),
    sa.Column("organization_id", sa.UUID(as_uuid=True)),
    sa.Column("key", sa.String),
    sa.Column("value", sa.JSON),
    sa.Column("created_at", sa.DateTime(timezone=True)),
    sa.Column("updated_at", sa.DateTime(timezone=True)),
    sa.Column("updated_by", sa.UUID(as_uuid=True)),
)

_users = sa.Table(
    "users",
    sa.MetaData(),
    sa.Column("id", sa.UUID(as_uuid=True)),
    sa.Column("organization_id", sa.UUID(as_uuid=True)),
    sa.Column("email", sa.String),
    sa.Column("hashed_password", sa.String),
    sa.Column("full_name", sa.String),
    sa.Column("role", sa.String),
    sa.Column("created_at", sa.DateTime(timezone=True)),
    sa.Column("updated_at", sa.DateTime(timezone=True)),
)

_projects = sa.Table(
    "projects",
    sa.MetaData(),
    sa.Column("id", sa.UUID(as_uuid=True)),
    sa.Column("organization_id", sa.UUID(as_uuid=True)),
    sa.Column("name", sa.String),
)

DEFAULT_CATEGORIES = [
    ("Materials & Supplies", "MAT"),
    ("Subcontractor Labour", "LAB"),
    ("Equipment Rental", "EQP"),
    ("Fuel & Logistics", "FUEL"),
    ("Site Utilities & Overhead", "UTIL"),
    ("Office & Admin", "ADM"),
    ("Miscellaneous", "MISC"),
    ("Uncategorized", "UNC"),
]

DEFAULT_VENDORS = [
    "UltraTech Cement Co.",
    "Apex Equipment Rentals",
    "Metro Fuel Station",
    "BuildPro Materials",
]


class AdminFinanceSeedingService:
    """Service for seeding schema-compliant finance data for an organization."""

    def __init__(self, conn: AsyncConnection):
        self.conn = conn

    async def seed_organization(
        self,
        organization_id: uuid.UUID,
        created_by: uuid.UUID,
        include_demo_transactions: bool = True,
    ) -> dict[str, int]:
        now = dt.datetime.now(dt.UTC)
        today = clock.today()

        categories_created = 0
        accounts_created = 0
        vendors_created = 0
        expenses_created = 0
        transactions_created = 0
        settings_created = 0

        # Ensure created_by references a valid user in users table for foreign key integrity
        user_check = await self.conn.execute(
            sa.select(_users.c.id).where(
                _users.c.organization_id == organization_id,
                _users.c.id == created_by,
            )
        )
        found_user = user_check.first()
        if not found_user:
            org_user_check = await self.conn.execute(
                sa.select(_users.c.id).where(
                    _users.c.organization_id == organization_id
                ).limit(1)
            )
            found_org_user = org_user_check.first()
            if found_org_user:
                created_by = found_org_user.id
            else:
                system_user_id = uuid.uuid4()
                await self.conn.execute(
                    sa.insert(_users).values(
                        id=system_user_id,
                        organization_id=organization_id,
                        email=f"system-seeder-{organization_id.hex[:8]}@mesiri.internal",
                        hashed_password="N/A",
                        full_name="System Finance Seeder",
                        role="ADMIN",
                        created_at=now,
                        updated_at=now,
                    )
                )
                created_by = system_user_id

        # 1. Seed Expense Categories. Dedup by `code`, not `name` --
        # uq_expense_categories_org_code is the actual unique constraint
        # (org, code); a name-only check misses a pre-existing row that
        # uses the same code under a different name and then collides on
        # insert instead of being recognized as "already seeded".
        category_ids: dict[str, uuid.UUID] = {}
        for name, code in DEFAULT_CATEGORIES:
            res = await self.conn.execute(
                sa.select(_expense_categories.c.id).where(
                    _expense_categories.c.organization_id == organization_id,
                    sa.or_(
                        _expense_categories.c.name == name,
                        _expense_categories.c.code == code,
                    ),
                )
            )
            row = res.first()
            if row:
                category_ids[name] = row.id
            else:
                cat_id = uuid.uuid4()
                await self.conn.execute(
                    sa.insert(_expense_categories).values(
                        id=cat_id,
                        organization_id=organization_id,
                        name=name,
                        code=code,
                        status="active",
                        created_at=now,
                        created_by=created_by,
                    )
                )
                category_ids[name] = cat_id
                categories_created += 1

        # 2. Seed Money Accounts
        # account_type is constrained (ck_money_accounts_account_type) to
        # 'cash' | 'bank' | 'employee_advance' | 'other' -- there is no
        # separate 'petty_cash' type; petty cash is just a cash account.
        accounts_def = [
            ("Main HDFC Bank Account", "bank", Decimal("500000.00")),
            ("Site Petty Cash Float", "cash", Decimal("50000.00")),
            ("Operational Cash Account", "cash", Decimal("100000.00")),
        ]
        account_ids: dict[str, uuid.UUID] = {}
        for acc_name, acc_type, op_bal in accounts_def:
            res = await self.conn.execute(
                sa.select(_money_accounts.c.id).where(
                    _money_accounts.c.organization_id == organization_id,
                    _money_accounts.c.name == acc_name,
                )
            )
            row = res.first()
            if row:
                account_ids[acc_name] = row.id
            else:
                acc_id = uuid.uuid4()
                await self.conn.execute(
                    sa.insert(_money_accounts).values(
                        id=acc_id,
                        organization_id=organization_id,
                        name=acc_name,
                        account_type=acc_type,
                        currency="INR",
                        opening_balance=op_bal,
                        opening_balance_date=today - dt.timedelta(days=30),
                        status="active",
                        created_at=now,
                        created_by=created_by,
                    )
                )
                account_ids[acc_name] = acc_id
                accounts_created += 1

        # 3. Seed Vendors
        vendor_ids: dict[str, uuid.UUID] = {}
        for v_name in DEFAULT_VENDORS:
            res = await self.conn.execute(
                sa.select(_vendors.c.id).where(
                    _vendors.c.organization_id == organization_id,
                    _vendors.c.name == v_name,
                )
            )
            row = res.first()
            if row:
                vendor_ids[v_name] = row.id
            else:
                v_id = uuid.uuid4()
                await self.conn.execute(
                    sa.insert(_vendors).values(
                        id=v_id,
                        organization_id=organization_id,
                        name=v_name,
                        status="active",
                        created_at=now,
                        created_by=created_by,
                    )
                )
                vendor_ids[v_name] = v_id
                vendors_created += 1

        # 4. Seed Organization Settings
        default_settings = [
            ("finance.default_currency", "INR"),
            ("finance.auto_approval_limit", "10000"),
            ("finance.low_float_alert_threshold", "10000"),
        ]
        for s_key, s_val in default_settings:
            res = await self.conn.execute(
                sa.select(_organization_settings.c.id).where(
                    _organization_settings.c.organization_id == organization_id,
                    _organization_settings.c.key == s_key,
                )
            )
            if not res.first():
                await self.conn.execute(
                    sa.insert(_organization_settings).values(
                        id=uuid.uuid4(),
                        organization_id=organization_id,
                        key=s_key,
                        value=s_val,
                        created_at=now,
                        updated_at=now,
                        updated_by=created_by,
                    )
                )
                settings_created += 1

        # 5. Seed Demo Transactions & Expenses if requested
        if include_demo_transactions:
            bank_id = account_ids.get("Main HDFC Bank Account")
            petty_id = account_ids.get("Site Petty Cash Float")

            # expenses.project_id is NOT NULL (FK to projects) -- reuse an
            # existing project for this org if there is one, otherwise create
            # a placeholder so the demo expenses have somewhere to attach.
            proj_res = await self.conn.execute(
                sa.select(_projects.c.id)
                .where(_projects.c.organization_id == organization_id)
                .limit(1)
            )
            proj_row = proj_res.first()
            if proj_row:
                demo_project_id = proj_row.id
            else:
                demo_project_id = uuid.uuid4()
                await self.conn.execute(
                    sa.insert(_projects).values(
                        id=demo_project_id,
                        organization_id=organization_id,
                        name="Demo Project",
                    )
                )

            # Check if demo transactions were already seeded
            res_tx = await self.conn.execute(
                sa.select(sa.func.count(_money_transactions.c.id)).where(
                    _money_transactions.c.organization_id == organization_id
                )
            )
            existing_tx_count = res_tx.scalar() or 0

            if existing_tx_count == 0:
                # Opening balance ledger record. ck_money_transactions_type has
                # no 'opening_balance' member -- money coming into an account
                # with no offsetting account is 'fund_received'.
                if bank_id:
                    await self.conn.execute(
                        sa.insert(_money_transactions).values(
                            id=uuid.uuid4(),
                            organization_id=organization_id,
                            transaction_type="fund_received",
                            to_account_id=bank_id,
                            amount=Decimal("500000.00"),
                            occurred_date=today - dt.timedelta(days=30),
                            description="Initial opening balance for Main HDFC Bank Account",
                            created_at=now,
                            created_by=created_by,
                        )
                    )
                    transactions_created += 1

                # Transfer to Petty Cash
                if bank_id and petty_id:
                    await self.conn.execute(
                        sa.insert(_money_transactions).values(
                            id=uuid.uuid4(),
                            organization_id=organization_id,
                            transaction_type="transfer",
                            from_account_id=bank_id,
                            to_account_id=petty_id,
                            amount=Decimal("50000.00"),
                            occurred_date=today - dt.timedelta(days=25),
                            description="Petty cash replenishment to Site Float",
                            created_at=now,
                            created_by=created_by,
                        )
                    )
                    transactions_created += 1

                # Sample Expense 1: Paid Material Expense
                mat_cat_id = category_ids.get("Materials & Supplies")
                ultratech_v_id = vendor_ids.get("UltraTech Cement Co.")
                if mat_cat_id and ultratech_v_id and bank_id:
                    exp1_id = uuid.uuid4()
                    await self.conn.execute(
                        sa.insert(_expenses).values(
                            id=exp1_id,
                            organization_id=organization_id,
                            project_id=demo_project_id,
                            category_id=mat_cat_id,
                            vendor_id=ultratech_v_id,
                            expense_number="EXP-DEMO-001",
                            amount=Decimal("45000.00"),
                            currency="INR",
                            description="Bulk Portland cement supply for foundation pouring",
                            occurred_date=today - dt.timedelta(days=20),
                            workflow_status="confirmed",
                            payment_status="paid",
                            source="control_plane_seeder",
                            created_at=now,
                            created_by=created_by,
                        )
                    )
                    expenses_created += 1

                    await self.conn.execute(
                        sa.insert(_money_transactions).values(
                            id=uuid.uuid4(),
                            organization_id=organization_id,
                            transaction_type="expense_payment",
                            from_account_id=bank_id,
                            amount=Decimal("45000.00"),
                            source_type="expense",
                            source_id=exp1_id,
                            occurred_date=today - dt.timedelta(days=20),
                            description="Payment to UltraTech Cement Co. (EXP-DEMO-001)",
                            created_at=now,
                            created_by=created_by,
                        )
                    )
                    transactions_created += 1

                # Sample Expense 2: Paid Equipment Rental Expense
                eqp_cat_id = category_ids.get("Equipment Rental")
                apex_v_id = vendor_ids.get("Apex Equipment Rentals")
                if eqp_cat_id and apex_v_id and bank_id:
                    exp2_id = uuid.uuid4()
                    await self.conn.execute(
                        sa.insert(_expenses).values(
                            id=exp2_id,
                            organization_id=organization_id,
                            project_id=demo_project_id,
                            category_id=eqp_cat_id,
                            vendor_id=apex_v_id,
                            expense_number="EXP-DEMO-002",
                            amount=Decimal("12500.00"),
                            currency="INR",
                            description="Weekly excavator rental for site excavation",
                            occurred_date=today - dt.timedelta(days=14),
                            workflow_status="confirmed",
                            payment_status="paid",
                            source="control_plane_seeder",
                            created_at=now,
                            created_by=created_by,
                        )
                    )
                    expenses_created += 1

                    await self.conn.execute(
                        sa.insert(_money_transactions).values(
                            id=uuid.uuid4(),
                            organization_id=organization_id,
                            transaction_type="expense_payment",
                            from_account_id=bank_id,
                            amount=Decimal("12500.00"),
                            source_type="expense",
                            source_id=exp2_id,
                            occurred_date=today - dt.timedelta(days=14),
                            description="Payment to Apex Equipment Rentals (EXP-DEMO-002)",
                            created_at=now,
                            created_by=created_by,
                        )
                    )
                    transactions_created += 1

                # Sample Expense 3: Petty Cash Fuel Expense
                fuel_cat_id = category_ids.get("Fuel & Logistics")
                metro_v_id = vendor_ids.get("Metro Fuel Station")
                if fuel_cat_id and metro_v_id and petty_id:
                    exp3_id = uuid.uuid4()
                    await self.conn.execute(
                        sa.insert(_expenses).values(
                            id=exp3_id,
                            organization_id=organization_id,
                            project_id=demo_project_id,
                            category_id=fuel_cat_id,
                            vendor_id=metro_v_id,
                            expense_number="EXP-DEMO-003",
                            amount=Decimal("3800.00"),
                            currency="INR",
                            description="Diesel fuel for generator & site truck",
                            occurred_date=today - dt.timedelta(days=7),
                            workflow_status="confirmed",
                            payment_status="paid",
                            source="control_plane_seeder",
                            created_at=now,
                            created_by=created_by,
                        )
                    )
                    expenses_created += 1

                    await self.conn.execute(
                        sa.insert(_money_transactions).values(
                            id=uuid.uuid4(),
                            organization_id=organization_id,
                            transaction_type="expense_payment",
                            from_account_id=petty_id,
                            amount=Decimal("3800.00"),
                            source_type="expense",
                            source_id=exp3_id,
                            occurred_date=today - dt.timedelta(days=7),
                            description="Petty Cash payment to Metro Fuel Station (EXP-DEMO-003)",
                            created_at=now,
                            created_by=created_by,
                        )
                    )
                    transactions_created += 1

                # Sample Expense 4: Unpaid/Draft Expense
                adm_cat_id = category_ids.get("Office & Admin")
                buildpro_v_id = vendor_ids.get("BuildPro Materials")
                if adm_cat_id and buildpro_v_id:
                    exp4_id = uuid.uuid4()
                    await self.conn.execute(
                        sa.insert(_expenses).values(
                            id=exp4_id,
                            organization_id=organization_id,
                            project_id=demo_project_id,
                            category_id=adm_cat_id,
                            vendor_id=buildpro_v_id,
                            expense_number="EXP-DEMO-004",
                            amount=Decimal("4200.00"),
                            currency="INR",
                            description="Safety helmets, gloves & site safety gear",
                            occurred_date=today - dt.timedelta(days=2),
                            workflow_status="pending_confirmation",
                            payment_status="unpaid",
                            source="control_plane_seeder",
                            created_at=now,
                            created_by=created_by,
                        )
                    )
                    expenses_created += 1

        return {
            "categories_created": categories_created,
            "accounts_created": accounts_created,
            "vendors_created": vendors_created,
            "settings_created": settings_created,
            "expenses_created": expenses_created,
            "transactions_created": transactions_created,
        }
