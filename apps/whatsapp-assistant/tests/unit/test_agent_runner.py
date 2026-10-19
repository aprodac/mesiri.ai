"""Request [40]: the agent loop -- limits, the one reply, and the failure policy."""

from __future__ import annotations

from datetime import datetime

import pytest

from channel.replies import ReplySpec
from mesiri_ai.fakes import FakeToolCallingProvider
from mesiri_contracts.common.errors import MesiriError
from runtime.agent import runner as r
from runtime.agent.gateway import StepResult
from runtime.agent.prompt import AgentContext, Turn, build_messages, render_context
from runtime.agent.tools import ScopeLookup

CTX = AgentContext(
    user_name="Anil",
    role="SUPERVISOR",
    company="Acme Builders",
    now=datetime(2026, 10, 19, 9, 30),
    projects=(("Project Alpha", "Kochi"),),
    sites=(("Site A1", "Project Alpha"),),
)
WORKERS = [{"trade": "mason", "headcount": 3}]


class Gateway:
    def __init__(self, *results):
        self.results = list(results)

    async def run(self, candidate, *, text):
        return self.results.pop(0)

    async def undo_latest_draft(self):
        return self.results.pop(0)

    async def finish(self):
        return None


async def _run(provider, *results, ctx=CTX, text="3 masons today"):
    return await r.AgentRunner(provider).run(
        ctx=ctx, user_text=text, gateway=Gateway(*results), scope=ScopeLookup()
    )


async def test_a_saved_note_gets_the_models_one_message_with_the_undo_line():
    provider = FakeToolCallingProvider([[("save_labour", {"workers": WORKERS})], "✅ 3 masons saved."])
    result = await _run(provider, StepResult("saved", text="Labour recorded"))
    assert result.outcome == "ok"
    assert result.reply.text == "✅ 3 masons saved.\n\nWrong? Reply UNDO."
    assert provider.calls == 1  # one model run, not one per part


async def test_one_recorded_line_per_thing_becomes_one_header_and_bullets():
    """B-9, the live reply of 19 Oct."""
    provider = FakeToolCallingProvider(
        [
            [("save_labour", {"workers": WORKERS}), ("save_material_usage", {}), ("save_work", {})],
            "Recorded 12 masons present today.\nRecorded 5 bags of cement used for slab work today."
            "\nRecorded slab work on 2nd floor today.",
        ]
    )
    result = await _run(
        provider, StepResult("saved", text="a"), StepResult("saved", text="b"), StepResult("saved", text="c")
    )
    assert result.reply.text == (
        "✅ Saved:\n• 12 masons present\n• 5 bags of cement used for slab work\n"
        "• Slab work on 2nd floor\n\nWrong? Reply UNDO."
    )


@pytest.mark.parametrize(
    "text",
    [
        "✅ Saved: 12 masons",  # one thing: as written
        "✅ Saved:\n• 12 masons\n• 5 bags cement used",  # already a list
        "6 mason, 3 helper വന്നത് സേവ് ചെയ്തു.\n10 bag cement ഉപയോഗിച്ചത് സേവ് ചെയ്തു.",
        "Saved. Wrong? Reply UNDO.",
        "Recorded. Thank you.",
    ],
)
def test_other_replies_are_left_as_written(text):
    assert r.saved_list(text) == text


def test_saved_and_recorded_lines_mix_and_other_lines_stay():
    text = "Recorded: Tiling done.\nSaved 4 masons and 2 helpers for today.\nGenerator noted as an issue."
    assert r.saved_list(text) == (
        "✅ Saved:\n• Tiling done\n• 4 masons and 2 helpers\nGenerator noted as an issue."
    )


async def test_an_undo_line_the_model_already_wrote_is_not_doubled():
    provider = FakeToolCallingProvider([[("save_labour", {"workers": WORKERS})], "Saved. Wrong? Reply UNDO."])
    result = await _run(provider, StepResult("saved", text="x"))
    assert result.reply.text.count("UNDO") == 1


async def test_a_pure_answer_has_no_undo_line():
    provider = FakeToolCallingProvider([[("query_labour", {})], "12 workers today."])
    result = await _run(provider, StepResult("answer", text="12"))
    assert result.reply.text == "12 workers today."


