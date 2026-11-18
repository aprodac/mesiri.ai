"""Variations (NXT-04, CC-24): extra or changed work the client asked for, priced, sent, approved, then billed.

Additive only. ``variations``: one per request from the client, numbered per project (VO-01, VO-02 ...):

- ``kind``: ``new`` (work not in the BOQ) or ``more`` (more of a BOQ line, ``line_id``).
- ``quantity`` × ``client_rate`` is what the client is asked for; ``cost_estimate`` what it will cost us (the margin).
- ``status``: draft → sent (to the client) → approved / rejected; cancelled from draft or sent.
- On approval the BOQ changes through its own repository: a ``new`` one becomes a line in the project's
  "Variations" section (code VO-xx), a ``more`` one raises the line's planned quantity (a revision whose reason
  names the VO). ``planned_item_id`` is the line it made; from then on the site's work on it is measured and billed
  on RA bills like any line.

Row-level security like 0522. Downgrade refuses while variations exist.

Revision ID: 0561
Revises: 0560
Create Date: 2026-11-18
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0561"
down_revision = "0560"
branch_labels = None
depends_on = None

_RULE = "mesiri_tenant() IS NULL OR organization_id = mesiri_tenant()"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE variations (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            site_id uuid REFERENCES sites(id) ON DELETE SET NULL,
            number integer NOT NULL,
            kind text NOT NULL DEFAULT 'new',
            title text NOT NULL,
            description text,
            line_id uuid REFERENCES work_package_planned_items(id) ON DELETE SET NULL,
            unit text NOT NULL,
            quantity numeric(14, 3) NOT NULL,
            client_rate numeric(14, 2) NOT NULL,
            cost_estimate numeric(16, 2),
            days_added integer,
            asked_by text,
            asked_on date NOT NULL DEFAULT current_date,
            status text NOT NULL DEFAULT 'draft',
            sent_on date,
            decided_on date,
            decided_by text,
            decision_note text,
            planned_item_id uuid REFERENCES work_package_planned_items(id) ON DELETE SET NULL,
            created_by uuid REFERENCES users(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_variations_kind CHECK (kind IN ('new', 'more')),
            CONSTRAINT ck_variations_more_has_line CHECK (kind = 'new' OR line_id IS NOT NULL),
            CONSTRAINT ck_variations_status CHECK (status IN ('draft', 'sent', 'approved', 'rejected', 'cancelled')),
            CONSTRAINT ck_variations_quantity CHECK (quantity > 0),
            CONSTRAINT ck_variations_rate CHECK (client_rate >= 0),
            CONSTRAINT ck_variations_days CHECK (days_added IS NULL OR days_added BETWEEN 0 AND 1000)
        )""")
    op.execute("CREATE UNIQUE INDEX uq_variations_number ON variations (project_id, number)")
    op.execute("CREATE INDEX ix_variations_org_status ON variations (organization_id, status)")
    op.execute("ALTER TABLE variations ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON variations USING ({_RULE}) WITH CHECK ({_RULE})")


def downgrade() -> None:
    if op.get_bind().execute(text("SELECT EXISTS (SELECT 1 FROM variations)")).scalar():
        raise RuntimeError("variations has rows: refusing to drop them")
    op.execute("DROP TABLE variations")
