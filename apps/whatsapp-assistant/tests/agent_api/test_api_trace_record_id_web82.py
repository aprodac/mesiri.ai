"""WEB-82: a save's trace keeps its record's id, so Live can ask what that record changed (GET /dpr/effects).

One helper writes both traces (saved in the turn, saved by the ✅ Save tap). Guards: a refused save keeps its
reason and no id; a save whose answer has no id is traced as before.
"""

from __future__ import annotations

from agent_api.agent import PendingWrite, WriteResult
from agent_api.whatsapp import _traced_save


def _write(tool: str = "record_receipt") -> PendingWrite:
    return PendingWrite(tool=tool, method="POST", path="/materials/inflows", params={}, body={"quantity": 50},
                        summary="Cement 50 bags in", idempotency_key="k1")


def test_a_saved_entry_is_traced_with_its_record_id() -> None:
    traced = _traced_save(WriteResult(_write(), 201, {"id": "3f0c9a52-8d1c-4f6e-9d55-1c2a7b6e4f10", "quantity": "50"}))
    assert traced == {"summary": "Cement 50 bags in", "tool": "record_receipt", "status": 201,
                      "id": "3f0c9a52-8d1c-4f6e-9d55-1c2a7b6e4f10"}


def test_sibling_attendance_and_usage_carry_their_ids_too() -> None:
    for tool in ("record_attendance", "record_usage", "record_work"):
        assert _traced_save(WriteResult(_write(tool), 201, {"id": "abc"}))["id"] == "abc"


def test_guard_a_refused_save_keeps_its_reason_and_has_no_id() -> None:
    traced = _traced_save(WriteResult(_write(), 422, {"detail": "More used than in stock", "id": "never-saved"}))
    assert "id" not in traced and traced["status"] == 422 and "More used than in stock" in traced["reason"]


def test_guard_an_answer_without_an_id_is_traced_as_before() -> None:
    assert _traced_save(WriteResult(_write(), 204, None)) == {"summary": "Cement 50 bags in", "tool": "record_receipt", "status": 204}
    assert "id" not in _traced_save(WriteResult(_write(), 201, ["not", "a", "dict"]))


# --- WEB-86: a save of several records (the day of two machines) keeps their ids ---------------------------------

def test_a_machine_log_of_two_machines_is_traced_with_both_ids() -> None:
    body = {"date": "2026-11-12", "items": [{"id": "log-1", "machine": "JCB"}, {"id": "log-2", "machine": "Mixer"}]}
    traced = _traced_save(WriteResult(_write("log_machines"), 201, body))
    assert traced == {"summary": "Cement 50 bags in", "tool": "log_machines", "status": 201, "ids": ["log-1", "log-2"]}


def test_guard_one_record_keeps_its_id_and_a_refused_machine_log_has_no_ids() -> None:
    assert "ids" not in _traced_save(WriteResult(_write(), 201, {"id": "abc", "items": [{"id": "not-the-record"}]}))
    refused = _traced_save(WriteResult(_write("log_machines"), 409, {"detail": "Which JCB?", "items": [{"id": "x"}]}))
    assert "ids" not in refused and "id" not in refused and "Which JCB?" in refused["reason"]
    assert "ids" not in _traced_save(WriteResult(_write("log_machines"), 201, {"items": ["not a dict", {"no": "id"}]}))
