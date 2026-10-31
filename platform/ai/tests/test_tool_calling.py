"""Tool calling (request [40]): the fake model, the Gemini adapter against a
scripted SDK client, and the resolver's routing."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from mesiri_ai.adapters.gemini.adapter import GeminiProvider
from mesiri_ai.fakes import FakeToolCallingProvider
from mesiri_ai.models import ChatMessage, ToolOutcome, ToolSpec
from mesiri_ai.ports.tool_calling import ToolCallingProvider
from mesiri_contracts.common.errors import MesiriError

TOOLS = [
    ToolSpec(
        name="save_labour",
        description="Save labour",
        parameters={"type": "object", "properties": {"count": {"type": "integer"}}},
    ),
    ToolSpec(name="ask_user", description="Ask", parameters={"type": "object", "properties": {}}),
]
MESSAGES = [ChatMessage(role="user", text="10 masons today")]


async def _echo(name: str, args: dict) -> ToolOutcome:
    return ToolOutcome(content={"saved": args}, stop=name == "ask_user")


def test_fake_satisfies_the_port() -> None:
    assert isinstance(FakeToolCallingProvider([]), ToolCallingProvider)


async def test_fake_runs_calls_then_answers() -> None:
    fake = FakeToolCallingProvider([[("save_labour", {"count": 10})], "Saved 10 masons."])
    result = await fake.run_tools("sys", MESSAGES, TOOLS, _echo)
    assert result.text == "Saved 10 masons."
    assert [c.name for c in result.calls] == ["save_labour"]
    assert result.steps == 1
    assert result.stop_reason == "answered"


async def test_fake_stops_when_a_tool_parks_the_conversation() -> None:
    fake = FakeToolCallingProvider([[("ask_user", {})], "never sent"])
    result = await fake.run_tools("sys", MESSAGES, TOOLS, _echo)
    assert result.stop_reason == "stopped_by_tool"
    assert result.text == ""


async def test_fake_respects_max_steps() -> None:
    fake = FakeToolCallingProvider([[("save_labour", {})]] * 5)
    result = await fake.run_tools("sys", MESSAGES, TOOLS, _echo, max_steps=2)
    assert result.steps == 2
    assert result.stop_reason == "max_steps"


# --- Gemini adapter, against a scripted SDK client -----------------------------


class _Models:
    def __init__(self, responses: list, delay: float = 0.0) -> None:
        self._responses = list(responses)
        self.requests: list[dict] = []
        self._delay = delay

    async def generate_content(self, **kwargs):
        self.requests.append(kwargs)
        if self._delay:
            await asyncio.sleep(self._delay)
        return self._responses.pop(0)


def _provider(responses: list, delay: float = 0.0) -> tuple[GeminiProvider, _Models]:
    from mesiri.bootstrap.settings import GeminiSettings

    provider = GeminiProvider(
        GeminiSettings(api_key=SecretStr("k"), model="gemini-test", timeout_seconds=5, max_retries=0)
    )
    models = _Models(responses, delay)
    provider._client = SimpleNamespace(aio=SimpleNamespace(models=models))
    return provider, models


def _call_response(*calls: tuple[str, dict]) -> SimpleNamespace:
    from google.genai import types

    parts = [types.Part(function_call=types.FunctionCall(name=n, args=a)) for n, a in calls]
    return SimpleNamespace(
        function_calls=[SimpleNamespace(name=n, args=a) for n, a in calls],
        text=None,
        candidates=[SimpleNamespace(content=types.Content(role="model", parts=parts))],
        usage_metadata=None,
    )


def _text_response(text: str) -> SimpleNamespace:
    return SimpleNamespace(function_calls=None, text=text, candidates=[], usage_metadata=None)


async def test_gemini_runs_the_tool_then_returns_the_models_answer() -> None:
    provider, models = _provider(
        [_call_response(("save_labour", {"count": 10})), _text_response("Saved.")]
    )
    result = await provider.run_tools("sys", MESSAGES, TOOLS, _echo)
    assert result.text == "Saved."
    assert result.calls[0].outcome.content == {"saved": {"count": 10}}
    assert result.stop_reason == "answered"
    # Second request carries the model's turn and the function response.
    second = models.requests[1]["contents"]
    assert [c.role for c in second] == ["user", "model", "user"]
    assert second[2].parts[0].function_response.name == "save_labour"


async def test_gemini_stops_on_a_parking_tool_without_another_model_call() -> None:
    provider, models = _provider([_call_response(("ask_user", {}))])
    result = await provider.run_tools("sys", MESSAGES, TOOLS, _echo)
    assert result.stop_reason == "stopped_by_tool"
    assert len(models.requests) == 1


async def test_gemini_takes_the_tools_away_after_max_steps() -> None:
    provider, models = _provider(
        [
            _call_response(("save_labour", {})),
            _call_response(("save_labour", {})),
            _text_response("Done."),
        ]
    )
    result = await provider.run_tools("sys", MESSAGES, TOOLS, _echo, max_steps=2)
    assert result.text == "Done."
    assert result.steps == 2
    assert models.requests[2]["config"].tools is None


async def test_gemini_reports_a_failing_tool_to_the_model_and_keeps_going() -> None:
    async def boom(name: str, args: dict) -> ToolOutcome:
        raise RuntimeError("db down")

    provider, _ = _provider([_call_response(("save_labour", {})), _text_response("Sorry.")])
    result = await provider.run_tools("sys", MESSAGES, TOOLS, boom)
    assert result.calls[0].error == "RuntimeError: db down"
    assert result.calls[0].outcome.content == {"error": "the tool failed"}
    assert result.text == "Sorry."


async def test_gemini_overall_deadline_raises_a_provider_timeout() -> None:
    provider, _ = _provider([_text_response("late")], delay=1.0)
    with pytest.raises(MesiriError) as info:
        await provider.run_tools("sys", MESSAGES, TOOLS, _echo, timeout_seconds=0.05)
    assert info.value.error_code == "PROVIDER_TIMEOUT"


# --- Resolver ------------------------------------------------------------------


def _resolver(routing: dict, *, gemini_key: str | None = "k"):
    from mesiri_ai.resolver import DynamicAIProviderResolver

    resolver = DynamicAIProviderResolver(
        db=None,
        redis_client=None,
        settings=SimpleNamespace(gemini=SimpleNamespace(model="gemini-flash")),
    )

    async def _config():
        return {"routing": routing, "secrets": {"gemini": {"api_key": gemini_key}}}

    resolver._resolve_config = _config  # type: ignore[method-assign]
    return resolver


async def test_resolver_uses_the_agent_route_model(monkeypatch) -> None:
    resolver = _resolver({"agent": {"provider_id": "gemini", "model": "gemini-pro"}})
    used: list[str] = []

    def _fake(config, model):
        used.append(model)
        return FakeToolCallingProvider(["ok"])

    monkeypatch.setattr(resolver, "_cached_gemini_provider", _fake)
    result = await resolver.run_tools("sys", MESSAGES, TOOLS, _echo)
    assert result.text == "ok"
    assert used == ["gemini-pro"]


async def test_a_caller_with_its_own_route_uses_it_else_the_agent_route(monkeypatch) -> None:
    """Request 178: the control panel's "agent_v2" route is v2's brain; unset, v2 uses "agent"."""
    both = _resolver(
        {
            "agent": {"provider_id": "gemini", "model": "flash"},
            "agent_v2": {"provider_id": "gemini", "model": "pro", "fallback_provider_id": "gemini", "fallback_model": "flash"},
        }
    )
    used: list[str] = []
    monkeypatch.setattr(both, "_cached_gemini_provider", lambda c, m: (used.append(m), FakeToolCallingProvider(["ok"]))[1])
    await both.run_tools("s", MESSAGES, TOOLS, _echo, capability="agent_v2")
    await both.run_tools("s", MESSAGES, TOOLS, _echo)  # today's agent is unchanged by the v2 route
    assert used == ["pro", "flash"]

    only_agent = _resolver({"agent": {"provider_id": "gemini", "model": "flash"}})
    used.clear()
    monkeypatch.setattr(only_agent, "_cached_gemini_provider", lambda c, m: (used.append(m), FakeToolCallingProvider(["ok"]))[1])
    await only_agent.run_tools("s", MESSAGES, TOOLS, _echo, capability="agent_v2")
    assert used == ["flash"]


async def test_resolver_defaults_to_the_standard_gemini_model(monkeypatch) -> None:
    resolver = _resolver({})
    used: list[str] = []
    monkeypatch.setattr(
        resolver,
        "_cached_gemini_provider",
        lambda c, m: (used.append(m), FakeToolCallingProvider(["ok"]))[1],
    )
    await resolver.run_tools("sys", MESSAGES, TOOLS, _echo)
    assert used == ["gemini-flash"]


async def test_resolver_refuses_when_no_gemini_key() -> None:
    with pytest.raises(MesiriError):
        await _resolver({}, gemini_key=None).run_tools("sys", MESSAGES, TOOLS, _echo)


async def test_resolver_retries_on_the_fallback_model_only_before_any_tool_ran(monkeypatch) -> None:
    from mesiri_contracts.common.errors import ErrorCode

    routing = {
        "agent": {
            "provider_id": "gemini",
            "model": "flash",
            "fallback_provider_id": "gemini",
            "fallback_model": "pro",
        }
    }
    err = MesiriError.configuration("x", code="CONFIG_MISSING")
    assert ErrorCode  # imported for clarity of intent

    # Fails before running any tool -> fallback is tried.
    resolver = _resolver(routing)
    seen: list[str] = []

    def _factory(config, model):
        seen.append(model)
        return FakeToolCallingProvider([], error=err) if model == "flash" else FakeToolCallingProvider(["ok"])

    monkeypatch.setattr(resolver, "_cached_gemini_provider", _factory)
    assert (await resolver.run_tools("s", MESSAGES, TOOLS, _echo)).text == "ok"
    assert seen == ["flash", "pro"]

    # Fails after a tool wrote -> never re-run.
    class _FailsAfterTool:
        async def run_tools(self, system_prompt, messages, tools, handler, **kw):
            await handler("save_labour", {})
            raise err

    resolver = _resolver(routing)
    seen.clear()
    monkeypatch.setattr(
        resolver, "_cached_gemini_provider", lambda c, m: (seen.append(m), _FailsAfterTool())[1]
    )
    with pytest.raises(MesiriError):
        await resolver.run_tools("s", MESSAGES, TOOLS, _echo)
    assert seen == ["flash"]


async def test_gemini_turns_thinking_off_on_flash_but_not_on_pro() -> None:
    flash, flash_models = _provider([_text_response("ok")])
    await flash.run_tools("sys", MESSAGES, TOOLS, _echo)
    assert flash_models.requests[0]["config"].thinking_config.thinking_budget == 0

    pro, pro_models = _provider([_text_response("ok")])
    pro._settings = pro._settings.model_copy(update={"model": "gemini-2.5-pro"})
    await pro.run_tools("sys", MESSAGES, TOOLS, _echo)
    assert pro_models.requests[0]["config"].thinking_config is None
