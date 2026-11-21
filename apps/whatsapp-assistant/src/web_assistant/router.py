"""Tell Mesiri from the dashboard (WEB-36, approved by Alan 25 Oct).

A second door into the same assistant: what someone types (and, next, says)
on the web goes through the very handler a WhatsApp message runs
(runtime/reply_capture.py, shared with the control panel's test message),
so the workflows, their confirmations, role rules, module switches and the
trial usage guard all apply unchanged. Mesiri's replies come back in the
response instead of going to WhatsApp (decided: no copy on WhatsApp in V1).

Who it acts as is never in the request: always the signed-in user, by the
WhatsApp number on their own account. No number, no messages; in a sample company, a sender id
that names them and can never be a phone (UX-26).
"""

from __future__ import annotations

import asyncio
import re
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from mesiri.domains.shared.auth import get_current_user
from mesiri.infrastructure.postgres.tenant import bind_tenant
from mesiri_ai.usage import ogg_duration_seconds
from mesiri_contracts.assistant.enums import InputModality
from mesiri_contracts.assistant.normalized_message import (
    MediaReference,
    NormalizedMessage,
    SenderInfo,
)
from mesiri_contracts.common.ids import new_id
from runtime.reply_capture import (
    CapturedReply,
    ReplyCapture,
    UserNotFound,
    identity_refusal,
    run_captured,
    user_whatsapp_number,
)

router = APIRouter(prefix="/assistant", tags=["assistant"])

#: Marks the message as from the dashboard in its log row (normalized
#: message metadata and raw payload), so the inbox can tell the doors apart.
SOURCE = "dashboard"
#: MOB-07: a message's own id, chosen by the client, so the same message sent again (a phone that lost signal
#: before the answer came, and sends its queue later) is answered once: the second send gets the first answer.
MESSAGE_ID_HEADER = "X-Mesiri-Message-Id"
_MESSAGE_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
#: How long a message id is remembered (its answer replayed), and how long one being worked on holds its claim.
ANSWER_TTL_S = 24 * 3600
CLAIM_TTL_S = 10 * 60
STILL_SENDING = "That one is still being worked on. Its answer will come in a moment."
#: How runtime/reply_capture.run_captured shows a run that broke.
BROKE_PREFIX = "[error:"
#: MOB-03: the mobile app uses the same door and says so in this header; any other value is the dashboard.
CLIENT_HEADER = "X-Mesiri-Client"
APP_SOURCE = "app"
MAX_TEXT = 2000
#: Per person, on top of the trial's daily AI cap (SS-09).
RATE_LIMIT = 20
RATE_WINDOW_S = 600
#: A voice note plus the model usually answers in 5-20 s.
REPLY_TIMEOUT_S = 60
STILL_WORKING = "Still working on it. It will show on Today when it is saved."
#: Voice notes from the browser: Ogg/Opus, like WhatsApp's, up to a minute.
VOICE_MIME = "audio/ogg"
#: MOB-03: phones (Android and iPhone alike) record AAC in an MP4 file (.m4a); the speech step reads it as it reads
#: Ogg (Sarvam reads the file itself, checked 21 Nov 2026 with a Malayalam note sent both ways).
M4A_MIME = "audio/mp4"
MAX_VOICE_SECONDS = 62
MAX_VOICE_BYTES = 5 * 1024 * 1024


class WebMessageRequest(BaseModel):
    text: str = ""
    #: A tap on one of Mesiri's buttons or list rows, by its id.
    interactive_reply_id: str | None = None


class ReadyEntry(BaseModel):
    """MOB-05: one entry on the person's list waiting for Save, as data (what the TO SAVE card shows in words)."""

    #: Its number on the card (1-based), as the assistant's Edit and Remove taps count it.
    line: int
    tool: str
    method: str
    path: str
    params: dict
    body: dict
    summary: str
    #: Its idempotency key: a client that saves it itself sends this as Idempotency-Key, so the assistant's own
    #: Save of the same entry later answers "already saved" instead of recording it twice.
    key: str
    #: The assistant's own tap that takes this line off the list (its Remove button).
    remove_id: str | None = None


class WebMessageResponse(BaseModel):
    message_id: str
    replies: list[CapturedReply]
    #: A voice note's words, as Mesiri heard them; None for typing.
    transcript: str | None = None
    #: MOB-05: the person's list waiting for Save after this message, read from the assistant's own state (never
    #: changed here). None when it can't be read; [] when nothing is waiting.
    ready: list[ReadyEntry] | None = None


