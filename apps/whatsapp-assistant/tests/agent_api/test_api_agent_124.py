"""WA-124: v3 faster, fewer taps, remembers three days.

- facts up front: the sender's projects and sites (one site: "never ask which site") and the
  company's materials and units are in the model's instructions before it runs;
- one tap: a question asked with ``ask`` comes with its options as buttons; tapping one is the answer;
- a bill photo: read by the vision step, the expense prepared, the photo attached by the code
  (the model never sees or sends the photo key);
- memory: today in full and the two days before, each marked with its day; written after the send;
- the instructions say "ready" (never "recorded") and "their script".
"""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import Depends, FastAPI
from pydantic import BaseModel
from tests.agent_api.standin import (
    ACTOR,
    ORG,
    PROJECT,
    SITE,
    STAND_IN_TOOLS,
    USER,
    stand_in_api,
    two_receipts_model,
)

from agent_api import whatsapp as wa
from agent_api.agent import ASK, SOP, ApiAgent
from agent_api.client import ApiClient
from agent_api.memory import DayMemory
from agent_api.tools import CONFIRM_ARG, Allowed, build_tools
from channel.replies import ReplySpec
from mesiri.domains.shared.auth import get_current_user
from mesiri.infrastructure.redis.client import FakeRedis
from mesiri_ai.fakes import FakeToolCallingProvider
from mesiri_contracts.assistant.enums import InputModality
from mesiri_contracts.assistant.normalized_message import (
    MediaReference,
    NormalizedMessage,
    SenderInfo,
)

CTX = SimpleNamespace(
    user_id=USER, organization_id=ORG, role="SITE_SUPERVISOR", full_name="Ravi", timezone="Asia/Kolkata",
    projects=[SimpleNamespace(id=PROJECT, name="Green Villa")],
    sites=[SimpleNamespace(id=SITE, name="Main block", project_id=PROJECT)],
)


def _message(text: str | None = "hi", modality=InputModality.TEXT, tap: str | None = None, key: str | None = None):
    return NormalizedMessage(
        message_id=f"wamid.{uuid.uuid4().hex[:6]}",
        sender=SenderInfo(wa_id="919876543210", profile_name="Ravi"),
        timestamp=dt.datetime(2026, 11, 1, 6, tzinfo=dt.UTC),
        modality=InputModality.INTERACTIVE if tap else modality, text=text,
        metadata={"interactive_reply_id": tap} if tap else {},
        media=MediaReference(media_id="m1", mime_type="image/jpeg", object_key=key) if key else None,
    )


@pytest.fixture(autouse=True)
def _stand_in_tools(monkeypatch):
    from agent_api import tools as tools_mod

    real = tools_mod.build_tools
    monkeypatch.setattr(wa, "build_tools", lambda openapi: real(
        openapi, tuple(a for a in tools_mod.ALLOWED if a.name in STAND_IN_TOOLS)))


def _service(model: Any, *, app: Any = None, describe: Any = None, sessions: Any = None):  # noqa: ANN202
    sent: list[ReplySpec] = []

    async def send(spec: ReplySpec, wa_id: str) -> None:
        sent.append(spec)

    service = wa.ApiWhatsApp(provider=model, database=None, redis=FakeRedis(), send=send, transcribe=None,
                             message_logger=AsyncMock(), app=app or stand_in_api([]), describe=describe,
                             sessions=sessions)
    return service, sent


# -- facts up front --------------------------------------------------------------------------


async def test_the_model_starts_with_the_sites_the_materials_and_the_units() -> None:
    model = FakeToolCallingProvider(["Hello Ravi."])
    service, _ = _service(model)
    await service.handle(_message("good morning"), CTX)
    prompt = model.last_system_prompt
    assert f"project Green Villa (project_id {PROJECT})" in prompt
    assert f"site Main block (site_id {SITE})" in prompt
    assert "Only one site: Main block. Use it; never ask which site." in prompt
    assert "Units (unit_id): bag" in prompt and "Materials (material_id, default unit):" in prompt


async def test_the_catalog_is_read_once_per_company_for_a_while() -> None:
    seen: list = []
    service, _ = _service(FakeToolCallingProvider(["a"]), app=stand_in_api(seen))
    await service.handle(_message("one"), CTX)
    service._agent._provider = FakeToolCallingProvider(["b"])
    await service.handle(_message("two"), CTX)
    catalog_reads = [p for m, p, *_ in seen if p.startswith("/materials")]
    assert len(catalog_reads) == 2  # materials + units, once for both messages


# -- one tap ---------------------------------------------------------------------------------


