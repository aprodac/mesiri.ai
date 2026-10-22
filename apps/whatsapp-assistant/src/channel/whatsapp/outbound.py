"""WhatsApp outbound delivery adapter.

Transport-level sender for the WhatsApp Cloud API. This is the only place that
constructs WhatsApp API payloads. Later, the Interaction layer (M7) will drive
replies via InteractionSpec through this same adapter; for now it supports a
simple text acknowledgement.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time

import httpx

from channel.replies import ListRow
from channel.whatsapp import usage as message_usage

logger = logging.getLogger(__name__)

# Meta Cloud API limits for interactive list messages (verified against the
# Cloud API reference). Enforced here, at the boundary, rather than trusted
# from the caller -- a row that silently exceeds these gets truncated or
# rejected by Meta with no useful error surfaced back to the user.
_LIST_BUTTON_MAX_CHARS = 20
_LIST_ROW_TITLE_MAX_CHARS = 24
_LIST_ROW_DESCRIPTION_MAX_CHARS = 72
_LIST_MAX_ROWS = 10
_REPLY_BUTTON_TITLE_MAX_CHARS = 20
_REPLY_BUTTON_MAX_COUNT = 3


class WhatsAppSender:
    """Send messages via the Meta WhatsApp Cloud API."""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        access_token: str,
        phone_number_id: str,
        api_version: str = "v21.0",
        graph_base_url: str = "https://graph.facebook.com",
    ) -> None:
        self._client = client
        self._access_token = access_token
        self._phone_number_id = phone_number_id
        self._api_version = api_version
        self._graph_base_url = graph_base_url.rstrip("/")
        #: B-7: uploads started ahead of the send (prepare_image), by content.
        self._prepared: dict[str, asyncio.Future[str | None]] = {}

    @property
    def enabled(self) -> bool:
        return bool(self._access_token and self._phone_number_id)

    async def mark_as_read(self, message_id: str, *, typing_indicator: bool = True) -> bool:
        """Mark an inbound message as read (blue tick) and, optionally, show
        the "typing..." indicator until a reply is sent or ~25s elapse.

        This is the Cloud API's combined read-receipt/typing-indicator call --
        there is no separate endpoint for either. Best-effort: callers treat a
        False return the same as every other send_* failure (log and move on),
        since a missed read receipt must never block the actual reply.
        """
        if not self.enabled:
            return False

        url = f"{self._graph_base_url}/{self._api_version}/{self._phone_number_id}/messages"
        payload: dict = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
        }
        if typing_indicator:
            payload["typing_indicator"] = {"type": "text"}

        try:
            resp = await self._client.post(
                url,
                json=payload,
                headers={"Authorization": f"Bearer {self._access_token}"},
            )
        except httpx.HTTPError as exc:
            logger.error("WhatsApp mark_as_read failed for %s: %s", message_id, exc)
            return False

        if resp.status_code >= 400:
            logger.error(
                "WhatsApp mark_as_read rejected (%s): %s", resp.status_code, resp.text[:300]
            )
            return False
        return True

    async def send_text(self, to_wa_id: str, body: str) -> bool:
        """Send a plain text message. Returns True on success."""
        return (await self.send_text_capturing_id(to_wa_id, body)) is not None

    async def send_text_capturing_id(self, to_wa_id: str, body: str) -> str | None:
        """Same as send_text, but returns Meta's wamid (or None on failure)
        instead of a bool -- for callers that need to record what was sent
        so a later reply to it can be resolved (#11 Reply Workflow)."""
        return await self._send(
            to_wa_id,
            {
                "type": "text",
                "text": {"body": body},
            },
        )

    async def send_reaction(self, to_wa_id: str, message_id: str, emoji: str = "✅") -> bool:
        """React to one of the user's own messages with an emoji -- an instant
        "got it" that costs the worker no extra message. Best effort: callers
        treat False like every other send_* failure and carry on."""
        if not message_id:
            return False
        return (
            await self._send(
                to_wa_id,
                {"type": "reaction", "reaction": {"message_id": message_id, "emoji": emoji}},
            )
        ) is not None

    async def send_list(
        self,
        to_wa_id: str,
        *,
        body: str,
        button_label: str,
        rows: list[ListRow],
        header: str | None = None,
        footer: str | None = None,
        section_title: str = "Options",
    ) -> bool:
        """Send a tappable WhatsApp list menu. Returns True on success.

        Payload shape and limits verified against the Cloud API reference:
        up to 10 rows total, 24-char row titles, 72-char descriptions,
        20-char button label. A row that violates these gets truncated here
        rather than silently rejected by Meta with no reply to the user.
        """
        if not rows:
            logger.error("send_list called with no rows to %s", to_wa_id)
            return False
        if len(rows) > _LIST_MAX_ROWS:
            logger.warning(
                "send_list to %s had %d rows, truncating to %d", to_wa_id, len(rows), _LIST_MAX_ROWS
            )
            rows = rows[:_LIST_MAX_ROWS]

        interactive: dict = {
            "type": "list",
            "body": {"text": body},
            "action": {
                "button": button_label[:_LIST_BUTTON_MAX_CHARS],
                "sections": [
                    {
                        "title": section_title[:_LIST_ROW_TITLE_MAX_CHARS],
                        "rows": [
                            {
                                "id": row.id,
                                "title": row.title[:_LIST_ROW_TITLE_MAX_CHARS],
                                "description": row.description[:_LIST_ROW_DESCRIPTION_MAX_CHARS],
                            }
                            for row in rows
                        ],
                    }
                ],
            },
        }
        if header:
            interactive["header"] = {"type": "text", "text": header}
        if footer:
            interactive["footer"] = {"text": footer}

        return (await self._send(to_wa_id, {"type": "interactive", "interactive": interactive})) is not None

    async def send_button(
        self,
        to_wa_id: str,
        *,
        body: str,
        buttons: list[ListRow],
        header_image: bytes | None = None,
    ) -> bool:
        """Send up to 3 tappable quick-reply buttons (e.g. Yes/No confirmation).

        ``header_image`` (PNG bytes) is uploaded and shown above the body as
        the message's image header -- the receipt card travels inside the
        reply this way. If the upload fails nothing is sent and False is
        returned, so the caller can fall back to text+buttons and the image
        as its own message.

        Returns True on success. Meta Cloud API limits: max 3 buttons,
        20-char titles -- enforced here rather than trusted from the caller,
        same reasoning as send_list.
        """
        if not buttons:
            logger.error("send_button called with no buttons to %s", to_wa_id)
            return False
        if len(buttons) > _REPLY_BUTTON_MAX_COUNT:
            logger.warning(
                "send_button to %s had %d buttons, truncating to %d",
                to_wa_id,
                len(buttons),
                _REPLY_BUTTON_MAX_COUNT,
            )
            buttons = buttons[:_REPLY_BUTTON_MAX_COUNT]

        interactive: dict = {
            "type": "button",
            "body": {"text": body},
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {
                            "id": button.id,
                            "title": button.title[:_REPLY_BUTTON_TITLE_MAX_CHARS],
                        },
                    }
                    for button in buttons
                ]
            },
        }
        if header_image is not None:
            media_id = await self._upload_media(
                header_image, mime_type="image/png", filename="receipt.png"
            )
            if media_id is None:
                return False
            interactive["header"] = {"type": "image", "image": {"id": media_id}}
        wamid = await self._send(to_wa_id, {"type": "interactive", "interactive": interactive})
        sent = wamid is not None
        if header_image is not None and sent:
            # Greppable proof in the server log that the card went out as the
            # message's header image (and which uploaded media it was).
            logger.info("receipt.sent as=header media_id=%s to=%s", media_id, to_wa_id)
            if wamid:
                await self.pin_message(to_wa_id, wamid)
        return sent

    async def send_image(
        self, to_wa_id: str, image_bytes: bytes, *, caption: str | None = None
    ) -> bool:
        """Upload an image and send it. Returns True on success.

        The Cloud API has no "send these raw bytes" call -- media must be
        uploaded first (POST /{phone-number-id}/media, multipart) to get a
        media id, then referenced in the message. Two HTTP calls, not one;
        a failure at either step degrades to False rather than raising, same
        as every other send_* method here.
        """
        if not self.enabled:
            logger.warning("WhatsApp sender disabled (missing phone_number_id/access_token)")
            return False

        media_id = await self._upload_media(image_bytes, mime_type="image/png", filename="receipt.png")
        if media_id is None:
            return False

        image_fields: dict = {"id": media_id}
        if caption:
            image_fields["caption"] = caption
        wamid = await self._send(to_wa_id, {"type": "image", "image": image_fields})
        sent = wamid is not None
        if sent:
            logger.info("receipt.sent as=image media_id=%s to=%s", media_id, to_wa_id)
            if wamid:
                await self.pin_message(to_wa_id, wamid)
        return sent

    async def pin_message(
        self, to_wa_id: str, message_id: str, *, expiration_days: int = 1
    ) -> bool:
        """EXPERIMENT: ask the Cloud API to pin one of our messages in a 1:1 chat.

        Meta documents pinning for groups only, so this is expected to be
        rejected for an individual recipient; the point is to log Meta's real
        answer (pin_test.* lines). Best effort, never raises. Runs after every
        receipt while the platform is pre-launch; remove once answered."""
        if not self.enabled or not message_id:
            return False
        url = f"{self._graph_base_url}/{self._api_version}/{self._phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_wa_id,
            "type": "pin",
            "pin": {"type": "pin", "message_id": message_id, "expiration_days": expiration_days},
        }
        try:
            resp = await self._client.post(
                url, json=payload, headers={"Authorization": f"Bearer {self._access_token}"}
            )
        except httpx.HTTPError as exc:
            logger.warning("pin_test.failed to=%s wamid=%s: %s", to_wa_id, message_id, exc)
            return False
        accepted = resp.status_code < 400
        logger.warning(
            "pin_test.%s status=%s to=%s wamid=%s body=%s",
            "accepted" if accepted else "rejected",
            resp.status_code,
            to_wa_id,
            message_id,
            resp.text[:300],
        )
        return accepted

    async def send_document(
        self,
        to_wa_id: str,
        document_bytes: bytes,
        *,
        filename: str,
        caption: str | None = None,
        mime_type: str = "application/pdf",
    ) -> bool:
        """Upload a document (e.g. a DPR PDF, #16 Daily Report Generation)
        and send it. Same two-step upload-then-reference flow as
        send_image -- see that docstring."""
        if not self.enabled:
            logger.warning("WhatsApp sender disabled (missing phone_number_id/access_token)")
            return False

        media_id = await self._upload_media(document_bytes, mime_type=mime_type, filename=filename)
        if media_id is None:
            return False

        document_fields: dict = {"id": media_id, "filename": filename}
        if caption:
            document_fields["caption"] = caption
        return (
            await self._send(to_wa_id, {"type": "document", "document": document_fields})
        ) is not None

    async def send_template(
        self,
        to_wa_id: str,
        *,
        name: str,
        language: str,
        body_params: tuple[str, ...] | list[str] = (),
        header_document: tuple[bytes, str] | None = None,
        mime_type: str = "application/pdf",
        button_url_param: str | None = None,
        quick_reply_payloads: tuple[str, ...] | list[str] = (),
    ) -> bool:
        """Send a Meta-approved template (WA-12) -- the only kind of message
        Meta delivers outside the 24h session window. `header_document` is
        (bytes, filename) for a template whose header is a document: it is
        uploaded first, same two-step flow as send_document.
        `button_url_param` fills the first button's variable; an
        authentication template's "Copy code" button takes the code here.
        `quick_reply_payloads` gives each quick-reply button, in order, the
        payload its tap comes back with (WA-04).
        Params are sent as given; channel/whatsapp/templates.py cleans them."""
        if not self.enabled:
            logger.warning("WhatsApp sender disabled (missing phone_number_id/access_token)")
            return False

        components: list[dict] = []
        if header_document is not None:
            data, filename = header_document
            media_id = await self._upload_media(data, mime_type=mime_type, filename=filename)
            if media_id is None:
                return False
            components.append(
                {
                    "type": "header",
                    "parameters": [
                        {"type": "document", "document": {"id": media_id, "filename": filename}}
                    ],
                }
            )
        if body_params:
            components.append(
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": str(p)} for p in body_params],
                }
            )
        if button_url_param is not None:
            components.append(
                {
                    "type": "button",
                    "sub_type": "url",
                    "index": "0",
                    "parameters": [{"type": "text", "text": str(button_url_param)}],
                }
            )
        for index, payload in enumerate(quick_reply_payloads):
            components.append(
                {
                    "type": "button",
                    "sub_type": "quick_reply",
                    "index": str(index),
                    "parameters": [{"type": "payload", "payload": str(payload)}],
                }
            )

        template: dict = {"name": name, "language": {"code": language}}
        if components:
            template["components"] = components
        message_id = await self._send(to_wa_id, {"type": "template", "template": template})
        if message_id is not None:
            # Meta reports a template failure later, on the webhook, by this
            # id only (ingress/receiver.py logs it) -- log the pairing here.
            logger.info("whatsapp.template_sent name=%s wamid=%s", name, message_id)
        return message_id is not None

    async def prepare_image(self, data: bytes) -> None:
        """Upload a PNG now so a later send_button / send_image of the same
        bytes needs no upload (B-7: the receipt card is uploaded while the
        reply is still being written). Never raises."""
        try:
            await self._upload_media(data, mime_type="image/png", filename="receipt.png")
        except Exception:  # noqa: BLE001 -- the send uploads it again
            logger.warning("whatsapp.prepare_image_failed", exc_info=True)

    async def _upload_media(self, data: bytes, *, mime_type: str, filename: str) -> str | None:
        """Upload once per content: a second call with the same bytes (the
        send after prepare_image) waits for, or reuses, the first upload's
        media id. A failed upload is not kept, so the send tries again."""
        key = hashlib.sha256(data).hexdigest()
        pending = self._prepared.get(key)
        if pending is not None:
            media_id = await asyncio.shield(pending)
            if media_id is not None:
                self._prepared.pop(key, None)
                return media_id
        future: asyncio.Future[str | None] = asyncio.get_running_loop().create_future()
        self._prepared[key] = future
        while len(self._prepared) > 16:  # bounded: one entry per reply in flight
            self._prepared.pop(next(iter(self._prepared)))
        try:
            media_id = await self._upload_media_once(data, mime_type=mime_type, filename=filename)
        except BaseException:
            self._prepared.pop(key, None)
            future.set_result(None)
            raise
        future.set_result(media_id)
        if media_id is None:
            self._prepared.pop(key, None)
        return media_id

    async def _upload_media_once(self, data: bytes, *, mime_type: str, filename: str) -> str | None:
        url = f"{self._graph_base_url}/{self._api_version}/{self._phone_number_id}/media"
        try:
            resp = await self._client.post(
                url,
                data={"messaging_product": "whatsapp", "type": mime_type},
                files={"file": (filename, data, mime_type)},
                headers={"Authorization": f"Bearer {self._access_token}"},
            )
        except httpx.HTTPError as exc:
            logger.error("WhatsApp media upload failed: %s", exc)
            return None

        if resp.status_code >= 400:
            logger.error("WhatsApp media upload rejected (%s): %s", resp.status_code, resp.text[:300])
            return None

        media_id = resp.json().get("id")
        if not media_id:
            logger.error("WhatsApp media upload response had no id: %s", resp.text[:300])
            return None
        return media_id

    async def _send(self, to_wa_id: str, message_fields: dict) -> str | None:
        """POST one message to the Cloud API. `message_fields` supplies the
        `type` key and its matching payload (`text`, `interactive`, ...).

        Returns Meta's own wamid for the sent message, or None on any
        failure -- every existing bool-returning send_* method below wraps
        this with `is not None`, so their contract is unchanged. The raw
        id is what #11 Reply Workflow needs: a reply to THIS message can
        only be resolved back to its context if the id was captured when
        it was sent (see channel/reply_dispatch.py's send_text_capturing_id
        and context/main_table_repositories.py's MainReplyContextProvider).
        """
        if not self.enabled:
            logger.warning("WhatsApp sender disabled (missing phone_number_id/access_token)")
            return None

        url = f"{self._graph_base_url}/{self._api_version}/{self._phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_wa_id,
            **message_fields,
        }
        # Timed because every outbound send sits between the last traced
        # pipeline stage and inbound_messages.processed_at, so its cost was
        # invisible in the per-stage breakdown -- and a reply is often two or
        # three sends (text, then a list, then a receipt image).
        started = time.perf_counter()
        try:
            resp = await self._client.post(
                url,
                json=payload,
                headers={"Authorization": f"Bearer {self._access_token}"},
            )
        except httpx.HTTPError as exc:
            logger.error(
                "WhatsApp send failed to %s after %sms: %s",
                to_wa_id,
                round((time.perf_counter() - started) * 1000, 1),
                exc,
            )
            return None

        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        if resp.status_code >= 400:
            logger.error(
                "WhatsApp send rejected (%s) after %sms: %s",
                resp.status_code,
                elapsed_ms,
                resp.text[:300],
            )
            return None

        logger.info(
            "whatsapp.sent type=%s to=%s send_ms=%s", message_fields["type"], to_wa_id, elapsed_ms
        )
        # Meta returns {"messages": [{"id": "wamid...."}], ...} on success.
        # A malformed/missing id degrades to None (still "sent", just not
        # reply-trackable) rather than raising -- the send itself succeeded.
        try:
            messages = resp.json().get("messages") or []
            wamid = str(messages[0]["id"]) if messages else None
        except (ValueError, KeyError, IndexError, TypeError):
            logger.warning("whatsapp.sent response had no parseable message id to=%s", to_wa_id)
            return None
        if wamid is not None:
            # BE-25: what this message costs (corrected later by the webhook).
            message_usage.report_sent(
                wamid=wamid, recipient=to_wa_id, message_fields=message_fields
            )
        return wamid
