"""WA-126: "mesiri bad ux" / "mesiri fix this" in v3 goes to the team bot, as in v2 (TM-18).

v3 offers the same ``tell_the_team`` tool as v2 (``agent_v2.skills.general.tools``: one
definition), its reply follows v2's feedback wording, it writes nothing, and the turn's trace
(``agent_api_turn``) carries the call with ``args``, the shape the production watch reads
(``teammate/brain/src/prod_watch.js``: stage agent_v2_live or agent_api_turn).
"""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from tests.agent_api.standin import ORG, PROJECT, SITE, STAND_IN_TOOLS, USER, stand_in_api

from agent_api import whatsapp as wa
from agent_v2.skills.general.tools import TELL_THE_TEAM
from channel.replies import ReplySpec
from mesiri.infrastructure.redis.client import FakeRedis
from mesiri_ai.fakes import FakeToolCallingProvider
from mesiri_contracts.assistant.enums import InputModality
from mesiri_contracts.assistant.normalized_message import NormalizedMessage, SenderInfo

CTX = SimpleNamespace(user_id=USER, organization_id=ORG, role="SITE_SUPERVISOR", full_name="Ravi",
                      timezone="Asia/Kolkata", projects=[SimpleNamespace(id=PROJECT, name="Green Villa")],
                      sites=[SimpleNamespace(id=SITE, name="Main block", project_id=PROJECT)])


@pytest.fixture(autouse=True)
def _stand_in_tools(monkeypatch):
    from agent_api import tools as tools_mod

    real = tools_mod.build_tools
    monkeypatch.setattr(wa, "build_tools", lambda openapi: real(
        openapi, tuple(a for a in tools_mod.ALLOWED if a.name in STAND_IN_TOOLS)))


def _message(text: str) -> NormalizedMessage:
    return NormalizedMessage(message_id=f"wamid.{uuid.uuid4().hex[:6]}", sender=SenderInfo(wa_id="919800000000"),
                             timestamp=dt.datetime(2026, 11, 2, 6, tzinfo=dt.UTC), modality=InputModality.TEXT,
                             text=text)


async def test_bad_ux_goes_to_the_team_with_the_trace_the_watch_reads() -> None:
    model = FakeToolCallingProvider([
        [(TELL_THE_TEAM, {"kind": "bad_ux", "about": "the ready list repeated twice in the stock reply"})],
        "Sorry about that. I've passed it to the team to fix. What was not good: the words, the buttons, or too long?",
    ])
    sent: list[ReplySpec] = []
    trace = AsyncMock()

    async def send(spec: ReplySpec, wa_id: str) -> None:
        sent.append(spec)

    service = wa.ApiWhatsApp(provider=model, database=None, redis=FakeRedis(), send=send, transcribe=None,
                             message_logger=AsyncMock(), trace_logger=trace, app=stand_in_api([]))
    await service.handle(_message("mesiri bad ux"), CTX)
    payload = trace.log_stage.await_args.kwargs
    assert payload["stage"] == "agent_api_turn"
    call = payload["stage_payload"]["calls"][0]
    assert call["tool"] == TELL_THE_TEAM and call["args"]["kind"] == "bad_ux"
    assert payload["stage_payload"]["pending"] == [] and not sent[-1].buttons
    assert "passed it to the team" in sent[-1].text


async def test_the_model_is_told_what_to_say_after_passing_it_on() -> None:
    seen: list = []

    def step(records):  # noqa: ANN001, ANN202
        seen.append(records[-1].outcome.content["status"])
        return "ok"

    model = FakeToolCallingProvider([[(TELL_THE_TEAM, {"kind": "missing_feature", "about": "add a member"})], step])
    service = wa.ApiWhatsApp(provider=model, database=None, redis=FakeRedis(), send=AsyncMock(), transcribe=None,
                             message_logger=AsyncMock(), app=stand_in_api([]))
    await service.handle(_message("mesiri add Suresh as supervisor"), CTX)
    assert seen and seen[0].startswith("Passed to the team.") and "cannot do this here yet" in seen[0]


def test_the_instructions_name_feedback() -> None:
    from agent_api.agent import SOP

    assert "mesiri bad ux" in SOP and "mesiri fix this" in SOP and "`tell_the_team`" in SOP
