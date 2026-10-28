"""Coordinate the WhatsApp ingress pipeline for verified webhook payloads."""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from channel.whatsapp import usage as message_usage
from ingress.deduplication import DeduplicationStore
from ingress.media_handoff import upload_downloaded_media
from ingress.media_ingestion import DownloadedMedia, MediaDownloader
from ingress.normalization import MessageNormalizer
from mesiri_contracts.assistant import NormalizedMessage
from mesiri_contracts.common.storage import ObjectStoragePort
from runtime.ai_outage import AIUnavailableError
from runtime.logging_ports import TraceLogger
from runtime.noop_loggers import NoopTraceLogger

logger = logging.getLogger(__name__)


class NormalizedMessageStore(ABC):
    """Persistence boundary for normalized inbound messages."""

    @abstractmethod
    async def save(self, message: NormalizedMessage) -> None:
        """Persist a normalized message for downstream processing."""


class InMemoryNormalizedMessageStore(NormalizedMessageStore):
    """Process-local store used by M2 ingress before async handoff is introduced."""

    def __init__(self) -> None:
        self._messages: dict[str, NormalizedMessage] = {}
        self._lock = asyncio.Lock()

    async def save(self, message: NormalizedMessage) -> None:
        async with self._lock:
            self._messages[message.message_id] = message
            logger.info("Persisted normalized WhatsApp message: %s", message.message_id)

    async def get(self, message_id: str) -> NormalizedMessage | None:
        async with self._lock:
            return self._messages.get(message_id)


@dataclass(frozen=True, slots=True)
class MessageIngressContext:
    """Context extracted from a Meta webhook change value."""

    message: Mapping[str, Any]
    contacts: tuple[Mapping[str, Any], ...]
    phone_number_id: str | None
    display_phone_number: str | None


def _sort_key(context: MessageIngressContext) -> tuple[int, str]:
    """Order a batch the way the sender actually sent it.

    Construction sites lose signal constantly; when the phone reconnects Meta
    delivers the whole backlog at once, and nothing guarantees the array is in
    send order. Processing "completed" before the "started" it refers to
    silently corrupts the timeline, so the send timestamp -- not arrival
    position -- is the ordering authority.

    Meta sends `timestamp` as unix seconds in a string. A malformed or absent
    value sorts to 0 (earliest) rather than raising: a message with a broken
    timestamp must still be processed, just without an ordering guarantee.
    `id` only breaks ties, so same-second messages stay deterministic.
    """
    raw = context.message.get("timestamp")
    try:
        seconds = int(str(raw))
    except (TypeError, ValueError):
        seconds = 0
    return seconds, str(context.message.get("id") or "")


class _SenderSerializer:
    """One processing lane per sender: strict FIFO within a conversation,
    full parallelism across conversations.

    Without this, `asyncio.create_task` per message means a burst races --
    message N+1's reply can land before N's, and worse, N+1 can resolve
    context (or a pending confirmation) against state N hasn't written yet.
    Ordering per sender is the invariant that makes replayed backlogs safe;
    ordering *across* senders was never needed and serializing it would make
    one slow voice note block an entire site.

    Locks are reference-counted and dropped at zero so a long-running process
    doesn't accumulate one lock per phone number that ever messaged it.
    """

    def __init__(self) -> None:
        self._lanes: dict[str, tuple[asyncio.Lock, int]] = {}

    def _acquire_lane(self, sender: str) -> asyncio.Lock:
        lock, waiters = self._lanes.get(sender, (asyncio.Lock(), 0))
        self._lanes[sender] = (lock, waiters + 1)
        return lock

    def _release_lane(self, sender: str) -> None:
        entry = self._lanes.get(sender)
        if entry is None:
            return
        lock, waiters = entry
        if waiters <= 1:
            del self._lanes[sender]
        else:
            self._lanes[sender] = (lock, waiters - 1)

    def lane(self, sender: str) -> _SenderLane:
        return _SenderLane(self, sender)


