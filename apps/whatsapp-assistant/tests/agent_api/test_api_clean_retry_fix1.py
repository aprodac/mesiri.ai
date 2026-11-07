"""Fix 1 (live sweep, 7 Nov 2026 ~00:05): "Site B scaffolding sheriyaakki, aa issue close cheyyu" and "3 electricians
came to Site B today" got no tool call; the code's one corrective retry got none either, and the person read "nothing is
ready, send it again". The retry used the same conversation, full of Mesiri's own "Ithokke record cheyyaan *Save*
amarthuka" replies, and copied them again.

Now the retry sees the person's own messages (their context) but not Mesiri's earlier replies.
"""

from __future__ import annotations

from typing import Any

from tests.agent_api.standin import ACTOR, stand_in_api, stand_in_tools

from agent_api.agent import ApiAgent, without_earlier_replies
from agent_api.client import ApiClient
from mesiri_ai.fakes import FakeToolCallingProvider
from mesiri_ai.models import ChatMessage

COPIED = "Ithokke record cheyyaan *Save* amarthuka."
HISTORY = [m for i in range(6) for m in (ChatMessage(role="user", text=f"update {i}"),
                                          ChatMessage(role="model", text=COPIED))]


class Recording(FakeToolCallingProvider):
    def __init__(self, script: list) -> None:
        super().__init__(script)
        self.seen: list[list[ChatMessage]] = []

    async def run_tools(self, system: str, messages: list[ChatMessage], *args: Any, **kwargs: Any) -> Any:
        self.seen.append(list(messages))
        return await super().run_tools(system, messages, *args, **kwargs)


async def test_the_retry_does_not_see_mesiris_earlier_replies() -> None:
    model = Recording([COPIED, "Sheri, scaffolding issue close cheyyatte?"])
    app = stand_in_api([])
    client = ApiClient(ACTOR, app=app)
    try:
        await ApiAgent(model, stand_in_tools(app)).run(
            client, "Site B scaffolding sheriyaakki, aa issue close cheyyu", history=HISTORY)
    finally:
        await client.close()
    first, retry = model.seen
    assert sum(m.text == COPIED for m in first) == 6  # the first try sees the conversation as it is
    earlier = retry[:-2]  # the retry ends with the model's own reply and the code's note
    assert all(m.role == "user" for m in earlier)
    assert earlier[-1].text == "Site B scaffolding sheriyaakki, aa issue close cheyyu"
    assert [m.text for m in earlier[:2]] == ["update 0", "update 1"]  # their context is kept


def test_only_the_persons_messages_are_kept_and_at_most_twelve() -> None:
    many = [ChatMessage(role="user", text=str(i)) for i in range(20)] + [ChatMessage(role="model", text="x")]
    kept = without_earlier_replies(many)
    assert [m.text for m in kept] == [str(i) for i in range(8, 20)]


async def test_fix3_with_a_card_waiting_an_order_message_still_gets_the_clean_retry() -> None:
    """Sweep SW07 (00:07): a request card was waiting ("extra? Save"); "aa cement request-inu order undaakku, ABC
    Traders, bag-inu 380" got no tool and "press Save", so Save saved a second REQUEST and no order existed. The same
    clean retry now runs with a card waiting, and the card stays as it was."""
    from agent_api.agent import PendingWrite

    waiting = [PendingWrite(tool="ask_for_material", method="POST", path="/procurement/requests", params={},
                            body={"quantity": 100}, summary="100 bags Cement Green Villa-ilekku", idempotency_key="r1")]
    model = Recording([COPIED, "ABC Traders-inu order: 100 bag cement, 380 rupees. Vendor list-il illa."])
    app = stand_in_api([])
    client = ApiClient(ACTOR, app=app)
    try:
        turn = await ApiAgent(model, stand_in_tools(app)).run(
            client, "aa cement request-inu order undaakku, ABC Traders, bag-inu 380 rupees", history=HISTORY,
            ready=waiting)
    finally:
        await client.close()
    assert len(model.seen) == 2 and all(m.role == "user" for m in model.seen[1][:-2])
    assert [e.idempotency_key for e in turn.pending] == ["r1"]  # the waiting card is untouched


def test_fix4_the_sop_says_what_cancel_with_nothing_waiting_gets() -> None:
    """Sweep (7 Nov, every reset): "cancel" with nothing waiting got "Enthanaanu cancel cheyyendathu? Please full line
    aayi parayumo?" (what should I cancel? say the full line)."""
    from agent_api.agent import SOP

    text = " ".join(SOP.split())
    assert "with nothing waiting: say in one short line that nothing is waiting to cancel" in text
    assert "Never ask what to cancel, never ask them to say the full line" in text
