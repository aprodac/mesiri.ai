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

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from mesiri.domains.shared.auth import get_current_user
from mesiri.infrastructure.postgres.tenant import bind_tenant
from mesiri_contracts.assistant.enums import InputModality
from mesiri_contracts.assistant.normalized_message import NormalizedMessage, SenderInfo
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


class WebMessageRequest(BaseModel):
    text: str = ""
    #: A tap on one of Mesiri's buttons or list rows, by its id.
    interactive_reply_id: str | None = None


class WebMessageResponse(BaseModel):
    message_id: str
    replies: list[CapturedReply]


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
    container: object, wa_id: str, *, text: str, tap: str | None
) -> WebMessageResponse:
    """Run one message as `wa_id` and return Mesiri's replies."""
    capture = ReplyCapture()
    message_id = new_id("web")
    refusal = await identity_refusal(container, wa_id)
    if refusal is not None:
        capture.text(refusal)
        return WebMessageResponse(message_id=message_id, replies=capture.replies)

    metadata: dict[str, object] = {"source": SOURCE}
    if tap:
        metadata["interactive_reply_id"] = tap
    message = NormalizedMessage(
        message_id=message_id,
        sender=SenderInfo(wa_id=wa_id, phone_number=wa_id),
        timestamp=datetime.now(UTC),
        modality=InputModality.INTERACTIVE if tap else InputModality.TEXT,
        text=text or tap or "",
        metadata=metadata,
    )
    try:
        await asyncio.wait_for(
            run_captured(container, message, capture, {"source": SOURCE}), timeout=REPLY_TIMEOUT_S
        )
    except TimeoutError:
        capture.text(STILL_WORKING)
    return WebMessageResponse(message_id=message_id, replies=capture.replies)


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
    return await handle(container, wa_id, text=text, tap=tap)
