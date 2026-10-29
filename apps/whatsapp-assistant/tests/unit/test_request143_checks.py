"""Request 143, phase 3 (D + E): the check layer, true card facts, and the code's
lines in the sender's language.

Repros (live, 29 Oct): "Site B 500 mason vannu" saved with no question; "Green
Villa ground floor tiling 40% aayi" after a saved 88% had no "went down, sure?";
"Saved 6 workers (6 helper)" while the day had 13; a late entry's card had no
day; the module-off line, "ok thanks" and the received/used question were English
for a Manglish sender; a cement order was an issue; a week summary carried the
Stock card.
"""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from runtime.agent import checks
from runtime.agent import draft as dr
from runtime.agent.actions import closed_lines, material_request_line
from runtime.agent.material_direction import asked_direction, is_cancel, is_material_order
from runtime.agent.wording import decide, language_of, say, usual_from
from runtime.day_facts import SiteHistory, work_key

TILING = work_key("tiling", "ground floor")


def _history(days=(), percents=None) -> SiteHistory:
    return SiteHistory(labour_days=tuple(days), percents=percents or {})


def _labour(*counts: int) -> dict:
    return {"lines": [{"trade": "mason", "headcount": c} for c in counts]}


# -- D: the check layer ------------------------------------------------------------


def test_500_masons_at_a_site_with_no_history_is_asked():
    found = checks.doubt(dr.KIND_LABOUR, {}, _labour(500), _history())
    assert found is not None and found.key == "check.labour_new" and found.values["workers"] == 500


def test_far_above_the_usual_day_is_asked_and_a_normal_day_is_not():
    usual = _history(days=(12, 14, 11, 13))
    assert checks.doubt(dr.KIND_LABOUR, {}, _labour(500), usual).key == "check.labour_many"
    assert checks.doubt(dr.KIND_LABOUR, {}, _labour(14), usual) is None
    assert checks.doubt(dr.KIND_LABOUR, {}, _labour(40), usual) is None  # 3x12=36, but 12+30=42
    assert checks.doubt(dr.KIND_LABOUR, {}, _labour(60), _history()) is None  # no history: up to 150


def test_a_percent_below_the_saved_one_is_asked():
    history = _history(percents={TILING: (88.0, "Tiling, ground floor: 88%")})
    args = {"work_type": "tiling", "location": "ground floor", "progress_percent": 40}
    found = checks.doubt(dr.KIND_WORK, args, {}, history)
    assert found.key == "check.percent_down" and (found.values["before"], found.values["percent"]) == ("88", "40")
    assert checks.doubt(dr.KIND_WORK, {**args, "progress_percent": 92}, {}, history) is None
    other = {**args, "location": "first floor"}
    assert checks.doubt(dr.KIND_WORK, other, {}, history) is None  # another place, another work


def test_a_percent_above_100_is_asked():
    assert checks.doubt(dr.KIND_WORK, {"work_type": "tiling", "progress_percent": 140}, {}, None).key == "check.percent_over"


def test_more_used_than_in_stock_is_asked():
    fields = {"quantity": 80, "available_stock": 50, "unit": "bags"}
    assert checks.doubt(dr.KIND_MATERIAL_OUT, {}, fields, None).key == "check.more_than_stock"
    assert checks.doubt(dr.KIND_MATERIAL_OUT, {}, {**fields, "quantity": 20}, None) is None
    assert checks.doubt(dr.KIND_MATERIAL_OUT, {}, {"quantity": 80}, None) is None  # stock not known


def test_the_usual_day_is_the_median_of_three_or_more():
    assert _history(days=(10, 30, 12)).usual_workers == 12
    assert _history(days=(10, 30)).usual_workers is None


def test_the_question_is_in_the_senders_language():
    found = checks.doubt(dr.KIND_LABOUR, {}, _labour(500), _history())
    assert say(found.key, "manglish", **found.values) == "Oru divasam 500 per, shariyaano?"
    assert say(found.key, "english", **found.values) == "500 workers in one day, is that right?"


@pytest.mark.parametrize("text", ["yes", "Sheri", "shari aanu", "correct", "haan sahi", "ശരി"])
def test_typed_yes_settles_a_check(text):
    assert checks.says_right(text)


