"""WA-170 (4 Nov 00:19, Ilan, Paraclette, cor ...b7ff1e and ...d13d3d): two replies began "(said by an older version of
Mesiri, with fewer tools: anything it said it couldn't do may work now)", the memory's own note on an older reply,
copied back by the model. [205] stripped only the drawn list's note. Now every memory note is cut in one place
(``memory.without_memory_notes``) before a reply is sent, spoken or kept; a stored reply that carries the note is
read back with it once.
"""

from __future__ import annotations

from tests.agent_api.test_api_reply_language_169 import Harness, Prefs, _tools  # noqa: F401 (autouse fixture)

from agent_api import memory
from agent_api.memory import OLDER_NOTE, without_memory_notes
from agent_api.whatsapp import for_memory, without_ready_block
from mesiri_ai.fakes import FakeToolCallingProvider

REPLY = "RFQ-കൾ തയ്യാറാക്കാനും അയക്കാനും Mesiriക്ക് നിലവിൽ കഴിയില്ല."


async def test_the_reported_reply_goes_out_without_the_note() -> None:
    h = Harness(Prefs(None), FakeToolCallingProvider([OLDER_NOTE + REPLY]))
    await h.say("ആർഎഫ് ക്യുന്റെ സെറ്റ് ആക്കിയോ")
    assert h.sent[-1].text == REPLY


async def test_sibling_a_short_reply_too() -> None:
    h = Harness(Prefs(None), FakeToolCallingProvider([OLDER_NOTE + "ഓക്കെ."]))
    await h.say("Ok")
    assert h.sent[-1].text == "ഓക്കെ."


def test_siblings_every_memory_note_and_a_cut_one() -> None:
    assert without_ready_block("(said by an older version of Mesiri…) Done") == "Done"
    assert without_ready_block("Done\n⁣[tools:0a1b2c3d]") == "Done"
    assert without_ready_block("Ready.\n(under this reply, waiting for the Save button: 2 bags)") == "Ready."
    assert without_memory_notes(OLDER_NOTE + OLDER_NOTE + "Hi") == "Hi"


def test_guard_ordinary_brackets_stay() -> None:
    assert without_ready_block("1 load (= 50 bags) at Tower A") == "1 load (= 50 bags) at Tower A"


def test_guard_the_memory_still_keeps_the_list_note() -> None:
    kept = for_memory("Ready.\n\n*Ready to save:*\n1. 2 bags cement")
    assert "(under this reply, waiting for the Save button: 2 bags cement)" in kept


def test_a_stored_reply_that_carries_the_note_is_read_with_it_once() -> None:
    stored = memory._tagged(OLDER_NOTE + REPLY, "deadbeef")
    read = memory._read("model", stored, "0a1b2c3d")
    assert read.text == OLDER_NOTE + REPLY
