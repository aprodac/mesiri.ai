"""TM-25: replay a production v3 turn as a scripted test.

``scripts/replay_to_test.py <correlation_id>`` reads a turn's ``agent_api_turn`` trace (what the person
said, every tool the model called with its arguments, what the API answered) and writes a test in
``tests/agent_api/replays/`` that runs the SAME turn through ``ApiAgent``: the model is scripted with the
recorded calls, and the API answers each GET with what production answered. Writes are prepared, not
sent (as in production, until Save). The generated test asserts what happened; the fix's author edits
the expectations to what SHOULD happen, so the test fails before the fix and passes after.
"""

from __future__ import annotations

import functools
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

from agent_api.agent import ApiAgent, ApiTurn, Places
from agent_api.client import ApiResponse
from mesiri_ai.fakes import FakeToolCallingProvider
from mesiri_ai.models import ChatMessage

#: Tools the agent handles itself (no API call).
_OWN = {"ask", "tell_the_team", "web_link", "save_ready_entries", "drop_ready_entries"}


@dataclass
class RecordedApi:
    """Answers GETs with the results production gave, in order per path; anything else is 200 {}."""

    answers: dict[str, list[Any]] = field(default_factory=dict)
    seen: list[tuple[str, str]] = field(default_factory=list)
    #: The material list read from the turn's facts (live replays): what ``GET /materials`` answers when the
    #: recording kept no answer for it.
    catalogue: list[dict[str, Any]] = field(default_factory=list)

    async def call(self, method: str, path: str, *, params: dict[str, Any] | None = None,
                   json: dict[str, Any] | None = None, idempotency_key: str | None = None) -> ApiResponse:
        self.seen.append((method, path))
        queue = self.answers.get(f"{method} {path}") or []
        if not queue and self.catalogue and (method, path) == ("GET", "/materials"):
            # WA-277 round 2: the company's material list, as the facts of that turn give it. Without it the code's
            # own material check is off in a replay (it reads an empty list and lets the model's pick stand), and
            # the real model is judged without the check production runs on every line.
            word = str((params or {}).get("search") or "").strip().lower()
            rows = [r for r in self.catalogue
                    if not word or any(word in n.lower() for n in (r["name"], *r["aliases"]))]
            return ApiResponse(status=200, body={"items": rows, "total": len(rows)})
        body = queue.pop(0) if queue else {}
        return ApiResponse(status=200, body=body)

    async def close(self) -> None:
        return None


@functools.lru_cache(maxsize=1)
def _built_tools() -> dict[str, Any]:
    from agent_api.app import build_api_app
    from agent_api.tools import build_tools

    return build_tools(build_api_app(None).openapi())


def _real_tools() -> dict[str, Any]:
    """Every tool on ALLOWED. Built once per run (WA-277 step A: with about 47 saved conversations, building the API
    app for each one took most of their time); each caller gets its own dict of the same (frozen) tools."""
    return dict(_built_tools())


_MATERIAL_LINE = re.compile(r"^- (?P<name>.+?) \((?P<id>[0-9a-f-]{36}), (?P<unit>[^)]*)\)(?: also called: (?P<aliases>.+))?$")
_UNIT = re.compile(r"(?P<code>[^,(]+?) \((?P<id>[0-9a-f-]{36})\)")


def facts_catalogue(facts: str) -> list[dict[str, Any]]:
    """The materials a turn's facts list ("- Steel (<id>, kg) also called: kambi, TMT"), as ``GET /materials`` rows."""
    units = {}
    for line in facts.splitlines():
        if line.startswith("Units (unit_id):"):
            units = {m["code"].strip(): m["id"] for m in _UNIT.finditer(line.split(":", 1)[1])}
    rows = []
    for line in facts.splitlines():
        if (m := _MATERIAL_LINE.match(line.strip())) is not None:
            rows.append({"id": m["id"], "name": m["name"], "is_active": True, "default_unit": m["unit"],
                         "default_unit_id": units.get(m["unit"]),
                         "aliases": [a.strip() for a in (m["aliases"] or "").split(",") if a.strip()]})
    return rows


_PROJECT = re.compile(r"^- project (?P<name>.+?) \(project_id (?P<id>[0-9a-f-]{36})\)\s*$")
_SITE = re.compile(r"^\s+- site (?P<name>.+?) \(site_id (?P<id>[0-9a-f-]{36})\)")


def facts_places(facts: str) -> Places | None:
    """WA-281: the person's projects and sites as the turn's facts list them, so a replay runs the code's site flow
    (which site an update goes to, the site question) as production does. None when the facts name no project."""
    projects: list[tuple[str, str]] = []
    sites: list[tuple[str, str, str]] = []
    for line in (facts or "").splitlines():
        if (m := _PROJECT.match(line)):
            projects.append((m["id"], m["name"]))
        elif (m := _SITE.match(line)) and projects:
            sites.append((m["id"], m["name"], projects[-1][0]))
    return Places(projects=tuple(projects), sites=tuple(sites)) if projects else None


