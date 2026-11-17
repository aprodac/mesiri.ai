"""A person in a learning sandbox can't hold a WhatsApp number (SS-66d).

Incoming WhatsApp messages find their company by the sender's number (users.whatsapp_number). A number typed into a
sandbox's team page would send that real person's messages into the sandbox and its replies back to them. Six places
write a person's number (the dashboard's and the control panel's people routes, create-user, company creation, signup,
contact sharing); this trigger is the one rule all of them meet, now and later. Its message starts with
``MESIRI_SANDBOX:``, which the API turns into a 422 with the reason (mesiri/http/db_errors.py).

Additive: a function and a trigger; no row changes. Downgrade drops both.

Revision ID: 0557
Revises: 0556
Create Date: 2026-11-17
"""

from __future__ import annotations

from alembic import op

revision = "0557"
down_revision = "0556"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE OR REPLACE FUNCTION refuse_sandbox_whatsapp_number() RETURNS trigger AS $$
        BEGIN
            IF NEW.whatsapp_number IS NOT NULL AND EXISTS (
                SELECT 1 FROM organizations o WHERE o.id = NEW.organization_id AND o.sandbox_of IS NOT NULL
            ) THEN
                RAISE EXCEPTION 'MESIRI_SANDBOX: People in the sample company can''t have a WhatsApp number, so nothing in it reaches a real phone.'
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER users_no_sandbox_whatsapp_number
        BEFORE INSERT OR UPDATE OF whatsapp_number, organization_id ON users
        FOR EACH ROW EXECUTE FUNCTION refuse_sandbox_whatsapp_number()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS users_no_sandbox_whatsapp_number ON users")
    op.execute("DROP FUNCTION IF EXISTS refuse_sandbox_whatsapp_number()")
