"""BE-39: units `cft` (cubic feet) and `load` (truck/tipper load).

Kerala sites buy sand and aggregate by the cubic foot or by the lorry load,
not by the cubic metre, so a report like "2 loads of M-sand arrived" or
"300 cft metal" had no unit to resolve to. Both are added to the global
units_of_measure vocabulary (not org-scoped, like the 0290 seed), with the
spellings people actually type in unit_aliases -- resolve_alias lowercases
and trims only, so punctuation variants ("cu.ft") are listed explicitly.

No unit conversion: a `load` is whatever the supplier's lorry carries, and
it is tracked as its own unit, the same way `bags` is.

Idempotent: every insert is ON CONFLICT DO NOTHING. 0290 auto-created
fallback units from raw production text, so a `load`/`loads` unit or alias
may already exist; an existing unit code is reused, and an alias that
already points at a different unit is left alone (repointing it would not
move the rows already recorded against that unit) and printed to the deploy
log for follow-up.

Revision ID: 0474
Revises: 0473
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op

revision = "0474"
down_revision = "0473"
branch_labels = None
depends_on = None

_UNITS: list[tuple[str, str]] = [
    ("cft", "Cubic Feet"),
    ("load", "Loads"),
]

# canonical code -> alias texts (lowercased). The code itself is added as a
# self-alias, as in 0290, so one alias lookup resolves codes and synonyms.
_ALIASES: dict[str, list[str]] = {
    "cft": [
        "cubic feet",
        "cubic foot",
        "cubic ft",
        "cu ft",
        "cu.ft",
        "cu. ft",
        "cuft",
        "ft3",
        "ft³",
    ],
    "load": [
        "loads",
        "lorry",
        "lorries",
        "lorry load",
        "lorry loads",
        "tipper",
        "tippers",
        "tipper load",
        "tipper loads",
        "truck load",
        "truck loads",
        "truckload",
        "truckloads",
        "ലോഡ്",
    ],
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
                    f"Migration 0474: alias {alias_text!r} already belongs to unit {owner!r}; "
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
            print(f"Migration 0474 downgrade: unit {code!r} is in use, kept")  # noqa: T201
        else:
            savepoint.commit()
