"""WEB-37: a voice note's English (from the speech step) is kept with its
words in the message log, so the Live report can show it being read."""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from channel.replies import ReplySpec
from mesiri_contracts.assistant.enums import InputModality
from mesiri_contracts.assistant.normalized_message import NormalizedMessage, SenderInfo
from runtime.agent.runner import AgentResult
from runtime.agent.turn import AgentTurnDeps, run_agent_turn
from runtime.noop_loggers import RecordingMessageLogger

WORDS = "ഇന്ന് അഞ്ച് പണിക്കാരുണ്ടായിരുന്നു"
ENGLISH = "There were five workers today"


def _voice() -> NormalizedMessage:
    return NormalizedMessage(
        message_id="wamid.voice.1",
        sender=SenderInfo(wa_id="919876543210", profile_name="Ravi"),
        timestamp=dt.datetime(2026, 10, 25, 13, tzinfo=dt.UTC),
        modality=InputModality.VOICE,
        text="",
    )


async def _run(
    transcript: str, translated: str | None
) -> tuple[RecordingMessageLogger, NormalizedMessage]:
    logger = RecordingMessageLogger()
    runner = SimpleNamespace(
        run=AsyncMock(
            return_value=AgentResult(
                outcome="ok", reply=ReplySpec(text="Saved"), toolbox=SimpleNamespace(parked=None)
            )
        )
    )
    gateway = SimpleNamespace(handled=[], finish=AsyncMock())
    deps = AgentTurnDeps(
        runner=runner,
        make_gateway=lambda msg, language: gateway,
        send_spec=AsyncMock(),
        transcribe=AsyncMock(return_value=(transcript, translated, "ml-IN")),
        message_logger=logger,
        send_agent_reply=AsyncMock(),
    )
    actor = SimpleNamespace(
        user_id=str(uuid.uuid4()),
        full_name="Ravi",
        role="SITE_ENGINEER",
        org_name="Acme",
        projects=[],
        sites=[],
        organization_id=str(uuid.uuid4()),
    )
    message = _voice()
    await run_agent_turn(message, actor, deps)
    return logger, message


@pytest.mark.asyncio
async def test_the_english_is_kept_with_the_words() -> None:
    logger, message = await _run(WORDS, ENGLISH)

    assert logger.transcriptions == [(message.correlation_id, WORDS)]
    assert logger.translations == [(message.correlation_id, ENGLISH)]


@pytest.mark.asyncio
@pytest.mark.parametrize("translated", [None, "", "   ", WORDS])
async def test_no_english_kept_when_there_is_none_or_it_says_the_same(translated) -> None:
    logger, _ = await _run(WORDS, translated)

    assert logger.translations == []
