"""Item 195 (bug 1): a swap of the material on an open line changes the line, quantity kept; a
correction that changes nothing is never answered "Got it" over the unchanged card."""

from __future__ import annotations

from tests.agent_v2.test_v2_roots_178 import CEMENT_25, say_v2, world  # noqa: F401
from tests.replay.test_draft_per_message_p1 import open_items


async def test_a_material_swap_changes_the_name_and_keeps_the_quantity(world):  # noqa: F811
    await say_v2(world, "25 bags cement vannu", [[CEMENT_25], "ok"])
    swap = ("change_line", {"item_index": 1, "changes": {"material": "bricks"}})
    result, _, _ = await say_v2(world, "cement maatti bricks aakku", [[swap], "ok"])
    (item,) = await open_items(world)
    assert "brick" in item.summary.casefold() and "25" in item.summary


async def test_a_change_that_alters_nothing_says_so_and_never_got_it(world):  # noqa: F811
    await say_v2(world, "25 bags cement vannu", [[CEMENT_25], "ok"])
    same = ("change_line", {"item_index": 1, "changes": {"quantity": 25}})
    result, _, _ = await say_v2(world, "cement maatti cement aakku", [[same], "ok"])
    text = result.reply.text
    assert "Got it" not in text and "couldn't change" in text.casefold()
    (item,) = await open_items(world)
    assert "25" in item.summary  # the card is as it was


async def test_a_change_on_a_line_that_does_not_exist_is_not_confirmed(world):  # noqa: F811
    await say_v2(world, "25 bags cement vannu", [[CEMENT_25], "ok"])
    bad = ("change_line", {"item_index": 7, "changes": {"material": "bricks"}})
    result, _, _ = await say_v2(world, "7th line bricks aakku", [[bad], "ok"])
    assert "Got it" not in result.reply.text
