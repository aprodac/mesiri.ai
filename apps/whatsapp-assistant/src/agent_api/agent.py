"""WA-119: one model, one SOP, the dashboard's API as its tools.

A turn: the model reads the message with the SOP and the tools, looks things up
(``GET`` routes run at once), and prepares entries (any other route is held, not
sent). The turn returns the model's own reply and the held entries; the caller
shows them and calls ``confirm`` when the person says yes. That is the only
place a write reaches the API, with an ``Idempotency-Key`` so a repeated
confirmation cannot record twice.

No classifier, no workflow, no word list, no reply rewriting.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from mesiri_ai.models import ChatMessage, ToolOutcome

from .client import ApiClient, new_idempotency_key
from .tools import SUMMARY_ARG, ApiTool

SOP = (Path(__file__).with_name("SOP.md")).read_text(encoding="utf-8")

MAX_STEPS = 8
TIMEOUT_SECONDS = 40.0
#: A read's JSON is cut to this many characters before the model sees it.
READ_LIMIT = 8000


@dataclass(frozen=True)
class PendingWrite:
    """An entry the model prepared; reaches the API only through ``confirm``."""

    tool: str
    method: str
    path: str
    params: dict[str, Any]
    body: dict[str, Any]
    summary: str
    idempotency_key: str


@dataclass(frozen=True)
class WriteResult:
    pending: PendingWrite
    status: int
    body: Any

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


@dataclass
class ApiTurn:
    reply: str
    pending: list[PendingWrite] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)
    stop_reason: str = "answered"


class ApiAgent:
    def __init__(self, provider: Any, tools: dict[str, ApiTool], *, sop: str = SOP,
                 max_steps: int = MAX_STEPS, timeout_seconds: float = TIMEOUT_SECONDS) -> None:
        self._provider = provider
        self._tools = tools
        self._sop = sop
        self._max_steps = max_steps
        self._timeout = timeout_seconds

    def system_prompt(self, *, sender_name: str, today: dt.date) -> str:
        who = f"You are talking to {sender_name}. " if sender_name else ""
        return f"{self._sop}\n{who}Today is {today.isoformat()} ({today.strftime('%A')})."

    async def run(self, client: ApiClient, text: str, *, history: list[ChatMessage] | None = None,
                  sender_name: str = "", timezone: str = "Asia/Kolkata",
                  correlation_id: str | None = None) -> ApiTurn:
        today = dt.datetime.now(ZoneInfo(timezone)).date()
        pending: list[PendingWrite] = []

        async def handler(name: str, arguments: dict) -> ToolOutcome:
            tool = self._tools.get(name)
            if tool is None:
                return ToolOutcome(content={"error": f"no tool named {name}"})
            missing = [r for r in tool.required if arguments.get(r) in (None, "")]
            if missing:
                return ToolOutcome(content={"error": f"missing: {', '.join(missing)}"})
            path = tool.path
            for p in tool.path_params:
                path = path.replace("{" + p + "}", str(arguments[p]))
            params = {q: arguments[q] for q in tool.query_params if arguments.get(q) not in (None, "")}
            body = {f: arguments[f] for f in tool.body_fields if f in arguments}
            if tool.is_write:
                entry = PendingWrite(
                    tool=name, method=tool.method, path=path, params=params, body=body,
                    summary=str(arguments.get(SUMMARY_ARG) or "").strip(),
                    idempotency_key=new_idempotency_key(),
                )
                pending.append(entry)
                return ToolOutcome(content={
                    "status": "ready, NOT saved",
                    "entry": len(pending),
                    "note": "It saves when the person confirms. Do not say it is saved.",
                })
            response = await client.call(tool.method, path, params=params)
            content = json.dumps(response.body, default=str, ensure_ascii=False)
            if len(content) > READ_LIMIT:
                content = content[:READ_LIMIT] + " ...(cut)"
            return ToolOutcome(content={"status": response.status, "result": content})

        result = await self._provider.run_tools(
            self.system_prompt(sender_name=sender_name, today=today),
            [*(history or []), ChatMessage(role="user", text=text)],
            [t.spec for t in self._tools.values()],
            handler,
            max_steps=self._max_steps,
            timeout_seconds=self._timeout,
            correlation_id=correlation_id,
        )
        calls = [{"tool": c.name, "arguments": c.arguments, "result": c.outcome.content if c.outcome else None}
                 for c in result.calls]
        return ApiTurn(reply=(result.text or "").strip(), pending=pending, calls=calls,
                       stop_reason=result.stop_reason)


async def confirm(client: ApiClient, pending: list[PendingWrite]) -> list[WriteResult]:
    """Send the held entries to the API, in order. The API's own checks
    (access, validation, stock guard) decide; a refusal comes back as-is."""
    results: list[WriteResult] = []
    for entry in pending:
        response = await client.call(entry.method, entry.path, params=entry.params, json=entry.body,
                                     idempotency_key=entry.idempotency_key)
        results.append(WriteResult(entry, response.status, response.body))
    return results
