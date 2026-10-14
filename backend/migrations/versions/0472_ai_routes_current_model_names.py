"""BE-29: replace retired AI model names in the routing table.

`deepseek-chat` / `deepseek-reasoner` stopped resolving at DeepSeek on
24 Jul 2026 (now `deepseek-flash`); `gemini-2.0-flash` is past Google's
earliest shutdown date (1 Jun 2026) and no longer priced (`gemini-2.5-flash`
is current). The resolver already maps these names at call time
(mesiri_ai/model_names.py); this makes the control panel show what is
really used. Data only, idempotent; the downgrade leaves the data alone.

Revision ID: 0472
Revises: 0471
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0472"
down_revision = "0471"
branch_labels = None
depends_on = None

# Kept in step with mesiri_ai/model_names.py RETIRED_MODELS (a migration
# must not import application code that may change later).
_REPLACEMENTS = {
    "deepseek-chat": "deepseek-flash",
    "deepseek-reasoner": "deepseek-flash",
    "deepseek-v4-flash": "deepseek-flash",
    "gemini-2.0-flash": "gemini-2.5-flash",
    "gemini-2.0-flash-001": "gemini-2.5-flash",
    "gemini-2.0-flash-lite": "gemini-2.5-flash-lite",
    "gemini-2.0-flash-lite-001": "gemini-2.5-flash-lite",
}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "ai_active_routes" not in inspector.get_table_names():
        return
    columns = {c["name"] for c in inspector.get_columns("ai_active_routes")}
    for column in ("model", "fallback_model"):
        if column not in columns:
            continue
        for old, new in _REPLACEMENTS.items():
            bind.execute(
                sa.text(f"UPDATE ai_active_routes SET {column} = :new WHERE {column} = :old"),
                {"old": old, "new": new},
            )


def downgrade() -> None:
    pass
