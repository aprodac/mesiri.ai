"""WA-118 step 2 part B: who gets an answer on a call, and that a call cannot write."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from types import SimpleNamespace

import pytest

from agent_api import call as call_module
from agent_api.call import NOT_KNOWN, NOT_NOW, NOT_ON_CALLS, CallAnswers
from agent_api.tools import ApiTool
from agent_api.whatsapp import CALL_RULES
from ingress.call_answer import CallAnswerRefused, read_call_question
from mesiri_ai.models import ToolSpec

SECRET = "test-app-secret"
CALLER = "919000000001"


def signed(body: bytes, prefix: bytes = b"call-answer:") -> str:
    return "sha256=" + hmac.new(SECRET.encode(), prefix + body, hashlib.sha256).hexdigest()


def question(**changes) -> bytes:
    return json.dumps({"wa_id": CALLER, "text": "innu ethra per", "at": time.time(), **changes}).encode()


def read(body: bytes, signature: str | None, allowed: str = CALLER) -> tuple[str, str]:
    return read_call_question(body, signature, app_secret=SECRET, allowed=allowed)


def test_a_signed_fresh_question_from_a_listed_number_passes() -> None:
    body = question()
    assert read(body, signed(body)) == (CALLER, "innu ethra per")


def test_a_plus_in_the_list_still_matches() -> None:
    body = question()
    assert read(body, signed(body), allowed=f" +{CALLER} ")[0] == CALLER


@pytest.mark.parametrize("signature", [None, "sha256=bad", "nonsense"])
def test_a_bad_signature_is_refused(signature) -> None:
    with pytest.raises(CallAnswerRefused):
        read(question(), signature)


def test_a_meta_style_signature_is_refused() -> None:
    """A signature made for a webhook body must not work here."""
    body = question()
    with pytest.raises(CallAnswerRefused):
        read(body, signed(body, prefix=b""))


@pytest.mark.parametrize("change", [{"at": time.time() - 3600}, {"wa_id": "919111111111"}, {"text": "  "}])
def test_stale_unlisted_or_empty_is_refused(change) -> None:
    body = question(**change)
    with pytest.raises(CallAnswerRefused):
        read(body, signed(body))


def test_unsigned_junk_is_refused_before_it_is_read() -> None:
    with pytest.raises(CallAnswerRefused):
        read(b"not json", None)


def test_signed_junk_is_refused() -> None:
    with pytest.raises(CallAnswerRefused):
        read(b"not json", signed(b"not json"))


class Actors:
    def __init__(self, ctx) -> None:
        self.ctx = ctx

    async def resolve_by_whatsapp_id(self, _wa_id):
        return self.ctx


class Guard:
    def __init__(self, over: bool) -> None:
        self.over = over

    async def check(self, _org):
        return SimpleNamespace(over_cap=self.over)


class OrgSettings:
    def __init__(self, mode) -> None:
        self.mode = mode

    async def get(self, *, organization_id, key):
        return self.mode


class Agent:
    def __init__(self, words: str = "12 per", fail: bool = False) -> None:
        self.words = words
        self.fail = fail
        self.asked: list[str] = []

    async def on_call(self, text, _ctx, _correlation):
        self.asked.append(text)
        if self.fail:
            raise RuntimeError("model down")
        return self.words


def answers(ctx, *, mode="api", over=False, agent=None) -> CallAnswers:
    built = CallAnswers(provider=None, database=None, redis=None, sessions=None, actor_reader=Actors(ctx),
                        org_settings=OrgSettings(mode), usage_guard=Guard(over))
    built._api = agent or Agent()
    return built


def person(active: bool = True) -> SimpleNamespace:
    return SimpleNamespace(organization_id="00000000-0000-0000-0000-000000000001", org_active=active)


@pytest.fixture(autouse=True)
def no_tenant(monkeypatch):
    monkeypatch.setattr(call_module, "bind_tenant", lambda _org: None)


@pytest.mark.asyncio
async def test_a_known_caller_on_the_api_agent_gets_the_answer() -> None:
    agent = Agent()
    assert await answers(person(), agent=agent).answer(CALLER, "innu ethra per") == "12 per"
    assert agent.asked == ["innu ethra per"]


@pytest.mark.asyncio
async def test_an_unknown_number_reaches_no_agent() -> None:
    agent = Agent()
    assert await answers(None, agent=agent).answer(CALLER, "hello") == NOT_KNOWN
    assert agent.asked == []


@pytest.mark.parametrize("ctx_active,mode,over", [(False, "api", False), (True, "classic", False), (True, "api", True)])
@pytest.mark.asyncio
async def test_a_suspended_company_another_mode_or_the_cap_reaches_no_agent(ctx_active, mode, over) -> None:
    agent = Agent()
    assert await answers(person(ctx_active), mode=mode, over=over, agent=agent).answer(CALLER, "hello") == NOT_ON_CALLS
    assert agent.asked == []


@pytest.mark.asyncio
async def test_a_failure_or_an_empty_answer_is_still_a_sentence() -> None:
    assert await answers(person(), agent=Agent(fail=True)).answer(CALLER, "hello") == NOT_NOW
    assert await answers(person(), agent=Agent(words="")).answer(CALLER, "hello") == NOT_NOW


def tool(name: str, method: str) -> ApiTool:
    return ApiTool(name=name, method=method, path=f"/{name}", path_params=(), query_params=(), body_fields=(),
                   spec=ToolSpec(name=name, description=name, parameters={"type": "object", "properties": {}}))


def test_the_call_agent_has_no_tool_that_writes(monkeypatch) -> None:
    import agent_api.whatsapp as module

    tools = {"read": tool("read", "GET"), "post": tool("post", "POST"), "patch": tool("patch", "PATCH"),
             "delete": tool("delete", "DELETE")}
    monkeypatch.setattr(module, "build_tools", lambda _openapi: tools)
    built = module.ApiWhatsApp(provider=None, database=None, redis=None, send=None, transcribe=None,
                               message_logger=None, app=SimpleNamespace(openapi=lambda: {}))
    assert list(built._call_agent._tools) == ["read"]
    assert len(built._agent._tools) == 4
    assert CALL_RULES in built._call_agent._sop


async def post_question(client, body: bytes, signature: str):
    return await client.post("/webhook/call-answer", content=body, headers={"X-Hub-Signature-256": signature})


@pytest.mark.asyncio
async def test_the_route_does_not_exist_until_a_number_is_listed(client) -> None:
    body = question()
    assert (await post_question(client, body, signed(body))).status_code == 404


@pytest.mark.asyncio
async def test_the_route_refuses_and_answers(app, client, monkeypatch) -> None:
    container = app.state.container
    monkeypatch.setattr(container.settings, "call_answers_allowed", CALLER)

    class Answers:
        async def answer(self, wa_id, text):
            return f"{wa_id}: {text}"

    monkeypatch.setattr(container, "call_answers", Answers())
    body = question()
    assert (await post_question(client, body, "sha256=bad")).status_code == 403
    response = await post_question(client, body, signed(body))
    assert response.json() == {"text": f"{CALLER}: innu ethra per"}
