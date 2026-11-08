"""Equipment & machinery (NXT-11, NXT-13, NXT-14, NXT-15): the machine register, the day's log, hire bills.

Content per machine per day decided by Ilan, 7 Nov 2026 (D-N5): name, owned or hired, hours worked, idle /
breakdown hours, diesel, hire rate. Plan: ``docs/plans/equipment-module-plan.md``.

``equipment`` (new) -- one row per machine or vehicle the company owns or hires (EQ-0001 per company): its kind,
owned / hired, the hire company (a vendor of kind ``hire``, 0516), the rate per hour / day / month and the hire's
minimum hours a day, where it is now (project and site), on hire from / off hire on, service every N hours.

``equipment_events`` (0110, unused until now) gains the register link and the day's log: ``event_type`` ``day_log``
is one machine's day at one site (worked = ``duration_hours``, idle, breakdown with its reason, diesel, operator,
trips, meter); ``moved`` / ``arrived`` / ``departed`` / ``serviced`` are what happened to it. A log can name the
expense its diesel was paid on and the site issue its breakdown raised. Voided, never deleted. One live day log
per machine per day.

``equipment_hire_bills`` (new) -- a hire company's bill for one machine and period (hours / days / amount), checked
against the day logs (NXT-13); its expense (the bill on the supplier ledger, CC-09) when there is one.

``material_categories.returnable`` -- shuttering, scaffolding and tools (NXT-14) are materials in a returnable
category: held per site and moved with transfers (BE-32), not a second stock system.

The ``equipment`` module is on for every company (asked in session, 8 Nov 2026): it is added to every company whose
module list is already stored, recorded in ``equipment_switched_on_0518`` so a downgrade takes it away from exactly
those (as 0506 did for finance).

Additive: new tables (row-level security, as every company table), new nullable columns, new checks. Downgrade
refuses while machines exist (dropping them would lose the logs).

Revision ID: 0518
Revises: 0517
Create Date: 2026-11-08
"""

from __future__ import annotations

from alembic import op

revision = "0518"
down_revision = "0517"
branch_labels = None
depends_on = None

