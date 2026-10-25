"""WEB-38: a question the agent answered with a lookup ("innu ethra per
vannu?", "stock ethra?") is tied in the message log to the lookup that
answered it, with its project and site, so the Live page can show the
question and Mesiri's answer."""

from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

from channel.replies import ReplySpec
from runtime.agent import journey_gateway
from runtime.agent.turn import _audit
from runtime.noop_loggers import RecordingMessageLogger


@pytest.mark.asyncio
async def test_an_answered_lookup_is_linked_with_its_site() -> None:
    logger = RecordingMessageLogger()
    message = SimpleNamespace(correlation_id="cor_q1")
    gateway = SimpleNamespace(handled=[], answered=[("wi_labour", "p1", "s1")])

    await _audit(message, gateway, ReplySpec(text="ഇന്ന് 5 പേർ"), SimpleNamespace(message_logger=logger))

    assert ("cor_q1", "wi_labour") in logger.workflow_links
    assert logger.completed == ["cor_q1"]


def test_the_gateway_records_what_it_answered() -> None:
    source = inspect.getsource(journey_gateway.JourneyGateway._direct)
    assert 'step.status == "answer"' in source and "self.answered.append" in source
