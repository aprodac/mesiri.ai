"""The photo -> vision -> agent hand-off, for attendance sheets.

An attendance sheet is the hardest thing this pipeline carries: a receipt has
about six scalar fields, a roster has fifteen rows of two. The hand-off between
the vision call and the extraction call was built for the former, and these
tests pin the three things that make it survive the latter.

Why this is worth its own file: every failure here *looks* like the AI failing
to read handwriting, so without these it would be diagnosed as "Gemini can't
read the sheet" when in fact the names were read correctly and thrown away in
transit. That misdiagnosis would be expensive -- it points at prompt tuning
instead of at ten lines of plumbing.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from mesiri_ai.models import VisionResult
from understanding.pipeline import _render_vision_value


class _RecordingVision:
    """Captures what the pipeline asked vision for, and returns a canned read."""

    def __init__(self, result: VisionResult) -> None:
        self._result = result
        self.hint: str | None = None
        self.calls = 0

    async def analyze_image(self, image, *, mime_type=None, hint=None, correlation_id=None):
        self.calls += 1
        self.hint = hint
        return self._result


# --- structure must survive the hand-off ----------------------------------


def test_a_worker_list_is_handed_over_as_json_not_python_repr():
    """The defect this guards: str() on a list of dicts produces
    ``[{'name': 'Ravi'}]`` -- single-quoted, not JSON -- which the extraction
    model then has to re-parse by eye. Fifteen workers become an unparseable
    blob that reads exactly like a failed handwriting read."""
    rendered = _render_vision_value(
        [{"name": "Ravi", "trade": "mason"}, {"name": "Arun", "trade": "painter"}]
    )
    assert json.loads(rendered) == [
        {"name": "Ravi", "trade": "mason"},
        {"name": "Arun", "trade": "painter"},
    ]
    assert "'" not in rendered


def test_scalars_still_render_as_plain_prose():
    """Receipts must be unaffected -- the extraction prompt was tuned against
    ``amount: 250`` reading like prose, not ``amount: "250"``."""
    assert _render_vision_value(250) == "250"
    assert _render_vision_value("ABC Suppliers") == "ABC Suppliers"


def test_unserializable_values_fall_back_instead_of_raising():
    """A vision provider returning something exotic must not take down the
    whole report."""
    assert _render_vision_value([{1, 2, 3}])


def test_nested_dicts_survive_too():
    assert json.loads(_render_vision_value({"total": {"amount": 12}})) == {"total": {"amount": 12}}


# --- the purpose tap reaches the vision model -----------------------------


async def _describe(vision, *, hint):
    from unittest.mock import AsyncMock

    from mesiri_contracts.assistant.enums import InputModality
    from mesiri_contracts.assistant.normalized_message import (
        MediaReference,
        NormalizedMessage,
        SenderInfo,
    )
    from understanding.pipeline import UnderstandingPipeline

    storage = AsyncMock()
    storage.get_object.return_value = type("Obj", (), {"data": b"fake-bytes"})()
    pipeline = UnderstandingPipeline(voice_extraction=AsyncMock(), vision=vision, object_storage=storage)
    message = NormalizedMessage(
        message_id="msg_1",
        correlation_id="cor_1",
        sender=SenderInfo(wa_id="919000000000", profile_name="Ravi"),
        timestamp=datetime(2026, 7, 26, 9, 0, tzinfo=UTC),
        modality=InputModality.IMAGE,
        media=MediaReference(object_key="media/sheet.jpg", mime_type="image/jpeg"),
    )
    return await pipeline.describe_media(message, hint)


async def test_the_attendance_tap_is_passed_to_the_vision_model():
    """When the user taps "Attendance" we already know what the photo is.
    Telling the vision model is the difference between transcribing rows and
    describing "a handwritten document on a clipboard"."""
    vision = _RecordingVision(
        VisionResult(document_classification="attendance_sheet", description="roster", raw_fields={})
    )
    await _describe(vision, hint="labour_update")
    assert vision.hint == "labour_update"


async def test_no_hint_is_passed_through_as_none():
    vision = _RecordingVision(
        VisionResult(document_classification="receipt", description="bill", raw_fields={"amount": 250})
    )
    await _describe(vision, hint=None)
    assert vision.hint is None


async def test_the_worker_list_reaches_the_agent_intact():
    """The agent reads the vision description with the fields it read: the
    roster arrives as JSON, names and all."""
    workers = [{"name": "Ravi", "trade": "mason"}, {"name": "Suresh", "trade": "helper"}]
    vision = _RecordingVision(
        VisionResult(document_classification="attendance_sheet", description="Attendance register", raw_fields={"workers": workers})
    )
    shown = await _describe(vision, hint="labour_update")
    assert shown.startswith("Attendance register (workers: ")
    assert json.dumps(workers) in shown


async def test_an_unreadable_photo_is_none():
    vision = _RecordingVision(VisionResult(document_classification="unknown", description="", raw_fields={}))
    assert await _describe(vision, hint=None) is None
