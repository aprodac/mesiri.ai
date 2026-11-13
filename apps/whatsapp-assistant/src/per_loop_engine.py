"""One database engine per event loop, for the routers that open their own engine (projects, users, admin).

An engine's connection pool belongs to the event loop it was first used on. Kept in a module-wide variable, it outlived
its loop wherever a process runs more than one (each test has its own): the next caller got pooled connections of a
closed loop and a 500 ("Event loop is closed"), and the cleanup failures after it took 39 more tests down in CI on
13 Nov 2026. The server runs one loop, so there each router keeps one engine, exactly as before.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any


class PerLoopEngine:
    """``get()`` returns the engine for the running event loop, made by ``factory`` the first time on each loop."""

    def __init__(self, factory: Callable[[], Any]) -> None:
        self._factory = factory
        self._loop: asyncio.AbstractEventLoop | None = None
        self._engine: Any = None

    def get(self) -> Any:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # called outside a loop (a script, a test setting up): the one kept is fine
            loop = self._loop
        if self._engine is None or loop is not self._loop:
            self._engine, self._loop = self._factory(), loop
        return self._engine

    async def dispose(self) -> None:
        """Close this loop's engine and forget it (a test's teardown); the next ``get()`` makes a new one."""
        engine, self._engine, self._loop = self._engine, None, None
        if engine is not None and hasattr(engine, "dispose"):
            await engine.dispose()
