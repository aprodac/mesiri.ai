# ruff: noqa: F811
"""WA-81 (plan of 27 Oct, phase 2): the open draft is the one record of what is
pending, and code answers the card's questions.

The live rounds of 27 Oct (docs/qa/runs/2026-10-27-whatsapp-live-tests) failed
where two stores disagreed: "which site?" lived in the [111] queue, which told
the sender "not saved, send it again" while the draft kept the card open and
brought it back 30 minutes later (#4314, #4322, #4331); and the answer to "How
many kg is 20 rod?" went back to the model, which asked the site, then showed
the steel line twice and lost the 12 kg (#4338-#4342).

Now "which site?" is a question of the card, answered once for every line
waiting on it, and a typed answer (a site's name, "oru rod 12 kg") is read by
code. The model is scripted; everything after it is the real journey.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from tests.replay.test_draft_per_message_p1 import _Workforce, open_items, titles
from tests.replay.test_draft_per_message_p3 import (  # noqa: F401  (fixtures)
    CEMENT,
    MASONS,
    STEEL,
    _SteelCatalog,
    at,
    tap,
    two,
)

from mesiri_ai.fakes import FakeToolCallingProvider
from runtime.agent import draft as dr
from runtime.agent import draft_answer

HELPERS = ("save_labour", {"workers": [{"trade": "helper", "headcount": 2}]})


async def typed(world, text: str):  # noqa: ANN001, ANN201
    """A typed message as the journey reads it before the model (message_journey._run_agent)."""
    draft = await world.drafts.open_for(world.actor.organization_id, world.actor.user_id)
    return await world.gateway(text).answer_draft_typed(draft, text) if draft is not None else None


# -- W1: "which site?" is a question of the card -------------------------------------------


async def test_a_line_with_no_site_waits_on_the_card_with_the_sites_as_buttons(two):
    result = await two.say(FakeToolCallingProvider([[MASONS], "Okay."]), "ഇന്ന് 4 മേസൺ വന്നു")
    (item,) = await open_items(two)
    assert item.needs_site and item.state == dr.NEEDS_ANSWER
    assert "4 mason" in result.reply.text and "📍" in result.reply.text
    assert {"Site A1", "Site A2"} <= set(titles(result.reply))
    assert "✅ Save" not in titles(result.reply)  # nothing is ready yet
    assert not [line for line in result.toolbox.system_lines if "not saved" in line.casefold()]


async def test_the_site_tap_settles_the_line_and_save_appears(two):
    result = await two.say(FakeToolCallingProvider([[MASONS], "Okay."]), "4 mason")
    card = await tap(two, result.reply, "Site A2")
    (item,) = await open_items(two)
    assert item.state == dr.OK and item.site == "Site A2"
    assert "4 workers (4 mason)" in card.text
    assert "✅ Save" in titles(card)


async def test_one_answer_settles_every_line_waiting_for_the_site(two):
    await two.say(FakeToolCallingProvider([[MASONS], "Okay."]), "4 mason")
    result = await two.say(FakeToolCallingProvider([[CEMENT], "Okay."]), "100 bags cement vannu")
    assert len(await open_items(two)) == 2
    await tap(two, result.reply, "Site A2")
    items = await open_items(two)
    assert [i.state for i in items] == [dr.OK, dr.OK]
    assert {i.site for i in items} == {"Site A2"}


async def test_the_site_typed_answers_it_without_the_model(two):
    await two.say(FakeToolCallingProvider([[MASONS], "Okay."]), "4 mason")
    card = await typed(two, "Site A2")
    assert card is not None and "4 workers (4 mason)" in card.text
    (item,) = await open_items(two)
    assert item.state == dr.OK and item.site == "Site A2"


async def test_an_update_that_names_a_site_is_not_taken_as_the_answer(two):
    await two.say(FakeToolCallingProvider([[MASONS], "Okay."]), "4 mason")
    assert await typed(two, "Site A2 2 helper vannu") is None  # the model reads it


async def test_a_waiting_labour_line_joins_the_labour_of_its_site_once_answered(two):
    await two.say(FakeToolCallingProvider([[MASONS], "Okay."]), "4 mason")
    result = await two.say(FakeToolCallingProvider([[at("Site A2", HELPERS)], "Okay."]), "Site A2 2 helper vannu")
    assert len(await open_items(two)) == 2  # the waiting line was not replaced by the update
    card = await tap(two, result.reply, "Site A2")
    (item,) = await open_items(two)
    assert "6 workers" in item.summary and "4 mason" in item.summary and "2 helper" in item.summary
    assert card.text.count("workers") == 1


async def test_a_card_for_one_site_gives_its_site_to_a_line_that_names_none(two):
    """Live 27 Oct (#4300s): "which site?" asked inside a card that already said Green Villa."""
    first = await two.say(FakeToolCallingProvider([[at("Site A2", CEMENT)], "Okay."]), "Site A2 100 bags cement vannu")
    assert "*To save* · Site A2" in first.reply.text
    result = await two.say(FakeToolCallingProvider([[MASONS], "Okay."]), "4 mason")
    assert all(i.state == dr.OK and i.site == "Site A2" for i in await open_items(two))
    assert "📍 Which" not in result.reply.text and "Site A1" not in titles(result.reply)


async def test_another_message_never_says_the_waiting_line_was_not_saved(two):
    """Live 27 Oct (#4314): "Site select cheyyaathathu kondu save cheythilla" while the card
    stayed open, and it came back 30 minutes later merged with a new count (#4331)."""
    await two.say(FakeToolCallingProvider([[MASONS], "Okay."]), "4 mason")
    asked = await two.say(
        FakeToolCallingProvider([[("query_labour", {"site": "Site A2"})], "Nobody yet."]), "labour at Site A2?"
    )
    assert not [line for line in asked.toolbox.system_lines if "save" in line.casefold()]
    (item,) = await open_items(two)
    assert item.needs_site  # still on the card, as the card says


async def test_a_second_count_merged_after_the_site_answer_still_asks_replace_or_add(two):
    two.workforce = _Workforce([{"trade": "mason", "headcount": 5}, {"trade": "helper", "headcount": 2}])
    await two.say(FakeToolCallingProvider([[MASONS], "Okay."]), "4 mason")
    result = await two.say(FakeToolCallingProvider([[CEMENT], "Okay."]), "100 bags cement vannu")
    card = await tap(two, result.reply, "Site A2")
    assert "Today already 7 workers" in card.text
    assert {"Replace", "Add"} <= set(titles(card))


# -- W2: code reads the typed amount ---------------------------------------------------------


@pytest.mark.parametrize(
    "text, amount",
    [
        ("oru rod 12 kg", Decimal(240)),
        ("1 rod = 12 kg", Decimal(240)),
        ("per rod 12 kg", Decimal(240)),
        ("240 kg", Decimal(240)),
        ("240", Decimal(240)),
        ("12.5 kg", Decimal("12.5")),
        ("Green Villa 2 helper vannu", None),  # an update, not an answer
        ("ethra aanu?", None),
        ("20 bags", None),  # another unit
    ],
)
def test_the_amount_answer(text, amount):
    assert draft_answer.amount_answer(text, {"quantity": 20, "unit": "rod"}, "kg") == amount


async def test_steel_in_rods_keeps_its_site_and_the_typed_kg_makes_it_a_line_to_save(two):
    """Live 27 Oct (#4337-#4344): the steel line had no site, its answer asked "which
    site?", the line showed twice and could never be saved."""
    two.catalog = _SteelCatalog()
    first = await two.say(
        FakeToolCallingProvider([[STEEL], "Sorry, 20 rod steel use cheythu ennu record cheyyan kazhinjilla."]),
        "Site A2: 20 rod steel use cheythu",
    )
    assert "Sorry" not in first.reply.text  # the line IS on the card, waiting on its question
    (item,) = await open_items(two)
    assert item.site == "Site A2" and item.answer_unit == "kg"
    card = await typed(two, "oru rod 12 kg")
    assert card is not None
    (item,) = await open_items(two)
    assert item.state == dr.OK and "240 kg" in item.summary
    assert card.text.startswith("20 rod = 240 kg.")
    lines = [ln for ln in card.text.splitlines() if ln.strip().startswith("•") or "Steel" in ln]
    assert len([ln for ln in lines if "Steel" in ln]) == 1
    assert "✅ Save" in titles(card)
    assert "Which site" not in card.text


async def test_the_same_steel_call_after_its_site_is_one_line_not_two(two):
    two.catalog = _SteelCatalog()
    await two.say(FakeToolCallingProvider([[STEEL], "Okay."]), "20 rod steel use cheythu")
    await two.say(FakeToolCallingProvider([[at("Site A2", STEEL)], "Okay."]), "Site A2")
    steel = [i for i in await open_items(two) if i.tool == STEEL[0]]
    assert len(steel) == 1
