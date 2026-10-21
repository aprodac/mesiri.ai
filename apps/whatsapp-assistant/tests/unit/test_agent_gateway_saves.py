"""WA-37: the agent only hears "saved" when the record was actually written."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from mesiri_contracts.application.results.execution_result import ExecutionStatus
from runtime.agent.journey_gateway import JourneyGateway
from workflows import WorkflowRunStatus


def _gateway(saved):
    async def process(message, pipeline, sink):
        run = SimpleNamespace(status=WorkflowRunStatus.STARTED, workflow_key=SimpleNamespace(value="site_issue_report"))
        return SimpleNamespace(workflow_run=run, planner_decision=None)

    async def save_now():
        return saved

    return JourneyGateway(
        message=SimpleNamespace(model_copy=lambda update: SimpleNamespace()),
        process=process,
        save_now=save_now,
        undo=None,
        followups=None,
        held_prompt=None,
    )


def _handled(status, reply="✅ Recorded. Thank you."):
    return SimpleNamespace(
        reply_text=reply,
        execution_result=SimpleNamespace(status=status, material_row_id="r1"),
        result=SimpleNamespace(confirmed_action=None),
    )


async def test_a_written_record_is_saved():
    gateway = _gateway(_handled(ExecutionStatus.SUCCEEDED))
    step = await gateway.run(SimpleNamespace(), text="rain today")
    assert step.status == "saved"
    assert len(gateway.handled) == 1


@pytest.mark.parametrize("status", [s for s in ExecutionStatus if s is not ExecutionStatus.SUCCEEDED])
async def test_a_refused_or_failed_save_is_never_called_saved(status):
    gateway = _gateway(_handled(status, reply="That issue is already reported today."))
    step = await gateway.run(SimpleNamespace(), text="rain today")
    assert step.status == "error"
    assert step.text == "That issue is already reported today."
    assert gateway.handled == []  # no Save card, no follow-ups for it


async def test_a_save_with_no_execution_is_not_saved():
    handled = _handled(ExecutionStatus.SUCCEEDED)
    handled.execution_result = None
    step = await _gateway(handled).run(SimpleNamespace(), text="rain today")
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
