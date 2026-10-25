"""Tell Mesiri from the dashboard (WEB-36, approved by Alan 25 Oct).

A second door into the same assistant: what someone types (and, next, says)
on the web goes through the very handler a WhatsApp message runs
(runtime/reply_capture.py, shared with the control panel's test message),
so the workflows, their confirmations, role rules, module switches and the
trial usage guard all apply unchanged. Mesiri's replies come back in the
response instead of going to WhatsApp (decided: no copy on WhatsApp in V1).

Who it acts as is never in the request: always the signed-in user, by the
WhatsApp number on their own account. No number, no messages.
"""

from __future__ import annotations

import asyncio
import uuid
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
MAX_TEXT = 2000
#: Per person, on top of the trial's daily AI cap (SS-09).
RATE_LIMIT = 20
RATE_WINDOW_S = 600
#: A voice note plus the model usually answers in 5-20 s.
REPLY_TIMEOUT_S = 60
STILL_WORKING = "Still working on it. It will show on Today when it is saved."
#: Voice notes from the browser: Ogg/Opus, like WhatsApp's, up to a minute.
VOICE_MIME = "audio/ogg"
MAX_VOICE_SECONDS = 62
MAX_VOICE_BYTES = 5 * 1024 * 1024


class WebMessageRequest(BaseModel):
    text: str = ""
    #: A tap on one of Mesiri's buttons or list rows, by its id.
    interactive_reply_id: str | None = None


class WebMessageResponse(BaseModel):
    message_id: str
    replies: list[CapturedReply]
    #: A voice note's words, as Mesiri heard them; None for typing.
    transcript: str | None = None


async def within_rate_limit(redis: object | None, user_id: str) -> bool:
    """RATE_LIMIT messages per RATE_WINDOW_S per person. Without Redis
    (tests, local) there is no limit."""
    if redis is None:
        return True
    key = f"web_assistant:rate:{user_id}"
    count = await redis.incr(key)  # type: ignore[attr-defined]
    if count == 1:
        await redis.expire(key, RATE_WINDOW_S)  # type: ignore[attr-defined]
    return int(count) <= RATE_LIMIT


async def sender_number(user: dict) -> tuple[uuid.UUID, str]:
    """The signed-in user's id and WhatsApp number, or the HTTP refusal."""
    try:
        org_id = uuid.UUID(str(user.get("org")))
        user_id = uuid.UUID(str(user.get("sub")))
    except ValueError:
        raise HTTPException(status_code=401, detail="Sign in again") from None
    bind_tenant(org_id)
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


async def handle(
    container: object,
    wa_id: str,
    *,
    text: str = "",
    tap: str | None = None,
    voice: bytes | None = None,
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

    metadata: dict[str, object] = {"source": SOURCE}
    if tap:
        metadata["interactive_reply_id"] = tap
    media = None
    modality = InputModality.INTERACTIVE if tap else InputModality.TEXT
    if voice is not None:
        key = f"media/{message_id}/web-voice.ogg"
        await container.object_storage.put_object(key, voice, content_type=VOICE_MIME)  # type: ignore[attr-defined]
        media = MediaReference(
            object_key=key,
            mime_type=VOICE_MIME,
            size_bytes=len(voice),
            duration_seconds=ogg_duration_seconds(voice),
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
            run_captured(container, message, capture, {"source": SOURCE}), timeout=REPLY_TIMEOUT_S
        )
    except TimeoutError:
        capture.text(STILL_WORKING)
    transcript = (
        await read_transcript(container, message.correlation_id) if voice is not None else None
    )
    return WebMessageResponse(message_id=message_id, replies=capture.replies, transcript=transcript)


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
    return await handle(container, wa_id, text=text, tap=tap)


@router.post("/messages/voice", response_model=WebMessageResponse)
async def send_voice(
    request: Request, user: dict = Depends(get_current_user)
) -> WebMessageResponse:
    """A voice note: the body is the recording itself, Ogg/Opus (what WhatsApp
    sends, so the speech step and its billing read it as they read those)."""
    audio = await request.body()
    if not audio:
        raise HTTPException(status_code=400, detail="Nothing was recorded. Try again.")
    if len(audio) > MAX_VOICE_BYTES:
        raise HTTPException(
            status_code=413, detail="That recording is too long. Keep it under a minute."
        )
    if not audio.startswith(b"OggS"):
        raise HTTPException(
            status_code=415, detail="The recording didn't come through. Record it again."
        )
    seconds = ogg_duration_seconds(audio)
    if seconds is not None and seconds > MAX_VOICE_SECONDS:
        raise HTTPException(
            status_code=413, detail="That recording is too long. Keep it under a minute."
        )
    container, wa_id = await _ready_sender(request, user)
    return await handle(container, wa_id, voice=audio)