async def within_rate_limit(redis: object | None, user_id: str) -> bool:
    """RATE_LIMIT messages per RATE_WINDOW_S per person. Without Redis
    (tests, local) there is no limit."""
    if redis is None:
        return True
    # UX-26 (found 17 Nov): this called incr/expire, which the app's Redis client (and its stand-in) don't have, so
    # every Tell Mesiri message answered 500 wherever Redis is set up. The client's own counter now.
    count = await redis.count(f"web_assistant:rate:{user_id}", ttl_seconds=RATE_WINDOW_S)  # type: ignore[attr-defined]
    return int(count) <= RATE_LIMIT


async def sender_number(user: dict) -> tuple[uuid.UUID, str]:
    """The signed-in user's id and WhatsApp number, or the HTTP refusal."""
    try:
        org_id = uuid.UUID(str(user.get("org")))
        user_id = uuid.UUID(str(user.get("sub")))
    except ValueError:
        raise HTTPException(status_code=401, detail="Sign in again") from None
    bind_tenant(org_id)
    if user.get("sandbox"):
        # UX-26: a person in a sample company has no number (nothing there may reach a phone): they talk to Mesiri
        # with a sender id that names them and can never be a phone (sandbox_gate.sample_sender_id).
        from mesiri.domains.shared.sandbox_gate import sample_sender_id

        try:
            await user_whatsapp_number(org_id, user_id)
        except UserNotFound:
            raise HTTPException(status_code=401, detail="Sign in again") from None
        return user_id, sample_sender_id(user_id)
    try:
        number = await user_whatsapp_number(org_id, user_id)
    except UserNotFound:
        raise HTTPException(status_code=401, detail="Sign in again") from None
    if not number:
        raise HTTPException(
            status_code=409,
            detail="Add your WhatsApp number to your profile to talk to Mesiri.",
        )
    return user_id, number


def voice_kind(audio: bytes) -> tuple[str, str] | None:
    """The recording's (mime type, file extension) when it is one the speech step reads, else None."""
    if audio.startswith(b"OggS"):
        return VOICE_MIME, "ogg"
    if audio[4:8] == b"ftyp":
        return M4A_MIME, "m4a"
    return None


def _boxes(data: bytes, start: int, end: int):
    """The MP4 boxes between ``start`` and ``end``: (type, body start, body end)."""
    at = start
    while at + 8 <= end:
        size = int.from_bytes(data[at:at + 4], "big")
        kind = data[at + 4:at + 8]
        head = 8
        if size == 1 and at + 16 <= end:
            size, head = int.from_bytes(data[at + 8:at + 16], "big"), 16
        elif size == 0:
            size = end - at
        if size < head or at + size > end:
            return
        yield kind, at + head, at + size
        at += size


def m4a_duration_seconds(audio: bytes) -> float | None:
    """An MP4 recording's length, from its movie header (moov/mvhd); None when it can't be read."""
    for kind, start, end in _boxes(audio, 0, len(audio)):
        if kind != b"moov":
            continue
        for inner, body, stop in _boxes(audio, start, end):
            if inner != b"mvhd" or body + 4 > stop:
                continue
            version = audio[body]
            if version == 1 and body + 32 <= stop:
                scale = int.from_bytes(audio[body + 20:body + 24], "big")
                length = int.from_bytes(audio[body + 24:body + 32], "big")
            elif version == 0 and body + 20 <= stop:
                scale = int.from_bytes(audio[body + 12:body + 16], "big")
                length = int.from_bytes(audio[body + 16:body + 20], "big")
            else:
                return None
            return length / scale if scale else None
    return None


def voice_seconds(audio: bytes) -> float | None:
    kind = voice_kind(audio)
    if kind is None:
        return None
    return ogg_duration_seconds(audio) if kind[0] == VOICE_MIME else m4a_duration_seconds(audio)


def client_source(request: Request) -> str:
    """Which door the message came through: the mobile app, or the dashboard (the default)."""
    headers = getattr(request, "headers", None) or {}
    said = next((v for k, v in headers.items() if str(k).lower() == CLIENT_HEADER.lower()), "")
    return APP_SOURCE if str(said).strip().lower() == APP_SOURCE else SOURCE


