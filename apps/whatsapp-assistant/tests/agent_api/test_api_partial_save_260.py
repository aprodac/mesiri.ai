"""WA-260 (Ilan, 8 Nov): two entries in one voice note, one saved and the other refused, and from then on Mesiri spoke
as if the refused one never existed (or as if both were saved).

Now: when anything is refused the code's ✅ / ❌ lines always go first and the model's words cannot say "saved"; the
refused line is remembered for the model ("NOT SAVED earlier in this chat ... and why"), so the missing part alone
puts it back, never "send it all again".
"""

from __future__ import annotations

from tests.agent_api.test_api_agent_124 import CTX, _message, _service
from tests.agent_api.test_api_refused_line_233 import LABOUR, WORDS, WORK, _app, _tools  # noqa: F401

from agent_api.agent import SAVE_READY, PendingWrite, WriteResult
from agent_api.whatsapp import UNSAVED_SECONDS, remember_unsaved, unsaved_fact
from mesiri_ai.fakes import FakeToolCallingProvider


async def _refused_one_of_two(model: FakeToolCallingProvider):  # noqa: ANN202
    posted: list = []
    service, sent = _service(model, app=_app(posted, refuse_all_work="work type not allowed here"))
    await service.handle(_message(WORDS), CTX)
    return service, sent, posted


async def test_the_reported_in_message_save_shows_what_was_refused_and_never_says_all_saved() -> None:
    model = FakeToolCallingProvider([[WORK, LABOUR], "OK."])
    service, sent, posted = await _refused_one_of_two(model)
    model._script = [[(SAVE_READY, {"numbers": [1, 2]})], "Randum save cheythu ✅"]
    await service.handle(_message("save cheyyu"), CTX)
    text = sent[-1].text
    assert [k for k, _ in posted] == ["attendance"]
    assert "❌" in text and "✅" in text and "Randum save cheythu" not in text
    assert "not saved yet" in text or "save aayittilla" in text


async def test_the_next_turn_knows_what_was_not_saved_and_why() -> None:
    model = FakeToolCallingProvider([[WORK, LABOUR], "OK."])
    service, sent, _ = await _refused_one_of_two(model)
    await service.handle(_message("Save", tap=sent[-1].buttons[0].id), CTX)
    model._script = ["Plastering-inu ethu floor aanu?"]
    await service.handle(_message("athu entha save aayille?"), CTX)
    told = model.last_system_prompt
    assert "NOT SAVED earlier in this chat" in told and "Plastering" in told


def _result(tool: str, ok: bool, material: str = "m1") -> WriteResult:
    entry = PendingWrite(tool=tool, method="POST", path="/materials/inflows", params={},
                         body={"material_id": material}, summary=f"{tool} line", idempotency_key=f"{tool}{material}")
    return WriteResult(entry, 201 if ok else 422, {"id": "x"} if ok else {"detail": "quantity is too high"})


def test_guards_saved_again_forgets_it_and_it_expires() -> None:
    state: dict = {}
    remember_unsaved(state, [_result("record_receipt", False)], [], 1000.0)
    assert "record_receipt line" in unsaved_fact(state, 1001.0)
    assert unsaved_fact(state, 1000.0 + UNSAVED_SECONDS + 1) == ""  # old: gone
    remember_unsaved(state, [_result("record_receipt", True)], [], 1002.0)  # the same line saved later
    assert unsaved_fact(state, 1003.0) == "" and "unsaved" not in state


def test_guard_a_line_kept_on_the_list_is_not_called_unsaved() -> None:
    state: dict = {}
    refused = _result("record_receipt", False)
    remember_unsaved(state, [refused], [refused.pending], 1000.0)
    assert unsaved_fact(state, 1001.0) == ""
