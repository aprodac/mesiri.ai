"""WA-286 (live test on Mesiri Test Builders, 13 Nov 2026): "Site B il 10 bag cement vannu, steel um vannu, 2 mason
undu", sent a second time, got the earlier card's lines written by the model with no tool called: "1. 📥 Delivery:
*Cement* · 10 bags ⏎ 2. 📥 Delivery: *Steel* · 1 nos ⏎ 3. 👷 Labour: *Masons* · at work · 2" and the steel question,
with no Save button and nothing prepared.

Root cause: the conversation keeps a card as a short note so the model never copies it (WA-130, PRC-32), but it found
the card by its old "Ready to save" header. Today's card lines (WA-262) have none, so the card stayed whole in memory.
Fix: (1) the memory keeps the code's card lines (found by the code's own format, ``receipts.CARD_LINE``) as the note;
(2) a card line in the model's words is cut (only the code draws the card); (3) a reply that writes card lines with
no tool called gets one more try, told nothing was prepared.
Guards: the code's own card still goes out whole; a numbered list the model writes for an answer (not a card) stays.
"""

from __future__ import annotations

from tests.agent_api.test_api_unbacked_figures_260 import _run

from agent_api.receipts import CARD_LINE, KIND_EMOJI
from agent_api.reply_guard import writes_card
from agent_api.whatsapp import for_memory, without_ready_block

#: What the model wrote, live (the code's card format, copied from the conversation).
COPIED = ("1. 📥 Delivery: *Cement* · 10 bags\n2. 📥 Delivery: *Steel* · 1 nos\n3. 👷 Labour: *Masons* · at work · 2\n\n"
          "1 Numbers Steel-il ethra Kilograms undu?")
#: The code's card as it went out the first time (its lines, then the code's Save line).
SENT_CARD = ("1. 📥 Delivery: *Cement* · 10 bags\n2. 📥 Delivery: *Steel* · 1 nos\n3. 👷 Labour: *Masons* · at work · 2\n\n"
             "Ithokke record cheyyaan *Save* amarthuka.")


def test_the_memory_keeps_the_card_as_a_note_never_as_card_lines() -> None:
    kept = for_memory(SENT_CARD)
    assert not CARD_LINE.search(kept) and "📥" not in kept
    assert "(under this reply, waiting for the Save button: Delivery: Cement · 10 bags; Delivery: Steel · 1 nos;" in kept


def test_a_card_line_in_the_models_words_is_cut_and_its_question_stays() -> None:
    assert without_ready_block(COPIED) == "1 Numbers Steel-il ethra Kilograms undu?"


def test_every_kind_of_card_line_is_known_and_a_plain_list_is_not_a_card() -> None:
    for mark in KIND_EMOJI.values():
        assert writes_card(f"1. {mark} Something: *x* · 2"), mark
    for plain in ("1. Cement: 95 bags\n2. Sand: 20 cft", "Main Block-il 12 workers undu.", "1) Save\n2) Cancel",
                  "Innu 3 issues: 1. leak, 2. crack, 3. scaffolding"):
        assert not writes_card(plain), plain


async def test_the_reported_copy_gets_one_more_try_with_the_tools() -> None:
    turn, model = await _run([COPIED, "Steel ethra vannu?"], "Site B il 10 bag cement vannu, steel um vannu, 2 mason undu")
    assert model.calls == 2 and "You wrote card lines yourself" in model.prompts[1]
    assert not CARD_LINE.search(turn.reply)


async def test_guard_an_answer_with_no_card_lines_is_not_retried() -> None:
    turn, model = await _run(["Sheri 👍", "never reached"], "ok thanks")
    assert model.calls == 1 and turn.reply == "Sheri 👍"
