"""render_execution_reply -- conflict_note (#12) surfaced to the user, never swallowed."""

from __future__ import annotations

from interactions.response_handler import render_execution_reply
from mesiri_contracts.application.results.execution_result import ExecutionResult, ExecutionStatus


def test_succeeded_with_no_conflict_note_is_the_plain_reply():
    result = ExecutionResult(
        status=ExecutionStatus.SUCCEEDED, idempotency_key="k1", material_row_id="row_1"
    )
    assert render_execution_reply(result) == "✅ Recorded. Thank you."


def test_succeeded_with_conflict_note_appends_it():
    result = ExecutionResult(
        status=ExecutionStatus.SUCCEEDED,
        idempotency_key="k1",
        material_row_id="row_1",
        conflict_note="Note: this activity was already marked Completed by someone else.",
    )
    reply = render_execution_reply(result)
    assert reply.startswith("✅ Recorded. Thank you.")
    assert "already marked Completed" in reply


def test_already_executed_with_conflict_note_appends_it_too():
    result = ExecutionResult(
        status=ExecutionStatus.ALREADY_EXECUTED,
        idempotency_key="k1",
        material_row_id="row_1",
        conflict_note="Note: held back.",
    )
    reply = render_execution_reply(result)
    assert "Note: held back." in reply


def test_rejected_ignores_conflict_note_field_entirely():
    result = ExecutionResult(
        status=ExecutionStatus.REJECTED, idempotency_key="k1", rejection_reasons=["quantity must be positive"]
    )
    reply = render_execution_reply(result)
    assert "Note:" not in reply
    assert "quantity must be positive" not in reply  # raw reason stays in the log
    assert "How much" in reply
