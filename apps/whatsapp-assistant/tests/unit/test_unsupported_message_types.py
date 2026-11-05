"""Unit tests for message types Mesiri can't act on yet (PDF, video, sticker,
location pin, shared contact, music file).

Real problem this fixes: normalization raised on any type outside
text/image/voice-note/interactive. That exception aborted ingress inside
WhatsAppReceiver._process_message's catch-all, which logged a trace row and
returned -- with no reply ever sent. The sender got pure silence and no way
to tell "Mesiri can't read PDFs" from "Mesiri is down", so they couldn't
know whether their report had landed.

These messages now normalize to InputModality.UNKNOWN and the runtime
declines them politely, except for reactions and Meta system notices, which
are deliberately answered with nothing (see SILENTLY_IGNORED_RAW_TYPES).
"""

from __future__ import annotations

import pytest

from channel.replies import (
    SILENTLY_IGNORED_RAW_TYPES,
    render_unsupported_media_reply,
)
from ingress.normalization import MessageNormalizer
from mesiri_contracts.assistant.enums import InputModality


def _message(raw_type: str, **extra: object) -> dict:
    return {
        "from": "919876543210",
        "id": f"wamid.{raw_type}",
        "timestamp": "1710000000",
        "type": raw_type,
        **extra,
    }


def _normalize(message: dict):
    return MessageNormalizer().normalize(
        message,
        contacts=[{"wa_id": "919876543210", "profile": {"name": "Site Engineer"}}],
        phone_number_id="PHONE_NUMBER_ID",
        display_phone_number="15550001111",
    )


@pytest.mark.parametrize(
    ("raw_type", "payload"),
    [
        ("document", {"document": {"id": "media-doc-1", "mime_type": "application/pdf"}}),
        ("video", {"video": {"id": "media-vid-1", "mime_type": "video/mp4"}}),
        ("sticker", {"sticker": {"id": "media-stk-1"}}),
        ("location", {"location": {"latitude": 12.9, "longitude": 77.5}}),
        ("contacts", {"contacts": [{"name": {"formatted_name": "Ravi"}}]}),
        ("reaction", {"reaction": {"message_id": "wamid.prev", "emoji": "👍"}}),
    ],
)
def test_unsupported_types_normalize_instead_of_raising(raw_type: str, payload: dict) -> None:
    """The load-bearing assertion: none of these may raise. A raise here is
    what produced total silence for the sender."""
    normalized = _normalize(_message(raw_type, **payload))

    assert normalized.modality is InputModality.UNKNOWN
    assert normalized.message_id == f"wamid.{raw_type}"
    # raw_type must survive onto the normalized message -- it's the only
    # thing left that lets the decline reply name what was actually sent,
    # since every one of these collapses to the same UNKNOWN modality.
    assert normalized.metadata["raw_type"] == raw_type


def test_voice_note_still_normalizes_as_voice() -> None:
    """Guard against the fix swallowing real voice notes: audio.voice truthy
    is a voice note and must stay VOICE, not become UNKNOWN."""
    normalized = _normalize(
        _message("audio", audio={"id": "media-audio-1", "voice": True, "mime_type": "audio/ogg"})
    )
    assert normalized.modality is InputModality.VOICE


def test_music_file_is_unknown_not_voice() -> None:
    """A shared music file (audio.voice falsy) is not a voice note -- it must
    not be sent to speech-to-text as though it were."""
    normalized = _normalize(
        _message("audio", audio={"id": "media-audio-2", "voice": False, "mime_type": "audio/mpeg"})
    )
    assert normalized.modality is InputModality.UNKNOWN
    assert normalized.metadata["raw_type"] == "audio"


def test_text_and_image_are_unaffected() -> None:
    text = _normalize(_message("text", text={"body": "20 bags cement"}))
    assert text.modality is InputModality.TEXT
    assert text.text == "20 bags cement"

    image = _normalize(_message("image", image={"id": "m1", "caption": "challan"}))
    assert image.modality is InputModality.IMAGE


# ---------------------------------------------------------------------------
# The reply itself
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw_type", "expected_fragment"),
    [
        ("document", "documents or PDFs"),
        ("video", "videos"),
        ("sticker", "stickers"),
        ("location", "location pins"),
        ("contacts", "shared contacts"),
        ("audio", "audio file type"),
    ],
)
def test_decline_reply_names_the_actual_type(raw_type: str, expected_fragment: str) -> None:
    reply = render_unsupported_media_reply(raw_type)
    assert expected_fragment in reply


def test_decline_reply_falls_back_for_an_unrecognized_type() -> None:
    """Meta can introduce new types at any time -- an unmapped one must still
    produce a sensible reply rather than an empty or broken string."""
    reply = render_unsupported_media_reply("some_future_type")
    assert "this kind of message" in reply
    assert reply.strip()


def test_decline_reply_handles_missing_type() -> None:
    assert render_unsupported_media_reply(None).strip()


