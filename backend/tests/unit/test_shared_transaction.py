"""Request 124: one transaction for several services (the Save tap).

`PostgresDatabase.shared_transaction()` lets every `transaction()` opened inside
it join one connection, so a Save that writes labour, materials and issues is
all-or-nothing. Outside the block nothing changes."""

from __future__ import annotations

import asyncio
import contextlib

import pytest

from mesiri.infrastructure.postgres.database import PostgresDatabase
from mesiri_contracts.common.errors import MesiriError


class _Conn:
    def __init__(self, log: list[str]) -> None:
        self.log = log
        self.busy = False

    @contextlib.asynccontextmanager
    async def begin_nested(self):
        self.log.append("savepoint")
        try:
            yield
        except BaseException:
            self.log.append("rollback to savepoint")
            raise
        self.log.append("release savepoint")

    async def write(self, what: str) -> None:
        assert not self.busy, "two statements on one connection at once"
        self.busy = True
        await asyncio.sleep(0)
        self.log.append(what)
        self.busy = False


class _Engine:
    def __init__(self) -> None:
        self.log: list[str] = []
        self.conns = 0

    @contextlib.asynccontextmanager
    async def begin(self):
        self.conns += 1
        conn = _Conn(self.log)
        try:
            yield conn
        except BaseException:
            self.log.append("rollback")
            raise
        self.log.append("commit")


def _db() -> tuple[PostgresDatabase, _Engine]:
    engine = _Engine()
    db = PostgresDatabase.__new__(PostgresDatabase)
    db._engine = engine
    return db, engine


async def test_without_a_shared_block_each_transaction_commits_on_its_own():
    db, engine = _db()
    async with db.transaction() as conn:
        await conn.write("a")
    async with db.transaction() as conn:
        await conn.write("b")
    assert engine.log == ["a", "commit", "b", "commit"]
    assert engine.conns == 2


async def test_transactions_inside_the_block_share_one_commit():
    db, engine = _db()
    async with db.shared_transaction():
        async with db.transaction() as conn:
            await conn.write("labour")
        async with db.transaction() as conn:
            await conn.write("cement")
    assert engine.conns == 1
    assert engine.log == ["savepoint", "labour", "release savepoint", "savepoint", "cement", "release savepoint", "commit"]


async def test_an_error_out_of_the_block_rolls_everything_back():
    db, engine = _db()
    with pytest.raises(MesiriError):
        async with db.shared_transaction():
            async with db.transaction() as conn:
                await conn.write("labour")
            raise ConnectionError("server closed the connection")
    assert engine.log[-1] == "rollback"
    assert "commit" not in engine.log


async def test_an_inner_failure_a_caller_catches_does_not_end_the_shared_transaction():
    db, engine = _db()
    async with db.shared_transaction():
        with contextlib.suppress(MesiriError):
            async with db.transaction():
                raise ConnectionError("a lookup failed")
        async with db.transaction() as conn:
            await conn.write("issue")
    assert "rollback to savepoint" in engine.log
    assert engine.log[-1] == "commit"


async def test_a_joined_block_may_open_another_in_the_same_task():
    db, engine = _db()
    async with db.shared_transaction():
        async with db.transaction() as conn:
            async with db.transaction() as inner:
                assert inner is conn
                await inner.write("nested")
    assert engine.log[-1] == "commit"


async def test_tasks_started_inside_take_turns_on_the_one_connection():
    db, engine = _db()

    async def write(what: str) -> None:
        async with db.transaction() as conn:
            await conn.write(what)

    async with db.shared_transaction():
        await asyncio.gather(write("a"), write("b"), write("c"))
    assert sorted(x for x in engine.log if len(x) == 1) == ["a", "b", "c"]
    assert engine.conns == 1


async def test_shared_blocks_nest():
    db, engine = _db()
    async with db.shared_transaction():
        async with db.shared_transaction():
            async with db.transaction() as conn:
                await conn.write("x")
    assert engine.conns == 1
    assert engine.log.count("commit") == 1


async def test_the_callers_own_exception_comes_out_as_it_is_after_the_rollback():
    class Mine(Exception):
        pass

    db, engine = _db()
    with pytest.raises(Mine):
        async with db.shared_transaction():
            async with db.transaction() as conn:
                await conn.write("labour")
            raise Mine("this item could not be saved")
    assert engine.log[-1] == "rollback"
