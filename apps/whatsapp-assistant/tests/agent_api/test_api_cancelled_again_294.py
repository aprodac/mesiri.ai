"""WA-294: a new message brought back the lines of messages the person had cancelled (live 13 Nov on the replay, and
again 14 Nov 04:39 IST with memory as state: the same carpenter message sent twice; the second time the model prepared
the cancelled 10 bags sand and 2 masons again from the messages it still saw). The code decides: a line the same as
one cancelled today is not prepared unless this message says its numbers again. With and without memory as state.
"""

from __future__ import annotations

import pytest
from tests.agent_api.standin import BAG, CEMENT, receipt_call, two_receipts_model
from tests.agent_api.test_api_whatsapp_119 import CTX, Harness, _message, _stand_in_tools  # noqa: F401

from agent_api.agent import cancelled_again, line_key
from mesiri_ai.fakes import FakeToolCallingProvider

RECEIPT = {"project_id": "p", "site_id": "s", "material_id": "m-sand", "unit_id": "bags", "quantity": 10}
LABOUR = {"project_id": "p", "site_id": "s", "occurred_date": "2026-11-14",
          "lines": [{"trade": "Mason", "headcount": 2}]}


def test_the_same_line_is_the_same_update_whatever_the_code_filled_in() -> None:
    key = line_key("record_receipt", RECEIPT)
    assert key == line_key("record_receipt", {**RECEIPT, "occurred_date": "2026-11-14", "notes": "x", "quantity": "10"})
    assert key != line_key("record_receipt", {**RECEIPT, "quantity": 12})
    assert key != line_key("record_receipt", {**RECEIPT, "site_id": "other"})
    assert line_key("record_attendance", LABOUR) == line_key(
        "record_attendance", {**LABOUR, "lines": [{"trade": " mason ", "headcount": 2.0}]})
    assert line_key("report_issue", {"title": "leak"}) is None  # only material lines and labour reports


def test_a_cancelled_line_comes_back_only_when_this_message_says_it_again() -> None:
    cancelled = [{"summary": "10 bags sand, Main Block", "key": line_key("record_receipt", RECEIPT)},
                 {"summary": "2 mason, Main Block", "key": line_key("record_attendance", LABOUR)}]
    # the live case: the carpenter message says neither
    assert cancelled_again("Main Block mein aaj 3 carpenter aaye", "record_receipt", RECEIPT, cancelled)
    assert cancelled_again("Main Block mein aaj 3 carpenter aaye", "record_attendance", LABOUR, cancelled)
    # said again: theirs again
    assert cancelled_again("10 bag sand vannu", "record_receipt", RECEIPT, cancelled) is None
    assert cancelled_again("2 mason vannu", "record_attendance", LABOUR, cancelled) is None
    # guards: another quantity, nothing cancelled, an older cancel log without keys
    assert cancelled_again("x", "record_receipt", {**RECEIPT, "quantity": 12}, cancelled) is None
    assert cancelled_again("x", "record_receipt", RECEIPT, None) is None
    assert cancelled_again("x", "record_receipt", RECEIPT, [{"summary": "10 bags sand"}]) is None


def _again(*calls) -> FakeToolCallingProvider:
    return FakeToolCallingProvider([list(calls), "Sheri."])


@pytest.mark.parametrize("as_state", [True, False])
async def test_live_14_nov_the_cancelled_line_is_not_prepared_again(as_state: bool) -> None:
    h = Harness(two_receipts_model())

    async def setting(ctx) -> bool:
        return as_state
    h.service._memory_as_state = setting
    await h.service.handle(_message(), CTX)  # 50 bags cement + 50 TMT: a card
    await h.service.handle(_message("cancel"), CTX)
    model = _again(receipt_call(CEMENT, BAG, "50 bags cement, Green Villa"))
    h.service._agent._provider = model
    await h.service.handle(_message("3 carpenter vannu"), CTX)
    state = await h.service._state(CTX)
    assert not state.get("pending")  # nothing came back on a card
    turn = [c.kwargs["stage_payload"] for c in h.trace.log_stage.call_args_list
            if (c.kwargs.get("stage_payload") or {}).get("text") == "3 carpenter vannu"][-1]
    results = [c.get("result") or {} for c in turn["calls"] if c.get("tool") == "record_receipt"]
    assert results and results[0]["status"] == "not prepared: cancelled earlier"
    assert "50 bags cement" in results[0]["note"]  # the model is told what it repeated

    # guard: said again, it is theirs again
    h.service._agent._provider = _again(receipt_call(CEMENT, BAG, "50 bags cement, Green Villa"))
    await h.service.handle(_message("50 bag cement vannu"), CTX)
    state = await h.service._state(CTX)
    assert [e["summary"] for e in state.get("pending") or []] == ["50 bags cement, Green Villa"]


async def test_the_state_block_is_in_the_turns_trace_only_with_memory_as_state() -> None:
    for on in (True, False):
        h = Harness(FakeToolCallingProvider(["Sheri."]))

        async def setting(ctx, on=on) -> bool:
            return on
        h.service._memory_as_state = setting
        await h.service.handle(_message("innu ethra pere?"), CTX)
        payloads = [c.kwargs.get("stage_payload") or {} for c in h.trace.log_stage.call_args_list]
        turn = next(p for p in payloads if "facts" in p)
        assert ("state_block" in turn) is on
        if on:
            assert turn["state_block"].rstrip().endswith('"innu ethra pere?"')
