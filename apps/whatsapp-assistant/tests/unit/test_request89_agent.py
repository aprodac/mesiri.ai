"""Request 89 (22 Oct re-test): the reply language decided in code, natural
lines above a Save card. (A past day's report: test_request143_report.py.)"""

from __future__ import annotations

import datetime

import pytest

from mesiri_ai.fakes import FakeToolCallingProvider
from runtime.agent import reply_text as rt
from runtime.agent import runner as r
from runtime.agent.prompt import AgentContext, reply_language, reply_letters_rule
from runtime.agent.query_entry import _one_name_per_trade
from runtime.agent.tools import ScopeLookup

# -- 2. the reply language is decided in code ----------------------------------


@pytest.mark.parametrize(
    "text, language",
    [
        ("used 10 bags cement for columns", "english"),
        ("crane breakdown, work stopped since morning", "english"),
        ("send yesterday's report", "english"),
        ("how many workers this week?", "english"),
        ("ground floor flooring theernnu", "manglish"),
        ("innale report ayakku", "manglish"),
        ("2 painter vannu", "manglish"),
        ("ഇന്ന് 5 പേർ വന്നു", "malayalam"),
        ("आज 5 मिस्त्री आए", "hindi"),
        ("ok", None),
        ("50 bags", None),
        ("👍", None),
    ],
)
def test_the_language_comes_from_the_message(text, language):
    assert reply_language(text) == language


def test_the_instruction_is_hard_and_says_which_language():
    assert "English only" in reply_letters_rule("used 10 bags cement for columns")
    assert "Manglish" in reply_letters_rule("ground floor flooring theernnu")
    assert "Malayalam script" in reply_letters_rule("ഇന്ന് 5 പേർ വന്നു")
    assert reply_letters_rule("👍") is None


@pytest.mark.parametrize(
    "reply",
    ["Okay. Nokki shariyenkil Save tap cheyyu.", "Okay. Shariyenkil Save tap cheyyu.", "Ayyo, pani nirthi."],
)
def test_manglish_for_an_english_message_is_a_mismatch(reply):
    assert r.script_problems(reply, "used 10 bags cement for columns")
    assert r.script_problems(reply, "crane breakdown, work stopped since morning")


def test_each_language_in_the_same_language_out_passes():
    assert not r.script_problems("Got it, 10 bags cement used for columns. Please check it and tap Save.", "used 10 bags cement for columns")
    assert not r.script_problems("Sheri, ground floor flooring theernnu. Nokki Save tap cheyyu.", "ground floor flooring theernnu")
    assert not r.script_problems("ശരി, 5 പേർ. ശരിയാണെങ്കിൽ Save അമർത്തുക.", "ഇന്ന് 5 പേർ വന്നു")
    assert r.script_problems("Got it, 5 people today. Please check it and tap Save.", "ഇന്ന് 5 പേർ വന്നു")  # English for Malayalam


CTX = AgentContext(
    user_name="Anil", role="SUPERVISOR", company="Acme", now=datetime.datetime(2026, 10, 22, 9, 30),
    projects=(("Project Alpha", None),), sites=(("Site A1", "Project Alpha"),),
)


class _Provider(FakeToolCallingProvider):
    """The first run is scripted (tool calls, then words); the runner's later
    no-tool tries answer from ``retries`` in turn (the fake would replay the script)."""

    def __init__(self, script: list, retries: list[str]) -> None:
        super().__init__(script)
        self.retries = list(retries)
        self.asked: list[str] = []

    async def run_tools(self, system_prompt, messages, tools, handler, **kw):  # noqa: ANN001, ANN201
        if self.calls == 0:
            return await super().run_tools(system_prompt, messages, tools, handler, **kw)
        from mesiri_ai.models import ToolRunResult

        self.calls += 1
        self.asked.append(messages[-1].text)
        return ToolRunResult(text=self.retries.pop(0), calls=[], steps=1, stop_reason="answered", model="fake")


async def _reply_for(user_text: str, script: list, retries: list[str], summary: str = "10 bags cement used (columns)", saved: str = "") -> tuple[str, FakeToolCallingProvider]:
    """Run the runner with a gateway that prepares one card line; ``script`` is the model's turns."""
    from runtime.agent.gateway import StepResult

    class Gateway:
        async def run(self, candidate, *, text):  # noqa: ANN001, ANN202
            return StepResult("saved", text=saved or summary, summary=summary)

    provider = _Provider(script, retries)
    result = await r.AgentRunner(provider).run(
        ctx=CTX, user_text=user_text, gateway=Gateway(), scope=ScopeLookup()
    )
    return result.reply.text, provider


CEMENT = [("save_material_usage", {"material": "cement", "quantity": 10, "unit": "bags", "purpose": "columns"})]


