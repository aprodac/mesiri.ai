"""What works pins: the conversation an admin chose as the model example of one journey (SA-39 phase 5).

The Playbook view of the control panel's What works page picks the best real conversation for every way people
ask for something by a score (decision D2). Decision D3 (15 Nov 2026): a platform admin may pin another one, e.g.
when the scored pick is a message nobody would show. One row per (capability, journey): the pinned request's
first inbound message, who pinned it and when. Every pin and unpin is in `admin_audit_log` in the same
transaction (`what_works.pinned` / `what_works.unpinned`).

Additive: one platform table (no company column, so no row-level security, like `announcements`); nothing else
reads it. Downgrade drops it; the page falls back to the scored pick.

Revision ID: 0552
Revises: 0551
Create Date: 2026-11-15
"""

from __future__ import annotations

from alembic import op

revision = "0552"
down_revision = "0551"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE what_works_pins (
            capability text NOT NULL,
            journey text NOT NULL,
            message_id uuid NOT NULL,
            note text,
            pinned_by uuid,
            pinned_by_label text,
            pinned_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (capability, journey),
            CONSTRAINT ck_what_works_pins_capability CHECK (btrim(capability) <> ''),
            CONSTRAINT ck_what_works_pins_journey CHECK (btrim(journey) <> '')
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS what_works_pins")
