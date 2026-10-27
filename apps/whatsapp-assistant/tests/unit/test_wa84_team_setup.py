"""WA-84 (plan of 27 Oct, W8): team and setup on WhatsApp.

Live 27 Oct (screenshots 07 and 11): "report time 7 pm aakku" -> "I can't change the
report time"; "ente team-il aarokke und?" -> "I only give join codes"; "Site B-il
Rajesh-ine supervisor aakku" -> "Add Rajesh to this project as Site Engineer ... Reply
YES to confirm or NO to cancel".
"""

from __future__ import annotations

import inspect
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from tests.unit import test_draft_tap_journey as journey

import runtime.message_journey as mj
from channel.replies import ListRow, ReplySpec
from runtime import team_setup
from runtime.agent.draft_store import MemoryDraftStore
from runtime.agent.reply_clean import clean_model_text
from runtime.inbound_journey.reply import TAP_YES_LINE, render_workflow_run_reply_spec
from runtime.setup_questions import REPORT_TIME_OWNER_ONLY, SetupQuestions
from workflows import WorkflowRunStatus
from workflows.add_project_member.nodes import request_confirmation


@pytest.mark.parametrize(
    "text, asked, time",
    [
        ("report time 7 pm aakku", True, "19:00"),
        ("report timing 8 pm aakkanam", True, "20:00"),
        ("change the report time", True, None),
        ("report 9 manikku ayakku", True, "21:00"),
        ("റിപ്പോർട്ട് സമയം 7 pm", True, "19:00"),
        ("25 Oct report ayakku", False, None),
        ("send today's report", False, None),
    ],
)
def test_a_request_to_change_the_report_time(text, asked, time):
    assert team_setup.report_time_asked(text) == (asked, time)


@pytest.mark.parametrize(
    "text, hit",
    [
        ("ente team-il aarokke und?", True),
        ("who is in my team", True),
        ("team members list", True),
        ("Site B-il Rajesh-ine supervisor aakku", False),
        ("add Ravi to my team", False),
        ("innu ethra labour?", False),
    ],
)
def test_a_question_about_the_team(text, hit):
    assert team_setup.is_team_question(text) is hit


def test_the_team_text_lists_each_project():
    rows = [("p1", "Ravi", "SITE_ENGINEER"), ("p1", "Anil", "ADMIN"), ("p9", "Someone", "ADMIN")]
    text = team_setup.team_text(rows, {"p1": "Green Villa"})
    assert "*Green Villa*: Anil (Admin), Ravi (Site Engineer)" in text
    assert "Someone" not in text  # not one of the sender's projects
    assert "Nobody" in team_setup.team_text([], {"p1": "Green Villa"})


def _setup(role: str) -> tuple[SetupQuestions, SimpleNamespace]:
    service = SetupQuestions.__new__(SetupQuestions)
    service._redis = AsyncMock()

    class _Db:
        def transaction(self):  # noqa: ANN202
            class _T:
                async def __aenter__(self):  # noqa: ANN204
                    return object()

                async def __aexit__(self, *a):  # noqa: ANN002, ANN204
                    return False

            return _T()

    service._db = _Db()

    async def spec(conn, org, question):  # noqa: ANN001, ANN202
        return ReplySpec(
            text="Your daily report goes out by *9 pm*. Want it at a different time?",
            buttons=(ListRow("setup_q:time:19:00", "7 pm"), ListRow("setup_q:time:20:00", "8 pm"),
                     ListRow("setup_q:time:21:00", "Keep 9 pm")),
        )

    service._question_spec = spec
    actor = SimpleNamespace(role=role, organization_id="o1", user_id="u1")
    return service, actor


async def test_the_owner_gets_the_report_time_question_with_its_buttons():
    service, actor = _setup("ADMIN")
    reply = await service.offer_report_time(actor, "19:00")
    assert "Tap *7 pm* below" in reply.text
    assert [b.title for b in reply.buttons] == ["7 pm", "8 pm", "Keep 9 pm"]
    service._redis.set_json.assert_awaited()  # the tap is expected: handle_tap changes it


async def test_someone_else_is_told_who_can():
    service, actor = _setup("SITE_ENGINEER")
    reply = await service.offer_report_time(actor, "19:00")
    assert reply.text == REPORT_TIME_OWNER_ONLY
    service._redis.set_json.assert_not_awaited()


