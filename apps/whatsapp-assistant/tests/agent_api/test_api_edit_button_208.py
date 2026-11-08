"""WA-208 (4 Nov, Adarsh): a voice note "5 chaak cement" was heard as 30; saying "it is 5 chaak" added a third line
(30 + 5) instead of changing the first. A ready list now has Save / ✏️ Edit / Cancel: Edit picks the line (asked at
once when there is one), the next message (typed or a voice note) is its right figure, and the code makes sure only
that line changes, whatever the model prepared.
"""

from __future__ import annotations

import time

import pytest
from tests.agent_api.standin import ORG, STAND_IN_TOOLS, USER, two_receipts_model
from tests.agent_api.test_api_agent_119 import _two_waiting
from tests.agent_api.test_api_whatsapp_119 import CTX, Harness, _message

from agent_api import whatsapp as wa
from agent_api.agent import CHANGE_READY, PendingWrite
from mesiri_ai.fakes import FakeToolCallingProvider
from runtime.agent.wording import say

# WA-207: Manglish is everyone's reply language until they choose another.
_WHICH = say("api.edit_which", "manglish")


def _ask(item: str) -> str:
    return say("api.edit_ask", "manglish", item=item)

_KEY = f"agent_api:{ORG}:{USER}"


@pytest.fixture(autouse=True)
def _stand_in_tools(monkeypatch):  # noqa: ANN001, ANN202 -- as test_api_whatsapp_119 does
    from agent_api import tools as tools_mod

    real = tools_mod.build_tools
    monkeypatch.setattr(wa, "build_tools", lambda openapi: real(
        openapi, tuple(a for a in tools_mod.ALLOWED if a.name in STAND_IN_TOOLS)))


def _entry(summary: str, key: str) -> PendingWrite:
    return PendingWrite(tool="record_receipt", method="POST", path="/materials/inflows", params={},
                        body={"quantity": 30}, summary=summary, idempotency_key=key)


async def _listed(model_after: list) -> Harness:  # noqa: ANN001
    h = Harness(FakeToolCallingProvider([*two_receipts_model()._script, *model_after]))
    await h.service.handle(_message(), CTX)
    return h


async def test_a_ready_list_has_save_edit_cancel() -> None:
    h = await _listed([])
    assert [b.title for b in h.sent[-1].buttons] == ["Save", wa.EDIT_TITLE, "Cancel"]
    assert all(len(b.title) <= 20 for b in h.sent[-1].buttons)  # WhatsApp's button limit


async def test_edit_with_several_lines_lets_them_pick_one() -> None:
    h = await _listed([])
    _save, edit, _cancel = h.buttons()
    await h.service.handle(_message("Edit", tap=edit), CTX)
    reply = h.sent[-1]
    assert reply.text == _WHICH
    assert [r.title for r in reply.list_rows] == ["1. 50 bags cement, Gree…", "2. 50 TMT bars, Green V…"]
    assert all(len(r.title) <= 24 for r in reply.list_rows)  # WhatsApp's list row limit
    assert h.posts() == 0


async def test_picking_a_line_asks_its_right_figure() -> None:
    h = await _listed([])
    batch = (await h.redis.get_json(_KEY))["batch"]
    await h.service.handle(_message("1", tap=f"{wa.EDIT_LINE_PREFIX}{batch}:1"), CTX)
    assert h.sent[-1].text == _ask("50 bags cement, Green Villa")
    editing = (await h.redis.get_json(_KEY))["editing"]
    assert editing["number"] == 1 and editing["batch"] == batch


async def test_the_answer_changes_only_that_line() -> None:
    # The fake model plays its script on every message, so the list is waiting already and the model only
    # answers the correction.
    h = Harness(FakeToolCallingProvider([
        [(CHANGE_READY, {"number": 1, "changes": [{"field": "quantity", "value": "5"}],
                         "confirm_line": "5 bags cement, Green Villa"})],
        "Changed to 5 bags.",
    ]))  # fmt: skip
    ready = await _two_waiting(h.app)
    await h.redis.set_json(_KEY, {"pending": [e.to_json() for e in ready], "batch": "b1", "pending_at": time.time(),
                                  "language": "english"})
    await h.service.handle(_message("1", tap=f"{wa.EDIT_LINE_PREFIX}b1:1"), CTX)
    await h.service.handle(_message("5 chaak"), CTX)
    reply = h.sent[-1]
    assert "1. 5 bags cement, Green Villa\n2. 50 TMT bars, Green Villa" in reply.text
    assert "50 bags cement" not in reply.text  # changed, not added beside it
    state = await h.redis.get_json(_KEY)
    assert len(state["pending"]) == 2 and "editing" not in state
    assert h.posts() == 0  # nothing saved until Save


def test_a_line_prepared_instead_of_changed_takes_its_place() -> None:
    """The model added "5 bags" instead of changing line 1: the code puts it in line 1's place."""
    ready = [_entry("30 bags cement", "a"), _entry("10 helpers", "b")]
    prepared = [*ready, _entry("5 bags cement", "c")]
    assert [e.summary for e in wa.edited_list(ready, prepared, 1)] == ["5 bags cement", "10 helpers"]


def test_the_other_lines_stay_whatever_the_model_did() -> None:
    ready = [_entry("30 bags cement", "a"), _entry("10 helpers", "b")]
    # The model changed line 2 by mistake (line 1 was the one being edited).
    prepared = [ready[0], _entry("5 helpers", "c")]
    assert [e.summary for e in wa.edited_list(ready, prepared, 1)] == ["5 helpers", "10 helpers"]


def test_removing_the_edited_line_removes_only_it() -> None:
    ready = [_entry("30 bags cement", "a"), _entry("10 helpers", "b")]
    assert [e.summary for e in wa.edited_list(ready, [ready[1]], 1)] == ["10 helpers"]


async def test_an_old_edit_is_an_ordinary_message() -> None:
    h = await _listed([])
    state = await h.redis.get_json(_KEY)
    state["editing"] = {"batch": state["batch"], "number": 1, "summary": "50 bags cement, Green Villa",
                        "at": time.time() - wa.EDIT_SECONDS - 1}
    assert wa._editing(state, [PendingWrite.from_json(e) for e in state["pending"]]) is None


async def test_edit_on_an_older_list_changes_nothing() -> None:
    h = await _listed([])
    await h.service.handle(_message("Edit", tap=f"{wa.EDIT_PREFIX}oldbatch"), CTX)
    assert h.sent[-1].text in wa.NOTHING_ON_CARD_WORDS


async def test_one_line_is_asked_at_once() -> None:
    h = Harness(FakeToolCallingProvider([]))
    state = {"pending": [_entry("30 bags cement", "a").to_json()], "batch": "b1", "pending_at": time.time()}
    await h.redis.set_json(_KEY, state)
    await h.service.handle(_message("Edit", tap=f"{wa.EDIT_PREFIX}b1"), CTX)
    assert h.sent[-1].text == wa.EDIT_ASK.format(item="30 bags cement")  # no language yet: English
    assert (await h.redis.get_json(_KEY))["editing"]["number"] == 1