_RULE = "mesiri_tenant() IS NULL OR organization_id = mesiri_tenant()"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE equipment (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            number integer NOT NULL,
            name text NOT NULL,
            type text,
            kind text NOT NULL DEFAULT 'machine',
            ownership text NOT NULL DEFAULT 'owned',
            vendor_id uuid REFERENCES vendors(id),
            rate numeric(12, 2),
            rate_unit text,
            min_hours_per_day numeric(4, 1),
            registration_no text,
            make_model text,
            fuel_type text,
            project_id uuid REFERENCES projects(id) ON DELETE SET NULL,
            site_id uuid REFERENCES sites(id) ON DELETE SET NULL,
            status text NOT NULL DEFAULT 'active',
            on_hire_from date,
            off_hire_on date,
            service_every_hours numeric(8, 1),
            last_service_on date,
            last_service_meter numeric(10, 1),
            operator_name text,
            operator_worker_id uuid REFERENCES workforce_workers(id) ON DELETE SET NULL,
            notes text,
            created_at timestamptz NOT NULL DEFAULT now(),
            created_by uuid REFERENCES users(id),
            updated_at timestamptz NOT NULL DEFAULT now(),
            updated_by uuid REFERENCES users(id),
            CONSTRAINT uq_equipment_number UNIQUE (organization_id, number),
            CONSTRAINT ck_equipment_name CHECK (btrim(name) <> ''),
            CONSTRAINT ck_equipment_kind CHECK (kind IN ('machine', 'vehicle')),
            CONSTRAINT ck_equipment_ownership CHECK (ownership IN ('owned', 'hired')),
            CONSTRAINT ck_equipment_status CHECK (status IN ('active', 'off_hire', 'retired')),
            CONSTRAINT ck_equipment_rate CHECK (rate IS NULL OR rate >= 0),
            CONSTRAINT ck_equipment_rate_unit CHECK (rate_unit IS NULL OR rate_unit IN ('hour', 'day', 'month')),
            CONSTRAINT ck_equipment_min_hours CHECK (min_hours_per_day IS NULL OR min_hours_per_day BETWEEN 0 AND 24),
            CONSTRAINT ck_equipment_service CHECK (service_every_hours IS NULL OR service_every_hours > 0)
        )
        """
    )
    # A name is how people say it on WhatsApp ("JCB 2"): one live machine per name per company.
    op.execute(
        "CREATE UNIQUE INDEX uq_equipment_org_name ON equipment (organization_id, lower(btrim(name))) "
        "WHERE status <> 'retired'"
    )
    op.execute("CREATE INDEX ix_equipment_site ON equipment (site_id) WHERE site_id IS NOT NULL")
    op.execute("CREATE INDEX ix_equipment_vendor ON equipment (vendor_id) WHERE vendor_id IS NOT NULL")

    op.execute(
        "ALTER TABLE equipment_events "
        "ADD COLUMN equipment_id uuid REFERENCES equipment(id), "
        "ADD COLUMN idle_hours numeric(5, 2), "
        "ADD COLUMN breakdown_hours numeric(5, 2), "
        "ADD COLUMN breakdown_reason text, "
        "ADD COLUMN operator_name text, "
        "ADD COLUMN operator_worker_id uuid REFERENCES workforce_workers(id) ON DELETE SET NULL, "
        "ADD COLUMN trips integer, "
        "ADD COLUMN meter_reading numeric(10, 1), "
        "ADD COLUMN expense_id uuid REFERENCES expenses(id) ON DELETE SET NULL, "
        "ADD COLUMN issue_id uuid REFERENCES site_issues(id) ON DELETE SET NULL, "
        "ADD COLUMN notes text, "
        "ADD COLUMN voided_at timestamptz, "
        "ADD COLUMN voided_by uuid REFERENCES users(id)"
    )
    op.execute(
        "ALTER TABLE equipment_events ADD CONSTRAINT ck_equipment_events_hours CHECK ("
        "(duration_hours IS NULL OR duration_hours >= 0) AND (idle_hours IS NULL OR idle_hours >= 0) "
        "AND (breakdown_hours IS NULL OR breakdown_hours >= 0) "
        "AND COALESCE(duration_hours, 0) + COALESCE(idle_hours, 0) + COALESCE(breakdown_hours, 0) <= 24)"
    )
    op.execute(
        "ALTER TABLE equipment_events ADD CONSTRAINT ck_equipment_events_fuel CHECK ("
        "(fuel_quantity IS NULL OR fuel_quantity >= 0) AND (fuel_cost IS NULL OR fuel_cost >= 0) "
        "AND (trips IS NULL OR trips >= 0))"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_equipment_events_day_log ON equipment_events (equipment_id, occurred_date) "
        "WHERE event_type = 'day_log' AND voided_at IS NULL"
    )
    op.execute(
        "CREATE INDEX ix_equipment_events_equipment ON equipment_events (equipment_id, occurred_date) "
        "WHERE equipment_id IS NOT NULL"
    )

    op.execute(
        """
        CREATE TABLE equipment_hire_bills (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            equipment_id uuid NOT NULL REFERENCES equipment(id) ON DELETE CASCADE,
            vendor_id uuid REFERENCES vendors(id),
            period_from date NOT NULL,
            period_to date NOT NULL,
            billed_hours numeric(8, 2),
            billed_days numeric(6, 1),
            amount numeric(14, 2) NOT NULL,
            bill_ref text,
            bill_date date,
            expense_id uuid REFERENCES expenses(id) ON DELETE SET NULL,
            notes text,
            created_at timestamptz NOT NULL DEFAULT now(),
            created_by uuid REFERENCES users(id),
            CONSTRAINT ck_equipment_hire_bills_period CHECK (period_to >= period_from),
            CONSTRAINT ck_equipment_hire_bills_amount CHECK (amount >= 0
                AND (billed_hours IS NULL OR billed_hours >= 0) AND (billed_days IS NULL OR billed_days >= 0))
        )
        """
    )
    op.execute("CREATE INDEX ix_equipment_hire_bills_equipment ON equipment_hire_bills (equipment_id, period_from)")

    for table in ("equipment", "equipment_hire_bills"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {table} USING ({_RULE}) WITH CHECK ({_RULE})")

    op.execute("ALTER TABLE material_categories ADD COLUMN returnable boolean NOT NULL DEFAULT false")

    # The module on for every company whose module list is stored (the code default has it for the others).
    op.execute(
        """
        CREATE TABLE equipment_switched_on_0518 (
            organization_id uuid PRIMARY KEY REFERENCES organizations(id) ON DELETE CASCADE,
            switched_on_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("ALTER TABLE equipment_switched_on_0518 ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON equipment_switched_on_0518 USING ({_RULE}) WITH CHECK ({_RULE})")
    op.execute(
        """
        INSERT INTO equipment_switched_on_0518 (organization_id)
        SELECT organization_id FROM organization_settings
         WHERE key = 'enabled_modules'
           AND jsonb_typeof(value) = 'array'
           AND NOT value @> '["equipment"]'::jsonb
        """
    )
    op.execute(
        """
        UPDATE organization_settings s
           SET value = s.value || '["equipment"]'::jsonb, updated_at = now()
          FROM equipment_switched_on_0518 f
         WHERE s.organization_id = f.organization_id AND s.key = 'enabled_modules'
        """
    )


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM equipment) "
        "THEN RAISE EXCEPTION 'machines are recorded; downgrading would lose them and their logs'; END IF; END $$"
    )
    op.execute(
        """
        UPDATE organization_settings s
           SET value = COALESCE(
                   (SELECT jsonb_agg(m) FROM jsonb_array_elements(s.value) m WHERE m <> '"equipment"'::jsonb),
                   '[]'::jsonb),
               updated_at = now()
          FROM equipment_switched_on_0518 f
         WHERE s.organization_id = f.organization_id AND s.key = 'enabled_modules'
        """
    )
    op.execute("DROP TABLE IF EXISTS equipment_switched_on_0518")
    op.execute("ALTER TABLE material_categories DROP COLUMN IF EXISTS returnable")
    op.execute("DROP TABLE IF EXISTS equipment_hire_bills")
    op.execute("DROP INDEX IF EXISTS ix_equipment_events_equipment")
    op.execute("DROP INDEX IF EXISTS uq_equipment_events_day_log")
    op.execute("ALTER TABLE equipment_events DROP CONSTRAINT IF EXISTS ck_equipment_events_fuel")
    op.execute("ALTER TABLE equipment_events DROP CONSTRAINT IF EXISTS ck_equipment_events_hours")
    op.execute(
        "ALTER TABLE equipment_events DROP COLUMN IF EXISTS voided_by, DROP COLUMN IF EXISTS voided_at, "
        "DROP COLUMN IF EXISTS notes, DROP COLUMN IF EXISTS issue_id, DROP COLUMN IF EXISTS expense_id, "
        "DROP COLUMN IF EXISTS meter_reading, DROP COLUMN IF EXISTS trips, DROP COLUMN IF EXISTS operator_worker_id, "
        "DROP COLUMN IF EXISTS operator_name, DROP COLUMN IF EXISTS breakdown_reason, "
        "DROP COLUMN IF EXISTS breakdown_hours, DROP COLUMN IF EXISTS idle_hours, DROP COLUMN IF EXISTS equipment_id"
    )
    op.execute("DROP TABLE IF EXISTS equipment")