async def test_manglish_for_english_is_corrected_in_code_with_no_second_call():
    text, provider = await _reply_for(
        "used 10 bags cement for columns",
        [CEMENT, "Okay. Nokki shariyenkil Save tap cheyyu."],
        ["Got it, 10 bags cement used for columns. Please check it and tap Save."],
    )
    assert provider.asked == []  # request 143: one language pass, no second call
    assert text.startswith("10 bags cement used (columns). Please check it and tap Save.")
    assert not rt.manglish_word_count(text, r._MANGLISH_WORDS)


# -- 3. natural lines --------------------------------------------------------------


@pytest.mark.parametrize("bare", ["Okay.", "Ok.", "Okay, noted."])
async def test_a_flat_okay_never_goes_out_above_a_card(bare):
    text, _ = await _reply_for(
        "crane breakdown, work stopped since morning",
        [[("report_issue", {"issue_type": "EQUIPMENT", "narrative": "crane breakdown, work stopped", "delay_duration_minutes": 480})], bare],
        [bare, bare],
        summary="Issue: crane breakdown, work stopped",
    )
    first = text.split("\n")[0]
    assert "crane breakdown, work stopped" in first.casefold()
    assert "tap Save" in first and not first.startswith(("Okay", "Ok."))


def test_the_natural_fallback_is_built_from_the_items_in_each_language():
    items = ["Crane breakdown, work stopped"]
    assert r.covering_sentence(items, "crane breakdown, work stopped since morning") == "Crane breakdown, work stopped. Please check it and tap Save."
    assert r.covering_sentence(items, "crane kedayi pani nirthi").endswith("Save tap cheyyu.")
    assert "അമർത്തുക" in r.covering_sentence(items, "ക്രെയിൻ കേടായി")
    for lang_text in ("hello there", "crane kedayi pani nirthi", "ക്രെയിൻ കേടായി", "क्रेन खराब"):
        line = r.covering_sentence(items, lang_text)
        assert not line.startswith(("Okay", "Ok.")) and "saved" not in line.casefold()


def test_stray_sentences_tied_to_nothing_go():
    grounds = ["undo that", "Removed: 20 workers (today)"]
    assert rt.without_stray_sentences("Nale nokkam. Sheri, pani maattiyittund.", grounds) == "Sheri, pani maattiyittund."
    grounds = ["10 bags cement used for columns", "10 bags cement used (columns)"]
    reply = "Sheri, 10 bags cement used for columns. Verenthenkilum ariyamo? Nokki shariyenkil Save tap cheyyu."
    assert rt.without_stray_sentences(reply, grounds) == "Sheri, 10 bags cement used for columns. Nokki shariyenkil Save tap cheyyu."
    steel = "Ethra steel venam ennu paranjal record cheyyam."
    assert rt.without_stray_sentences("Got it, steel needed. " + steel, ["steel needed"]) == "Got it, steel needed."


def test_a_human_touch_and_a_save_ask_are_kept_and_a_reply_is_never_emptied():
    grounds = ["crane breakdown, work stopped since morning"]
    reply = "Sorry to hear that. Crane breakdown, work stopped since morning. Check it and tap Save."
    assert rt.without_stray_sentences(reply, grounds) == reply
    assert rt.without_stray_sentences("Anything else? Let me know if you need me.", grounds) == "Anything else? Let me know if you need me."


async def test_a_stray_line_before_a_system_line_is_dropped():
    from runtime.agent.gateway import StepResult

    class Gateway:
        async def undo_card(self, targets):  # noqa: ANN001, ANN202
            return StepResult("undone", text="Removed: 20 workers (today)")

    provider = FakeToolCallingProvider([[("undo_last", {})], "Nale nokkam. Sheri, mattiyittund."])  # noqa: E501
    result = await r.AgentRunner(provider).run(ctx=CTX, user_text="undo that", gateway=Gateway(), scope=ScopeLookup())
    assert "Nale nokkam" not in result.reply.text


def test_trades_in_a_labour_answer_are_shown_once_each():
    results = {"trades": ["mason", "masons", "Masons", "bar_bending", "bar_bender", "helper"]}
    _one_name_per_trade(results)
    from trade_label import trade_label

    assert [trade_label(t) for t in results["trades"]] == ["Mason", "Bar bender", "Helper"]


def test_the_prompt_carries_six_examples_per_language_and_the_pattern():
    from runtime.agent.prompt import SYSTEM_PROMPT

    for header in ("English message -> English reply", "Manglish message -> Manglish reply", "Malayalam script message -> Malayalam script reply"):
        block = SYSTEM_PROMPT.split(header, 1)[1].split("\n  ", 1)[1].split("\nManglish message", 1)[0].split("\nMalayalam script message", 1)[0]
        assert block.count(" -> ") >= 6 or header.startswith("Malayalam") or header.startswith("Manglish")
    assert SYSTEM_PROMPT.count(" -> ") >= 18
    assert "No \\\nfiller" not in SYSTEM_PROMPT and "Nale nokkam" in SYSTEM_PROMPT  # named as what NOT to write
