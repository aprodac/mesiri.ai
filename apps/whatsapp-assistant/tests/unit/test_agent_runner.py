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
    provider = FakeToolCallingProvider([[("save_labour", {"workers": WORKERS})], "Sheri, 3 masons. Check and tap Save."])
    result = await _run(provider, StepResult("saved", text="Labour recorded"))
    assert result.outcome == "ok"
    assert result.reply.text == "Sheri, 3 masons. Check and tap Save.\n\nWrong? Reply UNDO."
    assert provider.calls == 1  # one model run, not one per part


async def test_recorded_lines_the_model_wrote_are_dropped_before_save():
    """B-9's "Recorded 12 masons present today." lines (19 Oct) say it is kept
    before the Save tap; WA-37 drops them instead of listing them."""
    provider = FakeToolCallingProvider(
        [
            [("save_labour", {"workers": WORKERS}), ("save_material_usage", {})],
            "Recorded 12 masons present today.\nRecorded 5 bags of cement used for slab work today."
            "\nCheck it and tap Save.",
        ]
    )
    result = await _run(
        provider,
        StepResult("saved", text="a", summary="12 workers (12 mason)"),
        StepResult("saved", text="b", summary="Cement used: 5 bags (slab)"),
        text="12 mason, 5 bag cement slab",
    )
    assert "Recorded" not in result.reply.text
    assert result.reply.text.startswith("Check it and tap Save.\n\n✅ Saved:\n• 12 workers (12 mason)")


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
    assert messages[-1][1].startswith("User message:\nand 10 more")


def test_no_history_means_one_user_message():
    assert len(build_messages(CTX, "hi")) == 1


@pytest.mark.parametrize(
    "needle",
    ["this user's own company", "tap Save", "ONE short question", "Never add, subtract or estimate"],
)
def test_the_rules_are_in_the_system_prompt(needle):
    from runtime.agent.prompt import SYSTEM_PROMPT

    assert needle in SYSTEM_PROMPT


# -- WA-37: the model writes every reply ------------------------------------------


async def test_a_note_that_only_saves_still_gets_the_models_words_over_the_saved_line():
    provider = FakeToolCallingProvider(
        [
            [("save_labour", {"workers": WORKERS}), ("save_material_usage", {})],
            "Sheri, 3 mason and 5 bag cement. Check and tap Save.",
        ]
    )
    result = await _run(
        provider,
        StepResult("saved", text="✅ Recorded. Thank you.", summary="3 masons"),
        StepResult("saved", text="✅ Recorded. Thank you.", summary="5 bags cement used"),
        text="3 mason, 5 bag cement use cheythu",
    )
    assert provider.calls == 1
    assert result.run.stop_reason == "answered"  # the second round ran
    assert result.reply.text == (
        "Sheri, 3 mason and 5 bag cement. Check and tap Save.\n\n"
        "✅ Saved:\n• 3 masons\n• 5 bags cement used\n\nWrong? Reply UNDO."
    )


async def test_an_answer_in_the_same_round_is_said_in_the_models_words():
    provider = FakeToolCallingProvider(
        [[("save_labour", {"workers": WORKERS}), ("query_labour", {})], "12 workers this week, and 3 masons today."]
    )
    result = await _run(
        provider,
        StepResult("saved", text="x", summary="3 masons"),
        StepResult("answer", text="12 workers this week."),
    )
    assert result.reply.text.startswith("12 workers this week, and 3 masons today.\n\n✅ Saved: 3 masons")


@pytest.mark.parametrize(
    ("reply", "unbacked"),
    [
        ("Cement 140 bags, used 20.", set()),
        ("Stock ippo 160 bag aakum.", {"160"}),  # 140 + 20 worked out by the model
        ("1,500 bricks came.", set()),
        ("40 bags left.", {"40"}),
        ("1 more thing.", set()),
    ],
)
def test_figures_must_come_from_the_message_or_the_records(reply, unbacked):
    sources = ["used 20 bags", '{"stock": "Cement 140 bags"}', "1500 bricks"]
    assert r.unbacked_numbers(reply, sources) == unbacked


async def test_a_made_up_figure_drops_the_models_words_but_keeps_the_saved_line():
    provider = FakeToolCallingProvider(
        [[("save_material_usage", {"material": "cement", "quantity": 20, "unit": "bags"})],
         "Done, stock ippo 160 bag."]
    )
    result = await _run(
        provider,
        StepResult("saved", text="x", summary="Cement used: 20 bags"),
        text="20 bag cement use cheythu",
    )
    assert "160" not in result.reply.text
    assert result.reply.text.startswith("✅ Saved: Cement used: 20 bags")


async def test_another_language_still_gets_the_models_reply():
    import dataclasses

    provider = FakeToolCallingProvider([[("save_labour", {"workers": WORKERS})], "3 മേസൺ ✅"])
    result = await r.AgentRunner(provider).run(
        ctx=dataclasses.replace(CTX, last_language="malayalam"),
        user_text="3 mason vannu",
        gateway=Gateway(StepResult("saved", text="x", summary="3 masons")),
        scope=ScopeLookup(),
    )
    assert result.run.stop_reason == "answered"