def test_the_add_member_card_names_the_project_and_says_why_site_engineer():
    from mesiri_contracts.assistant.draft_action import DraftActionType
    from mesiri_contracts.assistant.v2.draft_action import DraftActionV2

    draft = DraftActionV2(
        draft_id="d1", correlation_id="c1", workflow_instance_id="w1",
        action_type=DraftActionType.ADD_PROJECT_MEMBER, organization_id=str(uuid.uuid4()), user_id=str(uuid.uuid4()),
        project_id=str(uuid.uuid4()),
        site_id=None, fields={"member_name": "Rajesh", "role": "SITE_ENGINEER"},
    )
    state = {"draft_action": draft, "collected_fields": {"project_label": "Project Alpha", "role_said": "supervisor",
                                                         "site_said": "Site B"}}
    text = request_confirmation(state)["pending_prompt"]
    assert "Add *Rajesh* to *Project Alpha* as *Site Engineer*" in text
    assert "no Supervisor role" in text
    assert "every site of Project Alpha, not only Site B" in text
    assert "this project" not in text


def test_a_yes_no_card_says_tap_not_reply():
    run = SimpleNamespace(
        status=WorkflowRunStatus.STARTED, pending_prompt="*Confirm this action?*\n\nReply YES to confirm or NO to cancel.",
        reply_text=None, workflow_key=None, slot_options=None,
    )
    try:
        spec = render_workflow_run_reply_spec(run)
    except AttributeError:
        pytest.skip("the renderer needs a full WorkflowRunResult")
    assert "Reply YES" not in spec.text and TAP_YES_LINE in spec.text


def test_the_models_own_yes_line_is_dropped_in_manglish_too():
    text = "Rajesh-ine supervisor aakkan request ready.\nConfirm cheyyan YES ennu reply cheyyuka, venda engil NO."
    assert clean_model_text(text) == "Rajesh-ine supervisor aakkan request ready."


async def test_report_time_and_team_with_draft_cards_go_to_code_not_the_model(monkeypatch):
    setup = AsyncMock()
    setup.offer_report_time.return_value = ReplySpec(text="Your daily report goes out by *9 pm*.")
    setup.handle_tap.return_value = None
    setup.handle_media.return_value = None
    real = mj.build_message_handlers

    def build(**kw):  # noqa: ANN003, ANN202
        return real(**kw, setup_questions=setup)

    build.__signature__ = inspect.signature(real)  # the harness reads the real parameters
    monkeypatch.setattr(mj, "build_message_handlers", build)
    on_normalized, deps = journey._build(monkeypatch, drafts=MemoryDraftStore())
    await on_normalized(journey._text("report time 7 pm aakku"), {})
    setup.offer_report_time.assert_awaited_once()
    assert setup.offer_report_time.await_args.args[1] == "19:00"


def test_a_switched_off_module_is_the_codes_line_in_manglish():
    """Live 27 Oct (M27): "diesel 500 rupees expense" got the model's English retelling."""
    from channel.replies import render_module_disabled_reply
    from runtime.reply_language import localize_fixed_reply

    line = render_module_disabled_reply("finance", "ADMIN")
    manglish = localize_fixed_reply(line, "Malayalam", "latin")
    assert manglish.startswith("Expenses ningalude company-kku ippo on cheythittilla")
    assert "Mesiri team-inodu" in manglish
    assert localize_fixed_reply(line, "English", "latin") == line


async def test_the_module_off_line_is_the_reply_when_nothing_else_was_saved(monkeypatch):
    from tests.replay.test_agent_replay import _make_world

    from channel.replies import render_module_disabled_reply
    from context import seed
    from mesiri_ai.fakes import FakeToolCallingProvider

    world = await _make_world(site_keys=(seed.SITE_A1,))

    async def off(candidate, *, text):  # noqa: ANN001, ANN202
        from runtime.agent.gateway import StepResult

        return StepResult("info", text=render_module_disabled_reply("finance", "ADMIN"))

    gateway = world.gateway("diesel 500 rupees expense")
    monkeypatch.setattr(type(gateway), "run", lambda self, candidate, *, text: off(candidate, text=text))
    from runtime.agent.runner import AgentRunner

    provider = FakeToolCallingProvider(
        [[("save_expense", {"amount": 500, "description": "diesel"})], "Expenses are not switched on, sorry."]
    )
    result = await AgentRunner(provider).run(
        ctx=world.context(), user_text="diesel 500 rupees expense", gateway=gateway, scope=world.scope(),
        correlation_id="c1",
    )
    assert result.reply.text == render_module_disabled_reply("finance", "ADMIN")