async def handle(
    container: object,
    wa_id: str,
    *,
    text: str = "",
    tap: str | None = None,
    voice: bytes | None = None,
    source: str = SOURCE,
    who: tuple[uuid.UUID, uuid.UUID] | None = None,
) -> WebMessageResponse:
    """Run one message as `wa_id` and return Mesiri's replies. A voice note
    is stored where WhatsApp's are and sent as one (the agent transcribes it
    as it would a WhatsApp voice note); its words come back as `transcript`."""
    capture = ReplyCapture()
    message_id = new_id("web")
    refusal = await identity_refusal(container, wa_id)
    if refusal is not None:
        capture.text(refusal)
        return WebMessageResponse(message_id=message_id, replies=capture.replies)

    metadata: dict[str, object] = {"source": source}
    if tap:
        metadata["interactive_reply_id"] = tap
    media = None
    modality = InputModality.INTERACTIVE if tap else InputModality.TEXT
    if voice is not None:
        mime, extension = voice_kind(voice) or (VOICE_MIME, "ogg")
        key = f"media/{message_id}/web-voice.{extension}"
        await container.object_storage.put_object(key, voice, content_type=mime)  # type: ignore[attr-defined]
        media = MediaReference(
            object_key=key,
            mime_type=mime,
            size_bytes=len(voice),
            duration_seconds=voice_seconds(voice),
        )
        modality = InputModality.VOICE
    message = NormalizedMessage(
        message_id=message_id,
        sender=SenderInfo(wa_id=wa_id, phone_number=wa_id),
        timestamp=datetime.now(UTC),
        modality=modality,
        text=text or tap or "",
        media=media,
        metadata=metadata,
    )
    try:
        await asyncio.wait_for(
            run_captured(container, message, capture, {"source": source}), timeout=REPLY_TIMEOUT_S
        )
    except TimeoutError:
        capture.text(STILL_WORKING)
    transcript = (
        await read_transcript(container, message.correlation_id) if voice is not None else None
    )
    ready = await read_ready(container, *who) if who is not None else None
    return WebMessageResponse(
        message_id=message_id, replies=capture.replies, transcript=transcript, ready=ready
    )


