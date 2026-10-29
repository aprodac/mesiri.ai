"""Run one message through the production handler and keep the replies.

The control panel's test message (admin/system_graph_router.py, `simulate`)
and the dashboard's "Tell Mesiri" (web_assistant/router.py, WEB-36) both
need exactly what a WhatsApp message gets -- the same handler
(runtime/message_journey.py via `container.simulate_handler`), so taps,
YES/NO cards, the agent, the workflows and the trial usage guard all behave
as on WhatsApp -- with one difference: the replies are captured instead of
sent. This module is that one difference, shared, so the two doors can't
drift apart.
"""

from __future__ import annotations

import uuid
from typing import Any

import sqlalchemy as sa
from pydantic import BaseModel

from mesiri_contracts.common.ids import new_id


class ReplyOption(BaseModel):
    id: str
    title: str
    description: str | None = None


class CapturedReply(BaseModel):
    type: str  # "text" | "buttons" | "list"
    text: str
    buttons: list[ReplyOption] = []
    list_rows: list[ReplyOption] = []
    button_label: str | None = None


def _options(rows: Any) -> list[ReplyOption]:
    return [
        ReplyOption(
            id=getattr(r, "id", str(r)),
            title=getattr(r, "title", str(r)),
            description=getattr(r, "description", None),
        )
        for r in rows
    ]


class ReplyCapture:
    """Collects what Mesiri would have sent. `texts` is the plain-text view
    (the control panel's log); `replies` keeps the buttons and list rows."""

    def __init__(self) -> None:
        self.texts: list[str] = []
        self.replies: list[CapturedReply] = []

    def text(self, text: str) -> None:
        self.texts.append(text)
        self.replies.append(CapturedReply(type="text", text=text))

    def list(self, body: str, button_label: str, rows: Any) -> None:
        options = _options(rows)
        self.texts.append(body + "\n" + "\n".join(f"  • {o.title}" for o in options))
        self.replies.append(
            CapturedReply(type="list", text=body, button_label=button_label, list_rows=options)
        )

    def buttons(self, body: str, buttons: Any) -> None:
        options = _options(buttons)
        self.texts.append(f"{body}\n\nReply " + " / ".join(o.title for o in options))
        self.replies.append(CapturedReply(type="buttons", text=body, buttons=options))

    def sender(self) -> Any:
        """A WhatsApp sender whose every send lands here instead."""
        capture = self

        class _CapturingSender:
            async def send_text(self, _to: str, text: str, *args: object, **kwargs: object) -> bool:
                capture.text(text)
                return True

            async def send_text_capturing_id(self, _to: str, text: str) -> str:
                capture.text(text)
                return new_id("sim")

            async def send_list(
                self, _to: str, *, body: str, button_label: str, rows: Any, **kwargs: object
            ) -> bool:
                capture.list(body, button_label, rows)
                return True

            async def send_button(
                self, _to: str, *, body: str, buttons: Any, **kwargs: object
            ) -> bool:
                capture.buttons(body, buttons)
                return True

            async def send_image(
                self, _to: str, _data: bytes, *, caption: str | None = None, filename: str = "", **kwargs: object
            ) -> bool:
                capture.text(f"[image]{' ' + caption if caption else ''}")
                return True

            async def send_document(
                self, _to: str, _data: bytes, *, filename: str, **kwargs: object
            ) -> bool:
                capture.text(f"[document: {filename}]")
                return True

            def __getattr__(self, _name: str):  # mark_as_read, send_reaction, prepare_image, ...
                async def _quiet(*args: object, **kwargs: object) -> bool:
                    return True

                return _quiet

        return _CapturingSender()


class UserNotFound(LookupError):
    """No such user in that company."""


async def user_whatsapp_number(organization_id: uuid.UUID, user_id: uuid.UUID) -> str | None:
    """The user's registered WhatsApp number (the pipeline keys identity off
    it), or None when they have none. Raises UserNotFound."""
    from admin.router import get_engine, users_table

    engine = get_engine()
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                sa.select(users_table.c.whatsapp_number).where(
                    sa.and_(
                        users_table.c.id == user_id,
                        users_table.c.organization_id == organization_id,
                    )
                )
            )
        ).first()
    if row is None:
        raise UserNotFound(str(user_id))
    return str(row.whatsapp_number) if row.whatsapp_number else None


async def identity_refusal(container: Any, wa_id: str) -> str | None:
    """What WhatsApp would answer instead of handling the message (unknown
    number, no company, company suspended), or None to go on. The same check
    the real webhook path runs first (M4)."""
    from context.live_identity import (
        NO_ORG_MESSAGE,
        ORG_SUSPENDED_MESSAGE,
        resolve_sender,
        unregistered_message,
    )

    ctx = await resolve_sender(container.actor_reader, wa_id)
    if ctx is None:
        return unregistered_message(wa_id)
    if ctx.organization_id is None:
        return NO_ORG_MESSAGE.format(name=ctx.full_name)
    if not ctx.org_active:
        return ORG_SUSPENDED_MESSAGE
    return None


async def run_captured(
    container: Any, message: Any, capture: ReplyCapture, raw_payload: dict | None = None
) -> None:
    """Handle `message` with the production handler, replies into `capture`.
    An outage is captured as a reply, not raised."""
    handler = container.simulate_handler(capture.sender())
    try:
        await handler(message, raw_payload or {})
    except Exception as exc:  # noqa: BLE001 -- shown, not raised
        capture.text(f"[error: {type(exc).__name__}]")
