"""TM-69: Mesiri remembers what this person told the team about. A v3 turn reads their open requests (in parallel with
the facts, under a time cap) and the model starts from them, so "is the primer thing fixed?" is answered as someone
who knows. Guards: no requests, no block; a slow or broken read never holds the reply up or breaks it."""

from __future__ import annotations

import asyncio
import datetime as dt

from tests.agent_api.test_api_agent_124 import CTX, _message, _service, _stand_in_tools  # noqa: F401 (autouse)

from agent_api import whatsapp as wa
from mesiri_ai.fakes import FakeToolCallingProvider
from runtime import request_progress

ROW = {"correlation_id": "cor_0123456789abcdef0123456789abcdef", "created_at": dt.datetime(2026, 11, 3, 11, 20, tzinfo=dt.UTC),
       "stage": "understood", "ref": "#012345",
       "line": "The 2 drums of primer you received at Green Villa weren't saved, so its stock is 40 L short."}


class _Db:
    def transaction(self):  # the real read is replaced below; only its presence matters
        raise AssertionError("not called in these tests")


def _with(monkeypatch, read):
    model = FakeToolCallingProvider(["Haan, primer receipt fix aakkikondirikkunnu (#012345)."])
    service, sent = _service(model)
    service._database = _Db()
    monkeypatch.setattr(request_progress, "open_requests", read)
    return model, service, sent


async def test_the_model_starts_from_the_persons_open_requests(monkeypatch) -> None:
    seen = []

    async def read(db, wa_id, **kw):
        seen.append(wa_id)
        return [ROW]

    model, service, sent = _with(monkeypatch, read)
    await service.handle(_message("primer issue sheriyaayo?"), CTX)
    prompt = model.last_system_prompt
    assert "OPEN REQUESTS (this person told us about these" in prompt
    assert "#012345 being fixed" in prompt and "40 L short" in prompt
    assert seen and sent


async def test_guard_no_open_requests_no_block(monkeypatch) -> None:
    async def read(db, wa_id, **kw):
        return []

    model, service, _ = _with(monkeypatch, read)
    await service.handle(_message("good morning"), CTX)
    assert "OPEN REQUESTS (this person" not in model.last_system_prompt


async def test_guard_a_slow_or_broken_read_never_holds_the_reply(monkeypatch) -> None:
    monkeypatch.setattr(wa, "OPEN_REQUESTS_TIMEOUT_S", 0.05)

    async def slow(db, wa_id, **kw):
        await asyncio.sleep(5)
        return [ROW]

    model, service, sent = _with(monkeypatch, slow)
    started = asyncio.get_running_loop().time()
    await service.handle(_message("good morning"), CTX)
    assert asyncio.get_running_loop().time() - started < 2
    assert "OPEN REQUESTS (this person" not in model.last_system_prompt and sent

    async def broken(db, wa_id, **kw):
        raise RuntimeError("db down")

    model, service, sent = _with(monkeypatch, broken)
    await service.handle(_message("good morning"), CTX)
    assert sent


async def test_guard_no_database_reads_nothing() -> None:
    service, sent = _service(FakeToolCallingProvider(["Hello."]))
    assert await service._open_requests(_message("hi")) == ""