async def test_a_question_comes_with_its_options_as_buttons_and_a_tap_answers_it() -> None:
    model = FakeToolCallingProvider([
        [(ASK, {"question": "Which material are the rods?", "options": ["steel", "metal"]})],
        "Which material are the rods?",
    ])
    service, sent = _service(model)
    await service.handle(_message("50 rods vannu"), CTX)
    assert [b.title for b in sent[-1].buttons] == ["steel", "metal"]
    tap = sent[-1].buttons[0]
    answer = FakeToolCallingProvider(["Steel it is."])
    service._agent._provider = answer
    await service.handle(_message("steel", tap=tap.id), CTX)
    assert answer.last_messages[-1].text == "steel"


async def test_without_a_question_the_list_has_one_save_button() -> None:
    service, sent = _service(two_receipts_model())
    await service.handle(_message("50 bag cement and 50 TMT"), CTX)
    assert [b.title for b in sent[-1].buttons] == ["Save", "Cancel"]


# -- a bill photo ----------------------------------------------------------------------------


class _Expense(BaseModel):
    project_id: uuid.UUID
    amount: float
    occurred_date: str
    vendor_text: str | None = None
    source: str = "web"
    media_object_key: str | None = None


def _expense_api(posted: list[dict]) -> FastAPI:
    app = stand_in_api([])

    @app.post("/expenses")
    async def record(body: _Expense, jwt: dict = Depends(get_current_user)):
        posted.append(body.model_dump())
        return {"id": str(uuid.uuid4())}

    return app


async def test_a_bill_photo_becomes_one_expense_with_the_photo_attached_by_the_code() -> None:
    posted: list[dict] = []
    app = _expense_api(posted)
    expense = Allowed("record_expense", "POST", "/expenses", "Prepare an expense.",
                      hide=("source", "media_object_key"), fixed=(("source", "whatsapp"),))
    tools = build_tools(app.openapi(), (expense,))
    assert "media_object_key" not in tools["record_expense"].spec.parameters["properties"]
    model = FakeToolCallingProvider([
        [("record_expense", {"project_id": PROJECT, "amount": 1840, "occurred_date": "2026-11-01",
                             "vendor_text": "Sri Hardwares", CONFIRM_ARG: "₹1,840 Sri Hardwares bill"})],
        "Bill of ₹1,840 from Sri Hardwares is ready. Tap Save.",
    ])
    client = ApiClient(ACTOR, app=app)
    try:
        turn = await ApiAgent(model, tools).run(client, "(sent a photo)\nWhat the photo shows: bill ₹1,840",
                                                photo_key="media/wamid.x/m1")
        assert posted == []  # nothing before Save
        from agent_api.agent import confirm

        await confirm(client, turn.pending)
    finally:
        await client.close()
    assert posted[0]["media_object_key"] == "media/wamid.x/m1" and posted[0]["source"] == "whatsapp"


async def test_a_photo_is_read_first_and_the_model_gets_what_it_shows() -> None:
    model = FakeToolCallingProvider(["Bill of ₹1,840 is ready."])

    async def describe(message: Any, hint: str | None = None) -> str:
        return "A hardware bill: Sri Hardwares, ₹1,840, 1 Nov 2026"

    service, sent = _service(model, describe=describe)
    assert await service.handle(_message("bill", modality=InputModality.IMAGE, key="media/w/1"), CTX)
    said = model.last_messages[-1].text
    assert said.startswith("(sent a photo: bill)") and "Sri Hardwares, ₹1,840" in said


async def test_an_unreadable_photo_is_said_plainly() -> None:
    async def describe(message: Any, hint: str | None = None) -> None:
        return None

    model = FakeToolCallingProvider(["x"])
    service, sent = _service(model, describe=describe)
    await service.handle(_message(None, modality=InputModality.IMAGE, key="media/w/2"), CTX)
    assert sent[-1].text == wa.COULD_NOT_READ and model.calls == 0


# -- memory: today and the two days before ---------------------------------------------------


async def test_today_and_the_two_days_before_are_remembered_each_marked() -> None:
    redis = FakeRedis()
    memory = DayMemory(None, redis)
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=5, minutes=30))).date()
    for back, said in ((3, "four days ago"), (2, "two days ago: 40 bag cement"), (1, "yesterday: 6 masons"),
                       (0, "today: hi")):
        day = today - dt.timedelta(days=back)
        await redis.set_json(memory._redis_key(CTX, day), [{"role": "user", "text": said},
                                                            {"role": "model", "text": "ok"}])
    texts = [m.text for m in await memory.load(CTX)]
    assert "four days ago" not in texts
    assert texts.index("two days ago: 40 bag cement") < texts.index("yesterday: 6 masons") < texts.index("today: hi")
    assert any(t.startswith("(conversation of") for t in texts) and any(t.startswith("(today,") for t in texts)