class _SenderLane:
    """Async context manager for one sender's serialized lane."""

    def __init__(self, serializer: _SenderSerializer, sender: str) -> None:
        self._serializer = serializer
        self._sender = sender
        self._lock: asyncio.Lock | None = None

    async def __aenter__(self) -> None:
        # Registered synchronously at task-creation order, awaited after --
        # asyncio.Lock wakes waiters FIFO, so tasks created in sorted order
        # run in sorted order.
        self._lock = self._serializer._acquire_lane(self._sender)
        await self._lock.acquire()

    async def __aexit__(self, *exc: object) -> None:
        if self._lock is not None:
            self._lock.release()
        self._serializer._release_lane(self._sender)


class WhatsAppReceiver:
    """Orchestrate deduplication, media retrieval, and normalization for ingress."""

    def __init__(
        self,
        *,
        deduplication_store: DeduplicationStore,
        media_downloader: MediaDownloader,
        message_store: NormalizedMessageStore,
        object_storage: ObjectStoragePort,
        normalizer: MessageNormalizer | None = None,
        on_normalized: (
            Callable[[NormalizedMessage, Mapping[str, Any], str | None], Awaitable[None]] | None
        ) = None,
        on_message_claimed: Callable[[str], Awaitable[None]] | None = None,
        trace_logger: TraceLogger | None = None,
        enqueue: Callable[[MessageIngressContext], Awaitable[None]] | None = None,
        groups_enabled: bool = False,
        on_group_event: Callable[[str, Mapping[str, Any]], Awaitable[None]] | None = None,
    ) -> None:
        self._deduplication_store = deduplication_store
        self._media_downloader = media_downloader
        self._message_store = message_store
        self._object_storage = object_storage
        self._normalizer = normalizer or MessageNormalizer()
        # Durable handoff (see runtime/queue.py): when set, a claimed message
        # is written to the ARQ/Redis job queue instead of being handed to
        # asyncio.create_task. A process crash between "claimed" and "done"
        # used to lose the message outright -- the task lived only in this
        # process's event loop, with nothing to recover it on restart. Once
        # `enqueue` succeeds the job survives in Redis independent of this
        # process, and a separate worker (worker.py) does the actual
        # processing. None in dev/test (no real Redis configured), which
        # keeps the previous in-process behaviour for those environments.
        self._enqueue = enqueue
        # Optional M3 handoff: invoked after a message is normalized+stored.
        # Takes a replayable envelope of the raw Meta payload alongside the
        # normalized message (see _envelope) so it can be persisted for
        # debugging, and replayed later via `replay()` if processing failed.
        self._on_normalized = on_normalized
        # Fired the moment a message is claimed, concurrently with (not
        # before) the real work -- see handle_payload. This is the WhatsApp
        # read receipt + "typing..." indicator, and it used to be sent from
        # inside the journey callback, which for voice/image meant it waited
        # on the Meta media download (~1.5-1.7s measured) plus upload plus
        # normalization first. The sender saw no blue tick for seconds after
        # sending, which reads as "it didn't go through".
        self._on_message_claimed = on_message_claimed
        # Best-effort: records ingestion-time failures (media download,
        # normalization, or anything the on_normalized callback lets escape)
        # that would otherwise vanish into stdout with no persisted row.
        self._trace_logger: TraceLogger = trace_logger or NoopTraceLogger()
        self._background_tasks: set[asyncio.Task[None]] = set()
        self._serializer = _SenderSerializer()
        # WA-87: with groups off, a group message never gets past ingress
        # (see _iter_message_contexts); with them on it is processed and
        # runtime/group_chat.py decides who it is from. `on_group_event`
        # takes Meta's group_* webhooks (group made, join requests, ...).
        self._groups_enabled = groups_enabled
        self._on_group_event = on_group_event

    async def handle_payload(self, payload: Mapping[str, Any]) -> int:
        """Schedule ingress work for all messages in a verified webhook payload.

        Messages are sorted by send timestamp before scheduling (see
        `_sort_key`) and each sender's messages then run in a strict FIFO lane
        (see `_SenderSerializer`), so a reconnecting phone's backlog replays in
        the order it was actually sent rather than the order it happened to
        arrive.
        """
        scheduled_count = 0
        _log_failed_statuses(payload)
        # BE-25: Meta's pricing for messages we sent (billable, category).
        message_usage.report_pricing(payload)

        if self._on_group_event is not None:
            for field_name, value in _iter_group_changes(payload):
                task = asyncio.create_task(self._on_group_event(field_name, value))
                self._background_tasks.add(task)
                task.add_done_callback(self._background_tasks.discard)

        for context in sorted(self._extract_message_contexts(payload), key=_sort_key):
            message_id = str(context.message["id"])
            if not await self._deduplication_store.try_claim(message_id):
                continue

            # Blue tick + "typing..." starts here, in parallel with
            # processing rather than after it. Deliberately not awaited: it's
            # a full HTTP round trip to Meta that nothing downstream depends
            # on, so awaiting it only delays the actual reply.
            if self._on_message_claimed is not None:
                ack_task = asyncio.create_task(
                    self._acknowledge(message_id, claimed_at=time.perf_counter())
                )
                self._background_tasks.add(ack_task)
                ack_task.add_done_callback(self._background_tasks.discard)

            if self._enqueue is not None:
                # Durable path: this await is just a Redis write (fast), not
                # the message processing itself -- the job sits in the queue
                # until a worker claims it, so it survives this process
                # dying immediately after.
                await self._enqueue(context)
            else:
                task = asyncio.create_task(self._process_message(context))
                self._background_tasks.add(task)
                task.add_done_callback(self._background_tasks.discard)
            scheduled_count += 1

        logger.info("Scheduled %s WhatsApp message(s) for ingress processing", scheduled_count)
        return scheduled_count

    async def _acknowledge(self, message_id: str, *, claimed_at: float | None = None) -> None:
        """Read receipt / typing indicator. Best-effort by design: this runs
        detached, so an exception here would otherwise surface as an
        unretrieved task exception rather than anything actionable, and it
        must never affect whether the message itself gets processed.

        Logs two separate numbers because they have different causes and
        different fixes: ``scheduling_ms`` is how long this detached task sat
        before the event loop ran it (loop congestion -- the pre-pipeline
        block does ~15 sequential DB round trips per in-flight message), and
        ``send_ms`` is Meta's own round trip. The blue tick still reads as
        slow and we don't yet know which of the two is responsible.
        """
        if self._on_message_claimed is None:
            return
        started = time.perf_counter()
        scheduling_ms = round((started - claimed_at) * 1000, 1) if claimed_at is not None else None
        try:
            await self._on_message_claimed(message_id)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to acknowledge WhatsApp message %s", message_id)
        else:
            logger.info(
                "whatsapp.ack_sent message_id=%s scheduling_ms=%s send_ms=%s",
                message_id,
                scheduling_ms,
                round((time.perf_counter() - started) * 1000, 1),
            )

    async def wait_until_idle(self) -> None:
        """Wait for in-flight ingress background tasks to complete."""
        if not self._background_tasks:
            return
        await asyncio.gather(*self._background_tasks, return_exceptions=True)

    async def replay(self, envelope: Mapping[str, Any], *, retry_of_id: str) -> str | None:
        """Re-run ingress for a previously captured envelope (see `_envelope`).

        Used by the admin "retry" action on a failed message. Bypasses the
        webhook-time dedup claim (this is an explicit, one-off admin action,
        not inbound traffic that needs deduping against Meta's at-least-once
        delivery) and threads `retry_of_id` through so the write path can
        record the new attempt as a retry of the original, with a dedup key
        that can't collide with it. Returns the new correlation_id, or None
        if the retry itself failed before a message could even be normalized.
        """
        context = MessageIngressContext(
            message=envelope["message"],
            contacts=tuple(envelope.get("contacts") or ()),
            phone_number_id=envelope.get("phone_number_id"),
            display_phone_number=envelope.get("display_phone_number"),
        )
        normalized = await self._process_message(context, retry_of_id=retry_of_id)
        return normalized.correlation_id if normalized is not None else None

    @staticmethod
    def _envelope(context: MessageIngressContext) -> dict[str, Any]:
        """A self-contained, replayable snapshot of one inbound message —
        everything `MessageNormalizer.normalize` needs, so a failed message
        can be replayed later without re-fetching anything from Meta."""
        return {
            "message": dict(context.message),
            "contacts": [dict(c) for c in context.contacts],
            "phone_number_id": context.phone_number_id,
            "display_phone_number": context.display_phone_number,
        }

    async def process_claimed_message(
        self, context: MessageIngressContext
    ) -> NormalizedMessage | None:
        """Run ingress for a message already claimed via the dedup store.

        The public entry point for the ARQ worker (worker.py): the webhook
        process only enqueues, it never runs this itself once `enqueue` is
        configured, so this is what the worker process calls after pulling a
        job off the queue.
        """
        return await self._process_message(context)

    async def _process_message(
        self, context: MessageIngressContext, *, retry_of_id: str | None = None
    ) -> NormalizedMessage | None:
        """Process one message inside its sender's FIFO lane.

        The lane wraps the *entire* journey, not just normalization: message
        N+1 must not resolve context, or answer a pending confirmation,
        against state that message N has not finished writing. Different
        senders never share a lane, so one slow voice note cannot block a
        whole site.
        """
        sender = str(context.message.get("from") or "unknown")
        async with self._serializer.lane(sender):
            return await self._process_message_locked(context, retry_of_id=retry_of_id)

    async def _process_message_locked(
        self, context: MessageIngressContext, *, retry_of_id: str | None = None
    ) -> NormalizedMessage | None:
        message_id = str(context.message["id"])
        ingress_t0 = time.perf_counter()
        download_ms: float | None = None
        upload_ms: float | None = None
        try:
            download_t0 = time.perf_counter()
            downloaded_media = await self._download_media_if_required(context.message)
            if downloaded_media is not None:
                download_ms = round((time.perf_counter() - download_t0) * 1000, 2)
            media = None
            if downloaded_media is not None:
                upload_t0 = time.perf_counter()
                media = await upload_downloaded_media(
                    message_id=message_id,
                    downloaded=downloaded_media,
                    object_storage=self._object_storage,
                )
                upload_ms = round((time.perf_counter() - upload_t0) * 1000, 2)
            normalized = self._normalizer.normalize(
                context.message,
                contacts=context.contacts,
                phone_number_id=context.phone_number_id,
                display_phone_number=context.display_phone_number,
                media=media,
            )

            if downloaded_media is not None:
                # Logged here, before message_store.save()/on_normalized() --
                # on_normalized runs the ENTIRE rest of the pipeline
                # (understanding, context, canonicalization, planner,
                # workflow) synchronously and this used to be logged *after*
                # that call returned, so duration_ms was actually "ingress +
                # everything downstream", not ingress alone (real bug: a
                # 6-10s "ingress" duration_ms was really ~1.5-1.7s of actual
                # download+upload plus the whole rest of the journey hiding
                # inside it). This success path used to write nothing at all
                # before that -- traced report found ~10-16s of untraced
                # time on image messages, bigger than every logged LLM call
                # combined, with no way to tell whether it was the Meta CDN
                # download or the R2 upload. download_ms/upload_ms settles
                # that split correctly now that duration_ms only covers
                # ingress's own work.
                await self._trace_logger.log_stage(
                    correlation_id=normalized.correlation_id,
                    stage="ingress",
                    stage_payload={
                        "download_ms": download_ms,
                        "upload_ms": upload_ms,
                        "file_size_bytes": downloaded_media.file_size,
                        "mime_type": downloaded_media.mime_type,
                    },
                    duration_ms=int((time.perf_counter() - ingress_t0) * 1000),
                    succeeded=True,
                )

            await self._message_store.save(normalized)
            if self._on_normalized is not None:
                await self._on_normalized(normalized, self._envelope(context), retry_of_id)
            return normalized
        except AIUnavailableError:
            # Not a failure to record: the sender was told it is queued, and
            # worker.py turns this into an ARQ retry (runtime/ai_outage.py).
            raise
        except Exception as exc:
            logger.exception("Failed to process WhatsApp message %s", message_id)
            # This is the last line of defence: process_inbound_message already
            # persists a trace row for failures in its own stages, so this only
            # fires for failures upstream of it (media download, normalization)
            # or a stage exception that somehow still escaped unlogged.
            try:
                await self._trace_logger.log_stage(
                    correlation_id=f"unrouted:{message_id}",
                    stage="ingress",
                    stage_payload=None,
                    duration_ms=None,
                    succeeded=False,
                    error_code=type(exc).__name__,
                    error_message=str(exc),
                    severity="error",
                    event_source="unhandled_exception",
                )
            except Exception:  # noqa: BLE001
                logger.exception(
                    "Failed to record ingress failure trace for message %s", message_id
                )

    async def _download_media_if_required(
        self,
        message: Mapping[str, Any],
    ) -> DownloadedMedia | None:
        message_type = message.get("type")

        if message_type == "image":
            media_id = (message.get("image") or {}).get("id")
        elif message_type == "audio" and (message.get("audio") or {}).get("voice"):
            media_id = (message.get("audio") or {}).get("id")
        else:
            # Text, interactive, and everything Mesiri can't act on yet
            # (document/video/sticker/location/contacts, or a music file
            # rather than a voice note). Downloading a PDF we have no way to
            # read would burn a Meta API call and storage for nothing --
            # and raising here used to abort ingress entirely, leaving the
            # sender with no reply at all. Normalization now maps these to
            # InputModality.UNKNOWN and the runtime declines them politely.
            return None

        if not media_id:
            raise ValueError("Media message is missing media id")

        return await self._media_downloader.download(str(media_id))

    def _extract_message_contexts(
        self,
        payload: Mapping[str, Any],
    ) -> Iterator[MessageIngressContext]:
        return _iter_message_contexts(payload, groups_enabled=self._groups_enabled)


