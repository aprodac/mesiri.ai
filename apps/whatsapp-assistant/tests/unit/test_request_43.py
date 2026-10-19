"""Request [43]: the agent on the 19 Oct live messages (replayed with a
Gemini-shaped tool-calling response), the daily team-photo limit and the
2-hour YES/NO expiry."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from channel.replies import ReplySpec
from interactions.team_photo_hint import TeamPhotoHintStore
from runtime.agent import runner as r
from runtime.agent.gateway import StepResult
from runtime.agent.journey_gateway import _without_menu
from runtime.agent.prompt import AgentContext
from runtime.agent.tools import ScopeLookup

CTX = AgentContext(
    user_name="Anil",
    role="SUPERVISOR",
    company="Mesiri Test Builders",
    now=datetime(2026, 10, 19, 13, 4),
    projects=(("Green Villa", "Kochi"),),
    sites=(("Green Villa", "Green Villa"),),
)
NOTE = (
    "Today at Green Villa: 10 masons and 4 helpers. Shuttering done for 3rd floor slab. "
    "Received 35 bags cement from Sharma Traders. Paid 1500 rupees for tractor."
)
MENU = (
    "Expenses and money isn't switched on for your company, so I can't record that."
    "\n\nHere's what I can help with:\n  • Materials — x\n\nAsk your admin if you need it."
)


class Gateway:
    def __init__(self, by_tool):
        self.by_tool = by_tool

    async def run(self, candidate, *, text):
        return self.by_tool[candidate.semantic_type.value]

    async def undo_latest_draft(self):
        return StepResult("info", text="nothing")

    async def finish(self):
        return None


def _gemini_four_part_response():
    """Shape of a real Gemini 2.5 Flash reply to the 4-part note: ONE turn
    carrying four parallel function calls, no text."""
    from google.genai import types

    calls = [
        ("save_labour", {"workers": [{"trade": "mason", "headcount": 10}, {"trade": "helper", "headcount": 4}]}),
        ("save_work_done", {"description": "Shuttering done for 3rd floor slab"}),
        ("save_material_receipt", {"items": [{"material": "cement", "quantity": 35, "unit": "bags"}], "vendor": "Sharma Traders"}),
        ("save_expense", {"amount": 1500, "description": "tractor"}),
    ]
    parts = [types.Part(function_call=types.FunctionCall(name=n, args=a)) for n, a in calls]
    return SimpleNamespace(
        function_calls=[SimpleNamespace(name=n, args=a) for n, a in calls],
        text=None,
        candidates=[SimpleNamespace(content=types.Content(role="model", parts=parts))],
        usage_metadata=None,
    )


def _gemini_text_response(text):
    return SimpleNamespace(function_calls=None, text=text, candidates=[], usage_metadata=None)


def _gemini_provider(responses):
    pytest.importorskip("google.genai")
    from pydantic import SecretStr

    from mesiri.bootstrap.settings import GeminiSettings
    from mesiri_ai.adapters.gemini.adapter import GeminiProvider

    provider = GeminiProvider(
        GeminiSettings(api_key=SecretStr("k"), model="gemini-test", timeout_seconds=5, max_retries=0)
    )
    queue = list(responses)

    async def generate_content(**kwargs):
        return queue.pop(0)

    provider._client = SimpleNamespace(
        aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    )
    return provider


async def _run(provider, gateway):
    return await r.AgentRunner(provider).run(
        ctx=CTX, user_text=NOTE, gateway=gateway, scope=ScopeLookup()
    )


async def test_four_part_note_gets_one_reply_never_the_classic_fallbacks():
    """Finding 1: the 4-part note must end in ONE message built from what was
    saved, not "couldn't make out"."""
    provider = _gemini_provider(
        [_gemini_four_part_response(), _gemini_text_response("✅ Saved labour, work, cement and the tractor expense.")]
    )
    gateway = Gateway(
        {
            "labour_attendance": StepResult("saved", text="Labour: 10 masons, 4 helpers"),
            "site_update": StepResult("saved", text="Work noted"),
            "material_receipt": StepResult("saved", text="35 bags cement"),
            "expense": StepResult("saved", text="Rs 1,500 tractor"),
        }
    )
    result = await _run(provider, gateway)
    assert result.outcome == "ok"
    assert "couldn't make out" not in result.reply.text
    assert result.reply.text.endswith("Wrong? Reply UNDO.")


async def test_gemini_returning_no_text_falls_back_to_what_was_saved():
    provider = _gemini_provider([_gemini_four_part_response(), _gemini_text_response("")])
    saved = StepResult("saved", text="Saved")
    gateway = Gateway(
        {k: saved for k in ("labour_attendance", "site_update", "material_receipt", "expense")}
    )
    result = await _run(provider, gateway)
    assert "couldn't make out" not in result.reply.text
    assert "Saved" in result.reply.text


async def test_switched_off_module_is_said_once_without_the_menu():
    """Finding 2: material saved, expenses off -> one short line, not the
    capability list twice."""
    assert "Here's what I can help with" not in _without_menu(MENU)
    assert _without_menu(MENU).startswith("Expenses and money isn't switched on")

    from mesiri_ai.fakes import FakeToolCallingProvider

    provider = FakeToolCallingProvider(
        [
            [("save_material_receipt", {"items": []}), ("save_expense", {"amount": 1500})],
            f"Cement saved.\n\n{_without_menu(MENU)}\n\n{_without_menu(MENU)}",
        ]
    )
    gateway = Gateway(
        {
            "material_receipt": StepResult("saved", text="35 bags cement"),
            "expense": StepResult("info", text=_without_menu(MENU)),
        }
    )
    result = await _run(provider, gateway)
    assert result.reply.text.count("isn't switched on") == 1
    assert "Here's what I can help with" not in result.reply.text


async def test_provider_failure_before_any_save_is_an_outage_not_a_menu():
    from mesiri_ai.fakes import FakeToolCallingProvider

    provider = FakeToolCallingProvider([RuntimeError("400 schema rejected")])
    result = await _run(provider, Gateway({}))
    assert result.outcome == "outage"
    assert result.reply is None


# -- team photo: once a day --------------------------------------------------


class _Redis:
    def __init__(self):
        self.data = {}

    def namespaced(self, *parts):
        return ":".join(parts)

    async def set_json(self, key, value, *, ttl_seconds=None):
        self.data[key] = value

    async def get_json(self, key):
        return self.data.get(key)


async def test_team_photo_is_offered_once_a_day():
    store = TeamPhotoHintStore(_Redis())
    assert await store.claim_daily_offer(user_id="u1", today="2026-10-19") is True
    assert await store.claim_daily_offer(user_id="u1", today="2026-10-19") is False
    assert await store.claim_daily_offer(user_id="u1", today="2026-10-20") is True
    assert await store.claim_daily_offer(user_id="u2", today="2026-10-19") is True


async def test_second_team_photo_offer_of_the_day_is_not_sent():
    from runtime.inbound_journey.seeding import _offer_team_photo

    store = TeamPhotoHintStore(_Redis())
    sent: list[ReplySpec] = []

    async def send(spec, wa_id):
        sent.append(spec)

    actor = SimpleNamespace(user_id="u1")
    await _offer_team_photo("rep-1", actor, "wa", store, send)
    await _offer_team_photo("rep-2", actor, "wa", store, send)
    assert len(sent) == 1
