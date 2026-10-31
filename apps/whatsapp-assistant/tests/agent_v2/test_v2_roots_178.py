"""Request 178: the five roots of the 31 Oct live test (12/21 right, 3 would-be wrong saves).

Each test is the class (the reported message), a sibling, and the guard (what must not change).
The model is scripted; everything after it is the real journey, as in the other v2 tests.
"""

from __future__ import annotations

import pytest
from tests.agent_v2.evalkit import _Books, _given
from tests.replay.test_agent_replay import _Catalog, _make_world
from tests.replay.test_draft_per_message_p1 import open_items

from agent_v2.agents.main import MainAgent, catalog_text, likely_duplicates, v2_card_words
from agent_v2.runner import V2Runner
from agent_v2.skills.materials import tools as skill
from context import seed
from mesiri_ai.fakes import FakeToolCallingProvider
from runtime.agent import draft as dr
from runtime.agent.draft_store import MemoryDraftStore
from runtime.agent.runner import AgentRunner

CEMENT_25 = ("draft_receipt", {"material": "cement", "quantity": 25, "unit": "bags"})
SAND_2 = ("draft_usage", {"material": "sand", "quantity": 2, "unit": "load"})


@pytest.fixture
async def world():
    world = await _make_world(site_keys=(seed.SITE_A1,))
    world.draft_v2 = True
    world.drafts = MemoryDraftStore()
    world.catalog = _Catalog()
    world.inventory = _Books()
    return world


async def say_v2(world, text, script, *, given=()):
    await _given(world, {"given": [list(g) for g in given]})
    classic = FakeToolCallingProvider(["never"])
    v2 = FakeToolCallingProvider(script)
    from runtime.agent import draft as draft_card

    card = draft_card.context_line(await world.drafts.open_for(world.actor.organization_id, world.actor.user_id))
    result = await V2Runner(v2, AgentRunner(classic)).run(
        ctx=world.context(card_line=card), user_text=text, gateway=world.gateway(text), scope=world.scope(),
        correlation_id="cor_178",
    )
    return result, v2, classic


# -- root 2: change a line, remove a line ---------------------------------------------------


async def test_a_correction_replaces_the_figure_on_the_line_never_adds_a_second(world):
    change = ("change_line", {"item_index": 1, "changes": {"quantity": 35}, "unplaced": [{"figure": 25, "reason": "old figure replaced"}]})
    result, _, classic = await say_v2(world, "25... alla 35", [[change], "x"], given=[[CEMENT_25]])
    (item,) = await open_items(world)
    assert item.kind == dr.KIND_MATERIAL_IN and item.args["quantity"] == 35
    assert "did not put" not in result.reply.text  # 25 is explained: it is the figure replaced
    assert classic.calls == 0


async def test_the_correction_works_on_the_supplier_and_other_fields_too(world):
    change = ("change_line", {"item_index": 1, "changes": {"supplier": "Raju"}})
    await say_v2(world, "supplier Raju aanu", [[change], "x"], given=[[CEMENT_25]])
    (item,) = await open_items(world)
    assert item.args["supplier"] == "Raju" and item.args["quantity"] == 25


async def test_a_line_that_is_not_on_the_card_is_not_changed(world):
    change = ("change_line", {"item_index": 5, "changes": {"quantity": 35}})
    await say_v2(world, "alla 35", [[change], "x"], given=[[CEMENT_25]])
    (item,) = await open_items(world)
    assert item.args["quantity"] == 25  # guard: nothing changed, the card is as it was


async def test_remove_line_takes_one_line_off_and_keeps_the_rest(world):
    remove = ("remove_line", {"item_index": 2})
    result, _, classic = await say_v2(world, "sand venda", [[remove], "x"], given=[[CEMENT_25, SAND_2]])
    items = await open_items(world)
    assert [i.kind for i in items] == [dr.KIND_MATERIAL_IN]
    assert "Removed from the card" in result.reply.text and classic.calls == 0
    assert world.dispatcher.dispatched == []  # nothing was ever written


async def test_removing_the_only_line_discards_the_card(world):
    result, _, _ = await say_v2(world, "cement venda", [[("remove_line", {"item_index": 1})], "x"], given=[[CEMENT_25]])
    assert await open_items(world) == []
    assert "Removed from the card" in result.reply.text and not result.reply.buttons


async def test_remove_line_with_no_open_card_says_so_and_changes_nothing(world):
    result, _, _ = await say_v2(world, "cement venda", [[("remove_line", {"item_index": 1})], "There is no card."])
    assert await open_items(world) == []


