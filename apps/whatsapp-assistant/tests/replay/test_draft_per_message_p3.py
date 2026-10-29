"""Request 129 (replaces 128): the live re-test of P2 on 27 Oct.

A. A unit question the sender cannot answer by tap ("20 rod" of steel, counted in
   kg) is a line of the card, "Steel used: 20 rod (❓ How many kg is 20 rod?)".
B. The site of an update that names none, in order: one site -> it; named -> it;
   a save in the last 3 hours on one site -> preselected and shown with
   "📍 Change site" (which moves every item); otherwise asked. Never from a
   cancelled card, a team / setup message or a question.
C. Wording: a correction is pending until Save; the Yes / No note is in the
   sender's language and second person; a card with no Save button says what to
   tap; typed "cancel" / "venda" is the Cancel button.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
from types import SimpleNamespace

import pytest
from tests.replay.test_agent_replay import _Catalog, _make_world
from tests.replay.test_draft_per_message_p1 import TODAY_13, _Workforce, open_items, titles

from channel.replies import ListRow
from context import seed
from mesiri_ai.fakes import FakeToolCallingProvider
from runtime.agent import draft as dr
from runtime.agent import work_site
from runtime.agent.draft_store import MemoryDraftStore

STEEL = ("save_material_usage", {"material": "steel", "quantity": 20, "unit": "rod"})
CEMENT = ("save_material_receipt", {"material": "cement", "quantity": 100, "unit": "bags"})
SITE_A1, SITE_A2 = seed.SITE_A1, seed.SITE_A2
MASONS = ("save_labour", {"workers": [{"trade": "mason", "headcount": 4}]})


def at(site: str, call: tuple[str, dict]) -> tuple[str, dict]:
    return call[0], {**call[1], "site": site}


class _SteelCatalog(_Catalog):
    """Steel is counted in kg; "rod" is not a unit we know."""

    def _row(self, name):  # noqa: ANN001, ANN202
        row = super()._row(name)
        return {**row, "default_unit_id": "u-kg"} if name == "steel" else row

    async def resolve_unit(self, text):  # noqa: ANN001, ANN202
        return {"id": "u-kg", "code": "kg"} if text in ("kg", "kgs") else None

    async def get_unit(self, unit_id):  # noqa: ANN001, ANN202
        return {"id": unit_id, "code": "kg"}


async def tap(world, reply, title: str, drafts=True):  # noqa: ANN001, ANN201
    """The tap on ``title`` as the journey's tap handler runs it (message_journey._draft_tap_reply)."""
    rows = [*(reply.buttons or ()), *(reply.list_rows or ())]
    row = next(r for r in rows if r.title.startswith(title) or r.title.endswith(title))
    action, draft_id, extra = dr.parse_tap(row.id)
    draft = await world.drafts.get(draft_id, world.actor.organization_id, world.actor.user_id)
    gateway = world.gateway("tap")
    if action == dr.SAVE:
        return await gateway.save_draft(draft)
    if action == dr.CANCEL:
        return await gateway.cancel_draft(draft)
    if action == dr.CHANGE_SITE:
        return gateway.change_site_draft(draft)
    if action == dr.MOVE_SITE:
        return await gateway.move_draft_site(draft, extra[0])
    return await gateway.answer_draft(draft, extra[0], int(extra[1]))


async def only_waiting_for_site(world) -> bool:  # noqa: ANN001
    """WA-81: what asks "which site?" is a line of the card waiting for it (nothing
    ready to save yet), not a call held in a queue of its own."""
    items = await open_items(world)
    return bool(items) and all(i.needs_site for i in items)


@pytest.fixture
async def world():
    world = await _make_world(site_keys=(seed.SITE_A1,))
    world.draft_v2, world.drafts = True, MemoryDraftStore()
    return world


@pytest.fixture
async def two():
    """Two sites, nothing remembered: the sender's first message of the day. Their
    projects and sites carry the database's ids, as in production, where the context
    layer's id and the database's are one (the seed company's readable ids are its own)."""
    world = await _make_world(site_keys=(seed.SITE_A1, seed.SITE_A2))
    world.draft_v2, world.drafts = True, MemoryDraftStore()
    project, site = type(world.actor.projects[0]), type(world.actor.sites[0])
    project_id = await world.deps.bridge.canonical_project_id(seed.PROJ_ALPHA)
    world.actor = dataclasses.replace(
        world.actor,
        projects=[project(id=project_id, name="Project Alpha")],
        sites=[site(id=world.site_ids[s.id], name=s.name, project_id=project_id) for s in world.actor.sites],
    )
    world.project_id = project_id
    return world


