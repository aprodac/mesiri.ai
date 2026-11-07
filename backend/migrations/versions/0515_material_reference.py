"""Material knowledge as data, slice 1 (MK-02): unit facts, material kinds, plausible sizes.

Platform-wide reference, the trade facts a site clerk knows, each row with its source, so they are reviewed and
corrected as data instead of living in code (ADR-material-knowledge). Seeded only for what slice 1 uses: TMT bars and
sand (M-sand, P-sand, river sand). A company's own sizes stay in ``material_unit_conversions``; these rows only say
what is possible, so "1 load M-sand = 60 cum" (New India, 5 Nov) is refused with the usual range instead of saved.

- ``ref_unit_facts``: 1 ``from_code`` = ``factor`` ``to_code`` (exact conversions).
- ``ref_material_kinds``: a kind of material, the unit it is naturally stocked in, the words that name it in a
  catalogue item's name, and an optional mass rule (a round bar: D²/divisor kg per metre, a standard length).
- ``ref_kind_ranges``: 1 ``from_unit_code`` of a kind is usually ``min_value``..``max_value`` ``to_unit_code``. Wide on
  purpose: they catch the impossible, not the unusual.

Additive only: three new tables, no company data. Platform-wide like ``units_of_measure`` (no organization_id, no
row-level security); the app login reads them through the schema's default privileges (app_db_login.sh).

Revision ID: 0515
Revises: 0514
Create Date: 2026-11-07
"""

from __future__ import annotations

from alembic import op

revision = "0515"
down_revision = "0514"
branch_labels = None
depends_on = None

_UNIT_FACTS = (
    ("tons", "kg", "1000", "SI: 1 tonne = 1000 kg"),
    ("mt", "kg", "1000", "SI: 1 tonne = 1000 kg"),
    ("cum", "cft", "35.3147", "SI: 1 m³ = 35.3147 ft³"),
    ("brass", "cft", "100", "Indian trade unit: 1 brass = 100 cft"),
    ("brass", "cum", "2.83168", "Indian trade unit: 1 brass = 100 cft = 2.83168 m³"),
    ("sqm", "sqft", "10.7639", "SI: 1 m² = 10.7639 ft²"),
)

_KINDS = (
    (
        "tmt_bar",
        "TMT steel bar",
        "kg",
        ["tmt", "steel", "rebar", "rod", "rods", "bar", "bars", "kambi", "fe415", "fe500", "fe500d", "fe550",
         "കമ്പി", "സ്റ്റീൽ"],
        '{"rule": "round_bar", "divisor": 162, "length_m": 12, "tolerance": 0.10}',
        "IS 1786: unit mass D²/162 kg per metre (D in mm); 12 m standard length; bills may differ within tolerance",
    ),
    (
        "sand",
        "Sand (M-sand, P-sand, river sand)",
        "cft",
        ["sand", "msand", "psand", "m sand", "p sand", "m-sand", "p-sand", "manal", "മണൽ", "എം സാൻഡ്", "പി സാൻഡ്"],
        None,
        "Sold per load, cft, brass or ton; a load is what the supplier's lorry carries (no standard)",
    ),
)

_RANGES = (
    ("tmt_bar", "nos", "kg", "2", "100", "One 12 m bar: 6 mm ~2.7 kg to 32 mm ~75.9 kg (IS 1786)"),
    ("tmt_bar", "pieces", "kg", "2", "100", "One 12 m bar: 6 mm ~2.7 kg to 32 mm ~75.9 kg (IS 1786)"),
    ("sand", "load", "cft", "50", "600", "Kerala 150 cft loads (Kottayam supplier); TN tippers 400-500 cft"),
    ("sand", "bags", "cft", "0.5", "2", "A bag of sand on site holds about 0.025-0.05 m³ (0.9-1.8 cft)"),
    ("sand", "tons", "cft", "15", "30", "Sand bulk density about 1.5-1.8 t/m³: 1 ton is 20-24 cft"),
)


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE ref_unit_facts (
            from_code text NOT NULL,
            to_code text NOT NULL,
            factor numeric(18, 7) NOT NULL CHECK (factor > 0),
            source text NOT NULL,
            PRIMARY KEY (from_code, to_code)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE ref_material_kinds (
            code text PRIMARY KEY,
            name text NOT NULL,
            stock_unit_code text NOT NULL,
            words text[] NOT NULL DEFAULT '{}',
            mass_rule jsonb,
            source text NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE ref_kind_ranges (
            kind_code text NOT NULL REFERENCES ref_material_kinds(code) ON DELETE CASCADE,
            from_unit_code text NOT NULL,
            to_unit_code text NOT NULL,
            min_value numeric(18, 7) NOT NULL CHECK (min_value > 0),
            max_value numeric(18, 7) NOT NULL,
            source text NOT NULL,
            PRIMARY KEY (kind_code, from_unit_code),
            CONSTRAINT ck_ref_kind_ranges_order CHECK (max_value >= min_value)
        )
        """
    )
    for from_code, to_code, factor, source in _UNIT_FACTS:
        op.execute(
            "INSERT INTO ref_unit_facts (from_code, to_code, factor, source) "
            f"VALUES ('{from_code}', '{to_code}', {factor}, $${source}$$)"
        )
    for code, name, unit, words, rule, source in _KINDS:
        array = "ARRAY[" + ", ".join(f"$${w}$$" for w in words) + "]::text[]"
        rule_sql = f"$${rule}$$::jsonb" if rule else "NULL"
        op.execute(
            "INSERT INTO ref_material_kinds (code, name, stock_unit_code, words, mass_rule, source) "
            f"VALUES ('{code}', $${name}$$, '{unit}', {array}, {rule_sql}, $${source}$$)"
        )
    for kind, from_code, to_code, low, high, source in _RANGES:
        op.execute(
            "INSERT INTO ref_kind_ranges (kind_code, from_unit_code, to_unit_code, min_value, max_value, source) "
            f"VALUES ('{kind}', '{from_code}', '{to_code}', {low}, {high}, $${source}$$)"
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ref_kind_ranges")
    op.execute("DROP TABLE IF EXISTS ref_material_kinds")
    op.execute("DROP TABLE IF EXISTS ref_unit_facts")
