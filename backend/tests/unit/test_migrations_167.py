"""WA-167: the container units and Paraclette's clean-up are one chain after 0497, and touch only rows found on 3 Nov."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

VERSIONS = Path(__file__).resolve().parents[2] / "migrations" / "versions"


def _run(name: str, direction: str) -> list[str]:
    statements: list[str] = []
    fake = types.ModuleType("alembic")
    fake.op = types.SimpleNamespace(execute=lambda sql: statements.append(" ".join(sql.split())))  # type: ignore[attr-defined]
    saved = sys.modules.get("alembic")
    sys.modules["alembic"] = fake
    try:
        spec = importlib.util.spec_from_file_location(name, VERSIONS / name)
        module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        getattr(module, direction)()
    finally:
        if saved is not None:
            sys.modules["alembic"] = saved
        else:
            del sys.modules["alembic"]
    return statements


def test_the_chain_is_0497_0498_0499_with_no_fork() -> None:
    downs = {}
    for path in VERSIONS.glob("04[89]*.py"):
        text = path.read_text()
        rev = text.split('revision = "')[1].split('"')[0]
        downs[rev] = text.split('down_revision = "')[1].split('"')[0]
    assert downs["0498"] == "0497" and downs["0499"] == "0498"
    assert list(downs.values()).count("0498") == 1 and list(downs.values()).count("0497") == 1


def test_container_units_are_added_once_and_only_unused_ones_are_removed() -> None:
    up = _run("0498_container_units.py", "upgrade")
    assert all("ON CONFLICT (code) DO NOTHING" in s for s in up) and len(up) == 4
    down = _run("0498_container_units.py", "downgrade")
    assert down[0].startswith("UPDATE units_of_measure u SET is_active = false") and "NOT (" in down[1]


def test_every_paraclette_change_is_by_id_and_only_while_the_row_is_as_found() -> None:
    up = _run("0499_paraclette_material_cleanup.py", "upgrade")
    moves = [s for s in up if s.startswith("UPDATE material_")]
    assert len(moves) == 6
    assert all("WHERE id IN (" in s and "AND material_id = '" in s and "default_unit_id" in s for s in moves)
    deletes = [s for s in up if s.startswith("DELETE")]
    assert len(deletes) == 2 and all("per_stock_unit = " in s for s in deletes)
    switched_off = [s for s in up if s.startswith("UPDATE materials_catalog")]
    assert len(switched_off) == 2 and all("NOT EXISTS" in s for s in switched_off)


def test_the_downgrade_puts_the_same_rows_back() -> None:
    down = _run("0499_paraclette_material_cleanup.py", "downgrade")
    assert sum(s.startswith("INSERT INTO material_unit_conversions") for s in down) == 2
    assert sum(s.startswith("UPDATE materials_catalog SET is_active = true") for s in down) == 2
    assert sum(s.startswith("UPDATE material_") and "SET material_id = '" in s for s in down) == 6
