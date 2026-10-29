# ruff: noqa: F811
"""Request 132 (replaces 131), P2.5 of docs/architecture/ADR-draft-per-message.md:
the understanding side follows the draft, and the model cannot write a card.

A. The site of a draft item is decided in one place (``draft_site``): never pinned
   by a mention.
C. The code renders every card; the model's text is filtered, and a guard fails
   when a reply carries text of a prompt or annotation constant.
D. The model is shown the state and a gist of the past, not its raw replies.
E. The polish of [130].

The model is scripted; everything after it is the real journey.
"""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest
from tests.replay.test_agent_replay import _Catalog
from tests.replay.test_draft_per_message_p1 import open_items, titles
from tests.replay.test_draft_per_message_p3 import (  # noqa: F401  (fixtures)
    CEMENT,
    MASONS,
    SITE_A1,
    SITE_A2,
    STEEL,
    _active,
    _remember,
    _SteelCatalog,
    only_waiting_for_site,
    tap,
    two,
    world,
)

from context import seed
from mesiri_ai.fakes import FakeToolCallingProvider
from runtime.agent import draft as dr
from runtime.agent import draft_site, history, reply_clean
from runtime.agent.prompt import AgentContext, Turn, build_messages
from runtime.agent.stale_questions import CLOSED

SET_SITE_A2 = ("set_work_site", {"site": "Site A2"})


# -- A. one resolver --------------------------------------------------------------------------


def _actor(*names: str) -> SimpleNamespace:
    sites = [SimpleNamespace(id=f"s{n}", name=name, project_id="p1") for n, name in enumerate(names)]
    return SimpleNamespace(sites=sites, projects=[SimpleNamespace(id="p1", name="Project")])


@pytest.mark.parametrize(
    "text, site",
    [
        ("Green Villa ground floor wall putty 200 sqft cheythu", "Green Villa"),
        ("Green Villa first floor wall putty 200 sqft cheythu", "Green Villa"),
        ("Site B-il Rajesh-ine supervisor aakku", "Site B"),
        ("cement vannu", None),
        ("cement from Site B to Green Villa", None),  # two sites: the question stands
    ],
)
def test_a_the_site_a_message_names_whole_words_in_any_position(text, site):
    found = draft_site.named_in(_actor("Green Villa", "Site B"), text)
    assert (found.name if found else None) == site


def test_a_the_one_order_single_then_named_then_saved_then_ask():
    one, two_ = _actor("Green Villa"), _actor("Green Villa", "Site B")
    assert draft_site.resolve(one, "x").kind == draft_site.SINGLE
    assert draft_site.resolve(two_, "Site B 4 mason", saved_site_id="s0").kind == draft_site.NAMED
    assert draft_site.resolve(two_, "4 mason", saved_site_id="s0").kind == draft_site.SAVED
    assert draft_site.resolve(two_, "4 mason", saved_site_id="gone").kind == draft_site.ASK
    assert draft_site.resolve(two_, "4 mason").kind == draft_site.ASK


@pytest.mark.parametrize(
    "text, move",
    [
        ("now at Site B", True),
        ("innu Site B site-il", True),
        ("I am at Site B today", True),
        ("Site B-il Rajesh-ine supervisor aakku", False),
        ("add Rajesh to Site B as supervisor", False),
        ("4 mason at Site B", False),
    ],
)
def test_a_only_a_plain_statement_of_where_they_are_is_a_move(text, move):
    assert draft_site.is_location_statement(_actor("Site B"), text, "Site B") is move


async def test_a_site_named_while_setting_up_the_team_pins_nothing(two):
    """27 Oct: "Site B-il Rajesh-ine supervisor aakku" pinned Site B for the day (the model
    called set_work_site); the next "4 mason" was put there without asking."""
    team = await two.say(
        FakeToolCallingProvider([[("set_work_site", {"site": "Site A2"})], "Sheri."]),
        "Site A2-il Rajesh-ine supervisor aakku",
    )
    outcome = team.run.calls[0].outcome.content
    assert outcome["status"] == "not_a_move"
    assert await _active(two) is None

    asked = await two.say(FakeToolCallingProvider([[MASONS], "Which site?"]), "4 mason")
    assert await only_waiting_for_site(two)  # WA-81: on the card, asking where
    assert {"Site A1", "Site A2"} <= set(titles(asked.reply))