def _clock(world, later: dt.timedelta) -> None:  # noqa: ANN001
    """The context layer's clock moves ``later`` ahead."""
    world.deps.active_context._clock = lambda: dt.datetime.now(dt.UTC) + later


async def _remember(world, site_key: str) -> None:  # noqa: ANN001
    """What a Save of a site update at ``site_key`` writes (work_site.remember_saved_site)."""
    await work_site.remember_saved_site(
        world.deps.active_context,
        organization_id=seed.ORG_A,
        user_id=seed.USER_ENGINEER,
        project_id=world.project_id,
        site_id=world.site_ids[site_key],
        own_site_ids={s.id for s in world.actor.sites},
        timezone=None,
    )


async def _active(world):  # noqa: ANN001, ANN202
    return await world.deps.active_context.get_active_context(organization_id=seed.ORG_A, user_id=seed.USER_ENGINEER)


# -- A. the unit question is a line of the card ------------------------------------------


async def test_a_steel_in_rods_is_a_card_line_with_its_question_and_cement_saves_on_its_own(world):
    world.catalog = _SteelCatalog()
    result = await world.say(
        FakeToolCallingProvider([[STEEL, CEMENT], "Ethra kg aanu 20 rod?"]), "20 rod steel use cheythu, 100 bags cement vannu"
    )
    text = result.reply.text
    assert "Cement in: 100 bags" in text
    assert "Steel used: 20 rod (❓ How many kg is 20 rod?)" in text  # on the card, not only in the words
    assert "✅ Save" in titles(result.reply)

    out = await tap(world, result.reply, "Save")
    assert len(world.dispatcher.dispatched) == 1  # the cement; steel is not written
    (left,) = await open_items(world)
    assert left.pending_answer and "20 rod" in left.summary
    assert "Steel used: 20 rod" in out.text  # the card for steel stays

    typed = await world.say(
        FakeToolCallingProvider([[("save_material_usage", {"material": "steel", "quantity": 600, "unit": "kg"})], "Check it."]),
        "600 kg",
    )
    (item,) = await open_items(world)
    assert item.state == dr.OK and item.summary.startswith("Steel used: 600 kg")
    assert "❓" not in typed.reply.text


# -- B. which site ---------------------------------------------------------------------------


async def test_b1_a_sender_on_one_site_is_never_asked(world):
    result = await world.say(FakeToolCallingProvider([[MASONS], "Check it."]), "4 mason")
    assert "Which site" not in result.reply.text and titles(result.reply) == ["✅ Save", "❌ Cancel"]


async def test_b2_a_site_named_in_the_message_is_that_site(two):
    result = await two.say(FakeToolCallingProvider([[at("Site A2", MASONS)], "Check it."]), "Site A2: 4 mason")
    assert "*To save* · Site A2:" in result.reply.text
    assert titles(result.reply) == ["✅ Save", "❌ Cancel", "📍 Change site"]  # always, on several sites


async def test_b3_within_three_hours_of_a_save_the_site_is_preselected_shown_and_changeable(two):
    await _remember(two, SITE_A2)
    _clock(two, dt.timedelta(hours=2, minutes=59))
    result = await two.say(FakeToolCallingProvider([[CEMENT], "Check it."]), "cement vannu")  # names no site
    assert "Which site" not in result.reply.text
    assert "*To save* · Site A2:" in result.reply.text  # the site, plainly, before Save
    assert titles(result.reply) == ["✅ Save", "❌ Cancel", "📍 Change site"]
    (item,) = await open_items(two)
    assert item.site == "Site A2"


async def test_b3_after_three_hours_the_site_is_asked_again(two):
    await _remember(two, SITE_A2)
    _clock(two, dt.timedelta(hours=3, minutes=1))
    result = await two.say(FakeToolCallingProvider([[CEMENT], "Which site?"]), "cement vannu")
    assert await only_waiting_for_site(two)  # WA-81: on the card, asking where
    assert {"Site A1", "Site A2"} <= set(titles(result.reply))  # the sites to pick from


