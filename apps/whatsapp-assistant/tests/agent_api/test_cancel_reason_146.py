"""WA-146: a Cancel asks why with one tap (Wrong site / Wrong amount / Something else), and the reason
goes to the team bot as feedback naming the cancelled entries and their tools (the shape its watch
reads). Guards: nothing is saved; a reason with nothing cancelled, or an unknown one, is just thanked;
"Something else" asks them to say what."""

from __future__ import annotations

from tests.agent_api.standin import two_receipts_model
from tests.agent_api.test_api_whatsapp_119 import CTX, Harness, _message, _stand_in_tools  # noqa: F401 (autouse)

from agent_api import whatsapp as wa
from runtime.agent.wording import say

#: The test message ("50 bag cement, 50 TMT vannu") is Manglish: the replies follow it.
LANG = "manglish"


async def _cancelled(h: Harness):
    await h.service.handle(_message(), CTX)
    _save, cancel = h.buttons()
    await h.service.handle(_message("Cancel", tap=cancel), CTX)
    return h.sent[-1]


async def test_cancel_offers_three_reasons() -> None:
    h = Harness(two_receipts_model())
    reply = await _cancelled(h)
    assert reply.text == say("api.cancelled_why", LANG)
    assert [b.title for b in reply.buttons] == list(wa._REASON_TITLES[LANG].values())
    assert h.posts() == 0


async def test_a_reason_reaches_the_team_with_what_was_cancelled() -> None:
    h = Harness(two_receipts_model())
    reply = await _cancelled(h)
    site = reply.buttons[0].id
    await h.service.handle(_message("Wrong site", tap=site), CTX)
    payload = h.trace.log_stage.await_args.kwargs["stage_payload"]
    (call,) = payload["calls"]
    assert call["tool"] == "tell_the_team" and call["args"]["kind"] == "wrong_reply"
    assert "wrong site" in call["args"]["about"] and "record_receipt" in call["args"]["about"]
    assert "50 bags cement" in call["args"]["about"]
    assert h.sent[-1].text == say("api.cancel_noted", LANG) and h.posts() == 0


async def test_something_else_asks_what() -> None:
    h = Harness(two_receipts_model())
    reply = await _cancelled(h)
    await h.service.handle(_message("Something else", tap=reply.buttons[2].id), CTX)
    assert h.sent[-1].text == say("api.cancel_other", LANG)


async def test_guard_a_second_or_unknown_reason_is_only_thanked() -> None:
    h = Harness(two_receipts_model())
    reply = await _cancelled(h)
    await h.service.handle(_message("Wrong site", tap=reply.buttons[0].id), CTX)
    told = h.trace.log_stage.await_count
    await h.service.handle(_message("Wrong amount", tap=reply.buttons[1].id), CTX)  # already told: once is enough
    assert h.sent[-1].text == say("api.thanks", LANG) and h.trace.log_stage.await_count == told
    await h.service.handle(_message("x", tap=f"{wa.WHY_PREFIX}bogus"), CTX)
    assert h.sent[-1].text == say("api.thanks", LANG)


def test_every_reason_title_fits_a_whatsapp_button() -> None:
    assert all(len(t) <= 20 for titles in wa._REASON_TITLES.values() for t in titles.values())
    assert all(set(titles) == set(wa.CANCEL_REASONS) for titles in wa._REASON_TITLES.values())
