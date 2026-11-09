"""Money received from clients lands in its account (found building Accounts, 9 Nov 2026).

``client_receipts`` (0529) recorded money into a company account but never wrote the account's money movement, so the
bank and cash balances on Finance › Money (opening + ``money_transactions``) left out every rupee clients paid. The
receipt code now writes a ``fund_received`` movement (``source_type`` ``client_receipt``) and a ``reversal`` when a
receipt is cancelled; this migration writes the same rows for receipts recorded before.

Additive only: inserts movements, changes no existing row. ``created_by`` is who recorded the receipt, or the
company's earliest user when that person is gone (the column is required). Downgrade deletes only these rows.

Revision ID: 0530
Revises: 0529
Create Date: 2026-11-09
"""

from __future__ import annotations

from alembic import op

revision = "0530"
down_revision = "0529"
branch_labels = None
depends_on = None

_WHO = ("COALESCE({col}, (SELECT u.id FROM users u WHERE u.organization_id = r.organization_id "
        "ORDER BY u.created_at LIMIT 1))")


def upgrade() -> None:
    op.execute(f"""
        INSERT INTO money_transactions (id, organization_id, transaction_type, to_account_id, amount, source_type,
                                        source_id, occurred_date, description, created_by, created_at)
        SELECT gen_random_uuid(), r.organization_id, 'fund_received', r.account_id, r.amount, 'client_receipt', r.id,
               r.received_on, 'Received from client', {_WHO.format(col='r.created_by')}, r.created_at
        FROM client_receipts r
        WHERE NOT EXISTS (SELECT 1 FROM money_transactions m WHERE m.source_type = 'client_receipt'
                          AND m.source_id = r.id AND m.transaction_type = 'fund_received')
          AND {_WHO.format(col='r.created_by')} IS NOT NULL""")
    op.execute(f"""
        INSERT INTO money_transactions (id, organization_id, transaction_type, from_account_id, amount, source_type,
                                        source_id, occurred_date, description, created_by, created_at)
        SELECT gen_random_uuid(), r.organization_id, 'reversal', r.account_id, r.amount, 'client_receipt', r.id,
               COALESCE(r.cancelled_at::date, r.received_on), 'Client receipt cancelled',
               {_WHO.format(col='COALESCE(r.cancelled_by, r.created_by)')}, COALESCE(r.cancelled_at, now())
        FROM client_receipts r
        WHERE r.status = 'cancelled'
          AND EXISTS (SELECT 1 FROM money_transactions m WHERE m.source_type = 'client_receipt'
                      AND m.source_id = r.id AND m.transaction_type = 'fund_received')
          AND NOT EXISTS (SELECT 1 FROM money_transactions m WHERE m.source_type = 'client_receipt'
                          AND m.source_id = r.id AND m.transaction_type = 'reversal')""")


def downgrade() -> None:
    op.execute("DELETE FROM money_transactions WHERE source_type = 'client_receipt'")
