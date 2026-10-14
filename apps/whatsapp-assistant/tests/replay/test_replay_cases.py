"""Replay suite (WA-15): real conversations that went wrong, kept as regression cases.

Each file in ``cases/`` is one message a real user sent (paraphrased and moved
onto the seed company, see ``context/seed.py``), what the AI understood from
it, and what the assistant should have done. The harness runs everything
*after* the AI step for real -- context, canonicalization, gates, planner,
workflow registry, reply rendering -- with the AI providers replaced by the
recorded understanding, so a case is deterministic and needs no network.

``status``:
- ``passing``: must pass. A failure is a regression.
- ``known_failure``: reproduces a problem not fixed yet. It runs as a strict
  xfail, so CI stays green while it fails, and turns red the moment it starts
  passing, which forces whoever fixed it to flip the case to ``passing`` and
  close the finding. WA-16 starts from these.

Scope: one message per case. Follow-ups that depend on the previous turn
(answering "which unit?", tapping a button) go through
runtime/message_journey.py, which this harness does not drive yet (WA-15b).
See README.md for the case format.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from context import seed
from context.resolver import ContextResolver
from interactions.category_hint import CategoryHintStore
from interactions.handler import InteractionHandler
from interactions.pending_report import PendingReportStore
from mesiri.infrastructure.objectstorage.fake import FakeObjectStorage
from mesiri_ai.fakes import FakeExtractionProvider, FakeVisionProvider, FakeVoiceExtractionProvider
from mesiri_ai.models import ExtractionResult
from mesiri_contracts.assistant.enums import InputModality
from mesiri_contracts.assistant.normalized_message import NormalizedMessage, SenderInfo
from planner import Planner
from runtime.inbound_journey import process_inbound_message
from runtime.noop_loggers import RecordingMessageLogger, RecordingTraceLogger
from understanding.pipeline import UnderstandingPipeline
from workflows import WorkflowRegistry, WorkflowRuntime
from workflows.fakes import FakeWorkflowInstanceRepository

CASES_DIR = Path(__file__).parent / "cases"

SENDERS = {
    "engineer": seed.WA_ENGINEER,
    "director": seed.WA_DIRECTOR,
    "abc_director": seed.WA_ABC_DIRECTOR,
    "unknown": seed.WA_UNKNOWN,
}

_CASE_KEYS = {
    "id",
    "source",
    "description",
    "status",
    "finding",
    "sender",
    "message",
    "understanding",
    "expect",
}
_EXPECT_KEYS = {
    "event_type",
    "decision",
    "workflow_key",
    "reply_kind",
    "reply_contains",
    "reply_not_contains",
    "reply_max_chars",
    "options_include",
}


class _MemoryRedis:
    """Just enough of the Redis adapter for the pending-report/category stores."""

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    def namespaced(self, *parts: str) -> str:
        return ":".join(parts)

    async def set_json(self, key: str, value: Any, *, ttl_seconds: int | None = None) -> None:
        self._data[key] = value

    async def get_json(self, key: str) -> Any | None:
        return self._data.get(key)

    async def get_delete_json(self, key: str) -> Any | None:
        return self._data.pop(key, None)

    async def delete(self, *keys: str) -> None:
        for key in keys:
            self._data.pop(key, None)


@dataclass
class Observed:
    event_type: str | None = None
    decision: str | None = None
    workflow_key: str | None = None
    replies: list[dict[str, Any]] = field(default_factory=list)

    @property
    def reply(self) -> dict[str, Any] | None:
        return self.replies[-1] if self.replies else None


async def run_case(case: dict[str, Any]) -> Observed:
    """Sends the case's one message through the real pipeline; returns what happened."""
    understanding = ExtractionResult(model="replay", latency_ms=0.0, **case["understanding"])
    message = case["message"]
    modality = InputModality(message.get("modality", "text"))
    sender = SENDERS[case.get("sender", "engineer")]

    observed = Observed()

    async def send_text(wa_id: str, body: str) -> None:
        observed.replies.append({"kind": "text", "text": body, "options": []})

    async def send_list(wa_id: str, *, body: str, button_label: str, rows) -> None:  # noqa: ANN001
        observed.replies.append({"kind": "list", "text": body, "options": [r.title for r in rows]})

    async def send_button(wa_id: str, *, body: str, buttons) -> None:  # noqa: ANN001
        observed.replies.append(
            {"kind": "buttons", "text": body, "options": [b.title for b in buttons]}
        )

    runtime = WorkflowRuntime(registry=WorkflowRegistry(), repo=FakeWorkflowInstanceRepository())
    redis = _MemoryRedis()
    result = await process_inbound_message(
        NormalizedMessage(
            message_id=f"wamid.replay.{case['id']}",
            correlation_id=f"cor_replay_{case['id']}",
            sender=SenderInfo(wa_id=sender, profile_name="Replay"),
            timestamp=datetime(2026, 7, 9, 10, 0, tzinfo=UTC),
            modality=modality,
            text=message.get("text"),
        ),
        sender,
        pipeline=UnderstandingPipeline(
            voice_extraction=FakeVoiceExtractionProvider(understanding),
            vision=FakeVisionProvider(None),
            extraction=FakeExtractionProvider(understanding),
            object_storage=FakeObjectStorage(),
        ),
        context_resolver=ContextResolver(seed.build_dependencies()),
        planner=Planner(),
        workflow_runtime=runtime,
        interaction_handler=InteractionHandler(workflow_runtime=runtime),
        send_text=send_text,
        send_list=send_list,
        send_button=send_button,
        message_logger=RecordingMessageLogger(),
        trace_logger=RecordingTraceLogger(),
        pending_report_store=PendingReportStore(redis),
        category_hint_store=CategoryHintStore(redis),
    )
    if result.canonical_event is not None:
        observed.event_type = result.canonical_event.event_type.value
    if result.planner_decision is not None:
        observed.decision = result.planner_decision.decision_type.value
        key = result.planner_decision.workflow_key
        observed.workflow_key = key.value if key is not None else None
    return observed


