"""Request 184: every question on the card is answerable (typed, said, a button's text).

Live 31 Oct: with a card holding "How many load is 20 nos?", each answer made the model call
change_line on the waiting line, which refuses it, and the code replied "send it again".
Each test is the class (the reported answer), a sibling, and the guard (what must not change).
"""

from __future__ import annotations

import pytest
from tests.agent_v2.test_v2_roots_178 import CEMENT_25, say_v2, world  # noqa: F401
from tests.replay.test_draft_per_message_p1 import open_items

from runtime.agent import draft as dr
from runtime.agent.wording import LANGUAGES, LINES

SAND_20_NOS = ("draft_usage", {"material": "sand", "quantity": 20, "unit": "nos"})


def _answer(index: int, text: str) -> tuple[str, dict]:
    return ("answer_question", {"item_index": index, "answer": text})


async def test_a_typed_answer_to_the_waiting_line_fills_it_and_never_says_send_again(world):  # noqa: F811
    first, _, _ = await say_v2(world, "20 nos sand used", [[SAND_20_NOS], "ok"])
    (waiting,) = await open_items(world)
    assert waiting.state == dr.NEEDS_ANSWER
    # The model's first instinct (a change on the waiting line) is refused with the way out;
    # then it answers the question.
    change = ("change_line", {"item_index": 1, "changes": {"unit": "load"}})
    result, _, classic = await say_v2(world, "20 nos = 1 load", [[change], [_answer(1, "2")], "ok"])
    (item,) = await open_items(world)
    print("ANSWERED", item.state, item.args, item.summary)
    assert item.state == dr.OK and item.args["unit"] == "load" and item.args["quantity"] == 2
    assert "send it again" not in result.reply.text.lower() and "veendum" not in result.reply.text
    assert classic.calls == 0


async def test_a_model_that_only_changes_the_waiting_line_gets_the_open_questions_not_send_again(world):  # noqa: F811
    await say_v2(world, "20 nos sand used", [[SAND_20_NOS], "ok"])
    change = ("change_line", {"item_index": 1, "changes": {"unit": "load"}})
    result, _, _ = await say_v2(world, "50 bag = 1 load", [[change], [change], "Sorry"])
    text = result.reply.text
    assert "send it again" not in text.lower() and "veendum ayakku" not in text
    assert "How many load is 20 nos?" in text  # named, drawn by code from the card
    assert dr.card_rows(await world.drafts.open_for(world.actor.organization_id, world.actor.user_id))


async def test_answer_question_for_a_line_that_waits_for_nothing_is_a_plain_error(world):  # noqa: F811
    await say_v2(world, "25 cement", [[CEMENT_25], "ok"])
    result, _, _ = await say_v2(world, "yes", [[_answer(1, "yes")], "Nothing to answer."])
    (item,) = await open_items(world)
    assert item.state == dr.OK  # the guard: a ready line is not touched


async def test_a_new_report_on_a_card_with_a_question_still_adds_lines(world):  # noqa: F811
    await say_v2(world, "20 nos sand used", [[SAND_20_NOS], "ok"])
    await say_v2(world, "25 bags cement vannu", [[CEMENT_25], "ok"])
    items = await open_items(world)
    assert len(items) == 2


def test_open_questions_text_is_drawn_from_the_card_model_only():
    draft = dr.MessageDraft.new(organization_id="o", user_id="u")
    draft.items.append(dr.DraftItem(
        kind=dr.KIND_MATERIAL_OUT, tool="save_material_usage", args={}, summary="Tmt steel bars used: 20 nos",
        state=dr.NEEDS_ANSWER, question="1 nos = how many load?", awaiting="unit",
    ))
    text = dr.open_questions_text(draft, "Card still has:")
    assert text == "Card still has:\n1. Tmt steel bars used: 20 nos: 1 nos = how many load?"
    assert dr.open_questions_text(None, "x") == "" and dr.open_questions_text(dr.MessageDraft.new(organization_id="o", user_id="u"), "x") == ""


@pytest.mark.parametrize("key", ["voice.cant_hear", "card.still_open", "card.answer_failed"])
def test_new_lines_exist_in_every_language(key):
    assert all(LINES[key].get(language) for language in LANGUAGES)


def test_an_answer_with_no_usable_words_is_not_an_outage_but_a_real_outage_still_is():
    from runtime.ai_outage import is_provider_failure

    class Coded(Exception):
        def __init__(self, code):
            self.error_code = code

    assert is_provider_failure(Coded("PROVIDER_UNAVAILABLE")) and is_provider_failure(RuntimeError("boom"))
    assert not is_provider_failure(Coded("VALIDATION_ERROR"))
