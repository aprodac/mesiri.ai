"""TM-25: replay a production v3 turn as a scripted test.

``scripts/replay_to_test.py <correlation_id>`` reads a turn's ``agent_api_turn`` trace (what the person
said, every tool the model called with its arguments, what the API answered) and writes a test in
``tests/agent_api/replays/`` that runs the SAME turn through ``ApiAgent``: the model is scripted with the
recorded calls, and the API answers each GET with what production answered. Writes are prepared, not
sent (as in production, until Save). The generated test asserts what happened; the fix's author edits
the expectations to what SHOULD happen, so the test fails before the fix and passes after.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from agent_api.agent import ApiAgent, ApiTurn
from agent_api.client import ApiResponse
from mesiri_ai.fakes import FakeToolCallingProvider

#: Tools the agent handles itself (no API call).
_OWN = {"ask", "tell_the_team", "web_link", "save_ready_entries", "drop_ready_entries"}


@dataclass
class RecordedApi:
    """Answers GETs with the results production gave, in order per path; anything else is 200 {}."""

    answers: dict[str, list[Any]] = field(default_factory=dict)
    seen: list[tuple[str, str]] = field(default_factory=list)

    async def call(self, method: str, path: str, *, params: dict[str, Any] | None = None,
                   json: dict[str, Any] | None = None, idempotency_key: str | None = None) -> ApiResponse:
        self.seen.append((method, path))
        queue = self.answers.get(f"{method} {path}") or []
        body = queue.pop(0) if queue else {}
        return ApiResponse(status=200, body=body)

    async def close(self) -> None:
        return None


def _real_tools() -> dict[str, Any]:
    from agent_api.app import build_api_app
    from agent_api.tools import build_tools

    return build_tools(build_api_app(None).openapi())


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


async def replay(recorded: dict[str, Any], *, facts: str = "", reply: str | None = None) -> tuple[ApiTurn, RecordedApi]:
    """Run the recorded turn again: same words, same tool calls, same API answers."""
    tools = _real_tools()
    calls = [(c["tool"], c.get("arguments") or c.get("args") or {}) for c in recorded.get("calls") or []
             if c.get("tool") in tools or c.get("tool") in _OWN]
    script: list[Any] = ([calls] if calls else []) + [reply if reply is not None else recorded.get("reply", "")]
    api = recorded_api(recorded, tools)
    turn = await ApiAgent(FakeToolCallingProvider(script), tools).run(
        api, recorded.get("text", ""), facts=facts, correlation_id=recorded.get("correlation_id"))  # type: ignore[arg-type]
    return turn, api


def load(text: str) -> dict[str, Any]:
    return json.loads(text)
