"""PostgreSQL connection management (M1).

Owns the async engine/pool lifecycle, a transaction helper, and a health probe.
SQLAlchemy + asyncpg are imported lazily so the default (fake-backed) test suite
does not require the driver. Only approved persistence adapters use this class —
workflows, planners, understanding, and transports must never import it.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

from ...bootstrap.settings import PostgresSettings
from ..errors import map_postgres_error

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine


def _is_http_error(exc: BaseException) -> bool:
    """FastAPI's HTTPException subclasses Starlette's; checked lazily so this
    module stays importable without the web stack (workers, scripts)."""
    try:
        from starlette.exceptions import HTTPException
    except ImportError:  # pragma: no cover
        return False
    return isinstance(exc, HTTPException)


def _is_database_error(exc: BaseException) -> bool:
    """A failure of the database or the connection to it (SQLAlchemy, the
    driver, the socket, a timeout) -- as opposed to the caller's own exception,
    which a ``shared_transaction()`` block lets through unchanged after rolling
    back (a Save's "this item could not be saved" must reach its caller as it is)."""
    try:
        from sqlalchemy.exc import SQLAlchemyError
    except ImportError:  # pragma: no cover
        return True
    return isinstance(exc, (SQLAlchemyError, OSError, TimeoutError))


class _SharedTransaction:
    """The one open transaction of a ``shared_transaction()`` block.

    A connection serves one statement at a time, so a block that joins it (a
    nested ``transaction()``) takes the guard for its length. The guard is
    re-entrant for the same task: a joined block that opens another one never
    waits on itself."""

    __slots__ = ("conn", "depth", "engine", "lock", "owner")

    def __init__(self, engine: Any, conn: Any) -> None:
        self.engine = engine
        self.conn = conn
        self.lock = asyncio.Lock()
        self.owner: asyncio.Task[Any] | None = None
        self.depth = 0

    @asynccontextmanager
    async def guard(self) -> AsyncIterator[None]:
        task = asyncio.current_task()
        if self.owner is task and self.depth:
            self.depth += 1
            try:
                yield
            finally:
                self.depth -= 1
            return
        async with self.lock:
            self.owner, self.depth = task, 1
            try:
                yield
            finally:
                self.owner, self.depth = None, 0


#: Set only inside ``PostgresDatabase.shared_transaction()``; nothing sets it
#: otherwise, so every other caller of ``transaction()`` is unchanged.
_shared: ContextVar[_SharedTransaction | None] = ContextVar("mesiri_shared_transaction", default=None)


class PostgresDatabase:
    name = "postgres"
    required = True

    def __init__(self, settings: PostgresSettings) -> None:
        self._settings = settings
        self._engine: AsyncEngine | None = None

    async def connect(self) -> None:
        if self._engine is not None:
            return
        from sqlalchemy.ext.asyncio import create_async_engine

        s = self._settings
        try:
            self._engine = create_async_engine(
                s.dsn(),
                pool_size=s.pool_max_size,
                pool_pre_ping=True,
                connect_args={"timeout": s.connect_timeout_seconds},
            )
        except Exception as exc:  # noqa: BLE001
            raise map_postgres_error(exc) from exc

    async def disconnect(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None

    @property
    def _require_engine(self) -> AsyncEngine:
        if self._engine is None:
            raise map_postgres_error(RuntimeError("postgres engine not connected"))
        return self._engine

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncConnection]:
        """Yield a connection inside a transaction; commit on success, roll back
        on any error (which is mapped to the shared error contract).

        An HTTP error raised by the code using the connection -- a route's
        own 401/403/404/409/422 -- still rolls back but is re-raised as it
        is (BE-28). Routes get their connection from `get_db_conn`, which
        holds this transaction open for the whole request, so mapping those
        turned every ordinary client error into 500 "postgres unavailable".

        Scoped to the bound company, if any (BE-03, postgres/tenant.py)."""
        from mesiri.infrastructure.postgres.tenant import apply_tenant

        engine = self._require_engine
        shared = _shared.get()
        if shared is not None and shared.engine is engine:
            async with self._join(shared) as conn:
                yield conn
            return
        try:
            async with engine.begin() as conn:
                await apply_tenant(conn)
                yield conn
        except Exception as exc:  # noqa: BLE001
            if _is_http_error(exc):
                raise
            raise map_postgres_error(exc) from exc

    @asynccontextmanager
    async def _join(self, shared: _SharedTransaction) -> AsyncIterator[AsyncConnection]:
        """A ``transaction()`` inside ``shared_transaction()``: the same
        connection, in a savepoint. Its own failure undoes only its own
        statements (a caller that catches it can go on), and nothing commits
        until the outer block ends."""
        async with shared.guard():
            try:
                async with shared.conn.begin_nested():
                    yield shared.conn
            except Exception as exc:  # noqa: BLE001
                if _is_http_error(exc):
                    raise
                raise map_postgres_error(exc) from exc

    @asynccontextmanager
    async def shared_transaction(self) -> AsyncIterator[None]:
        """One transaction for everything run inside the block: every
        ``transaction()`` opened meanwhile (by this database, in this task or
        one it starts) joins it instead of committing on its own. It commits
        when the block ends and rolls back on any error out of it, so a write
        made by several services is all-or-nothing (request 124: the Save tap).
        A database failure comes out mapped, as from ``transaction()``; the
        caller's own exception comes out as it is.

        Blocks nest: inside one, this joins it. Scoped to the bound company,
        like ``transaction()``."""
        from mesiri.infrastructure.postgres.tenant import apply_tenant

        engine = self._require_engine
        if (outer := _shared.get()) is not None and outer.engine is engine:
            yield
            return
        try:
            async with engine.begin() as conn:
                await apply_tenant(conn)
                token = _shared.set(_SharedTransaction(engine, conn))
                try:
                    yield
                finally:
                    _shared.reset(token)
        except Exception as exc:  # noqa: BLE001
            if _is_http_error(exc) or not _is_database_error(exc):
                raise
            raise map_postgres_error(exc) from exc

    async def execute(self, statement: str, params: dict[str, Any] | None = None) -> Any:
        from sqlalchemy import text

        engine = self._require_engine
        try:
            async with engine.begin() as conn:
                return await conn.execute(text(statement), params or {})
        except Exception as exc:  # noqa: BLE001
            raise map_postgres_error(exc) from exc

    async def check_health(self) -> None:
        from sqlalchemy import text

        engine = self._require_engine
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception as exc:  # noqa: BLE001
            raise map_postgres_error(exc) from exc

    # -- Infrastructure heartbeat (used by the M1 golden scenario) -----------
    async def write_heartbeat(self, key: str, note: str) -> None:
        await self.execute(
            "INSERT INTO infra_heartbeat (key, note, observed_at) "
            "VALUES (:key, :note, now()) "
            "ON CONFLICT (key) DO UPDATE SET note = :note, observed_at = now()",
            {"key": key, "note": note},
        )

    async def read_heartbeat(self, key: str) -> dict[str, Any] | None:
        from sqlalchemy import text

        engine = self._require_engine
        try:
            async with engine.connect() as conn:
                row = (
                    await conn.execute(
                        text("SELECT key, note FROM infra_heartbeat WHERE key = :key"),
                        {"key": key},
                    )
                ).first()
        except Exception as exc:  # noqa: BLE001
            raise map_postgres_error(exc) from exc
        return {"note": row.note} if row is not None else None


class FakePostgres:
    """In-memory stand-in used by scenarios/tests without a live database.

    Supports a tiny key/value 'heartbeat' table so the golden scenario can
    perform a real write+read round-trip against the same interface.
    """

    name = "postgres"
    required = True

    def __init__(self, *, fail_health: bool = False) -> None:
        self.fail_health = fail_health
        self._connected = False
        self._heartbeats: dict[str, dict[str, Any]] = {}

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def write_heartbeat(self, key: str, note: str) -> None:
        self._heartbeats[key] = {"note": note}

    async def read_heartbeat(self, key: str) -> dict[str, Any] | None:
        return self._heartbeats.get(key)

    async def check_health(self) -> None:
        if self.fail_health or not self._connected:
            raise map_postgres_error(ConnectionError("fake postgres unavailable"))
