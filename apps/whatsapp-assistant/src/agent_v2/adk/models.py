"""The model ADK runs (request 185).

``gemini(model, api_key)``: ADK's own Gemini model with a client on the key Mesiri already has
(the provider settings), so nothing new is configured on the server. Thinking is off for Flash
models, as in the provider loop (it is the difference between ~1 s and ~4 s a round).

``ScriptedLlm``: the test model. Same script format as ``mesiri_ai.fakes.FakeToolCallingProvider``
(a step is a list of ``(tool, args)`` calls or a final string), so a scripted conversation runs
through either engine unchanged.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextvars import ContextVar
from typing import Any

from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from pydantic import PrivateAttr


def gemini(model: str, api_key: str) -> BaseLlm:
    from google.adk.models.google_llm import Gemini
    from google.genai import Client

    return Gemini(model=model, client=Client(api_key=api_key))


def content_config(model: str) -> types.GenerateContentConfig:
    return types.GenerateContentConfig(
        thinking_config=None if "pro" in model.lower() else types.ThinkingConfig(thinking_budget=0),
    )


class ScriptedLlm(BaseLlm):
    """Plays a fixed script; records every request it was sent (what the model saw)."""

    model: str = "scripted"
    _script: list[Any] = PrivateAttr(default_factory=list)
    _error: BaseException | None = PrivateAttr(default=None)
    requests: list[LlmRequest] = []

    def __init__(self, script: list[Any], *, error: BaseException | None = None) -> None:
        super().__init__(model="scripted")
        self._script = list(script)
        self._error = error
        self.requests = []

    def load(self, script: list[Any]) -> None:
        """The steps of the next message (a replay sets them per turn)."""
        self._script = list(script)

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        self.requests.append(llm_request.model_copy(deep=True))
        if self._error is not None:
            raise self._error
        step = self._script.pop(0) if self._script else ""
        if isinstance(step, str):
            parts = [types.Part(text=step)] if step else []
        else:
            parts = [types.Part(function_call=types.FunctionCall(name=n, args=dict(a))) for n, a in step]
        yield LlmResponse(content=types.Content(role="model", parts=parts), turn_complete=True)

    def seen_texts(self, request_index: int = -1) -> list[tuple[str, str]]:
        """``(role, text)`` of every text part of one request (what the model was shown)."""
        req = self.requests[request_index]
        return [(c.role or "", p.text) for c in req.contents for p in (c.parts or []) if p.text]


#: The message being answered, for the usage ledger (set by AdkAgent.run for its run).
current_correlation_id: ContextVar[str | None] = ContextVar("adk_correlation_id", default=None)


class ResolvedGemini(BaseLlm):
    """Production's model for ADK: the control panel's ``agent_v2`` route (else ``agent``) and the
    Gemini key Mesiri has, read through ``DynamicAIProviderResolver`` on every call (a route or key
    changed in the control panel takes effect within its 5-minute cache, as for every other call).
    Each call is reported to the usage ledger like the provider loop's (costs page)."""

    model: str = "resolved"
    _resolver: Any = PrivateAttr(default=None)
    _capability: str = PrivateAttr(default="agent_v2")
    _cache: dict[tuple[str, str], Any] = PrivateAttr(default_factory=dict)

    def __init__(self, resolver: Any, *, capability: str = "agent_v2") -> None:
        super().__init__(model="resolved")
        self._resolver = resolver
        self._capability = capability
        self._cache = {}

    async def _inner(self) -> tuple[BaseLlm, str]:
        from mesiri_contracts.common.errors import MesiriError

        config = await self._resolver._resolve_config()
        routing = config.get("routing", {})
        route = routing.get(self._capability) or routing.get("agent") or {}
        key = config.get("secrets", {}).get("gemini", {}).get("api_key")
        if (route.get("provider_id") or "gemini") != "gemini" or not key:
            raise MesiriError.configuration("No tool-calling provider configured (v2 needs Gemini)", code="CONFIG_MISSING")
        model = route.get("model") or self._resolver._settings.gemini.model
        if (model, key) not in self._cache:
            self._cache[(model, key)] = gemini(model, key)
        return self._cache[(model, key)], model

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        import time

        from mesiri_ai import usage

        inner, model = await self._inner()
        llm_request.model = model
        if llm_request.config is not None:
            # Thinking off for Flash (speed), the model's default for Pro (it cannot be off).
            llm_request.config.thinking_config = content_config(model).thinking_config
        started = time.perf_counter()
        last: LlmResponse | None = None
        async for response in inner.generate_content_async(llm_request, stream):
            last = response
            yield response
        usage.report(
            usage.ProviderUsage(
                provider="gemini",
                operation="run_tools",
                model=model,
                correlation_id=current_correlation_id.get(),
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
                **usage.gemini_usage(last),
            )
        )
