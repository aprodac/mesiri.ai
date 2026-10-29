"""Request 146 (live 29 Oct): Mesiri can look at the photo it is holding, and asks in the sender's language.

Replay of the Paraclette conversation: a captionless card went out, the sender
swiped it, said "njan image ayachilla" came back; a held photo was "not visible".
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from interactions.image_purpose import localized_picker
from interactions.pending_media import PendingMediaStore
from mesiri_contracts.assistant.enums import InputModality
from mesiri_contracts.assistant.normalized_message import (
    MediaReference,
    NormalizedMessage,
    SenderInfo,
)


class _Redis:
    def __init__(self) -> None:
        self.data: dict[str, Any] = {}

    def namespaced(self, *parts: str) -> str:
        return ":".join(parts)

    async def set_json(self, key: str, value: Any, *, ttl_seconds: int | None = None) -> None:
        self.data[key] = value

    async def get_json(self, key: str) -> Any | None:
        return self.data.get(key)


def _run(coro):  # noqa: ANN001, ANN202
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def test_picker_follows_the_users_language() -> None:
    assert localized_picker("english").text == "📷 What is this photo for?"
    manglish = localized_picker("manglish")
    assert "Ee photo" in manglish.text and manglish.list_rows  # still the picker, still not auto-saved


def test_look_at_held_photo_does_not_pop_the_batch() -> None:
    store = PendingMediaStore(_Redis())  # type: ignore[arg-type]
    msg = NormalizedMessage(
        message_id="wamid.1",
        correlation_id="cor_1",
        modality=InputModality.IMAGE,
        sender=SenderInfo(wa_id="919"),
        text=None,
        timestamp=datetime.now(UTC),
        media=MediaReference(object_key="k", mime_type="image/jpeg"),
    )

    async def go():  # noqa: ANN202
        await store.add_pending(user_id="u", message=msg)
        first = await store.peek(user_id="u")
        again = await store.peek(user_id="u")
        return len(first), len(again), await store.has_pending(user_id="u")

    assert _run(go()) == (1, 1, True)


def test_toolbox_look_at_photo_reads_only_when_called() -> None:
    from mesiri_ai.models import ToolOutcome  # noqa: F401
    from runtime.agent import toolbox as tb
    from runtime.agent.tools import LOOK_AT_PHOTO, ScopeLookup

    calls: list[int] = []

    async def look() -> str:
        calls.append(1)
        return "A delivery challan for 50 bags of cement"

    box = tb.AgentToolbox(gateway=object(), scope=ScopeLookup(), user_text="noki nok", look_at_photo=look)  # type: ignore[arg-type]
    assert calls == []  # nothing runs on the reply path until the model asks
    out = _run(box.handle(LOOK_AT_PHOTO, {}))
    assert calls == [1] and out.content["status"] == "seen"
    assert "cement" in out.content["photo_shows"]

    nothing = tb.AgentToolbox(gateway=object(), scope=ScopeLookup(), user_text="x")  # type: ignore[arg-type]
    assert _run(nothing.handle(LOOK_AT_PHOTO, {})).content["status"] == "unreadable"
