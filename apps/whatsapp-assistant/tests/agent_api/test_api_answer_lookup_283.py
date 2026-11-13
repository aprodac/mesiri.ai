"""WA-283 (live test on Mesiri Test Builders, 13 Nov 2026): "How many workers at Main Block today, and how much cement
came there today?" got "10 workers (4 masons, 6 helpers), 45 bags" with no tool called. The records said 12 workers
and 95 bags: the morning's entries were not in the chat.

Root cause: the [260] guard sends a no-lookup answer back only for figures it cannot find anywhere, and it counted the
chat's own lists (this afternoon's saves, today's newest records) as backing. Those lists are partial.
Fix: on a turn that only answers (nothing prepared, changed or saved), a figure is backed only by a lookup or by what
the person said; else one more try, told to look it up (SOP line 14). Turns that do something keep the old rule.
Guards: a figure they said stands; an answer with no figures stands; single digits stand.
"""

from __future__ import annotations

from tests.agent_api.test_api_unbacked_figures_260 import _run

#: What the turn started from, live: the chat's saves and today's newest records (shortened).
FACTS = ("Saved earlier in this chat:\n1. 45 bags cement, Main Block\n2. 4 mason, 6 helper, Main Block\n\n"
         "Today's records:\n- 16:20 Main Block · SiteIssueReported: water leak (High)")
ASKED = "How many workers at Main Block today, and how much cement came there today?"
FROM_MEMORY = "Main Block-il innu 10 workers undu (4 masons, 6 helpers). Mattum, innu 45 bags cement vannittundu."
LOOKED_UP = "Main Block-il innu 12 workers (4 mason, 6 helper, 2 carpenter); 95 bags cement vannu."


async def test_the_reported_answer_from_the_chats_own_lists_is_looked_up() -> None:
    turn, model = await _run([FROM_MEMORY, LOOKED_UP], ASKED, facts=FACTS)
    assert model.calls == 2 and turn.reply == LOOKED_UP
    assert "(10, 45)" in model.prompts[1] and "Look it up now" in model.prompts[1]


async def test_sibling_a_count_from_the_newest_records_is_looked_up_too() -> None:
    turn, model = await _run(["Innu 16 workers undu.", "Innu 18 workers undu."], "How many workers are on site today?",
                             facts="Today's records:\n- 10:08 Main Block · LabourAttendanceRecorded: 16 workers recorded")
    assert model.calls == 2


async def test_guard_a_figure_they_said_and_an_answer_with_none_stand() -> None:
    turn, model = await _run(["Sheri, 45 bags thanne.", "never reached"], "45 bags alle vannathu?", facts=FACTS)
    assert model.calls == 1 and turn.reply == "Sheri, 45 bags thanne."
    turn, model = await _run(["Namaskaram! Enthu venam?", "never reached"], "hi", facts=FACTS)
    assert model.calls == 1
