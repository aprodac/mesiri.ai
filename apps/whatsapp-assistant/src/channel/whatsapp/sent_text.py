"""What a WhatsApp message said, by its wamid (live 29 Oct: swipe-replies).

When a sender swipes one of Mesiri's messages and replies to it, Meta sends only
the quoted message's id (``context.id``), never its text. To know what they are
answering, the sender records the words of every message it sends
(``report_sent``), and the agent turn records the sender's own words under their
message id (``remember``). ``text_of`` reads either back.

Where the text goes is set once at startup (``set_store``,
runtime/dependencies.py): Redis, kept for a week. No store: nothing is kept and a
swipe-reply is read as a plain message, as before.

Fire-and-forget, like ``usage``: recording never raises and never delays a send.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from typing import Any, Protocol

logger = logging.getLogger(__name__)

#: How long the words of a message are kept: a swipe-reply to a week-old message
#: is rare, and one older than that is read as a plain message.
TTL_SECONDS = 7 * 24 * 3600
#: The longest text kept (a WhatsApp body is at most 4096 characters).
MAX_CHARS = 1500


class _RedisLike(Protocol):
    async def set_json(self, key: str, value: Any, *, ttl_seconds: int | None = None) -> None: ...
    async def get_json(self, key: str) -> Any | None: ...


_store: _RedisLike | None = None
_pending: set[asyncio.Task[None]] = set()


def set_store(store: _RedisLike | None) -> None:
    global _store
    _store = store


def _key(wamid: str) -> str:
    return f"sent_text:{wamid}"


def text_of_fields(message_fields: Mapping[str, Any]) -> str:
    """The words a sent message shows: a text's body, an interactive message's
    header and body, a photo's or document's caption; empty for a template."""
    kind = message_fields.get("type")
    payload = message_fields.get(str(kind)) if kind else None
    if not isinstance(payload, Mapping):
        return ""
    if kind == "text":
        return str(payload.get("body") or "")
    if kind == "interactive":
        header = payload.get("header") or {}
        body = payload.get("body") or {}
        parts = [
            str(header.get("text") or "") if isinstance(header, Mapping) else "",
            str(body.get("text") or "") if isinstance(body, Mapping) else "",
        ]
        return "\n".join(p for p in parts if p)
    if kind in ("image", "document", "video"):
        return str(payload.get("caption") or "")
    return ""


async def remember(*, wamid: str, text: str, by: str = "mesiri") -> None:
    """Keep ``text`` under ``wamid``; ``by`` is "mesiri" or "sender". Never raises."""
    store = _store
    words = (text or "").strip()
    if store is None or not wamid or not words:
        return
    try:
        await store.set_json(_key(wamid), {"text": words[:MAX_CHARS], "by": by}, ttl_seconds=TTL_SECONDS)
    except Exception:  # noqa: BLE001 -- a swipe-reply then reads as a plain message
        logger.warning("sent_text.remember_failed wamid=%s", wamid)


def report_sent(*, wamid: str, message_fields: Mapping[str, Any]) -> None:
    """Called by the sender for every message it sent (channel/whatsapp/outbound.py)."""
    if _store is None:
        return
    text = text_of_fields(message_fields)
    if not text:
        return
    task = asyncio.ensure_future(remember(wamid=wamid, text=text))
    _pending.add(task)
    task.add_done_callback(_pending.discard)


async def text_of(wamid: str | None) -> tuple[str, str] | None:
    """``(text, by)`` of the message ``wamid``, or None when it is not known."""
    store = _store
    if store is None or not wamid:
        return None
    try:
        stored = await store.get_json(_key(wamid))
    except Exception:  # noqa: BLE001
        logger.warning("sent_text.lookup_failed wamid=%s", wamid)
        return None
    if not isinstance(stored, dict) or not str(stored.get("text") or "").strip():
        return None
    return str(stored["text"]), str(stored.get("by") or "mesiri")
