"""Convert Meta WhatsApp webhook message payloads into NormalizedMessage objects."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from mesiri_contracts.assistant import MediaReference, NormalizedMessage, ReplyContext, SenderInfo
from mesiri_contracts.assistant.enums import InputModality

logger = logging.getLogger(__name__)

_SUPPORTED_TYPES = {
    "text": InputModality.TEXT,
    "image": InputModality.IMAGE,
    "audio": InputModality.VOICE,
    "interactive": InputModality.INTERACTIVE,
    # A tap on a template's quick-reply button (WA-04) -- a menu tap like
    # any other, carrying the payload the template was sent with.
    "button": InputModality.INTERACTIVE,
}


class MessageNormalizer:
    """Map Meta webhook message payloads to Mesiri's canonical message format."""

    def normalize(
        self,
        message: Mapping[str, Any],
        *,
        contacts: Sequence[Mapping[str, Any]],
        phone_number_id: str | None,
        display_phone_number: str | None,
        media: MediaReference | None = None,
    ) -> NormalizedMessage:
        """Convert one Meta message object into a NormalizedMessage."""
        modality = self._resolve_modality(message)
        sender = self._resolve_sender(message, contacts)
        text = self._resolve_text(message, modality)
        reply_context = self._resolve_reply_context(message)
        metadata: dict[str, Any] = {
            "phone_number_id": phone_number_id,
            "display_phone_number": display_phone_number,
            "raw_type": message.get("type"),
        }
        forwarded, frequently_forwarded = self._resolve_forwarding(message)
        if forwarded:
            metadata["forwarded"] = True
            # Meta's own "many times forwarded" marker. Kept distinct rather
            # than collapsed into `forwarded`: a message relayed once by the
            # site engineer is ordinary second-hand reporting, while a
            # frequently-forwarded one is far more likely to be a broadcast or
            # chain message that was never about this site at all.
            if frequently_forwarded:
                metadata["frequently_forwarded"] = True

        if message.get("type") == "contacts":
            # SS-13: a shared contact card adds that person to the team.
            # Still modality UNKNOWN (there's nothing to understand); the
            # people on the card travel in metadata.
            metadata["shared_contacts"] = self._resolve_shared_contacts(message)

        if modality is InputModality.INTERACTIVE:
            interactive_reply = self._resolve_interactive_reply(message)
            if interactive_reply is not None:
                text = interactive_reply["title"]
                metadata["interactive_reply_id"] = interactive_reply["id"]
                metadata["interactive_reply_type"] = interactive_reply["type"]

        normalized = NormalizedMessage(
            message_id=str(message["id"]),
            channel="whatsapp",
            sender=sender,
            timestamp=self._resolve_timestamp(message),
            modality=modality,
            text=text,
            media=media,
            reply_context=reply_context,
            metadata=metadata,
        )
        logger.debug("Normalized WhatsApp message %s as %s", normalized.message_id, modality)
        return normalized

    def _resolve_modality(self, message: Mapping[str, Any]) -> InputModality:
        """Map Meta's `type` onto an InputModality, never raising.

        Anything Mesiri can't act on yet (document/video/sticker/location/
        contacts, or a music file rather than a voice note) resolves to
        UNKNOWN instead of raising. Raising used to abort ingress inside
        WhatsAppReceiver._process_message's catch-all, which logged a trace
        row and returned -- with no reply ever sent, so the sender got pure
        silence and no way to tell "Mesiri can't read PDFs" from "Mesiri is
        down". The message now normalizes successfully and the runtime
        declines it politely (see channel/replies.py's
        render_unsupported_media_reply); metadata["raw_type"] carries the
        original type through so that reply can be specific.
        """
        raw_type = message.get("type")
        if raw_type == "audio":
            audio_payload = message.get("audio") or {}
            if not audio_payload.get("voice"):
                return InputModality.UNKNOWN
            return InputModality.VOICE

        return _SUPPORTED_TYPES.get(raw_type, InputModality.UNKNOWN)

    def _resolve_sender(
        self,
        message: Mapping[str, Any],
        contacts: Sequence[Mapping[str, Any]],
    ) -> SenderInfo:
        wa_id = str(message["from"])
        profile_name = None

        for contact in contacts:
            if str(contact.get("wa_id")) == wa_id:
                profile = contact.get("profile") or {}
                profile_name = profile.get("name")
                break

        return SenderInfo(
            wa_id=wa_id,
            phone_number=wa_id,
            profile_name=profile_name,
        )

    @staticmethod
    def _resolve_shared_contacts(message: Mapping[str, Any]) -> list[dict[str, str]]:
        """Each card's name and number from a `contacts` message. The number
        is the card's WhatsApp id when Meta knows the person is on WhatsApp
        (digits, country code first), else the first phone as written.
        Cards without a number are dropped."""
        people: list[dict[str, str]] = []
        for card in message.get("contacts") or []:
            if not isinstance(card, Mapping):
                continue
            name_obj = card.get("name") or {}
            name = str(
                name_obj.get("formatted_name")
                or " ".join(
                    p for p in (name_obj.get("first_name"), name_obj.get("last_name")) if p
                )
                or ""
            ).strip()
            phones = [p for p in (card.get("phones") or []) if isinstance(p, Mapping)]
            number = next((str(p["wa_id"]) for p in phones if p.get("wa_id")), None) or next(
                (str(p["phone"]) for p in phones if p.get("phone")), None
            )
            if number:
                people.append({"name": name, "phone": number})
        return people

    def _resolve_timestamp(self, message: Mapping[str, Any]) -> datetime:
        timestamp = int(message["timestamp"])
        return datetime.fromtimestamp(timestamp, tz=UTC)

    def _resolve_text(
        self,
        message: Mapping[str, Any],
        modality: InputModality,
    ) -> str | None:
        if modality is InputModality.TEXT:
            text_payload = message.get("text") or {}
            return text_payload.get("body")

        if modality is InputModality.IMAGE:
            image_payload = message.get("image") or {}
            return image_payload.get("caption")

        return None

    def _resolve_interactive_reply(self, message: Mapping[str, Any]) -> dict[str, str] | None:
        """Extract the tapped list row or button from an interactive reply.

        Meta's shape (verified against the Cloud API reference): a template
        quick-reply tap is `type: "button"` with `button.payload`/`text`;
        otherwise the outer message carries `type: "interactive"`; the nested `interactive.type`
        is `"list_reply"` or `"button_reply"`, each with its own object of
        the same name holding `id` and `title`. Anything else (e.g. a Flow's
        `nfm_reply`, which Mesiri doesn't send) is not a menu tap -- returns
        None rather than raising, so the message still normalizes with no
        text/selection rather than being dropped outright.
        """
        if message.get("type") == "button":
            # A template quick-reply tap: `button.payload` is what the
            # template was sent with, `button.text` the button's label.
            button = message.get("button") or {}
            title = button.get("text")
            reply_id = button.get("payload") or title
            if not reply_id or not title:
                return None
            return {"id": str(reply_id), "title": str(title), "type": "template_button"}

        interactive = message.get("interactive") or {}
        reply_type = interactive.get("type")
        if reply_type not in ("list_reply", "button_reply"):
            logger.debug("Unhandled interactive reply type: %s", reply_type)
            return None

        reply = interactive.get(reply_type) or {}
        reply_id = reply.get("id")
        title = reply.get("title")
        if not reply_id or not title:
            return None

        return {"id": str(reply_id), "title": str(title), "type": reply_type}

    def _resolve_reply_context(self, message: Mapping[str, Any]) -> ReplyContext | None:
        context = message.get("context") or {}
        reply_to = context.get("message_id")
        if not reply_to:
            return None
        return ReplyContext(replied_to_message_id=str(reply_to))

    @staticmethod
    def _resolve_forwarding(message: Mapping[str, Any]) -> tuple[bool, bool]:
        """Whether Meta flagged this message as forwarded, and heavily so.

        Both flags live on the same `context` object as a reply's
        `message_id`, but they are independent: a forward carries
        `forwarded: true` with NO `message_id`, so it is never mistaken for a
        reply by `_resolve_reply_context` above.

        This matters because a forwarded report is second-hand -- the engineer
        is relaying a contractor's or supplier's message, not observing the
        work themselves. Recording it identically to a first-hand report is
        what makes an assistant feel careless, so the flag is carried through
        to the confirmation prompt (see canonicalization/builder.py).
        """
        context = message.get("context") or {}
        return bool(context.get("forwarded")), bool(context.get("frequently_forwarded"))
