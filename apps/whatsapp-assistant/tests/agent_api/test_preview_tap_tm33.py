"""TM-33: Confirm / Change it under a preview are answered by code in every mode and traced as preview_feedback."""

from __future__ import annotations

import pytest
from tests.agent_api.test_api_whatsapp_119 import _journey, _message, _stand_in_tools  # noqa: F401 (autouse)
from tests.unit.test_agent_routing import ASK

from mesiri_ai.fakes import FakeToolCallingProvider
from runtime.previews import FEEDBACK_STAGE

CID = "cor_0123456789abcdef0123456789abcdef"


@pytest.mark.parametrize("mode", ["api", "classic"])
@pytest.mark.parametrize(("tap", "words"), [(f"preview_ok:{CID}", "finish it like that"), (f"preview_change:{CID}", "What should be different?")])
async def test_a_preview_tap_is_answered_and_traced(monkeypatch, mode, tap, words) -> None:
    on_normalized, deps, harness = _journey(monkeypatch, mode, FakeToolCallingProvider(list(ASK._script)))
    await on_normalized(_message("Confirm ✅", tap=tap), {})
    texts = [c.args[1] for c in deps["sender"].send_text.await_args_list]
    assert any(words in t for t in texts), texts
    assert harness.seen == []
    stages = [c.kwargs.get("stage") for c in deps["trace_logger"].log_stage.await_args_list]
    assert FEEDBACK_STAGE in stages