def recorded_api(recorded: dict[str, Any], tools: dict[str, Any]) -> RecordedApi:
    api = RecordedApi()
    for call in recorded.get("calls") or []:
        tool = tools.get(call.get("tool"))
        if tool is None or tool.is_write:
            continue
        args = call.get("arguments") or call.get("args") or {}
        path = tool.path
        for p in tool.path_params:
            path = path.replace("{" + p + "}", str(args.get(p, "")))
        api.answers.setdefault(f"GET {path}", []).append(call.get("result") or {})
    return api


def live_provider() -> Any:
    """WA-148: the real model (GEMINI_API_KEY, GEMINI_MODEL), for the replays' live run; skips without a key."""
    import pytest

    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        pytest.skip("GEMINI_API_KEY not set")
    from pydantic import SecretStr

    from mesiri.bootstrap.settings import GeminiSettings
    from mesiri_ai.adapters.gemini.adapter import GeminiProvider

    return GeminiProvider(GeminiSettings(api_key=SecretStr(key), model=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")))


async def replay(recorded: dict[str, Any], *, facts: str = "", reply: str | None = None,
                 live: bool = False, places: bool | None = None) -> tuple[ApiTurn, RecordedApi]:
    """Run the recorded turn again: same words and API answers; the same tool calls (scripted) or the
    real model reading today's SOP.md (``live``, WA-148). GETs the recording has no answer for get {}."""
    # WA-281: the real model runs with the person's sites, as in production. A scripted replay asserts what
    # HAPPENED in its recording, made before the code decided the site, so it keeps its own setting unless asked.
    places = live if places is None else places
    tools = _real_tools()
    calls = [(c["tool"], c.get("arguments") or c.get("args") or {}) for c in recorded.get("calls") or []
             if c.get("tool") in tools or c.get("tool") in _OWN]
    script: list[Any] = ([calls] if calls else []) + [reply if reply is not None else recorded.get("reply", "")]
    api = recorded_api(recorded, tools)
    model = live_provider() if live else FakeToolCallingProvider(script)
    facts = facts or str(recorded.get("facts") or "")
    if live:
        api.catalogue = facts_catalogue(facts)
    # WA-271: the messages before this one, when the trace kept them (turns traced from 10 Nov 2026).
    history = [ChatMessage(role=str(m.get("role") or "user"), text=str(m.get("text") or ""))
               for m in recorded.get("before") or [] if isinstance(m, dict)]
    turn = await ApiAgent(model, tools).run(
        api, recorded.get("text", ""), facts=facts, history=history,  # type: ignore[arg-type]
        correlation_id=recorded.get("correlation_id"), places=facts_places(facts) if places else None)
    return turn, api


def load(text: str) -> dict[str, Any]:
    return json.loads(text)


def check(turn: ApiTurn, expect: dict[str, Any]) -> list[str]:
    """WA-148: what a turn got wrong against ``EXPECT`` (empty = right): tools it must / must not call,
    and the entries that must be waiting for Save (their summary contains each given text).

    WA-277 step A: ``must_call_any`` (one of several tools that answer the same question is enough: the stock of one
    material or of all), and ``pending_has`` (texts some waiting entry must mention, however many entries there are:
    a new material's own line may or may not be among them). An expectation is about what was held or looked up,
    never the model's sentence (WA-271)."""
    called = [c["tool"] for c in turn.calls]
    wrong = [f"did not call {t}" for t in expect.get("must_call") or [] if t not in called]
    wrong += [f"called {t}" for t in expect.get("must_not_call") or [] if t in called]
    if (any_of := expect.get("must_call_any")) and not set(any_of) & set(called):
        wrong.append(f"called none of {', '.join(any_of)}")
    if expect.get("pending_has"):
        held = " | ".join(e.summary.lower() for e in turn.pending)
        wrong += [f"no waiting entry mentions {w!r}" for w in expect["pending_has"] if w.lower() not in held]
    if expect.get("pending") is not None:
        summaries = " | ".join(e.summary.lower() for e in turn.pending)
        want = expect["pending"]
        if len(turn.pending) != len(want):
            wrong.append(f"{len(turn.pending)} entries waiting, expected {len(want)}: {summaries}")
        wrong += [f"no waiting entry mentions {w!r}" for w in want if w.lower() not in summaries]
    if wrong:
        # WA-271: what the model did, in the failure itself (the eval's summary line is all the team group sees).
        waiting = " | ".join(e.summary for e in turn.pending)
        wrong.append(f"(it called {called or 'nothing'}; waiting: {waiting or 'nothing'}; said: {(turn.reply or '')[:160]!r})")
    return wrong