@pytest.mark.parametrize("text", ["50", "no 50 aanu", "change"])
def test_other_words_do_not_settle_a_check(text):
    assert not checks.says_right(text)


def test_a_typed_figure_replaces_the_one_asked_about():
    labour = dr.DraftItem(kind=dr.KIND_LABOUR, tool="save_labour", args={"workers": [{"trade": "mason", "headcount": 500}]})
    assert checks.with_figure(labour, 50.0) == {"workers": [{"trade": "mason", "headcount": 50}]}
    work = dr.DraftItem(kind=dr.KIND_WORK, tool="save_work_done", args={"work_type": "tiling", "progress_percent": 40})
    assert checks.with_figure(work, 90.0)["progress_percent"] == 90
    two = dr.DraftItem(kind=dr.KIND_LABOUR, tool="save_labour", args={"workers": [{"headcount": 5}, {"headcount": 3}]})
    assert checks.with_figure(two, 50.0) is None  # which one? the model reads it instead


# -- E: card facts -----------------------------------------------------------------


def test_a_labour_line_says_the_days_true_total():
    fields = {
        "lines": [{"trade": "helper", "headcount": 6}],
        "day_counted_lines": [{"trade": "mason", "headcount": 7}],
    }
    assert dr.day_total_note(fields) == " · day total 13 workers"
    # The same trade again replaces its earlier figure (BE-10): 9 helpers, not 6 + 9.
    again = {"lines": [{"trade": "helper", "headcount": 9}], "day_counted_lines": [
        {"trade": "mason", "headcount": 2}, {"trade": "helper", "headcount": 6}]}
    assert dr.day_total_note(again) == " · day total 11 workers"
    assert dr.day_total_note({"lines": [{"trade": "mason", "headcount": 4}]}) == ""


def test_a_late_entry_says_its_day_whatever_its_kind():
    from interactions.saved_summary import summarise_draft
    from mesiri_contracts.assistant.draft_action import DraftActionType

    today = dt.date(2026, 10, 29)
    labour = SimpleNamespace(
        action_type=DraftActionType.RECORD_LABOUR_ATTENDANCE,
        fields={"lines": [{"trade": "mason", "headcount": 5}], "occurred_date": "2026-10-28"},
    )
    assert summarise_draft(labour, today=today).endswith("(yesterday, 28 Oct)")
    cement = SimpleNamespace(
        action_type=DraftActionType.RECORD_MATERIAL_USAGE,
        fields={"material_name": "cement", "quantity": 30, "unit": "bags", "occurred_date": "2026-10-29"},
    )
    assert "(" not in summarise_draft(cement, today=today)  # today: no day


def test_closed_issues_are_clean_lines():
    assert closed_lines(["Crane breakdown (since 20 Oct)."], []) == "✅ Closed: Crane breakdown (since 20 Oct)"
    two = closed_lines(["Crane breakdown", "Mixer  breakdown;"], ["Leak"])
    assert two == "✅ Closed:\n• Crane breakdown\n• Mixer breakdown\n❌ Couldn't close: Leak"
    assert closed_lines([], ["Leak"]) == "❌ Couldn't close: Leak\nNothing was changed."


# -- E: a material order is a request, never an issue -----------------------------


@pytest.mark.parametrize(
    "text", ["nale 50 bag cement order cheyyanam", "order 100 bags cement", "10 bag cement balance und, kooduthal venam"]
)
def test_an_order_is_read_as_an_order(text):
    assert is_material_order(text)


@pytest.mark.parametrize("text", ["50 bags cement arrived", "cement 30 bag use cheythu", "crane breakdown"])
def test_other_messages_are_not_orders(text):
    assert not is_material_order(text)


def test_the_request_line():
    assert material_request_line({"material": "cement", "quantity": 50, "unit": "bags", "needed_by": "nale"}) == (
        "50 bags cement (needed nale)"
    )


async def test_the_material_request_tool_is_a_card_not_an_issue():
    from runtime.agent.tools import ScopeLookup, to_candidate

    candidate = to_candidate("request_material", {"material": "cement", "quantity": 50, "unit": "bags"}, ScopeLookup())
    assert candidate.fields["_action"] == "material_request"


# -- E: the code's lines in the sender's language ---------------------------------


