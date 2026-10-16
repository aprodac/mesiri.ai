"""Forwarded batches: one summary reply instead of one reply each (WA-02).

An engineer often forwards a whole group's worth of updates at once. Each
forwarded message is still processed exactly as before (saved as a draft,
WA-01) -- only its replies are held back. After `window` seconds with no
further forwarded message from that sender, one summary goes:

    📥 Got 6 forwarded messages:
    • ✅ Saved: Plastering, wall 2 (40 sqm)
    • ✅ Saved: 10 workers
    ...
    Saved ones are drafts for today; you'll confirm them with tonight's
    report. Reply UNDO to remove the last one.

The wait starts once no forwarded message from that sender is still being
processed (AI reading a voice note or photo takes seconds), so a slow one
still joins the summary. A single forwarded message gets its own reply,
unchanged, after the wait.
If messages in the batch asked a question, only the last one can still be
answered (one pending question per person), so it is sent after the
summary and the earlier ones are marked "not saved, send it again on its
own" (WA-03: ask only what can't wait).

How: `BatchingSender` wraps the WhatsApp sender. While a forwarded message
is being processed (`capturing()`), its text / list / button sends are
recorded instead of sent; everything else (images, documents, read
receipts) goes as usual. The recorded replies join the sender's batch in
Redis; a delayed task sends the summary if no newer message joined it, the
Redis lock making sure only one worker does. If that task is lost (a
restart), the sender's next message flushes the stale batch first.

Dates: a forwarded update is "today" unless it says otherwise -- the same
rule as every message (canonicalization/occurred_date.py).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Iterator
from contextvars import ContextVar
from typing import Any

from channel.replies import ListRow

_log = logging.getLogger("mesiri.forward_batch")

_capture: ContextVar[list[dict[str, Any]] | None] = ContextVar("forward_capture", default=None)
_known_sender: ContextVar[bool] = ContextVar("forward_known_sender", default=False)

SUMMARY_HEADER = "📥 Got {n} forwarded messages:"
SUMMARY_FOOTER = (
    "Saved ones are drafts for today; you'll confirm them with tonight's report. "
    "Reply UNDO to remove the last one."
)
NOT_SAVED = " _(not saved, send it again on its own)_"
QUESTION_BELOW = " _(question below)_"

_SKIP_LINES = ("Saved as a draft", "Reply UNDO")
_LINE_MAX = 140
_TTL_SECONDS = 600
_LOCK_TTL_SECONDS = 5
#: A batch untouched this many windows is flushed by the next message even
#: if it still counts a message in progress (that process died).
_STUCK_WINDOWS = 6


def is_forwarded(message: Any) -> bool:
    return bool((getattr(message, "metadata", None) or {}).get("forwarded"))


def is_capturing() -> bool:
    return _capture.get() is not None


def mark_known_sender() -> None:
    """The journey resolved the sender to a company user (only they batch)."""
    _known_sender.set(True)


# ---------------------------------------------------------------------------
# The sender wrapper
# ---------------------------------------------------------------------------


def _rows(rows: list[ListRow]) -> list[dict[str, str]]:
    return [{"id": r.id, "title": r.title, "description": r.description} for r in rows]


class BatchingSender:
    """The WhatsApp sender, holding back text / list / button replies while
    a forwarded message is being processed."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    async def send_text(self, to_wa_id: str, body: str) -> bool:
        captured = _capture.get()
        if captured is None:
            return await self._inner.send_text(to_wa_id, body)
        captured.append({"kind": "text", "body": body})
        return True

    async def send_text_capturing_id(self, to_wa_id: str, body: str) -> str | None:
        captured = _capture.get()
        if captured is None:
            return await self._inner.send_text_capturing_id(to_wa_id, body)
        captured.append({"kind": "text", "body": body})
        return None  # no wamid: a reply to the summary isn't tied to this item

    async def send_list(self, to_wa_id: str, **kwargs: Any) -> bool:
        captured = _capture.get()
        if captured is None:
            return await self._inner.send_list(to_wa_id, **kwargs)
        captured.append({"kind": "list", **kwargs, "rows": _rows(kwargs.get("rows") or [])})
        return True

    async def send_button(self, to_wa_id: str, **kwargs: Any) -> bool:
        captured = _capture.get()
        if captured is None:
            return await self._inner.send_button(to_wa_id, **kwargs)
        captured.append({"kind": "button", **kwargs, "buttons": _rows(kwargs.get("buttons") or [])})
        return True

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


# ---------------------------------------------------------------------------
# The summary
# ---------------------------------------------------------------------------


def _line(sends: list[dict[str, Any]]) -> str:
    for send in sends:
        for raw in str(send.get("body") or "").splitlines():
            line = raw.strip()
            if line and not line.startswith(_SKIP_LINES):
                return line if len(line) <= _LINE_MAX else line[: _LINE_MAX - 1] + "…"
    return "(no reply)"


