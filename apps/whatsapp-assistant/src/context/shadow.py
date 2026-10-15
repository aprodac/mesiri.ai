"""BE-01 step 0: run the main-table lookups beside the context copy and compare.

``MESIRI_IDENTITY_SOURCE`` picks where the WhatsApp assistant reads who a
sender is and what they may reach:

- ``context``: the ``context_*`` copy only (the old behaviour).
- ``shadow``: the copy still answers; the same question is also put
  to the main tables, and any difference is recorded. Nothing a user sees
  changes. A failure on the main-table side is recorded, never raised.
- ``main`` (default since BE-01 step 1): the main tables answer; the copy is
  not read. It is still kept up to date (projection hooks, reconcile
  watchdog), so ``MESIRI_IDENTITY_SOURCE=shadow`` plus a restart is a safe,
  instant way back until step 3 removes it.

Differences go to ``identity_shadow_mismatches`` (one row per distinct
question, with a hit count), readable at ``GET /admin/reconcile/shadow``. A
table stays empty over a few days of real traffic -> switch to ``main``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from dataclasses import asdict, is_dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger("mesiri.identity.shadow")

SOURCES = ("context", "shadow", "main")
DEFAULT_SOURCE = "main"


def identity_source() -> str:
    value = os.environ.get("MESIRI_IDENTITY_SOURCE", DEFAULT_SOURCE).strip().lower()
    if value not in SOURCES:
        logger.error("unknown MESIRI_IDENTITY_SOURCE %r; using %r", value, DEFAULT_SOURCE)
        return DEFAULT_SOURCE
    return value


def _plain(value: Any) -> Any:
    """A comparable, JSON-able form. Lists compare as sets (row order is not
    meaningful: the copy sorts by text collation, the main side by UUID)."""
    if is_dataclass(value) and not isinstance(value, type):
        return _plain(asdict(value))
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        items = [_plain(v) for v in value]
        if isinstance(value, list):
            return sorted(items, key=lambda v: json.dumps(v, sort_keys=True, default=str))
        return items
    return value


class MismatchRecorder:
    """Writes differences, best effort and off the request path."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._pending: set[asyncio.Task] = set()

    def record(self, port: str, method: str, args: dict, old: Any, new: Any) -> None:
        logger.warning(
            "identity_shadow.mismatch port=%s method=%s args=%s context=%s main=%s",
            port,
            method,
            args,
            old,
            new,
        )
        task = asyncio.get_running_loop().create_task(self._write(port, method, args, old, new))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    async def _write(self, port: str, method: str, args: dict, old: Any, new: Any) -> None:
        from sqlalchemy import text

        body = json.dumps({"p": port, "m": method, "a": args}, sort_keys=True, default=str)
        fingerprint = hashlib.sha256(body.encode()).hexdigest()
        try:
            async with self._engine.connect() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO identity_shadow_mismatches "
                        "  (fingerprint, port, method, args, context_result, main_result) "
                        "VALUES (:f, :p, :m, CAST(:a AS jsonb), CAST(:o AS jsonb), CAST(:n AS jsonb)) "
                        "ON CONFLICT (fingerprint) DO UPDATE SET "
                        "  hits = identity_shadow_mismatches.hits + 1, last_seen_at = now(), "
                        "  context_result = EXCLUDED.context_result, "
                        "  main_result = EXCLUDED.main_result"
                    ),
                    {
                        "f": fingerprint,
                        "p": port,
                        "m": method,
                        "a": json.dumps(args, default=str),
                        "o": json.dumps(old, default=str),
                        "n": json.dumps(new, default=str),
                    },
                )
                await conn.commit()
        except Exception:  # noqa: BLE001 -- the comparison must never hurt a reply
            logger.exception("identity_shadow.record_failed")


class ShadowPort:
    """Answers from ``primary``; asks ``candidate`` the same thing and compares."""

    def __init__(self, port: str, primary: Any, candidate: Any, recorder: MismatchRecorder) -> None:
        self._port = port
        self._primary = primary
        self._candidate = candidate
        self._recorder = recorder

    def __getattr__(self, method: str) -> Any:
        primary_fn = getattr(self._primary, method)
        candidate_fn = getattr(self._candidate, method)

        async def call(*args: Any, **kwargs: Any) -> Any:
            old, new = await asyncio.gather(
                primary_fn(*args, **kwargs),
                candidate_fn(*args, **kwargs),
                return_exceptions=True,
            )
            if isinstance(old, BaseException):
                raise old
            call_args = {"args": list(args), **kwargs}
            if isinstance(new, BaseException):
                self._recorder.record(
                    self._port, method, call_args, _plain(old), {"error": repr(new)}
                )
            elif _plain(old) != _plain(new):
                self._recorder.record(self._port, method, call_args, _plain(old), _plain(new))
            return old

        return call
