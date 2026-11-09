"""Sent copies of period reports (RPT-01 / PRC-20, reports plan R2; approved by Ilan in session, 9 Nov 2026).

A report that is sent is frozen: the copy each person got keeps its figures, its note and its PDF, even when the
data changes later (the page then says what changed since it was sent). Additive only:

- ``report_snapshots``: one row per person a report went to. ``send_id`` groups one send (or one scheduled run);
  ``scope`` is ``project`` (one project, or one of its sites) or ``portfolio`` (the owner's brief); the period; the
  report as that person was allowed to see it (``report``, JSON: rupees only for the roles that see spending); the
  sender's note; the stored PDF; the notification row that carries it on WhatsApp.

Tenant row-level security like 0536. Downgrade drops it (nothing else refers to it; the PDFs stay in storage).

Revision ID: 0538
Revises: 0537
Create Date: 2026-11-09
"""

from __future__ import annotations

from alembic import op

revision = "0538"
down_revision = "0537"
branch_labels = None
depends_on = None

_RULE = "mesiri_tenant() IS NULL OR organization_id = mesiri_tenant()"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE report_snapshots (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            send_id uuid NOT NULL,
            scope text NOT NULL,
            project_id uuid REFERENCES projects(id) ON DELETE CASCADE,
            site_id uuid REFERENCES sites(id) ON DELETE SET NULL,
            period_kind text NOT NULL,
            date_from date NOT NULL,
            date_to date NOT NULL,
            audience text NOT NULL DEFAULT 'internal',
            recipient_user_id uuid REFERENCES users(id) ON DELETE SET NULL,
            sent_by uuid REFERENCES users(id) ON DELETE SET NULL,
            trigger text NOT NULL DEFAULT 'now',
            automation_id uuid,
            note text,
            report jsonb NOT NULL,
            pdf_object_key text,
            notification_id uuid,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_report_snapshots_scope CHECK (scope IN ('project', 'portfolio')),
            CONSTRAINT ck_report_snapshots_kind CHECK (period_kind IN ('week', 'month', 'custom')),
            CONSTRAINT ck_report_snapshots_trigger CHECK (trigger IN ('now', 'schedule')),
            CONSTRAINT ck_report_snapshots_project CHECK (scope = 'portfolio' OR project_id IS NOT NULL)
        )""")
    op.execute("CREATE INDEX ix_report_snapshots_org_created ON report_snapshots (organization_id, created_at DESC)")
    op.execute("CREATE INDEX ix_report_snapshots_project ON report_snapshots (project_id, created_at DESC)")
    op.execute("CREATE INDEX ix_report_snapshots_send ON report_snapshots (send_id)")
    op.execute("ALTER TABLE report_snapshots ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON report_snapshots USING ({_RULE}) WITH CHECK ({_RULE})")


def downgrade() -> None:
    op.execute("DROP TABLE report_snapshots")
