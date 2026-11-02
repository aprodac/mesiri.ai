"""TM-33: "Is this how you want it?" -- a preview of a requested change, to the person who asked (asked 2 Nov 2026).

When someone tells Mesiri that something is bad or missing, the team bot plans the change and starts building it at
once. For UX changes and new features it also draws what the reply will look like (labelled PREVIEW) and sends it
here; Mesiri sends it to that person from its own number, with *Confirm* and *Change it*. The build does not wait:
Confirm lets it carry on; Change it asks them what to change, and their answer goes to the team bot as feedback,
which adds it to the running build.

This route lets the team bot message a customer, so it is locked down (CLAUDE.md: security-sensitive):

- **Off** unless ``MESIRI_PREVIEWS=on`` is set on the server (an owner's decision; off answers 404).
- **The bot's token only** (``MESIRI_TEAMMATE_API_TOKEN``, the one the Requests page uses), compared in constant time.
- **Only the person who asked**: the recipient is read from the message the request came in (its correlation id),
  never given by the caller.
- **Only companies on v3** (``assistant_mode = api``: the test companies today).
- **Only inside WhatsApp's 24-hour window** (their last message to Mesiri, with a margin).
- **Once per request** (Redis), a PNG of at most 1 MB, and a short caption.
"""

from __future__ import annotations

import base64
import datetime as dt
import hmac
import logging
import os
import re
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from channel.replies import ListRow

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/teammate-api", tags=["teammate"])

CONFIRM_PREFIX = "preview_ok:"
CHANGE_PREFIX = "preview_change:"
#: The journey trace stage of a preview tap; the team bot's production watch reads its tell_the_team call.
FEEDBACK_STAGE = "preview_feedback"
MAX_PNG_BYTES = 1024 * 1024
#: WhatsApp's customer-service window is 24 hours; a margin so a preview never lands just outside it.
WINDOW_HOURS = 23.5
_CID = re.compile(r"^cor_[0-9a-f]{8,40}$")
_PNG = b"\x89PNG\r\n\x1a\n"