async def test_the_loop_is_bounded_to_three_steps_and_twenty_five_seconds():
    seen = {}

    class Spy(FakeToolCallingProvider):
        async def run_tools(self, *a, **kw):
            seen.update(kw)
            return await super().run_tools(*a, **kw)

    await _run(Spy(["hello"]))
    assert seen["max_steps"] == 3
    assert seen["timeout_seconds"] == 25.0


async def test_a_question_keeps_its_buttons_and_the_model_wording():
    provider = FakeToolCallingProvider(
        [[("ask_user", {"question": "Which site?", "options": ["Site A1", "Site A2"]})],
         "ഏത് സൈറ്റ്? Site A1 / Site A2 ?"]
    )
    result = await _run(provider)
    assert [b.title for b in result.reply.buttons] == ["Site A1", "Site A2"]
    assert result.reply.text.startswith("ഏത് സൈറ്റ്")


async def test_a_question_the_model_forgot_to_write_is_added():
    provider = FakeToolCallingProvider([[("ask_user", {"question": "Which site?"})], "Okay"])
    result = await _run(provider)
    assert "Which site?" in result.reply.text


async def test_saved_parts_and_a_gate_question_share_one_message():
    gate = StepResult("needs_answer", text="Which material?", reply=ReplySpec(text="Which material?"))
    provider = FakeToolCallingProvider(
        [[("save_labour", {"workers": WORKERS}), ("save_material_usage", {"material": "x", "quantity": 1, "unit": "u"})],
         "✅ Labour saved. Which material?"]
    )
    result = await _run(provider, StepResult("saved", text="Labour recorded"), gate)
    assert result.reply.text.count("Which material?") == 1
    assert result.saved_count == 1
    assert "UNDO" in result.reply.text


async def test_no_text_from_the_model_falls_back_to_the_pipelines_own_words():
    provider = FakeToolCallingProvider([[("save_labour", {"workers": WORKERS})], ""])
    result = await _run(provider, StepResult("saved", text="Labour recorded"))
    assert "Labour recorded" in result.reply.text


async def test_a_failure_before_anything_was_tried_is_an_outage_to_retry():
    err = MesiriError.configuration("down", code="PROVIDER_UNAVAILABLE")
    result = await _run(FakeToolCallingProvider([], error=err))
    assert result.outcome == "outage" and result.reply is None
    assert result.error is err


async def test_a_failure_after_a_save_is_never_retried_and_says_what_is_saved():
    class FailsAfterSave(FakeToolCallingProvider):
        async def run_tools(self, system_prompt, messages, tools, handler, **kw):
            await handler("save_labour", {"workers": WORKERS})
            raise RuntimeError("model went away")

    result = await _run(FailsAfterSave([]), StepResult("saved", text="Labour recorded"))
    assert result.outcome == "degraded"
    assert "Labour recorded" in result.reply.text
    assert "check what is saved" in result.reply.text


async def test_a_failure_while_a_save_was_in_flight_counts_as_attempted():
    class CutOff(FakeToolCallingProvider):
        async def run_tools(self, system_prompt, messages, tools, handler, **kw):
            import asyncio

            task = asyncio.ensure_future(handler("save_labour", {"workers": WORKERS}))
            await asyncio.sleep(0)
            task.cancel()
            raise TimeoutError

    result = await _run(CutOff([]), StepResult("saved", text="Labour recorded"))
    assert result.outcome == "degraded"


def test_the_context_names_the_sender_the_day_and_the_single_site():
    text = render_context(CTX)
    assert "Anil (SUPERVISOR) at Acme Builders" in text
    assert "Monday 19 October 2026" in text
    assert "never ask which site" in text


def test_recent_turns_come_before_the_new_message_with_alternating_roles():
    ctx = AgentContext(
        user_name="A",
        role="R",
        company="C",
        now=datetime(2026, 10, 19, 9, 0),
        turns=(Turn("2 painters", "Saved 2 painters"),),
    )
    messages = build_messages(ctx, "and 10 more")
    assert [role for role, _ in messages] == ["user", "model", "user", "model", "user"]
    assert messages[-1][1].endswith("and 10 more")


def test_no_history_means_one_user_message():
    assert len(build_messages(CTX, "hi")) == 1


@pytest.mark.parametrize(
    "needle",
    ["this user's own company", "Wrong? Reply UNDO", "ONE short question", "Never invent"],
)
def test_the_rules_are_in_the_system_prompt(needle):
    from runtime.agent.prompt import SYSTEM_PROMPT

    assert needle in SYSTEM_PROMPT