def _iter_group_changes(payload: Mapping[str, Any]) -> Iterator[tuple[str, Mapping[str, Any]]]:
    """WA-87: the `group_*` changes of a webhook (Meta's Groups API)."""
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            field_name = str(change.get("field") or "")
            if field_name.startswith("group_"):
                yield field_name, change.get("value") or {}


def _log_failed_statuses(payload: Mapping[str, Any]) -> None:
    """WA-12: Meta accepts a send (template or not) and only later reports
    that delivery failed -- e.g. a template paused or a recipient who can't
    receive it -- as a `statuses` entry on this webhook. Nothing else reads
    those, so log the failures; channel/whatsapp/outbound.py logs which
    template each wamid was."""
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            if change.get("field") != "messages":
                continue
            for status in (change.get("value") or {}).get("statuses") or []:
                if status.get("status") != "failed":
                    continue
                error = (status.get("errors") or [{}])[0]
                logger.warning(
                    "whatsapp.delivery_failed wamid=%s to=%s code=%s title=%s",
                    status.get("id"),
                    status.get("recipient_id"),
                    error.get("code"),
                    error.get("title"),
                )


def _iter_message_contexts(
    payload: Mapping[str, Any], *, groups_enabled: bool = False
) -> Iterator[MessageIngressContext]:
    entries = payload.get("entry") or []
    for entry in entries:
        changes = entry.get("changes") or []
        for change in changes:
            if change.get("field") != "messages":
                continue

            value = change.get("value") or {}
            messages = value.get("messages") or []
            contacts = tuple(value.get("contacts") or [])
            metadata = value.get("metadata") or {}
            phone_number_id = metadata.get("phone_number_id")
            display_phone_number = metadata.get("display_phone_number")

            for message in messages:
                if message.get("group_id") and not groups_enabled:
                    # WA-87: a message sent in a WhatsApp group Mesiri is a
                    # member of, with groups switched off. It must not reach
                    # the 1-on-1 path: that would save it under the sender and
                    # answer them privately. Not claimed, so no read receipt.
                    logger.info(
                        "whatsapp.group_message_ignored wamid=%s group_id=%s",
                        message.get("id"),
                        message.get("group_id"),
                    )
                    continue
                yield MessageIngressContext(
                    message=message,
                    contacts=contacts,
                    phone_number_id=str(phone_number_id) if phone_number_id else None,
                    display_phone_number=(
                        str(display_phone_number) if display_phone_number else None
                    ),
                )