def check(expect: dict[str, Any], observed: Observed) -> list[str]:
    """Every way ``observed`` misses ``expect``, in plain words (empty = pass)."""
    problems: list[str] = []
    for key in ("event_type", "decision", "workflow_key"):
        if key in expect and expect[key] != getattr(observed, key):
            problems.append(f"{key}: expected {expect[key]!r}, got {getattr(observed, key)!r}")

    reply = observed.reply
    reply_keys = _EXPECT_KEYS - {"event_type", "decision", "workflow_key"}
    if reply is None:
        if reply_keys & expect.keys():
            problems.append("no reply was sent")
        return problems
    text = reply["text"] or ""
    low = text.lower()
    if "reply_kind" in expect and reply["kind"] != expect["reply_kind"]:
        problems.append(f"reply_kind: expected {expect['reply_kind']!r}, got {reply['kind']!r}")
    for needle in expect.get("reply_contains", []):
        if needle.lower() not in low:
            problems.append(f"reply should contain {needle!r}: {text!r}")
    for needle in expect.get("reply_not_contains", []):
        if needle.lower() in low:
            problems.append(f"reply should not contain {needle!r}: {text!r}")
    if "reply_max_chars" in expect and len(text) > expect["reply_max_chars"]:
        problems.append(f"reply is {len(text)} chars, max {expect['reply_max_chars']}")
    options = [o.lower() for o in reply["options"]]
    for option in expect.get("options_include", []):
        if option.lower() not in options:
            problems.append(f"options should include {option!r}: {reply['options']}")
    return problems


def _load_cases() -> list[Any]:
    params = []
    for path in sorted(CASES_DIR.glob("*.json")):
        case = json.loads(path.read_text(encoding="utf-8"))
        marks = []
        if case.get("status") == "known_failure":
            marks.append(
                pytest.mark.xfail(
                    strict=True,
                    reason=f"known failure (finding {case.get('finding', '?')}); flip to 'passing' once fixed",
                )
            )
        params.append(pytest.param(path, case, id=path.stem, marks=marks))
    return params


def test_cases_are_well_formed():
    paths = sorted(CASES_DIR.glob("*.json"))
    assert paths, "no replay cases found"
    for path in paths:
        case = json.loads(path.read_text(encoding="utf-8"))
        assert case.get("id") == path.stem, f"{path.name}: id must equal the file name"
        assert set(case) <= _CASE_KEYS, f"{path.name}: unknown keys {set(case) - _CASE_KEYS}"
        assert case.get("status") in ("passing", "known_failure"), f"{path.name}: bad status"
        assert case.get("source") and case.get("description"), (
            f"{path.name}: say where it came from and what it is"
        )
        assert case.get("sender", "engineer") in SENDERS, f"{path.name}: unknown sender"
        assert case["expect"] and set(case["expect"]) <= _EXPECT_KEYS, (
            f"{path.name}: bad expect keys"
        )
        if case["status"] == "known_failure":
            assert case.get("finding"), f"{path.name}: a known failure must name its finding"


@pytest.mark.parametrize(("path", "case"), _load_cases())
async def test_replay_case(path: Path, case: dict[str, Any]):
    try:
        observed = await run_case(case)
    except ModuleNotFoundError as exc:
        # Workflow graphs need the optional `workflow` extra (LangGraph).
        if (exc.name or "").split(".")[0] == "langgraph":
            pytest.skip("needs LangGraph: install the `workflow` extra to run workflow cases")
        raise
    problems = check(case["expect"], observed)
    assert not problems, f"{path.name}: {case['description']}\n  " + "\n  ".join(problems)
