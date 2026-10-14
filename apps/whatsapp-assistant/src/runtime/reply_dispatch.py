"""Shared ReplySpec -> transport dispatch, used by both the main journey
(runtime/inbound_journey.py) and any fast-path handler that renders its own
ReplySpec outside the journey (e.g. the project-selection resume in
runtime/dependencies.py). One place decides send_text vs send_list vs
send_button so the two call sites can't drift.

Media and links (WA-14). One answer is at most two WhatsApp messages:

- image + buttons -> ONE button message with the image as its header
  (likewise image + link button)
- image alone     -> one image with the text as its caption
- image + list    -> the image, then the list (list headers can't be images)
- document        -> the document, then the rest of the reply

The image is always optional. If it can't go out (no image sender wired,
text over WhatsApp's 1,024-character caption/body limit for the merged
forms, or the send fails), the reply still goes out without it -- the text
carries the answer on its own by contract (see ReplySpec)."""

from __future__ import annotations

import dataclasses
from collections.abc import Awaitable, Callable
from typing import Any

from channel.replies import ListRow, ReplySpec

# Meta's limit for an image caption and for an interactive message body.
# Over it, the image goes as its own message rather than being merged.
_MEDIA_TEXT_MAX_CHARS = 1024


async def send_reply_spec(
    reply: ReplySpec,
    wa_id: str,
    *,
    send_text: Callable[[str, str], Awaitable[Any]],
    send_list: Callable[[str, str, str, tuple[ListRow, ...]], Awaitable[Any]] | None = None,
    send_button: Callable[[str, str, tuple[ListRow, ...]], Awaitable[Any]] | None = None,
    send_image: Callable[..., Awaitable[Any]] | None = None,
    send_document: Callable[..., Awaitable[Any]] | None = None,
    send_cta: Callable[..., Awaitable[Any]] | None = None,
) -> Any:
    """Dispatches by ReplySpec shape and returns whatever the underlying
    send_* call returned. Only the plain-text branch's return value is ever
    a wamid today (#11 Reply Workflow, see channel/whatsapp/outbound.py's
    send_text_capturing_id) -- the list/button/media branches return whatever
    their own bool-returning senders give back, which callers wanting a
    wamid must treat as "not captured" (see runtime/inbound_journey.py's
    final "Send reply" step, which only acts on a str result)."""
    if reply.document is not None and send_document is not None:
        await send_document(
            wa_id,
            reply.document.data,
            filename=reply.document.filename,
            mime_type=reply.document.mime_type,
        )

    if reply.image is None:
        return await _send_core(
            reply, wa_id, send_text=send_text, send_list=send_list,
            send_button=send_button, send_cta=send_cta,
        )

    without_image = dataclasses.replace(reply, image=None)
    fits = len(reply.text) <= _MEDIA_TEXT_MAX_CHARS

    if reply.buttons and send_button is not None and fits:
        result = await send_button(
            wa_id, body=reply.text, buttons=reply.buttons, header_image=reply.image
        )
        if result:
            return result
    elif reply.cta is not None and send_cta is not None and fits:
        result = await send_cta(
            wa_id,
            body=reply.text,
            label=reply.cta.label,
            url=reply.cta.url,
            header_image=reply.image,
        )
        if result:
            return result
    elif (
        send_image is not None
        and fits
        and not reply.buttons
        and not reply.list_rows
        and reply.cta is None
    ):
        result = await send_image(wa_id, reply.image, caption=reply.text, filename="card.png")
        if result:
            return result
    elif send_image is not None:
        # The image can't share a message with what follows (a list, a long
        # text, or a button/link with no sender for the merged form): send
        # it on its own first, then the rest.
        await send_image(wa_id, reply.image, filename="card.png")

    return await _send_core(
        without_image, wa_id, send_text=send_text, send_list=send_list,
        send_button=send_button, send_cta=send_cta,
    )


async def _send_core(
    reply: ReplySpec,
    wa_id: str,
    *,
    send_text: Callable[[str, str], Awaitable[Any]],
    send_list: Callable[[str, str, str, tuple[ListRow, ...]], Awaitable[Any]] | None,
    send_button: Callable[[str, str, tuple[ListRow, ...]], Awaitable[Any]] | None,
    send_cta: Callable[..., Awaitable[Any]] | None,
) -> Any:
    """The text / buttons / list / link part of a reply, with no media."""
    if reply.buttons and send_button is not None:
        return await send_button(wa_id, body=reply.text, buttons=reply.buttons)
    if reply.buttons:
        options = " / ".join(row.title for row in reply.buttons)
        return await send_text(wa_id, f"{reply.text}\n\nReply {options}")
    if reply.list_rows and send_list is not None:
        return await send_list(
            wa_id,
            body=reply.text,
            button_label=reply.list_button_label or "Choose one",
            rows=reply.list_rows,
        )
    if reply.list_rows:
        options = "\n".join(f"  • {row.title}" for row in reply.list_rows)
        return await send_text(wa_id, f"{reply.text}\n{options}")
    if reply.cta is not None and send_cta is not None:
        return await send_cta(wa_id, body=reply.text, label=reply.cta.label, url=reply.cta.url)
    if reply.cta is not None:
        return await send_text(wa_id, f"{reply.text}\n\n{reply.cta.label}: {reply.cta.url}")
    return await send_text(wa_id, reply.text)