def test_decline_reply_always_offers_a_way_forward() -> None:
    """A decline that doesn't say what to do instead just moves the dead end
    -- every variant must name a concrete alternative."""
    for raw_type in ("document", "video", "sticker", "location", "contacts", None):
        reply = render_unsupported_media_reply(raw_type)
        assert "photo" in reply.lower()
        assert "voice note" in reply.lower()
        assert "type" in reply.lower()


def test_reactions_and_system_notices_are_silently_ignored() -> None:
    """Answering every 👍 on one of Mesiri's own replies with "I can't handle
    this" would be maddening -- these are dropped quietly on purpose."""
    assert "reaction" in SILENTLY_IGNORED_RAW_TYPES
    assert "system" in SILENTLY_IGNORED_RAW_TYPES
    # The types a user actually sent as content must NOT be in the ignore
    # set -- those are exactly the ones that need an answer.
    for raw_type in ("document", "video", "sticker", "location", "contacts", "audio"):
        assert raw_type not in SILENTLY_IGNORED_RAW_TYPES


# ---------------------------------------------------------------------------
# Ingress end-to-end: the message must survive the receiver, not abort it
# ---------------------------------------------------------------------------


def _document_webhook_payload() -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WABA_ID",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "15550001111",
                                "phone_number_id": "PHONE_NUMBER_ID",
                            },
                            "contacts": [
                                {"wa_id": "919876543210", "profile": {"name": "Site Engineer"}}
                            ],
                            "messages": [
                                {
                                    "from": "919876543210",
                                    "id": "wamid.doc",
                                    "timestamp": "1710000000",
                                    "type": "document",
                                    "document": {
                                        "id": "media-doc-1",
                                        "mime_type": "application/pdf",
                                        "filename": "invoice.pdf",
                                    },
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


@pytest.mark.asyncio
async def test_receiver_accepts_a_pdf_without_downloading_it() -> None:
    """The end-to-end guard for the reported bug: a PDF must reach the
    normalized-message store (so the runtime gets a chance to reply) rather
    than dying in ingress. It must also NOT be downloaded -- fetching a file
    we have no way to read would burn a Meta API call and storage for
    nothing.
    """
    from unittest.mock import AsyncMock

    from ingress.deduplication import InMemoryDeduplicationStore
    from ingress.receiver import InMemoryNormalizedMessageStore, WhatsAppReceiver
    from mesiri.infrastructure.objectstorage.fake import FakeObjectStorage

    message_store = InMemoryNormalizedMessageStore()
    media_downloader = AsyncMock()
    receiver = WhatsAppReceiver(
        deduplication_store=InMemoryDeduplicationStore(),
        media_downloader=media_downloader,
        message_store=message_store,
        object_storage=FakeObjectStorage(),
    )

    scheduled = await receiver.handle_payload(_document_webhook_payload())
    await receiver.wait_until_idle()

    assert scheduled == 1
    media_downloader.download.assert_not_called()

    normalized = await message_store.get("wamid.doc")
    assert normalized is not None, (
        "the PDF must survive ingress -- if it dies here the sender gets no reply at all"
    )
    assert normalized.modality is InputModality.UNKNOWN
    assert normalized.metadata["raw_type"] == "document"
    assert normalized.media is None


# -- [250] (5 Nov, Ilan): a forwarded voice note (audio, voice=false, Ogg/Opus) was refused, twice ----------------


def test_a_forwarded_voice_note_is_a_voice_note() -> None:
    normalized = _normalize(
        _message("audio", audio={"id": "m1", "voice": False, "mime_type": "audio/ogg; codecs=opus"})
    )
    assert normalized.modality is InputModality.VOICE


def test_an_ogg_audio_document_is_a_voice_note_and_a_pdf_is_not() -> None:
    from ingress.normalization import audio_media

    ogg = _message("document", document={"id": "d1", "mime_type": "audio/ogg", "filename": "site.ogg"})
    assert _normalize(ogg).modality is InputModality.VOICE
    assert audio_media(ogg) == {"id": "d1", "mime_type": "audio/ogg", "filename": "site.ogg"}
    pdf = _message("document", document={"id": "d2", "mime_type": "application/pdf"})
    assert _normalize(pdf).modality is InputModality.UNKNOWN and audio_media(pdf) is None


def test_an_audio_decline_never_asks_for_the_audio_they_just_sent() -> None:
    reply = render_unsupported_media_reply("audio")
    assert "mic button" in reply and "Send it one of these ways" not in reply


async def test_the_receiver_downloads_a_forwarded_voice_note() -> None:
    from types import SimpleNamespace

    from ingress.receiver import WhatsAppReceiver

    asked: list[str] = []

    async def download(media_id: str):  # noqa: ANN202
        asked.append(media_id)
        return SimpleNamespace(id=media_id)

    receiver = WhatsAppReceiver.__new__(WhatsAppReceiver)
    receiver._media_downloader = SimpleNamespace(download=download)
    message = {"type": "audio", "audio": {"id": "m9", "voice": False, "mime_type": "audio/ogg; codecs=opus"}}
    await receiver._download_media_if_required(message)
    await receiver._download_media_if_required({"type": "audio", "audio": {"id": "mp3", "mime_type": "audio/mpeg"}})
    assert asked == ["m9"]
