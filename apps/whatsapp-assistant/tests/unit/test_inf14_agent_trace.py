"""INF-14: each agent turn leaves a trace of what the model decided -- tool
names, argument names and outcomes -- never what the sender said."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

from channel.replies import ReplySpec
from mesiri_ai.models import ToolCallRecord, ToolOutcome, ToolRunResult
from runtime.agent.later import LaterItem
from runtime.agent.runner import AgentResult
from runtime.agent.toolbox import SavedItem
from runtime.agent.turn import _trace_tools


async def test_the_trace_names_tools_and_outcomes_but_holds_no_values():
    run = ToolRunResult(
        text="ok",
        calls=[
            ToolCallRecord(
                name="save_material_receipt",
                arguments={"material": "Holobricks", "quantity": 100, "unit": "nos"},
                outcome=ToolOutcome(content={"status": "saved", "saved_as": "Holobricks 100 nos"}),
            ),
            ToolCallRecord(
                name="still_to_do",
                arguments={"items": [{"tool": "save_labour", "what": "scaffolders came"}]},
                outcome=ToolOutcome(content={"status": "noted"}),
            ),
        ],
    )
    box = SimpleNamespace(
        parked_by=None, held=[], later=[LaterItem("save_labour", "scaffolders came")],
        saved=[SavedItem("save_material_receipt", "ok", "Holobricks 100 nos")],
    )
    logger = AsyncMock()
    deps = SimpleNamespace(trace_logger=logger)

    await _trace_tools("cor_1", AgentResult("ok", ReplySpec(text="ok"), box, run=run), deps)

    kwargs = logger.log_stage.await_args.kwargs
    assert kwargs["stage"] == "agent_tools" and kwargs["succeeded"] is True
    payload = kwargs["stage_payload"]
    assert payload["calls"] == [
        {"tool": "save_material_receipt", "args": ["material", "quantity", "unit"], "status": "saved"},
        {"tool": "still_to_do", "args": ["items"], "status": "noted"},
    ]
    assert payload["still_to_do"] == ["save_labour"] and payload["saved"] == ["save_material_receipt"]
    text = str(payload)
    assert "Holobricks" not in text and "100" not in text and "scaffolders" not in text


async def test_no_trace_logger_no_trace():
    box = SimpleNamespace(parked_by=None, held=[], later=[], saved=[])
    await _trace_tools("cor_1", AgentResult("ok", ReplySpec(text="ok"), box), SimpleNamespace(trace_logger=None))