async def test_a_now_at_a_site_preselects_for_three_hours_not_until_midnight(two):
    from runtime.agent import work_site

    sites = work_site.WorkSite(active_context=two.deps.active_context, redis=two.redis)
    # The context layer keys its store by the seed's readable ids.
    sender = SimpleNamespace(organization_id=seed.ORG_A, user_id=seed.USER_ENGINEER, sites=two.actor.sites)

    async def preselect(project_id, site_id):  # noqa: ANN001, ANN202
        await sites.preselect(sender, project_id=two.project_id, site_id=site_id)
        return "Site A2"

    two.preselect_site = preselect
    done = await two.say(FakeToolCallingProvider([[SET_SITE_A2], "Okay."]), "now at Site A2")
    assert done.run.calls[0].outcome.content["status"] == "work_site_set"
    assert work_site.from_a_save(await _active(two))  # the save window, not the day

    result = await two.say(FakeToolCallingProvider([[MASONS], "Check it."]), "4 mason")
    assert "To save · Site A2:" in result.reply.text and "📍 Change site" in titles(result.reply)


async def test_a_a_site_named_in_the_message_is_used_even_when_the_model_passes_none(two):
    """27 Oct: "Green Villa first floor wall putty 200 sqft cheythu" -> "Ee update ethu site-inte
    aanu?" because the model left the site out; the name is in the message."""
    result = await two.say(FakeToolCallingProvider([[MASONS], "Check it."]), "Site A2 ground floor 4 mason vannu")
    assert "Which site" not in result.reply.text and "Ethu site" not in result.reply.text
    assert "To save · Site A2:" in result.reply.text
    (item,) = await open_items(two)
    assert item.site == "Site A2"


async def test_a_a_name_in_the_message_beats_the_site_of_the_last_save(two):
    await _remember(two, SITE_A1)
    result = await two.say(FakeToolCallingProvider([[CEMENT], "Check it."]), "Site A2 cement vannu")
    assert "To save · Site A2:" in result.reply.text


# -- C. the model cannot write a card -----------------------------------------------------------

FAKE_CARD = "📝 To save · 4 mason for Unknown purpose\n• 4 mason"
LEAKY = [
    f"Sheri.\n{FAKE_CARD}",
    f"Sheri. {CLOSED.strip()}",
    "Sheri. [options: Replace / Add]",
    "Sheri.\nReply YES to confirm",
    "Sheri (system: nothing is written).",
    "✅ Saved: 4 mason",
]


@pytest.mark.parametrize("said", LEAKY)
async def test_c_nothing_the_model_writes_as_a_card_or_a_note_reaches_the_sender(world, said):
    result = await world.say(FakeToolCallingProvider([[MASONS], said]), "4 mason")
    text = result.reply.text
    assert reply_clean.leaks(text) == []
    assert "Unknown purpose" not in text and "Reply YES" not in text and "[options" not in text
    assert "✅ Saved" not in text
    assert titles(result.reply) == ["✅ Save", "❌ Cancel"]  # the card is the code's


@pytest.mark.parametrize("said", LEAKY)
async def test_c_property_every_to_save_text_has_a_real_card_with_buttons(two, said):
    """Whatever the model wrote and whether or not the turn made a card, a reply that says
    "To save" has the card's buttons under it."""
    for calls in ([[MASONS]], [[]], [[CEMENT]]):
        result = await two.say(FakeToolCallingProvider([*calls, said]), "Site A2 4 mason")
        text = result.reply.text
        if "To save" in text:
            assert dr.SAVE_TITLE in titles(result.reply) or any("Cancel" in t for t in titles(result.reply)), text
        assert reply_clean.leaks(text) == []
        draft = await two.drafts.open_for(two.actor.organization_id, two.actor.user_id)
        if draft is not None:
            await two.drafts.discard(draft.id)


async def test_c_a_second_sentence_of_the_model_does_not_sit_above_a_card(world):
    result = await world.say(FakeToolCallingProvider([[MASONS], "Sheri, 4 mason. Njan ellam save cheythu. Venamengil paranjal."]), "4 mason")
    assert "Njan ellam" not in result.reply.text


