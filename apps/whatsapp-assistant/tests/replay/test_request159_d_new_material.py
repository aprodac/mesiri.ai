"""Request 159 (D): a material that is not in the list is added right where it came
in or was used, by anyone, with one tap or a typed "add".

Live 30 Oct (midlaj, SITE_ENGINEER): "2 ton TMT kambi vannu" -> "TMT steel bars isn't in
the material list. Which one is it?" with Fevi Stick / fevicol / sand ...; "Add Tmt
steel bars material" -> "I don't have it"; "TMT steel" -> "That wasn't saved ...".

The model is scripted; the card, the typed answer, the add and the Save are the real
journey.
"""

from __future__ import annotations

import dataclasses

import pytest
from tests.replay.test_agent_replay import _Catalog, _make_world, _MemoryRedis
from tests.replay.test_draft_per_message_p1 import open_items, titles

from context import ContextResolver, seed
from mesiri.domains.organizations import settings
from mesiri_ai.fakes import FakeToolCallingProvider
from runtime.agent import draft as dr
from runtime.agent.cards import CardStore
from runtime.agent.draft_store import MemoryDraftStore
from runtime.agent.material_entry import MaterialEntry

TMT = ("save_material_receipt", {"material": "Tmt steel bars", "quantity": 2, "unit": "tons"})


class _Settings:
    """The company never touched its settings: the default list applies."""

    async def get(self, *, organization_id, key):  # noqa: ANN001
        return settings.default_for(key)

    async def enabled_modules(self, *, organization_id):  # noqa: ANN001
        return ["dpr", "labour", "materials"]


class _AddingCatalog(_Catalog):
    def __init__(self) -> None:
        self.created: list[str] = []

    async def resolve_unit(self, text):  # noqa: ANN001
        return {"id": "u-ton", "name": "ton"} if text.startswith("ton") else None

    async def create_material(self, *, organization_id, name, unit_id, created_by):  # noqa: ANN001
        self.created.append(name)
        return {"id": "00000000-0000-4000-8000-0000000000aa", "name": name, "default_unit_id": unit_id, "is_active": True}


@pytest.fixture(params=["SITE_ENGINEER", "FINANCE", "PROJECT_MANAGER", "ADMIN"])
async def world(request):
    world = await _make_world(site_keys=(seed.SITE_A1,))
    world.actor = dataclasses.replace(world.actor, role=request.param)
    world.draft_v2 = True
    world.drafts = MemoryDraftStore()
    world.cards = CardStore(_MemoryRedis())
    world.catalog = catalog = _AddingCatalog()
    make = world.gateway

    def gateway(text, *a, **kw):
        gw = make(text, *a, **kw)
        gw.material_entry = MaterialEntry(
            ContextResolver(world.deps), catalog, None, _Settings(), world.actor,
            active_context=world.deps.active_context,
        )
        return gw

    world.gateway = gateway
    return world


async def _asked(world):
    result = await world.say(FakeToolCallingProvider([[TMT], "Add it?"]), "innu 2 ton TMT kambi vannu")
    return result.reply


async def test_anyone_is_asked_to_add_it_on_the_line_with_a_one_tap_button(world):
    reply = await _asked(world)
    assert "Tmt steel bars in: 2 tons" in reply.text
    assert "Add it as a new material?" in reply.text
    assert "➕ Add Tmt steel bars" in titles(reply)
    assert world.catalog.created == [] and world.dispatcher.dispatched == []


@pytest.mark.parametrize("typed", ["Add Tmt steel bars material", "TMT steel", "yes"])
async def test_a_typed_add_is_the_answer_and_the_line_is_ready_to_save(world, typed):
    await _asked(world)
    draft = await world.drafts.open_for(world.actor.organization_id, world.actor.user_id)
    card = await world.gateway(typed).answer_draft_typed(draft, typed)

    assert card is not None and world.catalog.created == ["Tmt steel bars"]
    (item,) = await open_items(world)
    assert item.state == dr.OK and "❓" not in card.text
    saved = await world.gateway("tap").save_draft(
        await world.drafts.open_for(world.actor.organization_id, world.actor.user_id)
    )
    assert saved.text.startswith("✅ *Saved*") and len(world.dispatcher.dispatched) == 1


async def test_a_new_update_while_the_question_waits_is_not_taken_for_the_answer(world):
    await _asked(world)
    draft = await world.drafts.open_for(world.actor.organization_id, world.actor.user_id)
    assert await world.gateway("3 mason vannu").answer_draft_typed(draft, "3 mason vannu") is None
    assert world.catalog.created == []


# -- request 159 (E): Cancel says what stayed saved -----------------------------------

CEMENT = ("save_material_receipt", {"material": "cement", "quantity": 50, "unit": "bags"})


async def test_cancel_after_a_partial_save_names_what_stayed_saved(world):
    result = await world.say(FakeToolCallingProvider([[CEMENT, TMT], "Check it."]), "50 bag cement, 2 ton TMT vannu")
    rows = [*(result.reply.buttons or ()), *(result.reply.list_rows or ())]
    save = next(r for r in rows if r.title.startswith("✅ Save"))
    _, draft_id, _ = dr.parse_tap(save.id)
    saved = await world.gateway("tap").save_draft(await world.drafts.get(draft_id, world.actor.organization_id, world.actor.user_id))
    assert "still need" in saved.text and len(world.dispatcher.dispatched) == 1

    rest = await world.drafts.open_for(world.actor.organization_id, world.actor.user_id)
    cancelled = await world.gateway("tap").cancel_draft(rest)
    assert cancelled.text == "❌ Cancelled the rest. Already saved: Cement in: 50 bags."
    assert "nothing saved" not in cancelled.text


async def test_cancel_of_a_card_never_saved_still_says_nothing_was_saved(world):
    await _asked(world)
    draft = await world.drafts.open_for(world.actor.organization_id, world.actor.user_id)
    cancelled = await world.gateway("tap").cancel_draft(draft)
    assert cancelled.text == dr.CANCELLED
