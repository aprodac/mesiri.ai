"""M2 -> M3 contract tests: shared NormalizedMessage through understanding."""

from __future__ import annotations

from datetime import UTC, datetime

from mesiri_contracts.assistant.enums import InputModality
from mesiri_contracts.assistant.normalized_message import (
    NormalizedMessage,
    SenderInfo,
)


def _msg(**kw) -> NormalizedMessage:
    base = dict(
        message_id="wamid.1",
        sender=SenderInfo(wa_id="15550001111"),
        timestamp=datetime.now(UTC),
        modality=InputModality.TEXT,
        text="paid 1500 to ABC Hardware",
    )
    base.update(kw)
    return NormalizedMessage(**base)




async def test_normalized_message_has_default_correlation_id():
    assert _msg().correlation_id.startswith("cor_")


