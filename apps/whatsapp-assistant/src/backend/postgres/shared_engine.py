"""One database pool per process (per event loop), shared by every repository here.

8 Nov 2026 (production incident): Postgres ran out of connections ("remaining connection slots are reserved for
roles with the SUPERUSER attribute", 96 of 100 idle Mesiri connections, the oldest idle ~9 h), so messages,
the dashboard and notifications failed. Four modules here (message_logger, trace_logger, actor,
workflow_instance) each built a NEW engine -- a new pool -- for every object, and objects were made per call: the
notification drain made a PostgresActorReader every minute in each app process, and ``last_inbound_at`` a
PostgresMessageLogger per waiting notification (many more since SA-37 holds announcements). No engine was ever
disposed, so each left pooled connections behind until the database was full.

Now every one of them gets the same engine for the process's event loop: making an object never opens a pool.
Keyed by the running loop too, so a test (or a script) on another loop never reuses a pool tied to a closed one.
"""

from __future__ import annotations

import asyncio
import os
import weakref
from typing import Any

#: Engines per event loop (a loop that is gone takes its engines with it), and for code outside any loop.
_BY_LOOP: weakref.WeakKeyDictionary[Any, dict[str, Any]] = weakref.WeakKeyDictionary()
_NO_LOOP: dict[str, Any] = {}


def _dsn() -> str:
    host = os.environ.get("MESIRI_POSTGRES__HOST", "localhost")
    port = os.environ.get("MESIRI_POSTGRES__PORT", "5432")
    user = os.environ.get("MESIRI_POSTGRES__USER", "mesiri")
    password = os.environ.get("MESIRI_POSTGRES__PASSWORD", "mesiri_local_dev")
    database = os.environ.get("MESIRI_POSTGRES__DATABASE", "mesiri")
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{database}"


def shared_engine() -> Any:
    """The process's engine for the current event loop (created once)."""
    # SQLAlchemy imported lazily to avoid the platform/ shadow-package issue during test collection.
    from sqlalchemy.ext.asyncio import create_async_engine

    try:
        engines = _BY_LOOP.setdefault(asyncio.get_running_loop(), {})
    except RuntimeError:
        engines = _NO_LOOP
    dsn = _dsn()
    engine = engines.get(dsn)
    if engine is None:
        engine = engines[dsn] = create_async_engine(dsn, echo=False, pool_pre_ping=True)
    return engine
