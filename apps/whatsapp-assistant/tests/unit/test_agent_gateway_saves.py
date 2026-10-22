"""WA-37: the agent only hears "saved" when the record was actually written."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from mesiri_contracts.application.results.execution_result import ExecutionStatus
from mesiri_contracts.assistant.candidates import Candidate
from mesiri_contracts.assistant.enums import InputModality, SemanticType
from mesiri_contracts.assistant.normalized_message import NormalizedMessage, SenderInfo
from runtime.agent.journey_gateway import JourneyGateway
from workflows import WorkflowRunStatus


class _Entry:
    """Any direct entry: the tool's arguments as a workflow's start."""

    async def prepare(self, message, understanding, candidate):  # noqa: ANN001
        return SimpleNamespace(decision=None, event=None)

    async def remember(self, ready, *, correlation_id):  # noqa: ANN001
        return None


def _gateway(saved):
    async def start_workflow(decision, event):  # noqa: ANN001
        return SimpleNamespace(status=WorkflowRunStatus.STARTED, workflow_key=SimpleNamespace(value="site_issue_report"))

    async def save_now():
        return saved

    entry = _Entry()
    return JourneyGateway(
        message=NormalizedMessage(
            message_id="wamid.1",
            correlation_id="cor",
            sender=SenderInfo(wa_id="919876543210"),
            timestamp=datetime(2026, 10, 22, 10, tzinfo=UTC),
            modality=InputModality.TEXT,
            text="rain today",
        ),
        save_now=save_now,
        undo=None,
        followups=None,
        held_prompt=None,
        material_entry=entry,
        site_entry=entry,
        labour_entry=entry,
        query_entry=entry,
        start_workflow=start_workflow,
    )


_ISSUE = Candidate(semantic_type=SemanticType.SITE_ISSUE, fields={})


def _handled(status, reply="✅ Recorded. Thank you."):
    return SimpleNamespace(
        reply_text=reply,
        execution_result=SimpleNamespace(status=status, material_row_id="r1"),
        result=SimpleNamespace(confirmed_action=None),
    )


async def test_a_written_record_is_saved():
    gateway = _gateway(_handled(ExecutionStatus.SUCCEEDED))
    step = await gateway.run(_ISSUE, text="rain today")
    assert step.status == "saved"
    assert len(gateway.handled) == 1


@pytest.mark.parametrize("status", [s for s in ExecutionStatus if s is not ExecutionStatus.SUCCEEDED])
async def test_a_refused_or_failed_save_is_never_called_saved(status):
    gateway = _gateway(_handled(status, reply="That issue is already reported today."))
    step = await gateway.run(_ISSUE, text="rain today")
    assert step.status == "error"
    assert step.text == "That issue is already reported today."
    assert gateway.handled == []  # no Save card, no follow-ups for it


async def test_a_save_with_no_execution_is_not_saved():
    handled = _handled(ExecutionStatus.SUCCEEDED)
    handled.execution_result = None
    step = await _gateway(handled).run(_ISSUE, text="rain today")
    assert step.status == "error"


async def test_a_unit_conversion_is_set_through_the_wired_service_and_said_back():
    calls = []

    async def set_conversion(material, unit, count):
        calls.append((material, unit, count))
        return "Saved for the company: 28 bags of Sand = 1 m³."

    gateway = _gateway(None)
    gateway.set_conversion = set_conversion
    step = await gateway.set_unit_conversion(material="sand", unit="bags", count=28)
    assert calls == [("sand", "bags", 28)]
    assert (step.status, step.text) == ("answer", "Saved for the company: 28 bags of Sand = 1 m³.")


async def test_a_refused_unit_conversion_is_said_as_it_is():
    async def set_conversion(material, unit, count):
        return "Only your admin or a project manager can set that for the company."

    gateway = _gateway(None)
    gateway.set_conversion = set_conversion
    step = await gateway.set_unit_conversion(material="sand", unit="bags", count=28)
    assert step.status == "info"


async def test_a_lookup_is_an_answer_not_a_save():
    """Round 3b: a stock question ended with "Wrong? Reply UNDO." -- its run
    goes through the save step, but it keeps nothing."""
    gateway = _gateway(_handled(ExecutionStatus.SUCCEEDED, reply="Cement: 398 bag in stock."))
    step = await gateway.run(Candidate(semantic_type=SemanticType.INVENTORY_QUERY, fields={}), text="cement stock?")
    assert step.status == "answer"
    assert step.text == "Cement: 398 bag in stock."
    assert gateway.handled == []


async def test_a_kind_with_no_entry_is_a_failure_not_a_question():
    """ARCH-06: there is no classic route behind the gateway; what has no
    entry is said plainly, never parked as a question."""
    step = await _gateway(None).run(SimpleNamespace(semantic_type=None), text="Yes")
    assert step.status == "error" and step.reply is None
