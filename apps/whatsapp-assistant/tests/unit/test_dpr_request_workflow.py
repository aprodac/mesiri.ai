"""dpr.request workflow -- "send me today's DPR" (#16 Daily Report Generation).

Protects the three status branches a supervisor can land in: a PDF is ready
(they get told a document is coming, with the code so the message and the
attachment that follows are recognisably the same thing), a report exists
but hasn't been rendered yet, or nothing has been generated at all -- these
must never be confused with each other, since only the first case is
followed by an actual document (see runtime/inbound_journey.py's post-reply
delivery step, which keys off the same dpr_status/dpr_object_key fields
this node reads).
"""

from __future__ import annotations

from mesiri_contracts.assistant.planner_decision import WorkflowKey
from workflows.dpr_request.nodes import generate_dpr_request_reply


def _state(*, dpr_status: str, dpr_code: str | None = None) -> dict:
    return {
        "workflow_instance_id": "wf_1",
        "workflow_key": WorkflowKey.DPR_REQUEST.value,
        "correlation_id": "cor_1",
        "organization_id": "11111111-1111-4111-8111-111111111111",
        "user_id": "22222222-2222-4222-8222-222222222222",
        "collected_fields": {"dpr_status": dpr_status, "dpr_code": dpr_code},
    }


def test_ready_status_mentions_the_document_and_its_code():
    reply = generate_dpr_request_reply(_state(dpr_status="ready", dpr_code="DPR-20260727-AB12"))
    assert "pending_prompt" in reply
    assert "DPR-20260727-AB12" in reply["pending_prompt"]


def test_ready_status_with_no_code_still_renders_without_a_dangling_placeholder():
    reply = generate_dpr_request_reply(_state(dpr_status="ready", dpr_code=None))
    text = reply["pending_prompt"]
    assert "()" not in text
    assert "{code_suffix}" not in text


def test_unconfirmed_updates_are_named_not_called_missing():
    state = _state(dpr_status="pending_confirmation")
    state["collected_fields"].update(
        {"dpr_site_name": "Green Villa", "dpr_update_count": 3, "dpr_confirmed": False}
    )
    text = generate_dpr_request_reply(state)["pending_prompt"]
    assert text.startswith("Green Villa: 3 updates, not confirmed yet.")
    assert "not reported" not in text


def test_pending_render_status_says_it_is_being_prepared():
    reply = generate_dpr_request_reply(_state(dpr_status="pending_render"))
    assert "prepared" in reply["pending_prompt"].lower()


def test_not_generated_status_explains_nothing_was_logged():
    reply = generate_dpr_request_reply(_state(dpr_status="not_generated"))
    text = reply["pending_prompt"].lower()
    assert "no dpr" in text


def test_missing_status_field_defaults_to_not_generated_not_a_crash():
    reply = generate_dpr_request_reply(
        {"collected_fields": {}}
    )
    assert "pending_prompt" in reply