class PreviewRequest(BaseModel):
    correlation_id: str = Field(pattern=_CID.pattern)
    image_base64: str = Field(min_length=10, max_length=MAX_PNG_BYTES * 4 // 3 + 8)
    caption: str = Field(default="", max_length=300)
    request_ref: str = Field(default="", max_length=12)


def enabled() -> bool:
    return os.environ.get("MESIRI_PREVIEWS", "").strip().lower() in ("on", "1", "true", "yes")


def _authorized(authorization: str | None) -> bool:
    from mesiri.bootstrap.settings import get_settings

    secret = get_settings().teammate_api_token
    token = secret.get_secret_value().strip() if secret is not None else ""
    given = (authorization or "").removeprefix("Bearer ").strip()
    return bool(token) and hmac.compare_digest(given.encode(), token.encode())


def preview_buttons(correlation_id: str, language: str | None = None) -> list[ListRow]:
    from runtime.agent.wording import say

    lang = language or "english"
    return [ListRow(id=f"{CONFIRM_PREFIX}{correlation_id}", title=say("preview.confirm", lang)),
            ListRow(id=f"{CHANGE_PREFIX}{correlation_id}", title=say("preview.change", lang))]


def parse_tap(tap: str) -> tuple[bool, str] | None:
    """``(confirmed, correlation_id)`` for a tap on a preview's buttons, else None."""
    for prefix, confirmed in ((CONFIRM_PREFIX, True), (CHANGE_PREFIX, False)):
        if tap.startswith(prefix):
            cid = tap[len(prefix):]
            return (confirmed, cid) if _CID.match(cid) else None
    return None


def tap_trace(confirmed: bool, correlation_id: str) -> dict[str, Any]:
    """Confirm is recorded; "Change it" is a tell_the_team call (bad_ux), so the watch adds it to the build."""
    if confirmed:
        return {"preview": "confirmed", "for": correlation_id,
                "calls": [{"tool": "preview_confirmed", "by": "code", "args": {"for": correlation_id}}]}
    return {"preview": "change", "for": correlation_id, "calls": [{"tool": "tell_the_team", "by": "code", "args": {
        "kind": "bad_ux", "about": f"the preview sent for request {correlation_id} is not what they want; their next message says what to change",
    }}]}


async def _request_row(db: Any, correlation_id: str) -> dict[str, Any] | None:
    import sqlalchemy as sa

    async with db.transaction() as conn:
        row = (await conn.execute(sa.text(
            "SELECT im.sender_wa_id, im.organization_id, im.body_text, "
            "(SELECT max(x.received_at) FROM inbound_messages x WHERE x.sender_wa_id = im.sender_wa_id) AS last_at "
            "FROM inbound_messages im WHERE im.correlation_id = :cid LIMIT 1"), {"cid": correlation_id})).mappings().first()
    return dict(row) if row else None


@router.post("/preview")
async def send_preview(body: PreviewRequest, request: Request, authorization: str | None = Header(default=None)) -> dict:
    if not enabled():
        raise HTTPException(status_code=404, detail="Not Found")
    if not _authorized(authorization):
        raise HTTPException(status_code=401, detail="unauthorized")
    try:
        png = base64.b64decode(body.image_base64, validate=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="image_base64 is not base64") from exc
    if not png.startswith(_PNG) or len(png) > MAX_PNG_BYTES:
        raise HTTPException(status_code=400, detail="a PNG of at most 1 MB")
    container = request.app.state.container
    row = await _request_row(container.material_db, body.correlation_id)
    if row is None or not row.get("sender_wa_id") or not row.get("organization_id"):
        raise HTTPException(status_code=404, detail="no such request")
    from mesiri.domains.organizations import settings as settings_spec

    stored = await container.org_settings_query.get(organization_id=str(row["organization_id"]), key=settings_spec.ASSISTANT_MODE)
    if settings_spec.assistant_mode(stored) != settings_spec.ASSISTANT_MODE_API:
        raise HTTPException(status_code=403, detail="previews go only to companies on v3")
    last = row.get("last_at")
    if last is None or (dt.datetime.now(dt.UTC) - (last if last.tzinfo else last.replace(tzinfo=dt.UTC))) > dt.timedelta(hours=WINDOW_HOURS):
        raise HTTPException(status_code=409, detail="outside the 24-hour window")
    if not await container.redis_client.set_if_absent(f"preview:{body.correlation_id}", "1", ttl_seconds=7 * 86400):
        raise HTTPException(status_code=409, detail="a preview was already sent for this request")
    from runtime.agent.wording import language_of, say

    language = language_of(str(row.get("body_text") or "")) or "english"
    text = say("preview.ask", language) + (f"\n\n{body.caption.strip()}" if body.caption.strip() else "") + (
        f"\n\n{body.request_ref}" if body.request_ref else "")
    sender = container.whatsapp_sender
    wa_id = str(row["sender_wa_id"])
    buttons = preview_buttons(body.correlation_id, language)
    shows = f"Preview of the change asked for in {body.correlation_id} (TM-33)"
    sent = await sender.send_button(wa_id, body=text, buttons=buttons, header_image=png, shows=shows)
    if not sent:  # the image header could not be uploaded: the picture, then the question with its buttons
        await sender.send_image(wa_id, png, caption=None, filename="preview.png", shows=shows)
        sent = await sender.send_button(wa_id, body=text, buttons=buttons)
    try:
        await container.trace_logger.log_stage(correlation_id=body.correlation_id, stage="preview_sent",
                                               stage_payload={"sent": bool(sent), "ref": body.request_ref},
                                               duration_ms=0, succeeded=bool(sent))
    except Exception:  # noqa: BLE001 -- the preview already went
        _log.warning("preview.trace_failed correlation_id=%s", body.correlation_id, exc_info=True)
    _log.info("preview.sent correlation_id=%s ok=%s", body.correlation_id, sent)
    return {"sent": bool(sent)}
