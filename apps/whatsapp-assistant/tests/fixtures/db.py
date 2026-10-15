"""Sync engine on the local test database, for integration tests that seed rows."""

from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine


def build_sync_engine() -> Engine:
    """Same connection settings as the app (MESIRI_POSTGRES__*)."""
    env = os.environ.get
    user = env("MESIRI_POSTGRES__USER", "mesiri")
    password = env("MESIRI_POSTGRES__PASSWORD", "mesiri_local_dev")
    host = env("MESIRI_POSTGRES__HOST", "localhost")
    port = env("MESIRI_POSTGRES__PORT", "5432")
    database = env("MESIRI_POSTGRES__DATABASE", "mesiri")
    dsn = f"postgresql+psycopg://{user}:{password}@{host}:{port}/{database}"
    return create_engine(dsn, future=True)
