"""Announcements: a message from the Mesiri team to the people of every company (SA-37).

Written and sent from the control panel (Announcements). Each send queues one `notifications` row per person
(rule_key `announcement`), so the WhatsApp sender's own rules apply: opt-outs, quiet hours, the 24-hour window.
Someone who has not messaged Mesiri in 24 hours gets it the next time they do (status `waiting_window`, at most
`hold_days`), or by the approved template when there is one.

Additive: one platform table (no company column, so no row-level security, like the other platform tables), and
the first announcement as a draft: Material Requests (PRC-22, 7 Nov 2026), for the team to check and send.

Revision ID: 0510
Revises: 0509
Create Date: 2026-11-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0510"
down_revision = "0509"
branch_labels = None
depends_on = None

_FIRST = {
    "title": "Material Requests",
    "message": (
        "*New in Mesiri: Material Requests* 📦\n"
        "Ask for material straight from WhatsApp, and the office sees it at once.\n\n"
        "*Just say:* \"Need 200 bags cement tomorrow for the slab\", or \"cement venam nale\". Then tap Save.\n"
        "• \"What did I ask for?\": your requests and where each one is\n"
        "• Office: \"Show the requests\" / \"Order Arun's cement, Malabar Hardware\" / \"Say no to the putty, "
        "enough at site\"\n\n"
        "You're told on WhatsApp when it's ordered, sent from another site, refused or received. If someone already "
        "asked for the same item, Mesiri tells you before it's sent twice.\n"
        "*Dashboard:* Materials → Requests shows what's at site, on its way, and still to buy."
    ),
}


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE announcements (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            title text NOT NULL,
            message text NOT NULL,
            image_keys jsonb NOT NULL DEFAULT '[]'::jsonb,
            hold_days integer NOT NULL DEFAULT 7,
            created_by uuid,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            sends jsonb NOT NULL DEFAULT '[]'::jsonb,
            CONSTRAINT ck_announcements_title CHECK (btrim(title) <> ''),
            CONSTRAINT ck_announcements_message CHECK (btrim(message) <> ''),
            CONSTRAINT ck_announcements_hold_days CHECK (hold_days BETWEEN 0 AND 14)
        )
        """
    )
    op.get_bind().execute(
        sa.text("INSERT INTO announcements (title, message) VALUES (:title, :message)"),
        {"title": _FIRST["title"], "message": _FIRST["message"]},
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS announcements")
