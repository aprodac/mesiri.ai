"""8 Nov 2026 incident: every PostgresActorReader / PostgresMessageLogger / trace or workflow repository built its own
pool, objects were made per minute and per notification, none was disposed, and Postgres ran out of connections.
Every one of them now gets the process's one engine (per event loop)."""

from __future__ import annotations

import asyncio

from backend.postgres import actor, message_logger, trace_logger, workflow_instance
from backend.postgres.shared_engine import shared_engine


async def test_every_repository_object_shares_one_engine() -> None:
    engines = {id(actor.PostgresActorReader()._get_engine()) for _ in range(20)}
    engines |= {id(message_logger.PostgresMessageLogger()._get_engine()) for _ in range(20)}
    engines |= {id(trace_logger.PostgresTraceLogger()._get_engine()) for _ in range(5)}
    engines |= {id(workflow_instance._build_engine()) for _ in range(5)}
    assert engines == {id(shared_engine())}


def test_another_event_loop_gets_its_own_engine() -> None:
    kept: list = []

    async def one() -> None:
        kept.append(shared_engine())

    asyncio.run(one())
    asyncio.run(one())
    assert kept[0] is not kept[1]  # a pool is never reused on a closed loop, even at the same address