def test_c_the_filter_keeps_plain_words_and_removes_only_the_system_text():
    assert reply_clean.clean_model_text("Sheri, 4 mason.") == "Sheri, 4 mason."
    assert reply_clean.clean_model_text("Sheri.\n📝 To save: x\n• a\n• b\nOk") == "Sheri.\nOk"
    assert reply_clean.clean_annotations("Okay (closed: not to be asked again unless the sender brings it up)") == "Okay"
    assert reply_clean.leaks(CLOSED) and reply_clean.leaks("[options: a / b]")


# -- D. what the model is shown ---------------------------------------------------------------------


def test_d_the_history_carries_the_senders_words_and_a_gist_never_a_card_or_a_note():
    turns = (
        Turn("20 rod steel", "Ethra kg aanu?\n[options: 2 / Other]", 1.0),
        Turn("6 mason vannu", f"Sheri, 6 mason vannu.\n📝 To save: 6 mason\n[options: Save / Cancel]{CLOSED}", 2.0),
        Turn("hi", "📝 To save: x\n• y", 3.0),
    )
    shown = history.for_model(turns)
    assert [t.user_text for t in shown] == ["20 rod steel", "6 mason vannu", "hi"]
    assert [t.assistant_reply for t in shown] == ["", "Sheri, 6 mason vannu.", ""]  # an old question is not re-asked


def test_d_the_guard_no_prompt_or_annotation_constant_reaches_the_model_in_draft_mode():
    from datetime import datetime

    from runtime.agent.turn import _turns_for_model

    raw = (Turn("20 rod steel", f"Ethra kg?\n[options: 2 / Other]{CLOSED}", 1.0),)
    ctx = AgentContext("Anil", "SUPERVISOR", "Acme", datetime(2026, 10, 27, 10, 0), turns=_turns_for_model(raw, 1000.0, True))
    sent = "\n".join(text for _role, text in build_messages(ctx, "ok"))
    assert CLOSED.strip(" ()") not in sent and "[options:" not in sent.split("User message:")[0].split("[context]", 1)[1].split("Understood.")[-1]
    old = AgentContext("Anil", "SUPERVISOR", "Acme", datetime(2026, 10, 27, 10, 0), turns=_turns_for_model(raw, 1000.0, False))
    assert CLOSED.strip(" ()") in "\n".join(text for _r, text in build_messages(old, "ok"))  # legacy unchanged


async def test_d_the_open_questions_are_in_the_state_block(world):
    world.catalog = _SteelCatalog()
    await world.say(FakeToolCallingProvider([[STEEL], "Ethra kg?"]), "20 rod steel use cheythu")
    draft = await world.drafts.open_for(world.actor.organization_id, world.actor.user_id)
    line = dr.context_line(draft)
    assert "Waiting for their answer (item 1): How many kg is 20 rod?" in line


# -- E. the polish of [130] -------------------------------------------------------------------------


async def test_e2_an_item_released_onto_the_card_is_not_also_listed_as_not_saved(two):
    """27 Oct: after the site pick merged two messages into one card, it ended with
    "Not saved (Green Villa first floor wall putty 200 sqft cheythu):" and nothing after it,
    although that item IS on the card (the call came back "drafted", not "saved")."""
    # WA-81: the line waits on the card for its site; the site's button settles it there
    # (the [111] queue and its "Not saved (...)" lines are not used with draft cards).
    first = await two.say(FakeToolCallingProvider([[MASONS], "Which site?"]), "4 mason")
    assert not [line for line in first.toolbox.system_lines if line.startswith("Not saved")]
    picked = await tap(two, first.reply, "Site A2")
    assert "Not saved" not in picked.text
    (item,) = await open_items(two)
    assert item.site == "Site A2" and item.state == dr.OK


class _CountCatalog(_Catalog):
    """Plywood is counted in nos; the unit table knows "nos" only."""

    NAMES = (*_Catalog.NAMES, "plywood")

    def _row(self, name):  # noqa: ANN001, ANN202
        row = super()._row(name)
        return {**row, "default_unit_id": "u-nos"} if name == "plywood" else row

    async def resolve_unit(self, text):  # noqa: ANN001, ANN202
        return {"id": "u-nos", "code": "nos"} if text in ("nos", "no") else None

    async def get_unit(self, unit_id):  # noqa: ANN001, ANN202
        return {"id": unit_id, "code": "nos"}


