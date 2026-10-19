"""Shared ReplySpec -> transport dispatch, used by both the main journey
(runtime/inbound_journey.py) and any fast-path handler that renders its own
ReplySpec outside the journey (e.g. the project-selection resume in
runtime/dependencies.py). One place decides send_text vs send_list vs
send_button so the two call sites can't drift."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from channel.replies import ListRow, ReplySpec
from runtime.reply_composer import numbered


async def send_reply_spec(
    reply: ReplySpec,
    wa_id: str,
    *,
    send_text: Callable[[str, str], Awaitable[Any]],
    send_list: Callable[[str, str, str, tuple[ListRow, ...]], Awaitable[Any]] | None = None,
    send_button: Callable[[str, str, tuple[ListRow, ...]], Awaitable[Any]] | None = None,
) -> Any:
    """Dispatches by ReplySpec shape and returns whatever the underlying
    send_* call returned. Only the plain-text branch's return value is ever
    a wamid today (#11 Reply Workflow, see channel/whatsapp/outbound.py's
    send_text_capturing_id) -- the list/button branches return whatever
    their own bool-returning senders give back, which callers wanting a
    wamid must treat as "not captured" (see runtime/inbound_journey.py's
    final "Send reply" step, which only acts on a str result)."""
    if reply.buttons and send_button is not None:
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

