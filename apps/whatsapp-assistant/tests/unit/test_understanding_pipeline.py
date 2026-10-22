"""What is left of the understanding pipeline (ARCH-06): the words of a voice
note for the agent, and media read once through object storage."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from mesiri_contracts.assistant.enums import InputModality
from mesiri_contracts.assistant.normalized_message import (
    MediaReference,
    NormalizedMessage,
    SenderInfo,
)
from mesiri_contracts.common.errors import MesiriError
from understanding.pipeline import UnderstandingPipeline


def _voice(media: MediaReference | None = MediaReference(object_key="media/v.ogg", mime_type="audio/ogg")):
    return NormalizedMessage(
        message_id="m1",
        correlation_id="c1",
        sender=SenderInfo(wa_id="919000000000"),
        timestamp=datetime(2026, 10, 22, 9, tzinfo=UTC),
        modality=InputModality.VOICE,
        media=media,
    )


def _pipeline(voice):  # noqa: ANN001
    storage = AsyncMock()
    storage.get_object.return_value = SimpleNamespace(data=b"ogg")
    return UnderstandingPipeline(voice_extraction=voice, vision=AsyncMock(), object_storage=storage), storage


async def test_a_voice_note_gives_its_words_and_language():
    voice = AsyncMock()
    voice.understand_voice.return_value = SimpleNamespace(
        transcript="innu 6 mason vannu", translated_text="6 masons came today", detected_language="Malayalam"
    )
    pipeline, storage = _pipeline(voice)
    assert await pipeline.transcribe_voice(_voice()) == ("innu 6 mason vannu", "6 masons came today", "Malayalam")
    # The same media is read once.
    await pipeline.transcribe_voice(_voice())
    storage.get_object.assert_awaited_once_with("media/v.ogg")


async def test_media_without_a_reference_is_a_validation_error():
    pipeline, _ = _pipeline(AsyncMock())
    with pytest.raises(MesiriError):
        await pipeline.transcribe_voice(_voice(media=None))
