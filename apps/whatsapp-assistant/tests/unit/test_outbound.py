"""Unit tests for the WhatsApp Cloud API outbound sender.

send_list's payload shape is verified against the Cloud API reference
(interactive.type="list", action.button, action.sections[].rows[]) --
these tests pin that shape rather than re-deriving it from memory.
"""

from __future__ import annotations

import json

import httpx
import pytest

from channel.replies import ListRow
from channel.whatsapp.outbound import WhatsAppSender


def _sender(captured: list[httpx.Request]) -> WhatsAppSender:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"messages": [{"id": "wamid.out.1"}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return WhatsAppSender(
        client=client,
        access_token="token",
        phone_number_id="PHONE_NUMBER_ID",
    )


@pytest.mark.asyncio
async def test_send_list_payload_matches_cloud_api_shape():
    captured: list[httpx.Request] = []
    sender = _sender(captured)

    ok = await sender.send_list(
        "919876543210",
        body="What are you reporting today?",
        button_label="Choose one",
        rows=[
            ListRow("cat_material", "Material", "Arrived or used on site"),
            ListRow("cat_expense", "Expense", "Petty cash spent"),
        ],
    )

    assert ok is True
    assert len(captured) == 1
    payload = json.loads(captured[0].content)
    assert payload["type"] == "interactive"
    assert payload["interactive"]["type"] == "list"
    assert payload["interactive"]["body"]["text"] == "What are you reporting today?"
    assert payload["interactive"]["action"]["button"] == "Choose one"
    rows = payload["interactive"]["action"]["sections"][0]["rows"]
    assert rows == [
        {"id": "cat_material", "title": "Material", "description": "Arrived or used on site"},
        {"id": "cat_expense", "title": "Expense", "description": "Petty cash spent"},
    ]


@pytest.mark.asyncio
async def test_send_list_truncates_fields_over_meta_limits():
    """Meta rejects (or silently truncates, with no reply reaching the user)
    rows over its published limits. Enforce them here instead."""
    captured: list[httpx.Request] = []
    sender = _sender(captured)

    await sender.send_list(
        "919876543210",
        body="body",
        button_label="X" * 30,  # over the 20-char button limit
        rows=[ListRow("r1", "Y" * 40, "Z" * 100)],  # over 24-char title, 72-char description
    )

    payload = json.loads(captured[0].content)
    assert payload["interactive"]["action"]["button"] == "X" * 20
    row = payload["interactive"]["action"]["sections"][0]["rows"][0]
    assert row["title"] == "Y" * 24
    assert row["description"] == "Z" * 72


@pytest.mark.asyncio
async def test_send_list_caps_at_ten_rows_total():
    captured: list[httpx.Request] = []
    sender = _sender(captured)

    await sender.send_list(
        "919876543210",
        body="body",
        button_label="Choose",
        rows=[ListRow(f"r{i}", f"Row {i}") for i in range(15)],
    )

    payload = json.loads(captured[0].content)
    assert len(payload["interactive"]["action"]["sections"][0]["rows"]) == 10


@pytest.mark.asyncio
async def test_send_list_with_no_rows_does_not_send():
    captured: list[httpx.Request] = []
    sender = _sender(captured)

    ok = await sender.send_list("919876543210", body="body", button_label="Choose", rows=[])

    assert ok is False
    assert captured == []


@pytest.mark.asyncio
async def test_send_text_still_sends_plain_text_shape():
    """send_list must not have disturbed the existing send_text behavior."""
    captured: list[httpx.Request] = []
    sender = _sender(captured)

    ok = await sender.send_text("919876543210", "Recorded. Thank you.")

    assert ok is True
    payload = json.loads(captured[0].content)
    assert payload["type"] == "text"
    assert payload["text"]["body"] == "Recorded. Thank you."


# --- #11 Reply Workflow: wamid capture -------------------------------------


@pytest.mark.asyncio
async def test_send_text_capturing_id_returns_metas_wamid():
    captured: list[httpx.Request] = []
    sender = _sender(captured)

    wamid = await sender.send_text_capturing_id("919876543210", "Recorded. Thank you.")

    assert wamid == "wamid.out.1"


@pytest.mark.asyncio
async def test_send_text_still_returns_bool_true_on_success():
    """send_text's own contract (bool) must be unchanged now that _send
    returns str | None internally."""
    captured: list[httpx.Request] = []
    sender = _sender(captured)

    result = await sender.send_text("919876543210", "hi")
    assert result is True
    assert isinstance(result, bool)


@pytest.mark.asyncio
async def test_send_text_capturing_id_returns_none_on_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="server error")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    sender = WhatsAppSender(client=client, access_token="token", phone_number_id="PHONE_NUMBER_ID")

    wamid = await sender.send_text_capturing_id("919876543210", "hi")
    assert wamid is None


