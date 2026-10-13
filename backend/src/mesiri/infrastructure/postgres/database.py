"""PostgreSQL connection management (M1).

Owns the async engine/pool lifecycle, a transaction helper, and a health probe.
SQLAlchemy + asyncpg are imported lazily so the default (fake-backed) test suite
does not require the driver. Only approved persistence adapters use this class —
workflows, planners, understanding, and transports must never import it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
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
        turned every ordinary client error into 500 "postgres unavailable"."""
        engine = self._require_engine
        try:
            async with engine.begin() as conn:
                yield conn
        except Exception as exc:  # noqa: BLE001
            if _is_http_error(exc):
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
