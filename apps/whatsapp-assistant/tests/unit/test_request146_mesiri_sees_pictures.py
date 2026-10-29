"""Request 146 (live 29 Oct, Ilan @ Paraclette): after an image lookup Mesiri said it could
not send images. The lookup's picture goes out after the run, so the stored reply is words
only; the turn history now lists the pictures sent with each earlier turn."""

from __future__ import annotations

import asyncio
import datetime as dt
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from channel.whatsapp import sent_text
from mesiri.infrastructure.redis.client import FakeRedis
from mesiri_contracts.assistant.enums import InputModality
from mesiri_contracts.assistant.normalized_message import NormalizedMessage, SenderInfo
from runtime.agent import runner as r
from runtime.agent.query_entry import _asked_label
from runtime.agent.turn import AgentTurnDeps, run_agent_turn

WA = "919000000001"


@pytest.fixture
def store(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(sent_text, "_store", redis)
    return redis


def _message(text):
    return NormalizedMessage(
        message_id="wamid.in",
        sender=SenderInfo(wa_id=WA, profile_name="A"),
        timestamp=dt.datetime(2026, 10, 29, 8, 0),
        modality=InputModality.TEXT,
        text=text,
    )


_ACTOR = SimpleNamespace(user_id="u", full_name="A", role="S", org_name="O", projects=[], sites=[], organization_id="o")


def _deps(seen, *, turns=()):
    async def run(**kw):
        seen.append(kw)
        return r.AgentResult("degraded", r.ReplySpec(text="ok"), SimpleNamespace(parked=None, saved=[]))

    memory = SimpleNamespace(
        load=AsyncMock(return_value=SimpleNamespace(recent_turns=list(turns), has_pending_confirmation=False))
    )
    return AgentTurnDeps(
        runner=SimpleNamespace(run=run),
        make_gateway=lambda m, lang: SimpleNamespace(handled=[], finish=AsyncMock()),
        send_spec=AsyncMock(),
        transcribe=None,
        message_logger=AsyncMock(),
    ), memory


# -- the label says what was asked ------------------------------------------------------------


def test_the_label_carries_the_words_they_asked_with():
    label = _asked_label(SimpleNamespace(text="innathe workers list image ayi ayakku"), "Labour Attendance list card (1 of 1)", 30)
    assert label == "Labour Attendance list card (1 of 1), 30 rows, asked: 'innathe workers list image ayi ayakku'"
    assert _asked_label(SimpleNamespace(text=None), "PDF list x.pdf", None) == "PDF list x.pdf"


# -- the history has the picture in it -------------------------------------------------------


async def test_replay_image_lookup_then_is_it_an_image(store):
    """The 29 Oct 19:36 conversation: the table went out after the run, so the stored reply is
    only 'Ithaa, innu vanna workkarsinte list.' -- the turn the model reads now lists the picture."""
    sent_text.report_sent(
        wamid="wamid.table",
        message_fields={"type": "image", "image": {"id": "m"}},
        recipient=WA,
        shows="Labour Attendance list card (1 of 1), 30 rows, asked: 'workers list image'",
    )
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    import time

    turns = [SimpleNamespace(user_text="workers list image ayi", assistant_reply="Ithaa, innu vanna workkarsinte list.", at=time.time() - 5)]
    seen: list = []
    deps, memory = _deps(seen, turns=turns)
    deps.memory_loader = memory
    await run_agent_turn(_message("image aano?"), _ACTOR, deps)
    ctx = seen[0]["ctx"]
    assert "[Mesiri also sent: [picture: Labour Attendance list card" in ctx.turns[-1].assistant_reply
    note = next(n for n in ctx.notes if "DID go out" in n)
    assert "never say you did not send" in note


async def test_no_media_leaves_the_turns_alone(store):
    seen: list = []
    deps, memory = _deps(seen, turns=[SimpleNamespace(user_text="hi", assistant_reply="Hello", at=1.0)])
    deps.memory_loader = memory
    await run_agent_turn(_message("ok"), _ACTOR, deps)
    assert all("also sent" not in t.assistant_reply for t in seen[0]["ctx"].turns)