async def read_ready(
    container: object, organization_id: uuid.UUID, user_id: uuid.UUID
) -> list[ReadyEntry] | None:
    """MOB-05: the entries waiting for this person's Save, from the v3 assistant's own state (the list its TO SAVE
    card shows), so the app can put one in a form. Read only: the list is the assistant's, changed only by its taps.
    None when there is no Redis or the state can't be read."""
    redis = getattr(container, "redis_client", None)
    if redis is None:
        return None
    from agent_api.reply_guard import without_ids
    from agent_api.whatsapp import REMOVE_PREFIX, state_key

    try:
        state = await redis.get_json(state_key(organization_id, user_id))  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 -- the replies already came; the list is a nicety for forms
        return None
    state = state if isinstance(state, dict) else {}
    batch = state.get("batch")
    entries: list[ReadyEntry] = []
    for line, raw in enumerate(state.get("pending") or [], start=1):
        if not isinstance(raw, dict):
            continue
        try:
            entries.append(
                ReadyEntry(
                    line=line,
                    tool=str(raw["tool"]),
                    method=str(raw["method"]),
                    path=str(raw["path"]),
                    params=dict(raw.get("params") or {}),
                    body=dict(raw.get("body") or {}),
                    summary=without_ids(str(raw.get("summary") or "")),
                    key=str(raw["idempotency_key"]),
                    remove_id=f"{REMOVE_PREFIX}{batch}:{line}" if batch else None,
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return entries


async def read_transcript(container: object, correlation_id: str) -> str | None:
    """The voice note's words, as the agent wrote them to the message's log
    row (agent/turn.py, update_body_text) -- read back rather than paying to
    transcribe twice. None when the log row isn't there (yet)."""
    database = getattr(container, "material_db", None)
    if database is None:
        return None
    try:
        async with database.transaction() as conn:
            row = (
                await conn.execute(
                    sa.text("SELECT body_text FROM inbound_messages WHERE correlation_id = :c"),
                    {"c": correlation_id},
                )
            ).first()
    except Exception:  # noqa: BLE001 -- the words are a nicety; the replies already came
        return None
    return (row.body_text or None) if row is not None else None


def message_id_of(request: Request) -> str | None:
    """The client's id for this message (MOB-07), when it sent a well-formed one."""
    headers = getattr(request, "headers", None) or {}
    said = next((v for k, v in headers.items() if str(k).lower() == MESSAGE_ID_HEADER.lower()), "")
    said = str(said).strip()
    return said if _MESSAGE_ID.match(said) else None


async def once(
    container: object,
    user: dict,
    message_id: str | None,
    run: Callable[[], Awaitable[WebMessageResponse]],
) -> WebMessageResponse:
    """MOB-07: run a message once per client message id. The same id again gets the first answer (with the list
    waiting for Save as it is now); while the first is still being worked on, a 409. Without an id, or without
    Redis, every send runs (as before)."""
    redis = getattr(container, "redis_client", None)
    if message_id is None or redis is None:
        return await run()
    org_id, user_id = _who(user)
    key = f"web_assistant:msg:{org_id}:{user_id}:{message_id}"
    answer = await redis.get_json(f"{key}:answer")  # type: ignore[attr-defined]
    if isinstance(answer, dict):
        replay = WebMessageResponse.model_validate(answer)
        replay.ready = await read_ready(container, org_id, user_id)
        return replay
    if not await redis.set_if_absent(f"{key}:claim", "1", ttl_seconds=CLAIM_TTL_S):  # type: ignore[attr-defined]
        raise HTTPException(status_code=409, detail=STILL_SENDING)
    try:
        response = await run()
    except BaseException:
        await redis.delete(redis.namespaced(f"{key}:claim"))  # type: ignore[attr-defined]  # delete() takes the raw key
        raise
    if any(r.text.startswith(BROKE_PREFIX) for r in response.replies):
        # The run broke (run_captured shows it as a reply): nothing is kept, so the phone's next try runs it again.
        await redis.delete(redis.namespaced(f"{key}:claim"))  # type: ignore[attr-defined]  # delete() takes the raw key
        return response
    await redis.set_json(f"{key}:answer", response.model_dump(mode="json"), ttl_seconds=ANSWER_TTL_S)  # type: ignore[attr-defined]
    return response


def _who(user: dict) -> tuple[uuid.UUID, uuid.UUID]:
    """The signed-in person's company and user id (already checked by ``sender_number``)."""
    return uuid.UUID(str(user.get("org"))), uuid.UUID(str(user.get("sub")))


async def _ready_sender(request: Request, user: dict) -> tuple[object, str]:
    """The container and the signed-in user's number, after every check."""
    container = request.app.state.container
    if getattr(container, "simulate_handler", None) is None:
        raise HTTPException(
            status_code=503, detail="Mesiri isn't ready yet. Try again in a minute."
        )
    user_id, wa_id = await sender_number(user)
    if not await within_rate_limit(getattr(container, "redis_client", None), str(user_id)):
        raise HTTPException(
            status_code=429, detail="That's a lot at once. Wait a few minutes and try again."
        )
    return container, wa_id


@router.post("/messages", response_model=WebMessageResponse)
async def send_message(
    body: WebMessageRequest,
    request: Request,
    user: dict = Depends(get_current_user),
) -> WebMessageResponse:
    text = body.text.strip()
    tap = (body.interactive_reply_id or "").strip() or None
    if not text and not tap:
        raise HTTPException(status_code=400, detail="Type or say the update first.")
    if len(text) > MAX_TEXT:
        raise HTTPException(status_code=413, detail=f"Keep it under {MAX_TEXT} characters.")
    container, wa_id = await _ready_sender(request, user)
    return await once(
        container,
        user,
        message_id_of(request),
        lambda: handle(container, wa_id, text=text, tap=tap, source=client_source(request), who=_who(user)),
    )


@router.post("/messages/voice", response_model=WebMessageResponse)
async def send_voice(
    request: Request, user: dict = Depends(get_current_user)
) -> WebMessageResponse:
    """A voice note: the body is the recording itself, Ogg/Opus (what WhatsApp and
    the browser send) or AAC in MP4 (.m4a, what the mobile app's phones record, MOB-03)."""
    audio = await request.body()
    if not audio:
        raise HTTPException(status_code=400, detail="Nothing was recorded. Try again.")
    if len(audio) > MAX_VOICE_BYTES:
        raise HTTPException(
            status_code=413, detail="That recording is too long. Keep it under a minute."
        )
    if voice_kind(audio) is None:
        raise HTTPException(
            status_code=415, detail="The recording didn't come through. Record it again."
        )
    seconds = voice_seconds(audio)
    if seconds is not None and seconds > MAX_VOICE_SECONDS:
        raise HTTPException(
            status_code=413, detail="That recording is too long. Keep it under a minute."
        )
    container, wa_id = await _ready_sender(request, user)
    return await once(
        container,
        user,
        message_id_of(request),
        lambda: handle(container, wa_id, voice=audio, source=client_source(request), who=_who(user)),
    )
