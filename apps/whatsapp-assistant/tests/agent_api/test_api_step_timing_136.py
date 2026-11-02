"""WA-136: v3 records its own steps on the journey's timer, so the perf report shows where a v3
reply's seconds go (facts + memory, the model and its tools, the send, the memory write) instead
of one ``_unaccounted_ms``. Guard: without a timer nothing changes; a failing timer never breaks a reply."""

from __future__ import annotations

from tests.agent_api.test_api_agent_124 import CTX, _message, _service, _stand_in_tools  # noqa: F401 (autouse)

from mesiri_ai.fakes import FakeToolCallingProvider
from runtime.step_timing import StepTimer


async def test_a_text_turn_records_its_steps() -> None:
    service, sent = _service(FakeToolCallingProvider(["Hello."]))
    timer = StepTimer()
    assert await service.handle(_message("hi there"), CTX, lap=timer.lap)
    steps = timer.steps
    for name in ("v3_facts_memory", "v3_model_tools", "v3_send", "v3_log", "v3_memory_write"):
        assert name in steps, steps
    assert sent  # the reply still went


async def test_guard_no_timer_and_a_broken_timer_change_nothing() -> None:
    service, sent = _service(FakeToolCallingProvider(["Hello.", "Hello again."]))
    assert await service.handle(_message("hi"), CTX)

    def broken(name: str) -> None:
        raise RuntimeError("timer broke")

    assert await service.handle(_message("hi"), CTX, lap=broken)
    assert len(sent) == 2