async def test_a_turn_is_remembered_after_the_reply_is_sent() -> None:
    order: list[str] = []
    service, _ = _service(FakeToolCallingProvider(["Hello."]))

    async def send(spec: ReplySpec, wa_id: str) -> None:
        order.append("sent")

    real = service._memory.remember

    async def remember(ctx: Any, said: str, sent_text: str) -> None:
        order.append("remembered")
        await real(ctx, said, sent_text)

    service._send = send
    service._memory.remember = remember  # type: ignore[method-assign]
    await service.handle(_message("good morning"), CTX)
    assert order == ["sent", "remembered"]
    texts = [m.text for m in await service._memory.load(CTX)]
    assert texts == ["good morning", "Hello."]


async def test_the_day_store_is_used_when_it_is_there() -> None:
    pytest.importorskip("google.adk")
    from google.adk.sessions import InMemorySessionService

    sessions = InMemorySessionService()
    memory = DayMemory(sessions, FakeRedis())
    await memory.remember(CTX, "50 bag cement vannu", "Ready: 50 bags cement.")
    texts = [m.text for m in await memory.load(CTX)]
    assert texts == ["50 bag cement vannu", "Ready: 50 bags cement."]


# -- the instructions ------------------------------------------------------------------------


def test_the_instructions_say_ready_never_recorded_and_their_script() -> None:
    assert "fewest taps" in SOP
    assert "njan record cheythu" in SOP and "Never say saved, recorded" in SOP
    assert "their script" in SOP and "Manglish in Latin letters gets Manglish in Latin" in SOP
    assert "never ask \"is this a bill?\"" in SOP


async def test_a_provider_without_the_capability_setting_still_runs() -> None:
    """Compare run of 1 Nov: v3 sent capability= to the plain Gemini provider -> TypeError on every
    message. The router takes it (the control-panel row); a single provider does not."""
    class Plain:
        def __init__(self) -> None:
            self.kw: dict = {}

        async def run_tools(self, system_prompt, messages, tools, handler, *, max_steps=3,  # noqa: ANN001
                            timeout_seconds=None, correlation_id=None):
            from mesiri_ai.models import ToolRunResult

            return ToolRunResult(text="Hello.")

    class Router(Plain):
        async def run_tools(self, system_prompt, messages, tools, handler, **kw):  # noqa: ANN001, ANN003
            self.kw = kw
            return await super().run_tools(system_prompt, messages, tools, handler)

    for provider in (Plain(), Router()):
        client = ApiClient(ACTOR, app=stand_in_api([]))
        try:
            turn = await ApiAgent(provider, {}, capability="api_agent").run(client, "hi")
        finally:
            await client.close()
        assert turn.reply == "Hello."
    assert provider.kw.get("capability") == "api_agent"


# -- compare run of 1 Nov 19:41 (gemini-2.5-flash / 3.6-flash): the fixes ---------------------


@pytest.mark.parametrize(("said", "told"), [
    ("inn 50 bag cement vannu, 20 bag use cheythu", "Manglish (Malayalam words in Latin letters"),
    ("plastering 180 sqm done on first floor east side", "This message is in English."),
])
async def test_the_code_tells_the_model_the_language_and_script(said: str, told: str) -> None:
    model = FakeToolCallingProvider(["ok"])
    service, _ = _service(model)
    await service.handle(_message(said), CTX)
    assert told in model.last_system_prompt


async def test_a_model_error_before_anything_was_done_is_tried_once_more() -> None:
    class Flaky:
        calls = 0

        async def run_tools(self, *a: Any, **k: Any):  # noqa: ANN204
            from mesiri_ai.models import ToolRunResult

            Flaky.calls += 1
            if Flaky.calls == 1:
                raise RuntimeError("malformed function call")
            return ToolRunResult(text="Ready.")

    client = ApiClient(ACTOR, app=stand_in_api([]))
    try:
        turn = await ApiAgent(Flaky(), {}).run(client, "tea 450")
    finally:
        await client.close()
    assert turn.reply == "Ready." and Flaky.calls == 2


async def test_no_words_after_a_lookup_gets_one_more_ask_for_the_answer() -> None:
    model = FakeToolCallingProvider([[("list_projects", {})], ""])
    service, sent = _service(model)
    answered = FakeToolCallingProvider(["Cement stock is 0 at Main block."])

    class Two:
        n = 0

        async def run_tools(self, *a: Any, **k: Any):  # noqa: ANN204
            Two.n += 1
            return await (model if Two.n == 1 else answered).run_tools(*a, **k)

    service._agent._provider = Two()
    await service.handle(_message("cement stock ethra und?"), CTX)
    assert sent[-1].text == "Cement stock is 0 at Main block."
    assert answered.last_messages[-1].text == "(answer my message now, in words)"


async def test_double_star_bold_is_whatsapp_bold() -> None:
    service, sent = _service(FakeToolCallingProvider(["All **done** below."]))
    await service.handle(_message("hi"), CTX)
    assert sent[-1].text == "All *done* below."
