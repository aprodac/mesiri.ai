"""V1 audit WRK-02: units `m` (metres) and `rft` (running feet), and the
spellings people type for square and cubic metres/feet.

"50 meter wiring done", "120 rft skirting done", "200 sq ft tiling done" and
"20 m3 concreting done" were each refused as "not a recognized unit" and
nothing was saved: there was no length unit at all, and `sqm`, `sqft` and
`cum` (0290) only had their bare code as an alias. The work tool's own
description already suggests "m3" and "m" to the model.

Same rules as 0474/0487: global vocabulary, additive and idempotent (ON
CONFLICT DO NOTHING); an existing unit code is reused, and an alias that
already points at another unit (0290 may have made fallback units from raw
production text) is left alone and printed to the deploy log. No unit
conversion: a running metre is tracked as metres, as sites say it. `mt`
stays metric tons (0290). The downgrade drops only the two new units and
the aliases this migration added, and keeps a unit rows already use.

Revision ID: 0489
Revises: 0488
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op

revision = "0489"
down_revision = "0488"
branch_labels = None
depends_on = None

# Units this migration creates (the downgrade removes only these).
_NEW_UNITS: list[tuple[str, str]] = [
    ("m", "Metres"),
    ("rft", "Running Feet"),
]

# canonical code -> alias texts (lowercased; resolve_alias lowercases and trims
# only, so punctuation variants are listed explicitly). New units also get the
# code as a self-alias, as in 0290/0474.
_ALIASES: dict[str, list[str]] = {
    "m": [
        "metre",
        "metres",
        "meter",
        "meters",
        "mtr",
        "mtrs",
        "rm",
        "rmt",
        "r.m",
        "running metre",
        "running metres",
        "running meter",
        "running meters",
    ],
    "rft": [
        "r.ft",
        "r ft",
        "running feet",
        "running foot",
        "running ft",
        "ft",
        "feet",
        "foot",
    ],
    "sqm": [
        "sq m",
        "sq.m",
        "sq. m",
        "sq mt",
        "sq.mt",
        "sq mtr",
        "sqmt",
        "sqmtr",
        "square metre",
        "square metres",
        "square meter",
        "square meters",
        "m2",
        "m²",
    ],
    "sqft": [
        "sq ft",
        "sq.ft",
        "sq. ft",
        "sq feet",
        "sft",
        "square feet",
        "square foot",
        "ft2",
        "ft²",
    ],
    "cum": [
        "cu m",
        "cu.m",
        "cu. m",
        "cubic metre",
        "cubic metres",
        "cubic meter",
        "cubic meters",
        "cbm",
        "m3",
        "m³",
    ],
}


def _add_alias(conn, unit_id, code: str, alias_text: str) -> None:
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
            f"Migration 0489: alias {alias_text!r} already belongs to unit {owner!r}; "
            f"left as is (not repointed to {code!r})"
        )


def upgrade() -> None:
    conn = op.get_bind()
    for code, display_name in _NEW_UNITS:
        conn.execute(
            sa.text(
                "INSERT INTO units_of_measure (id, code, display_name) "
                "VALUES (:id, :code, :display_name) ON CONFLICT (code) DO NOTHING"
            ),
            {"id": uuid.uuid4(), "code": code, "display_name": display_name},
        )
    new_codes = {code for code, _ in _NEW_UNITS}
    for code, aliases in _ALIASES.items():
        unit_id = conn.execute(
            sa.text("SELECT id FROM units_of_measure WHERE code = :code"), {"code": code}
        ).scalar_one()
        for alias_text in [code, *aliases] if code in new_codes else aliases:
            _add_alias(conn, unit_id, code, alias_text)


def downgrade() -> None:
    conn = op.get_bind()
    new_codes = {code for code, _ in _NEW_UNITS}
    for code, aliases in _ALIASES.items():
        unit_id = conn.execute(
            sa.text("SELECT id FROM units_of_measure WHERE code = :code"), {"code": code}
        ).scalar()
        if unit_id is None:
            continue
        if code not in new_codes:
            conn.execute(
                sa.text(
                    "DELETE FROM unit_aliases WHERE unit_id = :unit_id AND alias_text = ANY(:aliases)"
                ),
                {"unit_id": unit_id, "aliases": aliases},
            )
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
                {"unit_id": unit_id, "aliases": [code, *aliases]},
            )
            conn.execute(
                sa.text("DELETE FROM units_of_measure WHERE id = :unit_id"), {"unit_id": unit_id}
            )
        except sa.exc.IntegrityError:
            savepoint.rollback()
            print(f"Migration 0489 downgrade: unit {code!r} is in use, kept")  # noqa: T201
        else:
            savepoint.commit()
