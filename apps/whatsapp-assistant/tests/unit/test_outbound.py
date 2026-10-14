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


# --- WA-14: image headers, link buttons --------------------------------------


@pytest.mark.asyncio
async def test_send_image_uploads_with_the_given_filename():
    requests: list[httpx.Request] = []
    sender = _two_step_sender(requests)

    await sender.send_image("919876543210", b"\x89PNG fake", filename="card.png")

    assert b"card.png" in requests[0].content
    assert b"receipt.png" not in requests[0].content


@pytest.mark.asyncio
async def test_send_button_with_header_image_is_one_message_with_an_image_header():
    """Card + next-step buttons arrive as ONE message: the image is uploaded,
    then referenced as the reply-button message's header (Cloud API:
    interactive.header = {type: image, image: {id}})."""
    requests: list[httpx.Request] = []
    sender = _two_step_sender(requests)

    ok = await sender.send_button(
        "919876543210",
        body="14 materials on site.",
        buttons=[ListRow("pdf_full", "Full list (PDF)"), ListRow("low", "Low stock only")],
        header_image=b"\x89PNG fake",
    )

    assert ok is True
    assert [r.url.path.rsplit("/", 1)[-1] for r in requests] == ["media", "messages"]
    assert b"card.png" in requests[0].content
    interactive = json.loads(requests[1].content)["interactive"]
    assert interactive["type"] == "button"
    assert interactive["header"] == {"type": "image", "image": {"id": "media-123"}}
    assert interactive["body"] == {"text": "14 materials on site."}
    assert [b["reply"]["id"] for b in interactive["action"]["buttons"]] == ["pdf_full", "low"]


@pytest.mark.asyncio
async def test_send_button_without_header_image_makes_no_upload_and_has_no_header():
    captured: list[httpx.Request] = []
    sender = _sender(captured)

    await sender.send_button("919876543210", body="Confirm?", buttons=[ListRow("y", "Yes")])

    assert len(captured) == 1
    assert "header" not in json.loads(captured[0].content)["interactive"]


@pytest.mark.asyncio
async def test_send_button_still_sends_the_buttons_when_the_header_upload_fails():
    """The body carries the answer; a failed image upload must not lose the
    message."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/media"):
            return httpx.Response(500, text="upload broke")
        return httpx.Response(200, json={"messages": [{"id": "wamid.out.1"}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    sender = WhatsAppSender(client=client, access_token="token", phone_number_id="PHONE_NUMBER_ID")

    ok = await sender.send_button(
        "919876543210", body="Answer", buttons=[ListRow("y", "Yes")], header_image=b"png"
    )

    assert ok is True
    interactive = json.loads(requests[-1].content)["interactive"]
    assert "header" not in interactive


@pytest.mark.asyncio
async def test_send_cta_url_payload_matches_cloud_api_shape():
    captured: list[httpx.Request] = []
    sender = _sender(captured)

    ok = await sender.send_cta_url(
        "919876543210",
        body="Today's DPR is ready.",
        label="Open on dashboard",
        url="https://app.whatsapp.mesiri.ai/dpr/123",
    )

    assert ok is True
    payload = json.loads(captured[0].content)
    assert payload["type"] == "interactive"
    assert payload["interactive"] == {
        "type": "cta_url",
        "body": {"text": "Today's DPR is ready."},
        "action": {
            "name": "cta_url",
            "parameters": {
                "display_text": "Open on dashboard",
                "url": "https://app.whatsapp.mesiri.ai/dpr/123",
            },
        },
    }


@pytest.mark.asyncio
async def test_send_cta_url_truncates_label_to_twenty_chars():
    captured: list[httpx.Request] = []
    sender = _sender(captured)

    await sender.send_cta_url("919876543210", body="b", label="X" * 30, url="https://e.x")

    params = json.loads(captured[0].content)["interactive"]["action"]["parameters"]
    assert params["display_text"] == "X" * 20


@pytest.mark.asyncio
async def test_send_cta_url_with_header_image():
    requests: list[httpx.Request] = []
    sender = _two_step_sender(requests)

    await sender.send_cta_url(
        "919876543210", body="b", label="Open", url="https://e.x", header_image=b"png"
    )

    interactive = json.loads(requests[1].content)["interactive"]
    assert interactive["header"] == {"type": "image", "image": {"id": "media-123"}}
