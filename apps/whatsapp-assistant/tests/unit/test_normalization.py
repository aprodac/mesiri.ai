"""Unit tests for Meta payload normalization."""

from __future__ import annotations

from datetime import UTC, datetime

from ingress.normalization import MessageNormalizer
from mesiri_contracts.assistant import MediaReference
from mesiri_contracts.assistant.enums import InputModality


def test_normalize_text_message() -> None:
    normalizer = MessageNormalizer()
    message = {
        "from": "919876543210",
        "id": "wamid.text",
        "timestamp": "1710000000",
        "type": "text",
        "text": {"body": "Installed 20 bags of cement"},
    }
    contacts = [{"wa_id": "919876543210", "profile": {"name": "Site Engineer"}}]

    normalized = normalizer.normalize(
        message,
        contacts=contacts,
        phone_number_id="PHONE_NUMBER_ID",
        display_phone_number="15550001111",
    )

    assert normalized.message_id == "wamid.text"
    assert normalized.channel == "whatsapp"
    assert normalized.modality is InputModality.TEXT
    assert normalized.text == "Installed 20 bags of cement"
    assert normalized.sender.profile_name == "Site Engineer"
    assert normalized.timestamp == datetime.fromtimestamp(1710000000, tz=UTC)


def test_normalize_image_message_with_media_reference() -> None:
    normalizer = MessageNormalizer()
    message = {
        "from": "919876543210",
        "id": "wamid.image",
        "timestamp": "1710000001",
        "type": "image",
        "image": {
            "id": "media-image-1",
            "mime_type": "image/jpeg",
            "caption": "Delivery challan",
        },
    }
    media = MediaReference(
        object_key="media/wamid.image/media-image-1",
        mime_type="image/jpeg",
        size_bytes=1024,
    )

    normalized = normalizer.normalize(
        message,
        contacts=[],
        phone_number_id="PHONE_NUMBER_ID",
        display_phone_number="15550001111",
        media=media,
    )

    assert normalized.modality is InputModality.IMAGE
    assert normalized.text == "Delivery challan"
    assert normalized.media is not None
    assert normalized.media.object_key == "media/wamid.image/media-image-1"


def test_normalize_voice_message() -> None:
    normalizer = MessageNormalizer()
    message = {
        "from": "919876543210",
        "id": "wamid.voice",
        "timestamp": "1710000002",
        "type": "audio",
        "audio": {
            "id": "media-audio-1",
            "mime_type": "audio/ogg; codecs=opus",
            "voice": True,
        },
    }
    media = MediaReference(
        object_key="media/wamid.voice/media-audio-1",
        mime_type="audio/ogg",
        size_bytes=2048,
    )

    normalized = normalizer.normalize(
        message,
        contacts=[],
        phone_number_id="PHONE_NUMBER_ID",
        display_phone_number="15550001111",
        media=media,
    )

    assert normalized.modality is InputModality.VOICE
    assert normalized.media is not None
    assert normalized.media.object_key == "media/wamid.voice/media-audio-1"


def test_normalize_list_reply_carries_selected_row_into_text_and_metadata() -> None:
    """Payload shape verified against the Cloud API reference: interactive.type
    is "list_reply", nested under interactive.list_reply.{id,title,description}."""
    normalizer = MessageNormalizer()
    message = {
        "from": "919876543210",
        "id": "wamid.interactive",
        "timestamp": "1710000002",
        "type": "interactive",
        "interactive": {
            "type": "list_reply",
            "list_reply": {
                "id": "cat_material",
                "title": "Material",
                "description": "Arrived or used on site",
            },
        },
    }

    normalized = normalizer.normalize(
        message,
        contacts=[],
        phone_number_id="PHONE_NUMBER_ID",
        display_phone_number="15550001111",
    )

    assert normalized.modality is InputModality.INTERACTIVE
    assert normalized.text == "Material"
    assert normalized.metadata["interactive_reply_id"] == "cat_material"
    assert normalized.metadata["interactive_reply_type"] == "list_reply"


def test_normalize_button_reply_uses_the_same_shape_as_list_reply() -> None:
    normalizer = MessageNormalizer()
    message = {
        "from": "919876543210",
        "id": "wamid.button",
        "timestamp": "1710000003",
        "type": "interactive",
        "interactive": {
            "type": "button_reply",
            "button_reply": {"id": "btn_cancel", "title": "Cancel this report"},
        },
    }

    normalized = normalizer.normalize(
        message,
        contacts=[],
        phone_number_id="PHONE_NUMBER_ID",
        display_phone_number="15550001111",
    )

    assert normalized.text == "Cancel this report"
    assert normalized.metadata["interactive_reply_id"] == "btn_cancel"
    assert normalized.metadata["interactive_reply_type"] == "button_reply"


def test_normalize_template_quick_reply_carries_its_payload() -> None:
    """WA-04: a tap on a template's quick-reply button arrives as
    `type: "button"`; it reads like any other menu tap, id = the payload."""
    normalizer = MessageNormalizer()
    message = {
        "from": "919876543210",
        "id": "wamid.template_tap",
        "timestamp": "1710000005",
        "type": "button",
        "button": {"payload": "sdr:open:site-1:20261015", "text": "Open report"},
    }

    normalized = normalizer.normalize(
        message,
        contacts=[],
        phone_number_id="PHONE_NUMBER_ID",
        display_phone_number="15550001111",
    )

    assert normalized.modality is InputModality.INTERACTIVE
    assert normalized.text == "Open report"
    assert normalized.metadata["interactive_reply_id"] == "sdr:open:site-1:20261015"
    assert normalized.metadata["interactive_reply_type"] == "template_button"


def test_normalize_unrecognized_interactive_subtype_does_not_raise() -> None:
    """A WhatsApp Flow's nfm_reply (Mesiri doesn't send Flows) or any other
    unrecognized interactive subtype must not drop the message -- it
    normalizes with no text/selection rather than raising."""
    normalizer = MessageNormalizer()
    message = {
        "from": "919876543210",
        "id": "wamid.flow",
        "timestamp": "1710000004",
        "type": "interactive",
        "interactive": {"type": "nfm_reply", "nfm_reply": {"response_json": "{}"}},
    }

    normalized = normalizer.normalize(
        message,
        contacts=[],
        phone_number_id="PHONE_NUMBER_ID",
        display_phone_number="15550001111",
    )

    assert normalized.modality is InputModality.INTERACTIVE
    assert normalized.text is None
    assert "interactive_reply_id" not in normalized.metadata