async def test_b4_nothing_saved_yet_asks_which_site_before_any_card(two):
    result = await two.say(FakeToolCallingProvider([[CEMENT], "Which site?"]), "cement vannu")
    assert await only_waiting_for_site(two)  # WA-81: on the card, asking where
    assert {"Site A1", "Site A2"} <= set(titles(result.reply))


async def test_b_saves_on_two_sites_inside_the_window_ask_again(two):
    await _remember(two, SITE_A2)
    await _remember(two, SITE_A1)
    assert await _active(two) is None
    result = await two.say(FakeToolCallingProvider([[MASONS], "Which site?"]), "4 mason")
    assert await only_waiting_for_site(two)  # WA-81: on the card, asking where
    assert {"Site A1", "Site A2"} <= set(titles(result.reply))


async def test_b_a_save_makes_its_site_the_one_for_the_next_three_hours_only(two):
    result = await two.say(FakeToolCallingProvider([[at("Site A2", MASONS)], "Check it."]), "Site A2 4 mason")
    assert await _active(two) is None  # nothing is remembered from a card still open
    await tap(two, result.reply, "Save")
    active = await _active(two)
    assert active is not None and work_site.from_a_save(active)


async def test_b_a_cancelled_card_never_makes_its_site_the_default(two):
    result = await two.say(FakeToolCallingProvider([[at("Site A2", MASONS)], "Check it."]), "Site A2 4 mason")
    await tap(two, result.reply, "Cancel")
    assert await _active(two) is None
    again = await two.say(FakeToolCallingProvider([[CEMENT], "Which site?"]), "cement vannu")
    assert await only_waiting_for_site(two)  # WA-81: on the card, asking where
    assert {"Site A1", "Site A2"} <= set(titles(again.reply))


@pytest.mark.parametrize("key", ["ADD_PROJECT_MEMBER", "SITE_CREATE"])
async def test_b_a_team_or_setup_message_never_makes_its_site_the_default(two, key):
    from mesiri_contracts.assistant.planner_decision import WorkflowKey
    from runtime.agent.change_entry import ChangeEntry

    entry = ChangeEntry(None, None, two.actor, active_context=two.deps.active_context)
    ready = SimpleNamespace(
        decision=SimpleNamespace(workflow_key=WorkflowKey[key]),
        scope=(seed.ORG_A, seed.USER_ENGINEER, two.project_id, two.site_ids[SITE_A2]),
    )
    await entry.remember(ready)
    assert await _active(two) is None
    result = await two.say(FakeToolCallingProvider([[MASONS], "Which site?"]), "4 mason")
    assert await only_waiting_for_site(two)  # WA-81: on the card, asking where
    assert {"Site A1", "Site A2"} <= set(titles(result.reply))


async def test_b_a_question_never_makes_its_site_the_default(two):
    asked = await two.say(FakeToolCallingProvider([[("query_labour", {"site": "Site A2"})], "Nobody yet."]), "labour at Site A2?")
    assert asked.reply.text
    assert await _active(two) is None


async def test_b_a_site_the_sender_said_lasts_the_day_not_three_hours(two):
    store = two.deps.active_context
    await store.set_active_context(
        organization_id=seed.ORG_A, user_id=seed.USER_ENGINEER, project_id=two.project_id,
        site_id=two.site_ids[SITE_A1], ttl_seconds=10 * 3600,
    )
    _clock(two, dt.timedelta(hours=5))
    assert not work_site.from_a_save(await _active(two))
    await _remember(two, SITE_A2)  # a save at another site does not move it (V1 audit SIT-05)
    assert (await _active(two)).site_id == two.site_ids[SITE_A1]


async def test_b_change_site_moves_every_item_of_the_card(two):
    await _remember(two, SITE_A2)
    result = await two.say(FakeToolCallingProvider([[CEMENT, MASONS], "Check it."]), "cement and 4 mason")
    assert {i.site for i in await open_items(two)} == {"Site A2"}

    picker = await tap(two, result.reply, "Change site")
    assert titles(picker) == ["Site A1"]  # the card is on A2: the other site(s) to pick
    moved = await tap(two, picker, "Site A1")
    assert "Moved to Site A1" in moved.text and "*To save* · Site A1:" in moved.text
    assert {i.site for i in await open_items(two)} == {"Site A1"}
    assert len(await open_items(two)) == 2 and titles(moved) == ["✅ Save", "❌ Cancel", "📍 Change site"]

    await tap(two, moved, "Save")
    assert len(two.dispatcher.dispatched) == 2
    assert all(str(x.draft_action.site_id) == two.site_ids[SITE_A1] for x in two.dispatcher.dispatched)


