"""Request 185: replay a real conversation through an engine in the test World.

Each turn goes in as production sends it: a typed or voice message (its transcript) runs the
engine; a button tap presses the matching button of the previous reply when there is one (the
journey's tap handler), else it is read as typed text (WA-106: a button's text is an answer).
The engine's replies are then judged by ``agent_v2.replay.checks``, the same checks that score
what production answered.

The World is the fake company of the replay tests (one site, catalog, books): site and material
names of the real company are not there, so a "which site?" can appear that production did not
ask. That is noted in every report.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from typing import Any, Protocol

from tests.agent_v2.evalkit import _Books
from tests.replay.test_agent_replay import _Catalog, _make_world
from tests.replay.test_draft_per_message_p1 import press

from agent_v2.replay.checks import Finding, check_conversation
from agent_v2.replay.corpus import TAP, Conversation
from context import seed
from runtime.agent import draft as dr
from runtime.agent.draft_store import MemoryDraftStore
from runtime.agent.history import for_model
from runtime.agent.prompt import Turn

#: What production keeps of the conversation (memory/requirements.py RECENT_TURNS_MAX_ENTRIES).
HISTORY = 10


class Engine(Protocol):
    """One assistant brain: answers ``text`` given the world and what was said before."""

    async def reply(self, world: Any, history: list[Turn], text: str, correlation_id: str) -> Any: ...


@dataclass(slots=True)
class Replayed:
    key: str
    texts: list[str] = field(default_factory=list)
    replies: list[str] = field(default_factory=list)
    kinds: list[str] = field(default_factory=list)
    seconds: list[float] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def findings(self) -> list[Finding]:
        return check_conversation(self.texts, self.replies, self.kinds)


async def new_world() -> Any:
    world = await _make_world(site_keys=(seed.SITE_A1,))
    world.draft_v2 = True
    world.drafts = MemoryDraftStore()
    world.catalog = _Catalog()
    world.inventory = _Books()
    world.actor = replace(world.actor, role="PROJECT_MANAGER")
    return world


def _matching_row(reply: Any, title: str) -> str | None:
    if reply is None:
        return None
    want = title.strip().rstrip("…").casefold()
    for row in [*(getattr(reply, "buttons", None) or ()), *(getattr(reply, "list_rows", None) or ())]:
        if row.title.casefold().startswith(want[:20]) or want.startswith(row.title.rstrip("…").casefold()[:20]):
            return row.title
    return None


def _text(reply: Any) -> str:
    return str(getattr(reply, "text", None) or "")


async def replay(conv: Conversation, engine: Engine, *, max_turns: int | None = None) -> Replayed:
    world = await new_world()
    out = Replayed(conv.key)
    history: list[Turn] = []
    last_reply: Any = None
    for n, turn in enumerate(t for t in conv.turns if t.replayable):
        if max_turns is not None and n >= max_turns:
            break
        started = time.perf_counter()
        reply: Any = None
        try:
            title = _matching_row(last_reply, turn.text) if turn.kind == TAP else None
            if title is not None:
                reply, _ = await press(world, last_reply, title)
            else:
                reply = await engine.reply(world, history, turn.text, turn.correlation_id or f"cor_replay_{n}")
        except Exception as exc:  # noqa: BLE001 -- a crash is a finding, the replay goes on
            out.errors.append(f"turn {n}: {type(exc).__name__}: {exc}")
        text = _text(reply)
        out.texts.append(turn.text)
        out.replies.append(text)
        out.kinds.append(turn.kind)
        out.seconds.append(time.perf_counter() - started)
        history.append(Turn(turn.text, text, time.time()))
        last_reply = reply
    return out


class V2Engine:
    """Today's v2 (request 180) with today's memory: the last ten turns, each reply cut to its
    gist (runtime/agent/history.py), plus the open card as one line."""

    def __init__(self, provider: Any) -> None:
        from agent_v2.runner import V2Runner
        from mesiri_ai.fakes import FakeToolCallingProvider
        from runtime.agent.runner import AgentRunner

        self.classic_calls = FakeToolCallingProvider(["(today's agent would answer here)"])
        self.runner = V2Runner(provider, AgentRunner(self.classic_calls))

    async def reply(self, world: Any, history: list[Turn], text: str, correlation_id: str) -> Any:
        card = await world.drafts.open_for(world.actor.organization_id, world.actor.user_id)
        ctx = world.context(turns=for_model(tuple(history[-HISTORY:])), card_line=dr.context_line(card))
        result = await self.runner.run(
            ctx=ctx, user_text=text, gateway=world.gateway(text), scope=world.scope(), correlation_id=correlation_id
        )
        return result.reply


class AdkEngine:
    """v2 on ADK (request 185): the conversation is ADK's own session (``history`` is not
    used), the open card goes in the instructions. ``model`` is an ADK model (``gemini()``, a
    ``ScriptedLlm``) or a ``GeminiProvider`` whose key and model are reused."""

    def __init__(self, model: Any) -> None:
        from agent_v2.adk.agent import AdkAgent
        from agent_v2.runner import V2Runner
        from mesiri_ai.fakes import FakeToolCallingProvider
        from runtime.agent.runner import AgentRunner

        if hasattr(model, "run_tools"):  # a GeminiProvider from the live test: same key, same model
            from agent_v2.adk.models import gemini

            settings = model._settings
            model = gemini(settings.model, settings.api_key.get_secret_value())
        self.agent = AdkAgent(model, catalog=_Catalog())
        self.classic_calls = FakeToolCallingProvider(["(today's agent would answer here)"])
        self.runner = V2Runner(None, AgentRunner(self.classic_calls), agent=self.agent)

    async def reply(self, world: Any, history: list[Turn], text: str, correlation_id: str) -> Any:
        card = await world.drafts.open_for(world.actor.organization_id, world.actor.user_id)
        ctx = world.context(card_line=dr.context_line(card))
        result = await self.runner.run(
            ctx=ctx, user_text=text, gateway=world.gateway(text), scope=world.scope(), correlation_id=correlation_id
        )
        return result.reply