@pytest.mark.parametrize(
    ("text", "kept"),
    [
        ("ഇന്ന് മഴ കാരണം പണി കുറവാണെന്ന് രേഖപ്പെടുത്തിയിട്ടുണ്ട്. സേവ് ടാപ്പ് ചെയ്യുക.", "സേവ് ടാപ്പ് ചെയ്യുക."),
        ("Labour save cheythu. Check and tap Save.", "Check and tap Save."),
        ("Got it, 3 masons recorded. Tap Save to keep it.", "Got it. Tap Save to keep it."),
        ("This part was not saved: unit missing.", "This part was not saved: unit missing."),
        ("Sheri, 100 bag cement vannu. Check cheythu Save tap cheyyu.", "Sheri, 100 bag cement vannu. Check cheythu Save tap cheyyu."),
    ],
)
def test_a_sentence_saying_it_is_already_saved_is_dropped(text, kept):
    assert r.without_saved_claims(text) == kept


async def test_a_code_word_in_the_reply_is_never_sent():
    """The 21 Oct reply "സ്ല clientIdb-ന് 20 ബാഗ് സിമന്റ് ഉപയോഗിച്ചു"."""
    provider = FakeToolCallingProvider(
        [[("save_material_usage", {"material": "cement", "quantity": 20, "unit": "bags"})],
         "സ്ല clientIdb-ന് 20 ബാഗ് സിമന്റ് ഉപയോഗിച്ചു"]
    )
    result = await _run(
        provider, StepResult("saved", text="x", summary="Cement used: 20 bags (slab)"), text="slab-inu 20 bag cement use cheythu"
    )
    assert "clientIdb" not in result.reply.text
    assert result.reply.text.startswith("✅ Saved: Cement used: 20 bags (slab)")


@pytest.mark.parametrize(
    ("message", "rule"),
    [
        ("3 carpenters today", "English letters"),
        ("slab-inu 20 bag cement use cheythu", "English letters"),
        ("ഇന്ന് മഴയാണ്", "its own script"),
        ("👍", None),
    ],
)
def test_the_reply_letters_follow_this_message_not_the_earlier_ones(message, rule):
    import dataclasses

    ctx = dataclasses.replace(CTX, last_language="Malayalam", last_script="native")
    sent = build_messages(ctx, message)
    if rule is None:
        assert "Language of their earlier messages: Malayalam" in sent[0][1]
    else:
        assert rule in sent[-1][1]
        assert "earlier messages" not in sent[0][1]


# -- round 3b: a Manglish message answered in English gets one more try ------


class _Runs:
    """One scripted fake per run_tools call (each fake replays its own script)."""

    def __init__(self, *fakes):
        self._fakes = list(fakes)
        self.calls = 0
        self.tools_seen = []

    async def run_tools(self, system_prompt, messages, tools, handler, **kwargs):
        self.tools_seen.append(list(tools))
        fake = self._fakes[self.calls]
        self.calls += 1
        return await fake.run_tools(system_prompt, messages, tools, handler, **kwargs)


async def test_an_english_reply_to_manglish_is_said_again_in_manglish():
    provider = _Runs(
        FakeToolCallingProvider(
            [[("save_labour", {"workers": WORKERS})], "3 masons came today. Check and tap Save."]
        ),
        FakeToolCallingProvider(["Innu 3 mason vannu. Onnu nokki Save tap cheyyu."]),
    )
    result = await r.AgentRunner(provider).run(
        ctx=CTX,
        user_text="innu 3 mason vannu",
        gateway=Gateway(StepResult("saved", text="x", summary="3 masons")),
        scope=ScopeLookup(),
    )
    assert result.reply.text.startswith("Innu 3 mason vannu. Onnu nokki Save tap cheyyu.")
    assert provider.calls == 2
    assert provider.tools_seen[1] == []  # the second try has no tools
    assert len(result.toolbox.saved) == 1  # nothing was run or saved again


async def test_the_english_reply_stays_when_the_second_try_fails():
    provider = _Runs(
        FakeToolCallingProvider(
            [[("save_labour", {"workers": WORKERS})], "3 masons came today. Check and tap Save."]
        ),
        FakeToolCallingProvider([], error=TimeoutError("second try timed out")),
    )
    result = await r.AgentRunner(provider).run(
        ctx=CTX,
        user_text="innu 3 mason vannu",
        gateway=Gateway(StepResult("saved", text="x", summary="3 masons")),
        scope=ScopeLookup(),
    )
    assert result.reply.text.startswith("3 masons came today. Check and tap Save.")


async def test_an_english_message_gets_no_second_try():
    provider = FakeToolCallingProvider(
        [[("save_labour", {"workers": WORKERS})], "3 masons came today. Check and tap Save."]
    )
    await r.AgentRunner(provider).run(
        ctx=CTX,
        user_text="3 masons came today",
        gateway=Gateway(StepResult("saved", text="x", summary="3 masons")),
        scope=ScopeLookup(),
    )
    assert provider.calls == 1


def test_only_the_sentence_with_a_made_up_number_is_dropped():
    """Live golden set, 22 Oct: an example "100 bags?" took the whole
    question with it, and the sender got "Sorry, I couldn't work that out"."""
    from runtime.agent.runner import without_numbers

    reply = "Ethra bag cement vannu? 50 bags aano 100 bags aano?"
    assert without_numbers(reply, {"50", "100"}) == "Ethra bag cement vannu?"
    assert without_numbers("100 bags.", {"100"}) == ""


def test_a_made_up_decimal_or_a_leftover_scrap_never_goes_out():
    """Review, 22 Oct: "12.5" split at its "." and slipped through; "Rs." was
    left alone as the whole reply."""
    from runtime.agent.runner import without_numbers

    assert without_numbers("That comes to 12.5 bags left in stock.", {"12.5"}) == ""
    assert without_numbers("Rs. 4500 total for the week.", {"4500"}) == ""
    kept = without_numbers("Okay, noted the work. It is 12.5 bags. Anything else today?", {"12.5"})
    assert kept == "Okay, noted the work. Anything else today?"