@pytest.mark.parametrize(
    ("language", "script", "usual"),
    [("Malayalam", "latin", "manglish"), ("Malayalam", "native", "malayalam"), ("Hindi", "latin", "hinglish"),
     (None, "native", None), ("English", "latin", None)],
)
def test_the_usual_language_from_the_profile(language, script, usual):
    assert usual_from(language, script) == usual


@pytest.mark.parametrize(
    ("text", "usual", "language"),
    [("ok thanks", "manglish", "manglish"), ("👍", "malayalam", "malayalam"), ("thank you", "manglish", "manglish"),
     ("ok thanks", None, None), ("send me the stock", "manglish", "english"), ("cement vannu", None, "manglish")],
)
def test_one_decision_per_turn(text, usual, language):
    assert decide(text, usual) == language


def test_the_module_off_line_is_worded_in_the_turns_language():
    from channel.replies import module_disabled_line, render_module_disabled_reply

    key, values = module_disabled_line("finance", "SUPERVISOR")
    assert say(key, "english", **values) == render_module_disabled_reply("finance", "SUPERVISOR")
    assert say(key, "manglish", **values).startswith("Expenses ningalude company-kku ippo on cheythittilla")


async def test_the_toolbox_words_the_module_off_line_in_the_turns_language():
    from runtime.agent.gateway import StepResult
    from runtime.agent.toolbox import AgentToolbox
    from runtime.agent.tools import ScopeLookup

    box = AgentToolbox(gateway=SimpleNamespace(), scope=ScopeLookup(), user_text="ok", language="manglish")
    box._outcome("save_expense", StepResult("info", text="Expenses aren't switched on...", line_key="module.off.admin",
                                            line_values={"name": "Expenses", "verb": "aren't", "pronoun": "them"}))
    assert box.module_off_line.startswith("Expenses ningalude company-kku")


def test_the_direction_question_is_known_in_every_language_and_cancel_is_read():
    for language in ("english", "manglish", "malayalam", "hindi", "hinglish"):
        assert asked_direction(say("material.direction", language, what="50 bags cement"))
    assert is_cancel("Cancel") and is_cancel("venda") and not is_cancel("50 bags used")


async def test_cancel_on_the_direction_question_is_answered_by_code():
    from mesiri_ai.fakes import FakeToolCallingProvider
    from runtime.agent.prompt import AgentContext, Turn
    from runtime.agent.runner import AgentRunner
    from runtime.agent.tools import ScopeLookup

    asked = say("material.direction", "manglish", what="50 bags cement")
    ctx = AgentContext(user_name="Anil", role="SUPERVISOR", company="Acme", now=dt.datetime(2026, 10, 29, 10),
                       projects=(), sites=(), turns=(Turn("50 bags cement", asked),),
                       last_language="Malayalam", last_script="latin")
    provider = FakeToolCallingProvider([])  # never called
    result = await AgentRunner(provider).run(ctx=ctx, user_text="Cancel", gateway=SimpleNamespace(), scope=ScopeLookup())
    assert result.reply.text == say("material.direction_cancelled", "manglish")


async def test_the_direction_question_is_the_codes_with_cancel():
    from runtime.agent.toolbox import AgentToolbox
    from runtime.agent.tools import ScopeLookup

    box = AgentToolbox(gateway=SimpleNamespace(), scope=ScopeLookup(), user_text="50 bag cement", language="manglish")
    await box.handle("ask_user", {"question": "Received or used?"})
    assert box.parked.text == "50 bag cement vannatho, use cheythatho?"
    assert [b.title for b in box.parked.buttons] == ["Received", "Used", "Cancel"]


# -- E: a picture belongs to its answer --------------------------------------------


def test_the_stock_card_is_only_for_a_stock_only_answer():
    from runtime.agent.toolbox import AgentToolbox
    from runtime.agent.tools import ScopeLookup

    box = AgentToolbox(gateway=SimpleNamespace(), scope=ScopeLookup(), user_text="week summary")
    box._stock_answer = "Cement: 40 bags"
    box.answers = ["Cement: 40 bags"]
    assert box.answers_only_stock()
    box.answers.append("This week: tiling 40%, 60 workers")
    assert not box.answers_only_stock()


def test_language_of_defaults_to_english():
    assert language_of("ok") == "english"
