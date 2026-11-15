"""Live, Aprodac, 15 Nov 15:42 IST: "2 ton Tata steel, 3 ton TMT steel vannu" sent again after the same steel was
saved at 15:15. The model called nothing and said it was saved (twice, through the code's two retries); the code took
the words out and sent "nothing is ready to save, send it again with what's missing", a second copy waiting to happen.

Now, when the message repeats what this chat saved (its numbers and a word of its material), the code names those
saves and says a new one is added only when they say so. Words for "earlier" in Manglish and Hinglish ("nerathe",
"pehle") are never read as a save of this turn. Guards: a message that repeats nothing saved still gets the old
answer; a save older than the window is not named.
"""

from __future__ import annotations

from agent_api.reply_guard import claims_saved
from agent_api.whatsapp import already_saved_lines
from runtime.agent.wording import say

NOW = 1_000_000.0
SAID = "Innu site il steel vannu. Ithil 2 ton vannathu Tata Steelum, 3 ton vannathu TM steelum. Appo ithonnu add aakuka."
SAVED = [{"fp": "m", "summary": "New material: Tata steel · counted in Tons", "at": NOW - 1600},
         {"fp": "a", "summary": "2 tons Tata steel, Green Villa", "at": NOW - 1600},
         {"fp": "b", "summary": "3 tons TMT steel, Annex", "at": NOW - 1600},
         {"fp": "c", "summary": "40 bags Cement, Main block", "at": NOW - 1600}]


def test_live_a_repeat_of_saved_steel_names_what_was_saved() -> None:
    lines = already_saved_lines(SAVED, NOW, SAID)
    assert lines == "2 tons Tata steel, Green Villa · 3 tons TMT steel, Annex"  # never the cement, nor the material
    words = say("api.repeat_of_saved", "manglish", lines=lines)
    assert "nerathe save aayittundu" in words and "2 tons Tata steel" in words and "puthiya" in words


def test_earlier_in_manglish_and_hinglish_is_not_a_save_of_this_turn() -> None:
    assert not claims_saved("Ithu nerathe save cheythittundu.")
    assert not claims_saved("Yeh pehle save ho chuka hai.")
    assert claims_saved("Steel save aayi.")  # guard: a plain claim is still one


def test_guard_a_message_that_repeats_nothing_saved_names_nothing() -> None:
    assert already_saved_lines(SAVED, NOW, "10 bag cement vannu Annex-il") == ""  # 10 is not 40
    assert already_saved_lines(SAVED, NOW, "6 mason vannu") == ""


def test_guard_an_old_save_is_not_named() -> None:
    old = [{**r, "at": NOW - 13 * 3600} for r in SAVED]
    assert already_saved_lines(old, NOW, SAID) == ""


def test_every_language_has_the_words() -> None:
    for language in ("english", "manglish", "malayalam", "hindi", "hinglish"):
        assert "2 tons" in say("api.repeat_of_saved", language, lines="2 tons Tata steel")