@pytest.mark.parametrize("unit", ["sheets", "pcs", "pieces", "Nos", "numbers"])
async def test_e3_sheets_pieces_and_numbers_are_the_same_count_as_nos(world, unit):
    world.catalog = _CountCatalog()
    call = ("save_material_receipt", {"material": "plywood", "quantity": 10, "unit": unit})
    result = await world.say(FakeToolCallingProvider([[call], "Check it."]), "10 plywood received")
    assert "counted in" not in result.reply.text and "How much" not in result.reply.text
    (item,) = await open_items(world)
    assert item.state == dr.OK and "10" in item.summary


async def test_e3_a_unit_that_is_not_a_count_still_asks(world):
    world.catalog = _CountCatalog()
    call = ("save_material_receipt", {"material": "plywood", "quantity": 2, "unit": "loads"})
    await world.say(FakeToolCallingProvider([[call], "Check it."]), "2 loads plywood")
    (item,) = await open_items(world)
    assert item.state == dr.NEEDS_ANSWER


def test_e4_hindi_in_english_letters_is_replied_to_in_hindi():
    from runtime.agent.prompt import is_hinglish, reply_language, reply_letters_rule

    text = "aaj Green Villa mein 3 mistri aur 2 labour aaye"
    assert is_hinglish(text) and reply_language(text) == "hinglish"
    assert "Hindi typed in English letters" in reply_letters_rule(text)
    assert reply_language("innu 3 mason vannu") == "manglish"  # Manglish keeps winning
    assert reply_language("3 masons came today") == "english"
    from runtime.agent.prompt import SYSTEM_PROMPT

    assert "mistri = mason" in SYSTEM_PROMPT and "never tell them to select one" in SYSTEM_PROMPT


def test_e5_the_holiday_card_names_the_site():
    from zoneinfo import ZoneInfo

    from runtime.agent.action_entry import conditions_summary

    # India's date, as the summary's: UTC's date is "yesterday" there from 18:30 UTC.
    today = dt.datetime.now(ZoneInfo("Asia/Kolkata")).date()
    assert conditions_summary({"site_working": "none"}, today, "Asia/Kolkata", site="Site B").startswith("Site B: Holiday")
    line = conditions_summary({"site_working": "half"}, today, "Asia/Kolkata", site="Site B")
    assert line == "Site working: Half day"


@pytest.mark.parametrize(
    "text",
    ["enikku enthokke cheyyan pattum? help", "help", "what can you do", "Enthokke cheyyan pattum"],
)
def test_e6_the_help_question_is_recognised_with_a_trailing_help(text):
    from runtime.persona import is_what_can_you_do

    assert is_what_can_you_do(text)


def test_e6_the_help_lists_only_the_enabled_modules_with_three_examples():
    from runtime.persona import what_can_you_do

    text = what_can_you_do("Malayalam", "latin", "enikku enthokke cheyyan pattum? help", ["labour", "materials", "dpr"])
    assert "6 mason vannu" in text and "50 bags cement vannu" in text and "plastering 2nd floor 60% aayi" in text
    assert "xpense" not in text and "paid" not in text.lower()
    english = what_can_you_do(None, None, "help", ["labour", "finance"])
    assert "6 masons came" in english and "paid 5000" in english and "cement" not in english
    assert what_can_you_do(None, None, "help") == what_can_you_do(None, None, "help", None)  # no modules: the general help


def test_e7_an_issue_open_since_an_earlier_day_says_since():
    from runtime.agent.project_day import mark_carried_over

    today = dt.date(2026, 10, 27)
    work = {"open_issues": [{"occurred_at": "2026-10-24T09:00:00+00:00"}, {"occurred_at": "2026-10-27T08:00:00+00:00"}, {"occurred_at": None}]}
    mark_carried_over(work, today)
    first, second, third = work["open_issues"]
    assert first["carried_over"] and first["since"] == "24 Oct"
    assert second["carried_over"] is False and "since" not in second
    assert "since" not in third