def test_the_open_card_paragraph_names_the_v2_tools():
    text = "call update_pending_card with card_id abc. undo_last cancels the whole card."
    out = v2_card_words(text)
    assert "change_line" in out and "update_pending_card" not in out and "undo_last" not in out


# -- root 2: transfer, rate, unit ---------------------------------------------------------------


async def test_a_transfer_is_a_transfer_line_not_usage():
    world = await _make_world(site_keys=(seed.SITE_A1, seed.SITE_A2), usual_site=seed.SITE_A1)
    world.draft_v2, world.drafts, world.catalog = True, MemoryDraftStore(), _Catalog()
    call = ("transfer", {"material": "cement", "quantity": 20, "unit": "bags", "to_site": "Site A2"})
    result, _, classic = await say_v2(world, "20 bag cement Site A2 lekku kondupoyi", [[call], "x"])
    (item,) = await open_items(world)
    assert item.kind == dr.KIND_TRANSFER_MATERIAL and classic.calls == 0


async def test_a_receipt_with_a_rate_shows_the_rate_on_the_card(world):
    call = ("draft_receipt", {"material": "cement", "quantity": 50, "unit": "bags", "supplier": "Raju", "unit_cost": 380})
    result, _, _ = await say_v2(world, "50 bag cement vannu Raju 380 bag", [[call], "x"])
    (item,) = await open_items(world)
    assert item.args["unit_cost"] == 380 and "₹380" in item.line
    assert "₹380" in result.reply.text


async def test_a_receipt_without_a_rate_shows_none(world):  # guard
    result, _, _ = await say_v2(world, "50 bag cement vannu", [[("draft_receipt", {"material": "cement", "quantity": 50, "unit": "bags"})], "x"])
    (item,) = await open_items(world)
    assert "₹" not in item.line


async def test_the_unit_stays_as_the_sender_said_it(world):
    call = ("draft_receipt", {"material": "sand", "quantity": 5, "unit": "load"})
    await say_v2(world, "5 load sand vannu", [[call], "x"])
    (item,) = await open_items(world)
    assert item.args["unit"] == "load" and item.args["quantity"] == 5


# -- root 3: the catalog the model reads ------------------------------------------------------------


class _Wide:
    """A company with 90 materials, aliases and the Steel / TMT Steel Bars overlap."""

    async def catalog_with_aliases(self, *, organization_id):  # noqa: ANN001
        rows = [{"name": f"Material {n:02d}", "aliases": []} for n in range(88)]
        rows += [{"name": "Steel", "aliases": []}, {"name": "TMT Steel Bars", "aliases": ["kambi", "കമ്പി"]}]
        return rows


async def test_the_prompt_lists_every_material_with_its_aliases_and_the_overlaps():
    line = await MainAgent(FakeToolCallingProvider([]), catalog=_Wide()).catalog_line("org")
    assert "Material 87" in line and "TMT Steel Bars (also called: kambi, കമ്പി)" in line
    assert "Steel / TMT Steel Bars" in line  # two materials fit "steel": a question, not a guess


async def test_a_catalog_without_aliases_still_reads_as_before():
    line = await MainAgent(FakeToolCallingProvider([]), catalog=_Catalog()).catalog_line("org")
    assert "cement" in line and "also called" not in line


def test_overlapping_names_are_found_and_distinct_ones_are_not():
    assert likely_duplicates(["Steel", "TMT Steel Bars", "Cement", "Bricks"]) == [("Steel", "TMT Steel Bars")]
    assert likely_duplicates(["Cement", "Bricks", "Metal"]) == []
    assert "empty" in catalog_text([])


# -- root 4: the model's own account of the figures ---------------------------------------------------


def test_a_figure_the_model_explains_is_not_asked_about():
    calls = [("draft_stock_count", {"material": "cement", "counted": 5, "unplaced": [{"figure": 176, "reason": "176 = what the app shows"}]})]
    assert skill.unplaced_figures("app-il 176, 5 bag cement baakki", calls) == []


def test_an_explanation_without_a_reason_does_not_count():  # guard: the model cannot silence the check
    calls = [("draft_stock_count", {"material": "cement", "counted": 5, "unplaced": [{"figure": 176, "reason": ""}]})]
    assert skill.unplaced_figures("176 and 5 bag cement baakki", calls) == ["176"]


