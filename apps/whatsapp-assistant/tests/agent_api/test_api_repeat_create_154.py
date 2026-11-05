"""WA-154 (3 Nov, Paraclette): "Rana Mart" re-sent at 22:44, 23:34 and 00:58 made three empty projects. A create
the same person already saved in the last day is asked about once ("Already saved at 22:44 ... another?"); a yes
in the next message lets the same create through (still behind Save). Any create, not only projects."""

from __future__ import annotations

import time

import pytest
from tests.agent_api.standin import (
    ACTOR,
    BAG,
    CEMENT,
    NOS,
    TMT,
    receipt_call,
    stand_in_api,
    stand_in_tools,
)

from agent_api.agent import ApiAgent, PendingWrite, WriteResult, create_fingerprint, remember_saves
from agent_api.client import ApiClient
from mesiri_ai.fakes import FakeToolCallingProvider

LINE = "50 bags cement, Green Villa"


async def _run(model, app, **kw):  # noqa: ANN001, ANN003, ANN202
    client = ApiClient(ACTOR, app=app)
    try:
        return await ApiAgent(model, stand_in_tools(app)).run(client, "50 bag cement vannu", **kw)
    finally:
        await client.close()


async def _saved_once(app) -> list:  # noqa: ANN001
    first = await _run(FakeToolCallingProvider([[receipt_call(CEMENT, BAG, LINE)], "Ready."]), app)
    [entry] = first.pending
    return remember_saves([], [WriteResult(entry, 201, {"id": "r1"})], time.time() - 3600)


async def test_the_same_create_again_is_asked_about_not_prepared() -> None:
    app = stand_in_api([])
    recent = await _saved_once(app)
    model = FakeToolCallingProvider([[receipt_call(CEMENT, BAG, LINE)], "You saved this an hour ago. Another one?"])
    turn = await _run(model, app, recent_saves=recent)
    assert turn.pending == []
    error = turn.calls[0]["result"]["error"]
    assert error.startswith("Already saved at ") and LINE in error and "Ask the person" in error
    assert len(turn.repeat_asked) == 1

    # Their yes, in the next message: the same create goes through, still waiting for Save.
    yes = await _run(FakeToolCallingProvider([[receipt_call(CEMENT, BAG, LINE)], "Ready."]), app,
                     recent_saves=recent, repeat_ok=turn.repeat_asked)
    assert [e.summary for e in yes.pending] == [LINE]


async def test_sibling_a_different_create_and_a_change_are_not_asked() -> None:
    app = stand_in_api([])
    recent = await _saved_once(app)
    other = await _run(FakeToolCallingProvider([[receipt_call(TMT, NOS, "50 TMT bars")], "Ready."]), app, recent_saves=recent)
    assert [e.summary for e in other.pending] == ["50 TMT bars"]
    assert create_fingerprint("x", "PATCH", "/projects/1", {"name": "Rana Mart"}) is None  # edits are never asked


def test_guard_the_memory_keeps_one_day_and_only_saved_creates() -> None:
    now = time.time()
    entry = PendingWrite("create_project", "POST", "/projects", {}, {"name": "Rana  MART", "channel": "voice"}, "Rana Mart", "k")
    kept = remember_saves([{"fp": "old", "at": now - 90_000}], [WriteResult(entry, 201, {}), WriteResult(entry, 422, {})], now)
    assert [k["summary"] for k in kept] == ["Rana Mart"]
    same = create_fingerprint("create_project", "POST", "/projects", {"name": "rana mart", "channel": "text"})
    assert kept[0]["fp"] == same  # case, spacing and how it was sent don't make it different


@pytest.fixture
def _stand_in_wa(monkeypatch):  # noqa: ANN001, ANN202
    from tests.agent_api.standin import STAND_IN_TOOLS

    from agent_api import tools as tools_mod
    from agent_api import whatsapp as wa

    real = tools_mod.build_tools
    monkeypatch.setattr(wa, "build_tools", lambda openapi: real(
        openapi, tuple(a for a in tools_mod.ALLOWED if a.name in STAND_IN_TOOLS)))


# End to end through the WhatsApp service: Save tap, the same message again, the question, the yes.
@pytest.mark.usefixtures("_stand_in_wa")
async def test_through_whatsapp_a_resent_message_asks_before_a_second_copy() -> None:
    from tests.agent_api.test_api_agent_124 import CTX, _message, _service

    seen: list = []
    app = stand_in_api(seen)
    prepare = [[receipt_call(CEMENT, BAG, LINE)], "Ready."]
    service, sent = _service(FakeToolCallingProvider(prepare), app=app)
    await service.handle(_message("50 bag cement vannu"), CTX)
    await service.handle(_message("Save", tap=sent[-1].buttons[0].id), CTX)
    assert sum(1 for m, p, *_ in seen if m == "POST") == 1

    asked = FakeToolCallingProvider([prepare[0], "You saved 50 bags cement a moment ago. Another one?"])
    service._agent._provider = asked
    await service.handle(_message("50 bag cement vannu"), CTX)  # re-sent
    assert not sent[-1].buttons  # nothing prepared, no Save
    assert len((await service._state(CTX)).get("repeat_asked") or []) == 1  # asked about, remembered for the yes

    service._agent._provider = FakeToolCallingProvider(prepare)
    await service.handle(_message("athe, onnu koodi"), CTX)  # yes, another
    assert [b.title for b in sent[-1].buttons] == ["Save", "✏️ Edit", "Cancel"]
