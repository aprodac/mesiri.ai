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
import time
from collections.abc import Mapping
from typing import Any, Protocol

logger = logging.getLogger(__name__)

#: How long the words of a message are kept: a swipe-reply to a week-old message
#: is rare, and one older than that is read as a plain message.
TTL_SECONDS = 7 * 24 * 3600
#: The longest text kept (a WhatsApp body is at most 4096 characters).
MAX_CHARS = 1500
#: ``text_of``'s "by" for a swiped message whose words are not kept (agent/turn.py).
UNKNOWN = "unknown"


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
    header and body, a photo's or document's caption, a template's filled-in values."""
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
    if kind == "template":
        # The template's own wording lives at Meta; its filled-in values are what
        # this message said (a reminder's site, a summary's figures).
        values = [
            str(parameter.get("text") or "")
            for component in payload.get("components") or []
            if isinstance(component, Mapping) and component.get("type") == "body"
            for parameter in component.get("parameters") or []
            if isinstance(parameter, Mapping) and parameter.get("type") == "text"
        ]
        return "\n".join(v for v in values if v)
    return ""


def media_label_of_fields(message_fields: Mapping[str, Any], shows: str | None = None) -> str:
    """What a sent picture / PDF / video shows, as a short bracketed label
    ("[picture: Workers list card, 29 Oct]"), or "" for a message with no media.
    Live 29 Oct: Mesiri kept only a caption, so a captionless card was "not sent"
    to it. ``shows`` is the sender's own description; without one the label still
    says a picture or file went out (a document names its file)."""
    kind = message_fields.get("type")
    payload = message_fields.get(str(kind)) if kind else None
    if not isinstance(payload, Mapping):
        return ""
    noun = {"image": "picture", "document": "PDF", "video": "video"}.get(str(kind))
    if kind == "interactive":
        header = payload.get("header")
        if isinstance(header, Mapping) and header.get("type") == "image":
            noun = "picture"
    if noun is None:
        return ""
    detail = (shows or "").strip()
    if not detail and kind == "document":
        detail = str(payload.get("filename") or "").strip()
    return f"[{noun}: {detail[:200]}]" if detail else f"[{noun}]"


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


async def _remember_last(recipient: str, text: str) -> None:
    store = _store
    if store is None or not recipient:
        return
    try:
        await store.set_json(
            f"last_sent:{recipient}", {"text": text[:MAX_CHARS], "at": time.time()}, ttl_seconds=24 * 3600
        )
    except Exception:  # noqa: BLE001
        logger.warning("sent_text.remember_last_failed")


#: How many recently sent pictures / files are kept per recipient, and for how long.
MEDIA_KEPT = 8
MEDIA_TTL_SECONDS = 24 * 3600


async def _remember_media(recipient: str, label: str) -> None:
    store = _store
    if store is None or not recipient:
        return
    try:
        kept = await store.get_json(f"sent_media:{recipient}")
        items = [i for i in kept if isinstance(i, dict)] if isinstance(kept, list) else []
        items.append({"label": label[:MAX_CHARS], "at": time.time()})
        await store.set_json(f"sent_media:{recipient}", items[-MEDIA_KEPT:], ttl_seconds=MEDIA_TTL_SECONDS)
    except Exception:  # noqa: BLE001
        logger.warning("sent_text.remember_media_failed")


async def recent_media_to(recipient: str | None) -> list[tuple[str, float]]:
    """``(label, sent at)`` of the pictures and files sent to ``recipient`` in the
    last day, oldest first. Never raises."""
    store = _store
    if store is None or not recipient:
        return []
    try:
        kept = await store.get_json(f"sent_media:{recipient}")
    except Exception:  # noqa: BLE001
        return []
    if not isinstance(kept, list):
        return []
    return [
        (str(i["label"]), float(i.get("at") or 0.0))
        for i in kept
        if isinstance(i, dict) and str(i.get("label") or "").strip()
    ]


def report_sent(
    *,
    wamid: str,
    message_fields: Mapping[str, Any],
    recipient: str | None = None,
    shows: str | None = None,
) -> None:
    """Called by the sender for every message it sent (channel/whatsapp/outbound.py).
    The latest one per ``recipient`` is kept too (``last_sent_to``). A picture or
    file is kept as its label (``shows``) plus its caption, caption or not."""
    if _store is None:
        return
    words = text_of_fields(message_fields).strip()
    label = media_label_of_fields(message_fields, shows)
    text = "\n".join(p for p in (label, words) if p)
    if not text:
        return
    jobs = [remember(wamid=wamid, text=text), _remember_last(recipient or "", text)]
    if label:
        jobs.append(_remember_media(recipient or "", label))
    for job in jobs:
        task = asyncio.ensure_future(job)
        _pending.add(task)
        task.add_done_callback(_pending.discard)


async def last_sent_to(recipient: str | None) -> tuple[str, float] | None:
    """``(text, sent at epoch seconds)`` of the latest message sent to
    ``recipient`` in the last day -- a reminder, a setup question, a DPR, a
    reply -- or None. Live 29 Oct: what Mesiri sent on its own (not as a reply)
    was never in the conversation the model sees, so "yes" to it meant nothing."""
    store = _store
    if store is None or not recipient:
        return None
    try:
        stored = await store.get_json(f"last_sent:{recipient}")
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(stored, dict) or not str(stored.get("text") or "").strip():
        return None
    return str(stored["text"]), float(stored.get("at") or 0.0)


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
