"""SA-15: which statements the control panel's Database page runs, and how
cells are made JSON-safe. The runs themselves are tested against Postgres
in tests/integration/test_database_console_postgres.py."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest

from mesiri.infrastructure.postgres.repositories import database_console as console


@pytest.mark.parametrize(
    ("sql", "keyword"),
    [
        ("select 1", "select"),
        ("  -- note\n  SELECT 1", "select"),
        ("/* a\nb */ with x as (select 1) select * from x", "with"),
        ("(select 1) union (select 2)", "select"),
        ("DELETE FROM users", "delete"),
        ("", ""),
        ("-- only a comment", ""),
    ],
)
def test_first_keyword(sql: str, keyword: str) -> None:
    assert console.first_keyword(sql) == keyword


@pytest.mark.parametrize("sql", ["select 1", "WITH x AS (select 1) select * from x", "explain select 1", "show timezone"])
def test_reads_run_in_read_mode(sql: str) -> None:
    assert console.check_statement(sql + ";", console.READ) == sql


@pytest.mark.parametrize("sql", ["delete from users where id = 1", "UPDATE users SET x = 1", "insert into t values (1)"])
def test_writes_are_refused_in_read_mode_with_the_way_to_run_them(sql: str) -> None:
    with pytest.raises(console.QueryRefused, match="Dry run"):
        console.check_statement(sql, console.READ)


@pytest.mark.parametrize(
    "sql",
    [
        "drop table users",
        "truncate users",
        "alter table users add column x int",
        "create table t (x int)",
        "grant all on users to public",
        "commit",
        "begin",
        "rollback",
        "do $$ begin perform 1; end $$",
        "copy users to stdout",
        "set transaction_read_only = off",
        "vacuum users",
    ],
)
@pytest.mark.parametrize("mode", [console.READ, console.DRY_RUN, console.WRITE])
def test_schema_changes_and_transaction_control_are_never_run(sql: str, mode: str) -> None:
    with pytest.raises(console.QueryRefused):
        console.check_statement(sql, mode)


def test_empty_and_unknown_mode_are_refused() -> None:
    with pytest.raises(console.QueryRefused):
        console.check_statement("  ;  ", console.READ)
    with pytest.raises(console.QueryRefused):
        console.check_statement("select 1", "admin")


def test_json_safe_cells() -> None:
    uid = uuid.uuid4()
    assert console.json_safe(uid) == str(uid)
    assert console.json_safe(Decimal("12.50")) == "12.50"
    assert console.json_safe(dt.datetime(2026, 10, 24, 9, 0, tzinfo=dt.UTC)) == "2026-10-24T09:00:00+00:00"
    assert console.json_safe(b"\x01\x02") == "\\x0102 (2 bytes)"
    assert console.json_safe({"a": [Decimal("1"), None]}) == {"a": ["1", None]}
    long = "x" * (console.MAX_CELL_CHARS + 5)
    assert len(console.json_safe(long)) == console.MAX_CELL_CHARS + 1
