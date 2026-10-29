"""WRK-02 (audit 04): the units people really type for work done.

"50 meter wiring", "120 rft skirting", "200 sq ft tiling" and "20 m3 concreting"
were refused ("not a recognized unit") and nothing was saved. Adds the units
the audit named that did not exist -- `m` (metres), `rm` (running metres),
`rft` (running feet), `percent` -- and the spellings of the existing sqm /
sqft / cum / nos. Spelling variants that differ only by spaces, dots or the
superscript digits (sq.ft, m²) are folded by `resolve_alias` itself
(UnitsOfMeasureRepository), so only the spaced words are listed here.

Additive and idempotent like 0474 / 0487: ON CONFLICT DO NOTHING; an alias
that already belongs to another unit is left alone and printed to the deploy
log. The downgrade drops only the aliases it added and the units it added,
and a unit only when no row uses it.

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

# (code, display name). The first four are new; the rest exist already (0290)
# and are listed so a database without them still gets them.
_UNITS: list[tuple[str, str]] = [
    ("m", "Meters"),
    ("rm", "Running Meters"),
    ("rft", "Running Feet"),
    ("percent", "Percent"),
    ("sqm", "Square Meters"),
    ("sqft", "Square Feet"),
    ("cum", "Cubic Meters"),
    ("nos", "Numbers"),
]

_ALIASES: dict[str, list[str]] = {
    "m": ["meter", "meters", "metre", "metres", "mtr", "mtrs", "mtr."],
    "rm": ["rmt", "running meter", "running meters", "running metre", "running metres"],
    "rft": ["running feet", "running foot", "running ft", "r.ft", "rfeet"],
    "percent": ["%", "per cent", "pct"],
    "sqm": ["sq m", "sq meter", "sq meters", "sq metre", "sq metres", "square meter",
            "square meters", "square metre", "square metres", "m2", "m²", "sq.m", "sqmt", "sqmtr"],
    "sqft": ["sq ft", "sq.ft", "sft", "sq feet", "sq foot", "square feet", "square foot",
             "ft2", "ft²", "sq. ft"],
    "cum": ["cu m", "cu.m", "cubic meter", "cubic meters", "cubic metre", "cubic metres",
            "m3", "m³", "cbm", "cubic m"],
    "nos": ["no", "no.", "nos.", "number", "numbers", "each", "ea"],
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
        for alias_text in [code, *_ALIASES.get(code, [])]:
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


def downgrade() -> None:
    conn = op.get_bind()
    for code, _display_name in reversed(_UNITS):
        unit_id = conn.execute(
            sa.text("SELECT id FROM units_of_measure WHERE code = :code"), {"code": code}
        ).scalar()
        if unit_id is None:
            continue
        # Only the aliases this migration added to a unit that existed before it
        # (sqm / sqft / cum / nos) go; the unit and its own code stay.
        conn.execute(
            sa.text(
                "DELETE FROM unit_aliases WHERE unit_id = :unit_id AND alias_text = ANY(:aliases)"
            ),
            {"unit_id": unit_id, "aliases": _ALIASES.get(code, [])},
        )
        if code in {"sqm", "sqft", "cum", "nos"}:
            continue
        savepoint = conn.begin_nested()
        try:
            conn.execute(
                sa.text("DELETE FROM unit_aliases WHERE unit_id = :unit_id"), {"unit_id": unit_id}
            )
            conn.execute(
                sa.text("DELETE FROM units_of_measure WHERE id = :unit_id"), {"unit_id": unit_id}
            )
        except sa.exc.IntegrityError:
            savepoint.rollback()
            print(f"Migration 0489 downgrade: unit {code!r} is in use, kept")  # noqa: T201
        else:
            savepoint.commit()