@pytest.mark.asyncio
async def test_send_text_capturing_id_returns_none_when_disabled():
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})))
    sender = WhatsAppSender(client=client, access_token="", phone_number_id="")

    wamid = await sender.send_text_capturing_id("919876543210", "hi")
    assert wamid is None


@pytest.mark.asyncio
async def test_send_text_capturing_id_degrades_to_none_on_malformed_response():
    """Meta responding 200 with no parseable messages[0].id must not raise --
    the send itself succeeded, there's just nothing to record for later
    reply resolution."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"messaging_product": "whatsapp"})  # no "messages" key

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    sender = WhatsAppSender(client=client, access_token="token", phone_number_id="PHONE_NUMBER_ID")

    wamid = await sender.send_text_capturing_id("919876543210", "hi")
    assert wamid is None


@pytest.mark.asyncio
async def test_send_list_and_send_button_bool_contract_unchanged_by_str_refactor():
    """send_list/send_button return bool, not the raw _send result -- pins
    the (await self._send(...)) is not None wrapping added alongside
    send_text_capturing_id."""
    captured: list[httpx.Request] = []
    sender = _sender(captured)

    result = await sender.send_list(
        "919876543210", body="b", button_label="Choose", rows=[ListRow("r1", "Row 1")]
    )
    assert result is True
    assert isinstance(result, bool)


def _two_step_sender(requests: list[httpx.Request]) -> WhatsAppSender:
    """Distinguishes the media-upload POST from the message-send POST by
    path, mirroring the Cloud API's actual two-call shape (see send_image/
    send_document's docstrings)."""

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/media"):
            return httpx.Response(200, json={"id": "media-123"})
        return httpx.Response(200, json={"messages": [{"id": "wamid.out.1"}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return WhatsAppSender(client=client, access_token="token", phone_number_id="PHONE_NUMBER_ID")


@pytest.mark.asyncio
async def test_send_document_uploads_then_references_the_media_id():
    """#16 Daily Report Generation's PDF delivery -- same two-call shape as
    send_image, but type=document with a filename Meta requires."""
    requests: list[httpx.Request] = []
    sender = _two_step_sender(requests)

    ok = await sender.send_document(
        "919876543210", b"%PDF-1.4 fake", filename="DPR-20260727.pdf", caption="Today's DPR"
    )

    assert ok is True
    assert len(requests) == 2
    assert requests[0].url.path.endswith("/media")
    assert requests[1].url.path.endswith("/messages")
    payload = json.loads(requests[1].content)
    assert payload["type"] == "document"
    assert payload["document"] == {
        "id": "media-123",
        "filename": "DPR-20260727.pdf",
        "caption": "Today's DPR",
    }


@pytest.mark.asyncio
async def test_send_document_uses_pdf_filename_for_the_upload_multipart():
    """The upload step's multipart filename must be the real one, not a
    hardcoded receipt.png -- Meta/downstream viewers use it for the
    document's display name."""
    requests: list[httpx.Request] = []
    sender = _two_step_sender(requests)

    await sender.send_document("919876543210", b"%PDF-1.4 fake", filename="DPR-20260727.pdf")

    assert b"DPR-20260727.pdf" in requests[0].content


@pytest.mark.asyncio
async def test_send_document_degrades_to_false_when_upload_fails():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="server error")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    sender = WhatsAppSender(client=client, access_token="token", phone_number_id="PHONE_NUMBER_ID")

    ok = await sender.send_document("919876543210", b"%PDF-1.4", filename="x.pdf")
    assert ok is False


@pytest.mark.asyncio
async def test_send_image_still_uploads_with_its_own_filename():
    """Pins send_image's behavior unchanged by _upload_media's new filename
    parameter -- it must still upload as receipt.png."""
    requests: list[httpx.Request] = []
    sender = _two_step_sender(requests)

    ok = await sender.send_image("919876543210", b"\x89PNG fake", caption="Saved")

    assert ok is True
    assert b"receipt.png" in requests[0].content
    payload = json.loads(requests[1].content)
    assert payload["type"] == "image"
    assert payload["image"] == {"id": "media-123", "caption": "Saved"}


@pytest.mark.asyncio
async def test_receipt_is_sent_as_an_interactive_message_with_an_image_header(caplog):
    """The receipt card must ride as header.type=image with the uploaded media
    id, and receipt.sent logs that id (request [53])."""
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if request.url.path.endswith("/media"):
            return httpx.Response(200, json={"id": "MEDIA-42"})
        return httpx.Response(200, json={"messages": [{"id": "wamid.out.2"}]})

    sender = WhatsAppSender(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        access_token="token",
        phone_number_id="PHONE_NUMBER_ID",
    )

    with caplog.at_level("INFO"):
        ok = await sender.send_button(
            "919876543210",
            body="Saved",
            buttons=[ListRow("save_undo", "Undo")],
            header_image=b"\x89PNG-bytes",
        )

    assert ok is True
    # The last request is the pin experiment; the card is the one before it.
    payload = json.loads(captured[-2].content)
    assert payload["type"] == "interactive"
    assert payload["interactive"]["header"] == {"type": "image", "image": {"id": "MEDIA-42"}}
    assert "receipt.sent as=header media_id=MEDIA-42" in caplog.text


async def test_a_prepared_image_is_not_uploaded_again_by_the_send():
    """B-7: prepare_image uploads ahead; the send reuses the media id."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("/media"):
            return httpx.Response(200, json={"id": "MEDIA1"})
        return httpx.Response(200, json={"messages": [{"id": "wamid.1"}]})

    sender = WhatsAppSender(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        access_token="t",
        phone_number_id="P",
    )
    await sender.prepare_image(b"png-bytes")
    sent = await sender.send_button(
        "91", body="Saved", buttons=[ListRow(id="u", title="Undo")], header_image=b"png-bytes"
    )
    assert sent is True
    assert sum(p.endswith("/media") for p in calls) == 1


@pytest.mark.asyncio
async def test_receipt_image_is_followed_by_a_pin_attempt_that_never_fails_the_send():
    """EXPERIMENT: a pin is tried after the receipt image; Meta rejecting it
    (pin is group-only in the docs) must not fail the image send."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/media"):
            return httpx.Response(200, json={"id": "media-1"})
        if json.loads(request.content).get("type") == "pin":
            return httpx.Response(422, json={"error": {"code": 131009, "message": "not a group"}})
        return httpx.Response(200, json={"messages": [{"id": "wamid.img.1"}]})

    sender = WhatsAppSender(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        access_token="token",
        phone_number_id="PHONE_NUMBER_ID",
    )

    assert await sender.send_image("919876543210", b"png") is True
    pin = json.loads(requests[-1].content)
    assert pin["type"] == "pin"
    assert pin["pin"] == {"type": "pin", "message_id": "wamid.img.1", "expiration_days": 1}
