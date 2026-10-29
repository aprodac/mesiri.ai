"""Request 143, phase 4 (F): fewer and smaller model calls per message.

Live 29 Oct: taps 2.5-7.9 s, messages 6-11 s (a transfer 10.8-11.4 s). Each message
made the tool loop's model calls, then up to four more (re-say in Manglish, in one
script, the answer in their language, the covering sentence), each with every tool
spec (~30K characters). Now: one language pass in code, a round that only made card
lines ends the loop (``ToolOutcome.done``), and a turn shows the model the tool
families its message names (``tool_choice.tools_for``).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.agent import tools as t
from runtime.agent.tool_choice import CORE, families_of, tools_for

CONVERSATION = Path(__file__).resolve().parents[1] / "conversation"


def _names(text: str, **kw) -> set[str]:
    return {spec.name for spec in tools_for(text, **kw)}


def test_a_labour_message_gets_the_labour_tools_and_the_core_not_money():
    names = _names("Green Villa innu 5 mason 3 helper vannu")
    assert {t.SAVE_LABOUR, *CORE} <= names
    assert t.SAVE_EXPENSE not in names and t.ADD_MEMBER not in names


def test_every_tool_is_reachable_through_the_core_or_a_family():
    """A tool added later must be put in a family (or the core), never left out silently."""
    from runtime.agent.tool_choice import FAMILIES

    reachable = set(CORE).union(*(tools for _words, tools in FAMILIES.values()))
    assert {spec.name for spec in t.tool_specs()} <= reachable


def test_a_language_ask_gets_the_language_tool():
    assert t.SET_REPLY_LANGUAGE in _names("reply in english please")


def test_the_subset_is_much_smaller():
    full = sum(len(json.dumps(s.parameters)) + len(s.description) for s in t.tool_specs())
    some = sum(len(json.dumps(s.parameters)) + len(s.description) for s in tools_for("6 mason vannu"))
    assert some < full / 2


@pytest.mark.parametrize("text", ["50", "ok sheri", "hmm"])
def test_words_that_name_no_family_get_every_tool(text):
    assert len(tools_for(text)) == len(t.tool_specs())


def test_native_script_and_answers_get_every_tool():
    assert len(tools_for("ഇന്ന് മഴയാണ്, പണി കുറവാണ്")) == len(t.tool_specs())
    assert len(tools_for("6 mason vannu", keep_all=True)) == len(t.tool_specs())


@pytest.mark.parametrize(
    ("text", "family"),
    [
        ("chai pani ke liye 300 diye", "money"),
        ("only 4 masons came, short of labour", "site_problem"),
        ("JCB worked 6 hours today", "equipment"),
        ("nale 50 bag cement order cheyyanam", "material"),
        ("innathe report ayakku", "report"),
        ("ground floor tiling 40% aayi", "work"),
    ],
)
def test_families(text, family):
    assert family in families_of(text)


def _golden(name: str) -> list[dict]:
    path = CONVERSATION / name
    return [json.loads(line.strip()[2:]) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip().startswith("- {")]


@pytest.mark.parametrize("name", ["draft_golden.yaml", "site_golden.yaml", "materials_golden.yaml"])
def test_every_golden_message_is_shown_the_tools_it_needs(name):
    """The guard: each golden message's good calls are within the tools its words get."""
    for case in _golden(name):
        for turn in [*case.get("before", []), case]:
            needed = {call[0] for call in turn.get("calls", [])}
            missing = needed - _names(turn["message"])
            assert not missing, (name, case["id"], turn["message"], missing)


# -- a round of card lines ends the run --------------------------------------------


async def test_a_card_only_turn_costs_one_model_call():
    pytest.importorskip("langgraph", reason="needs the `workflow` extra (LangGraph)")
    from tests.conversation.test_draft_golden import villa_world

    from mesiri_ai.fakes import FakeToolCallingProvider

    world = await villa_world()
    provider = FakeToolCallingProvider(
        [[("save_labour", {"workers": [{"trade": "mason", "headcount": 5}], "site": "Green Villa"})], "never read"]
    )
    result = await world.say(provider, "Green Villa 5 mason vannu")
    assert result.run.stop_reason == "done_by_tools"
    assert "never read" not in result.reply.text and "5 mason" in result.reply.text


async def test_a_card_with_an_answer_still_gets_the_models_words():
    pytest.importorskip("langgraph", reason="needs the `workflow` extra (LangGraph)")
    from tests.conversation.test_draft_golden import villa_world

    from mesiri_ai.fakes import FakeToolCallingProvider

    world = await villa_world()
    provider = FakeToolCallingProvider(
        [
            [("query_materials", {})],
            [("save_labour", {"workers": [{"trade": "mason", "headcount": 5}], "site": "Green Villa"})],
            "Cement stock is fine.",
        ]
    )
    result = await world.say(provider, "Green Villa 5 mason vannu, cement stock ethra?")
    assert result.run.stop_reason == "answered"
