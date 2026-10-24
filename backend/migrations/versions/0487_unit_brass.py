"""WA [103]: unit `brass` (100 cubic feet), the way Kerala sites buy sand and metal.

A report like "3 brass of M-sand arrived" had no unit to resolve to. `cft`,
`load`, `tons` and `cum` already exist (0290, 0474); only `brass` was missing.
It is a unit of its own, like `load`: converting it is the company's choice
(unit conversions, 0486), never assumed here.

Additive and idempotent like 0474: ON CONFLICT DO NOTHING, an existing alias
that points at another unit is left alone and printed to the deploy log. The
downgrade drops only the unit and its aliases, and only when no row uses it.

Revision ID: 0487
Revises: 0486
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op

revision = "0487"
down_revision = "0486"
branch_labels = None
depends_on = None

_UNITS: list[tuple[str, str]] = [
    ("brass", "Brass"),
]

# canonical code -> alias texts (lowercased); the code itself is added as a
# self-alias, as in 0290/0474.
_ALIASES: dict[str, list[str]] = {
    "brass": ["brasses"],
}


def upgrade() -> None:
    conn = op.get_bind()
    for code, display_name in _UNITS:
        conn.execute(
            sa.text(
                "INSERT INTO units_of_measure (id, code, display_name) "
                "VALUES (:id, :code, :display_name) ON CONFLICT (code) DO NOTHING"
            ),
            {"id": uuid.uuid4(), "code": code, "display_name": display_name},
        )
        unit_id = conn.execute(
            sa.text("SELECT id FROM units_of_measure WHERE code = :code"), {"code": code}
        ).scalar_one()
        for alias_text in [code, *_ALIASES[code]]:
            conn.execute(
                sa.text(
                    "INSERT INTO unit_aliases (id, unit_id, alias_text) "
                    "VALUES (:id, :unit_id, :alias_text) ON CONFLICT (alias_text) DO NOTHING"
                ),
                {"id": uuid.uuid4(), "unit_id": unit_id, "alias_text": alias_text},
            )
            owner = conn.execute(
                sa.text(
                    "SELECT u.code FROM unit_aliases a JOIN units_of_measure u ON u.id = a.unit_id "
                    "WHERE a.alias_text = :alias_text"
                ),
                {"alias_text": alias_text},
            ).scalar_one()
            if owner != code:
                print(  # noqa: T201 - deliberately surfaced in deploy log for follow-up cleanup
                    f"Migration 0487: alias {alias_text!r} already belongs to unit {owner!r}; "
                    f"left as is (not repointed to {code!r})"
                )


def downgrade() -> None:
    conn = op.get_bind()
    for code, _display_name in _UNITS:
        unit_id = conn.execute(
            sa.text("SELECT id FROM units_of_measure WHERE code = :code"), {"code": code}
        ).scalar()
        if unit_id is None:
            continue
        # A unit that recorded rows already reference cannot be dropped without
        # losing data, so it is kept with its aliases: the savepoint rolls the
        # alias delete back when the unit delete hits a foreign key.
        savepoint = conn.begin_nested()
        try:
            conn.execute(
                sa.text(
                    "DELETE FROM unit_aliases WHERE unit_id = :unit_id AND alias_text = ANY(:aliases)"
                ),
                {"unit_id": unit_id, "aliases": [code, *_ALIASES[code]]},
            )
            conn.execute(
                sa.text("DELETE FROM units_of_measure WHERE id = :unit_id"), {"unit_id": unit_id}
            )
        except sa.exc.IntegrityError:
            savepoint.rollback()
            print(f"Migration 0487 downgrade: unit {code!r} is in use, kept")  # noqa: T201
        else:
            savepoint.commit()