def compose(entries: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """The sends that go out for a batch: one entry's own replies as they
    were, or the summary plus the last question still answerable."""
    entries = [entry for entry in entries if entry]
    if not entries:
        return []
    if len(entries) == 1:
        return entries[0]
    questions = [i for i, entry in enumerate(entries) if any(s["kind"] != "text" for s in entry)]
    last_question = questions[-1] if questions else None
    lines = [SUMMARY_HEADER.format(n=len(entries))]
    for i, entry in enumerate(entries):
        note = ""
        if i == last_question:
            note = QUESTION_BELOW
        elif i in questions:
            note = NOT_SAVED
        lines.append(f"• {_line(entry)}{note}")
    lines += ["", SUMMARY_FOOTER]
    sends: list[dict[str, Any]] = [{"kind": "text", "body": "\n".join(lines)}]
    if last_question is not None:
        sends += [s for s in entries[last_question] if s["kind"] != "text"]
    return sends


async def _deliver(sender: Any, wa_id: str, sends: list[dict[str, Any]]) -> None:
    for send in sends:
        kind = send["kind"]
        if kind == "text":
            await sender.send_text(wa_id, send["body"])
            continue
        kwargs = {k: v for k, v in send.items() if k not in ("kind", "rows", "buttons")}
        if kind == "list":
            kwargs["rows"] = [ListRow(**r) for r in send["rows"]]
            await sender.send_list(wa_id, **kwargs)
        elif kind == "button":
            kwargs["buttons"] = [ListRow(**r) for r in send["buttons"]]
            await sender.send_button(wa_id, **kwargs)


# ---------------------------------------------------------------------------
# The batch
# ---------------------------------------------------------------------------


class Capture:
    """One forwarded message's held-back replies, and whether its sender
    turned out to be a company user (set when the capture ends)."""

    def __init__(self) -> None:
        self.sends: list[dict[str, Any]] = []
        self.known_sender = False


class ForwardBatcher:
    def __init__(self, *, redis: Any, sender: Any, window_seconds: float = 10.0) -> None:
        self._redis = redis
        self._sender = sender
        self._window = window_seconds
        self._tasks: set[asyncio.Task[None]] = set()

    @contextlib.contextmanager
    def capturing(self) -> Iterator[Capture]:
        """While a forwarded message is processed: hold back its replies."""
        capture = Capture()
        token = _capture.set(capture.sends)
        known = _known_sender.set(False)
        try:
            yield capture
        finally:
            capture.known_sender = _known_sender.get()
            _capture.reset(token)
            _known_sender.reset(known)

    # RedisClient namespaces keys itself in set_json / get_json /
    # set_if_absent, but delete() takes the full key: hence the two forms.
    @staticmethod
    def _key(wa_id: str) -> str:
        return f"fwd_batch:{wa_id}"

    @contextlib.asynccontextmanager
    async def _locked(self, wa_id: str):  # type: ignore[no-untyped-def]
        lock = f"fwd_batch_lock:{wa_id}"
        for _ in range(50):
            if await self._redis.set_if_absent(lock, "1", ttl_seconds=_LOCK_TTL_SECONDS):
                break
            await asyncio.sleep(0.1)
        try:
            yield
        finally:
            await self._redis.delete(self._redis.namespaced(lock))

    async def begin(self, wa_id: str) -> None:
        """A forwarded message from this sender started processing: the
        summary waits for it."""
        async with self._locked(wa_id):
            batch = await self._redis.get_json(self._key(wa_id)) or {"seq": 0, "entries": []}
            batch["in_progress"] = int(batch.get("in_progress") or 0) + 1
            batch["last_at"] = time.time()
            await self._redis.set_json(self._key(wa_id), batch, ttl_seconds=_TTL_SECONDS)

    async def finish(self, wa_id: str, captured: list[dict[str, Any]], *, known_sender: bool) -> None:
        """After a forwarded message: a company user's replies join the
        batch; anyone else's (unregistered...) go straight away."""
        async with self._locked(wa_id):
            batch = await self._redis.get_json(self._key(wa_id)) or {"seq": 0, "entries": []}
            batch["in_progress"] = max(int(batch.get("in_progress") or 0) - 1, 0)
            batch["seq"] += 1
            if captured and known_sender:
                batch["entries"].append(captured)
            batch["last_at"] = time.time()
            await self._redis.set_json(self._key(wa_id), batch, ttl_seconds=_TTL_SECONDS)
        if captured and not known_sender:
            await _deliver(self._sender, wa_id, captured)
        task = asyncio.create_task(self._flush_after(wa_id, batch["seq"]))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _flush_after(self, wa_id: str, seq: int) -> None:
        await asyncio.sleep(self._window)
        try:
            await self.flush(wa_id, expected_seq=seq)
        except Exception:  # noqa: BLE001 -- the next message flushes it instead
            _log.exception("forward_batch.flush_failed")

    async def flush(
        self, wa_id: str, *, expected_seq: int | None = None, stale_only: bool = False
    ) -> bool:
        """Send the batch's summary and clear it. With `expected_seq`, only if
        no newer message joined; with `stale_only`, only if the window has
        passed (the next-message safety net)."""
        async with self._locked(wa_id):
            batch = await self._redis.get_json(self._key(wa_id))
            if not batch:
                return False
            idle = time.time() - float(batch.get("last_at") or 0)
            busy = int(batch.get("in_progress") or 0) > 0
            if expected_seq is not None and (batch.get("seq") != expected_seq or busy):
                return False  # a newer or unfinished message: a later timer sends it
            if stale_only and (idle < self._window or (busy and idle < self._window * _STUCK_WINDOWS)):
                return False
            await self._redis.delete(self._redis.namespaced(self._key(wa_id)))
        sends = compose(batch.get("entries") or [])
        _log.info("forward_batch.flush messages=%d sends=%d", len(batch.get("entries") or []), len(sends))
        await _deliver(self._sender, wa_id, sends)
        return True
