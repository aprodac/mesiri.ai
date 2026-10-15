"""BE-25: what every AI call and WhatsApp message costs, per company.

Extends `provider_executions` (0230) rather than adding a cost table: it is
already "one row per provider call". The new rows are `metered = true`, one
per actual provider response (written by the AI adapters through
mesiri_ai.usage) and one per outbound WhatsApp message. The older
per-pipeline-stage rows stay `metered = false`, so readers that summarise
latency keep counting exactly what they counted before.

New columns:
- `organization_id` -- the company, when known at write time. NO foreign
  key: a deleted trial's cost history is exactly what the trials funnel
  (SS-11) needs. Rows written while handling a message are also attributed
  through `correlation_id` -> inbound_messages.organization_id at read time.
- tokens (`input_tokens` with its `cached_input_tokens` and
  `audio_input_tokens` parts, `output_tokens` incl. thinking) and
  `audio_seconds` for providers that bill by time.
- WhatsApp: `category` (Meta's pricing category), `billable` (Meta's verdict
  from the status webhook), `external_id` (the wamid, unique) and
  `recipient` (digits).
- cost: `cost_native` in `cost_currency` (USD for Gemini/DeepSeek, INR for
  Sarvam/WhatsApp), `cost_inr` at the exchange rate of the day, and
  `price_ref`, the price table version used (domains/usage/prices.py).
- `purpose` -- what the call was for, when the caller said.

`correlation_id` becomes nullable: a call outside an inbound message (a
scheduled job, a dashboard upload, a template sent at 7 pm) has none.

Expand-only: older code neither reads nor writes any of it. The downgrade
deletes the metered rows (they mean nothing without these columns) and
restores NOT NULL on correlation_id.

Revision ID: 0478
Revises: 0477
Create Date: 2026-10-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0478"
down_revision = "0477"
branch_labels = None
depends_on = None

_TABLE = "provider_executions"


def upgrade() -> None:
    op.add_column(
        _TABLE,
        sa.Column("metered", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(_TABLE, sa.Column("organization_id", sa.UUID(as_uuid=True), nullable=True))
    op.add_column(_TABLE, sa.Column("purpose", sa.String(), nullable=True))
    op.add_column(_TABLE, sa.Column("input_tokens", sa.Integer(), nullable=True))
    op.add_column(_TABLE, sa.Column("cached_input_tokens", sa.Integer(), nullable=True))
    op.add_column(_TABLE, sa.Column("audio_input_tokens", sa.Integer(), nullable=True))
    op.add_column(_TABLE, sa.Column("output_tokens", sa.Integer(), nullable=True))
    op.add_column(_TABLE, sa.Column("audio_seconds", sa.Numeric(10, 2), nullable=True))
    op.add_column(_TABLE, sa.Column("category", sa.String(), nullable=True))
    op.add_column(_TABLE, sa.Column("billable", sa.Boolean(), nullable=True))
    op.add_column(_TABLE, sa.Column("external_id", sa.String(), nullable=True))
    op.add_column(_TABLE, sa.Column("recipient", sa.String(), nullable=True))
    op.add_column(_TABLE, sa.Column("cost_native", sa.Numeric(18, 10), nullable=True))
    op.add_column(_TABLE, sa.Column("cost_currency", sa.String(3), nullable=True))
    op.add_column(_TABLE, sa.Column("cost_inr", sa.Numeric(18, 8), nullable=True))
    op.add_column(_TABLE, sa.Column("price_ref", sa.String(), nullable=True))
    op.alter_column(_TABLE, "correlation_id", existing_type=sa.String(), nullable=True)

    op.create_index(
        "ix_provider_executions_org_created",
        _TABLE,
        ["organization_id", "created_at"],
        postgresql_where=sa.text("metered"),
    )
    op.create_index(
        "ix_provider_executions_recipient_created",
        _TABLE,
        ["recipient", "created_at"],
        postgresql_where=sa.text("recipient IS NOT NULL"),
    )
    op.create_index(
        "uq_provider_executions_external_id",
        _TABLE,
        ["external_id"],
        unique=True,
        postgresql_where=sa.text("external_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_provider_executions_external_id", table_name=_TABLE)
    op.drop_index("ix_provider_executions_recipient_created", table_name=_TABLE)
    op.drop_index("ix_provider_executions_org_created", table_name=_TABLE)
    # extractions.provider_execution_id is ON DELETE SET NULL, so this is safe.
    op.execute(f"DELETE FROM {_TABLE} WHERE metered OR correlation_id IS NULL")
    op.alter_column(_TABLE, "correlation_id", existing_type=sa.String(), nullable=False)
    for column in (
        "price_ref",
        "cost_inr",
        "cost_currency",
        "cost_native",
        "recipient",
        "external_id",
        "billable",
        "category",
        "audio_seconds",
        "output_tokens",
        "audio_input_tokens",
        "cached_input_tokens",
        "input_tokens",
        "purpose",
        "organization_id",
        "metered",
    ):
        op.drop_column(_TABLE, column)