async def test_b_change_site_to_a_site_that_is_not_theirs_changes_nothing(two):
    await two.say(FakeToolCallingProvider([[at("Site A2", MASONS)], "Check it."]), "Site A2 4 mason")
    draft = await two.drafts.open_for(two.actor.organization_id, two.actor.user_id)
    out = await two.gateway("x").move_draft_site(draft, "someone-elses-site")
    assert "isn't one of yours" in out.text
    assert {i.site for i in await open_items(two)} == {"Site A2"}


def test_b_the_change_site_taps_are_draft_taps():
    draft_id = "a" * 32
    assert dr.parse_tap(dr.tap_id(dr.CHANGE_SITE, draft_id)) == (dr.CHANGE_SITE, draft_id, ())
    assert dr.parse_tap(dr.tap_id(dr.MOVE_SITE, draft_id, "s1")) == (dr.MOVE_SITE, draft_id, ("s1",))
    assert dr.parse_tap(dr.tap_id(dr.MOVE_SITE, draft_id)) is None
    assert dr.parse_tap(dr.tap_id(dr.CHANGE_SITE, draft_id, "x")) is None


# -- C. wording ------------------------------------------------------------------------------


async def test_c_a_correction_is_told_to_the_model_as_pending(world):
    result = await world.say(FakeToolCallingProvider([[MASONS], "Check it."]), "4 mason")
    assert "CHANGE" not in str(result.run.calls[0].outcome.content)  # a new line is not a change
    fix = ("update_pending_card", {"item_index": 1, "changes": {"workers": [{"trade": "mason", "headcount": 5}]}})
    fixed = await world.say(FakeToolCallingProvider([[fix], "Sheri."]), "alla, 5 mason")
    instruction = fixed.run.calls[0].outcome.content["instruction"]
    assert "waits for their Save tap" in instruction and "never in the past tense" in instruction


async def test_c_the_yes_no_note_is_in_the_senders_language_and_second_person(world):
    async def waiting() -> bool:
        return True

    for text, expected in [
        ("4 masons came today", "Note: you still have a Yes / No question waiting above."),
        ("innu 4 mason vannu, pani nadannu", "mukalil oru Yes / No question baakiyundu"),
        ("ഇന്ന് 4 മേസൺ വന്നു", "മുകളിൽ ഒരു Yes / No ചോദ്യം ബാക്കിയുണ്ട്"),
    ]:
        gateway = world.gateway(text)
        gateway.pending_confirmation = waiting
        from runtime.agent import draft_flow

        note = await draft_flow._pending_note(gateway)
        assert expected in note and "of theirs" not in note


async def test_c_a_card_with_no_save_button_says_what_to_tap(world):
    world.workforce = _Workforce(TODAY_13)
    provider = FakeToolCallingProvider(
        [[("save_labour", {"workers": [{"trade": "mason", "headcount": 6}]})], "Sheri, 6 mason. Nokki Save tap cheyyu."]
    )
    result = await world.say(provider, "innu 6 mason vannu")
    assert titles(result.reply) == ["❌ Cancel", "Replace", "Add"]
    assert "Save tap" not in result.reply.text  # there is nothing to Save yet
    assert "Replace or Add tap cheyyu" in result.reply.text


def test_c_typed_cancel_and_venda_are_the_cancel_button():
    from runtime.reply_composer import resolve_choice

    draft_id = "b" * 32
    rows = [
        ListRow(dr.tap_id(dr.SAVE, draft_id), dr.SAVE_TITLE),
        ListRow(dr.tap_id(dr.CANCEL, draft_id), dr.CANCEL_TITLE),
    ]
    for word in ("cancel", "Cancel.", "venda", "വേണ്ട", "cancel that"):
        assert resolve_choice(word, rows) is rows[1], word
    assert resolve_choice("4 mason", rows) is None