def test_a_figure_nobody_placed_or_explained_is_still_asked_about():  # guard
    calls = [("draft_receipt", {"material": "cement", "quantity": 50, "unit": "bags"})]
    assert skill.unplaced_figures("176 and 50 bag cement vannu", calls) == ["176"]


def test_figures_placed_by_the_model_count_as_placed():
    calls = [("draft_receipt", {"material": "cement", "figures_placed": [50, 380]})]
    assert skill.unplaced_figures("50 bag cement vannu 380", calls) == []


async def test_the_account_never_reaches_the_card_line(world):
    call = ("draft_receipt", {"material": "cement", "quantity": 50, "unit": "bags", "figures_placed": [50]})
    await say_v2(world, "50 bag cement vannu", [[call], "x"])
    (item,) = await open_items(world)
    assert "figures_placed" not in item.args and "unplaced" not in item.args


async def test_a_lookup_with_a_number_does_not_get_a_figure_line(world):
    result, _, _ = await say_v2(world, "enough for 500 bricks?", [[("stock_for", {"material": "bricks"})], "No bricks recorded."])
    assert "did not put" not in result.reply.text


# -- the small ones -------------------------------------------------------------------------------------


async def test_a_material_request_gets_one_fast_honest_line_and_no_second_model_round(world):
    result, v2, classic = await say_v2(world, "please send 20 bags of cement tomorrow", [[("material_request_not_available", {})], "never read"])
    assert "Material requests aren't in Mesiri yet" in result.reply.text
    assert v2.calls == 1 and classic.calls == 0  # one model round, today's agent never runs
    assert await open_items(world) == []


async def test_the_request_line_is_worded_in_the_senders_language(world):
    result, _, _ = await say_v2(world, "cement venam", [[("material_request_not_available", {})], "x"])
    assert "Material request ippo Mesiri-il illa" in result.reply.text


async def test_a_request_next_to_a_receipt_keeps_the_card_and_adds_the_line(world):
    script = [[CEMENT_25, ("material_request_not_available", {})], "x"]
    result, _, _ = await say_v2(world, "25 bags cement came. also send sand tomorrow", script)
    assert [i.kind for i in await open_items(world)] == [dr.KIND_MATERIAL_IN]
    assert "Material requests aren't in Mesiri yet" in result.reply.text


async def test_a_stock_answer_names_the_site(world):
    result, _, _ = await say_v2(world, "cement stock ethra und?", [[("stock_for", {"material": "cement"})], "176 bags"])
    assert result.reply.text.startswith("📍 Site A1") or "📍 Site A1" in result.reply.text


async def test_a_stock_answer_for_all_sites_says_so():
    world = await _make_world(site_keys=(seed.SITE_A1, seed.SITE_A2))
    world.draft_v2, world.drafts, world.catalog, world.inventory = True, MemoryDraftStore(), _Catalog(), _Books()
    result, _, _ = await say_v2(world, "cement stock at all sites", [[("stock_for", {"material": "cement"})], "176 bags"])
    assert "📍" in result.reply.text and "All your sites" in result.reply.text


# -- live re-test of 31 Oct (second round) --------------------------------------------------------------


@pytest.mark.parametrize(
    "text,placed",
    [
        ("2 box 1.5 sq mm wire um 20 switch um vannu", [2, 20]),  # the reported message
        ("10 nos 4 inch pipe, 2 bag M20 mix vannu", [10, 2]),  # siblings: other size / grade words
        ("12 mm TMT 3 ton vannu", [3]),
    ],
)
def test_a_size_or_grade_is_not_a_figure_to_ask_about(text, placed):
    calls = [("draft_receipt", {"material": "x", "quantity": n, "figures_placed": [n]}) for n in placed]
    assert skill.unplaced_figures(text, calls) == []


def test_a_real_quantity_next_to_a_size_is_still_asked_about():  # guard
    calls = [("draft_receipt", {"material": "wire", "quantity": 2, "figures_placed": [2]})]
    assert skill.unplaced_figures("2 box 1.5 sq mm wire, 20 switch vannu", calls) == ["20"]


async def test_all_sites_beside_a_named_site_reads_every_site():
    world = await _make_world(site_keys=(seed.SITE_A1, seed.SITE_A2))
    world.draft_v2, world.drafts, world.catalog, world.inventory = True, MemoryDraftStore(), _Catalog(), _Books()
    script = [[("stock_for", {"material": "cement", "site": "all sites"})], "176 bags"]
    result, _, _ = await say_v2(world, "how much cement is left at Site A1? and at all sites?", script)
    assert "All your sites" in result.reply.text
