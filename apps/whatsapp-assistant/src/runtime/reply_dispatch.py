"""Shared ReplySpec -> transport dispatch, used by both the main journey
(runtime/inbound_journey.py) and any fast-path handler that renders its own
ReplySpec outside the journey (e.g. the project-selection resume in
runtime/dependencies.py). One place decides send_text vs send_list vs
send_button so the two call sites can't drift."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Any

from channel.replies import ListRow, ReplySpec
from runtime.reply_composer import numbered

_log = logging.getLogger("mesiri.reply_dispatch")


async def send_reply_spec(
    reply: ReplySpec,
    wa_id: str,
    *,
    send_text: Callable[[str, str], Awaitable[Any]],
    send_list: Callable[[str, str, str, tuple[ListRow, ...]], Awaitable[Any]] | None = None,
    send_button: Callable[[str, str, tuple[ListRow, ...]], Awaitable[Any]] | None = None,
    send_image: Callable[..., Awaitable[Any]] | None = None,
) -> Any:
    """Dispatches by ReplySpec shape and returns whatever the underlying
    send_* call returned. Only the plain-text branch's return value is ever
    a wamid today (#11 Reply Workflow, see channel/whatsapp/outbound.py's
    send_text_capturing_id) -- the list/button branches return whatever
    their own bool-returning senders give back, which callers wanting a
    wamid must treat as "not captured" (see runtime/inbound_journey.py's
    final "Send reply" step, which only acts on a str result)."""
    image = reply.header_image
    if image is not None and not (reply.buttons and send_button is not None):
        # Only a reply-button message can carry the image as its header:
        # any other form sends its text, then the image on its own.
        sent = await send_reply_spec(
            replace(reply, header_image=None),
            wa_id,
            send_text=send_text,
            send_list=send_list,
            send_button=send_button,
        )
        if send_image is not None:
            await send_image(wa_id, image, caption=None)
        return sent
    if reply.buttons and send_button is not None:
        if image is not None:
            sent = await send_button(
                wa_id, body=reply.text, buttons=reply.buttons, header_image=image
            )
            if sent is not False:
                return sent
            # The header send failed (upload or API): the reply goes out
            # without it, then the image on its own -- the old behaviour.
            _log.warning("receipt.header_send_failed wa_id=%s", wa_id)
            sent = await send_button(wa_id, body=reply.text, buttons=reply.buttons)
            if send_image is not None:
                await send_image(wa_id, image, caption=None)
            if sent is not False:
                return sent
            return await send_text(wa_id, numbered(reply.text, reply.buttons))
        sent = await send_button(wa_id, body=reply.text, buttons=reply.buttons)
        if sent is not False:
            return sent
        return await send_text(wa_id, numbered(reply.text, reply.buttons))
    if reply.buttons:
        options = " / ".join(row.title for row in reply.buttons)
        return await send_text(wa_id, f"{reply.text}\n\nReply {options}")
    if reply.list_rows and send_list is not None:
        sent = await send_list(
            wa_id,
            body=reply.text,
            button_label=reply.list_button_label or "Choose one",
            rows=reply.list_rows,
        )
        if sent is not False:
            return sent
        return await send_text(wa_id, numbered(reply.text, reply.list_rows))
    if reply.list_rows:
        options = "\n".join(f"  • {row.title}" for row in reply.list_rows)
        return await send_text(wa_id, f"{reply.text}\n{options}")
    return await send_text(wa_id, reply.text)

