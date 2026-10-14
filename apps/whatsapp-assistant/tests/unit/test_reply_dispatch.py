"""runtime/reply_dispatch.py -- shape dispatch and the #11 Reply Workflow
return-value passthrough (only the plain-text branch ever returns a wamid)."""

from __future__ import annotations

from channel.replies import ListRow, ReplySpec
from runtime.reply_dispatch import send_reply_spec


class _Recorder:
    def __init__(self, result):
        self._result = result
        self.calls: list[tuple] = []

    async def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self._result


async def test_plain_text_reply_returns_whatever_send_text_returned():
    send_text = _Recorder("wamid.123")
    reply = ReplySpec(text="Recorded. Thank you.")

    result = await send_reply_spec(reply, "919876543210", send_text=send_text)

    assert result == "wamid.123"
    assert len(send_text.calls) == 1


async def test_button_reply_returns_send_buttons_result_not_a_wamid():
    send_button = _Recorder(True)  # send_button's real contract is bool
    send_text = _Recorder("should_not_be_called")
    reply = ReplySpec(text="Confirm?", buttons=(ListRow("yes", "YES"), ListRow("no", "NO")))

    result = await send_reply_spec(
        reply, "919876543210", send_text=send_text, send_button=send_button
    )

    assert result is True
    assert send_text.calls == []


async def test_button_reply_falls_back_to_text_when_no_send_button_provided():
    send_text = _Recorder(True)
    reply = ReplySpec(text="Confirm?", buttons=(ListRow("yes", "YES"), ListRow("no", "NO")))

    result = await send_reply_spec(reply, "919876543210", send_text=send_text)

    assert result is True
    assert len(send_text.calls) == 1
    body = send_text.calls[0][0][1]
    assert "YES" in body and "NO" in body


async def test_list_reply_returns_send_list_result_not_a_wamid():
    send_list = _Recorder(True)
    send_text = _Recorder("should_not_be_called")
    reply = ReplySpec(text="Pick one", list_rows=(ListRow("a", "Option A"),))

    result = await send_reply_spec(
        reply, "919876543210", send_text=send_text, send_list=send_list
    )

    assert result is True
    assert send_text.calls == []


async def test_list_reply_falls_back_to_text_when_no_send_list_provided():
    send_text = _Recorder(True)
    reply = ReplySpec(text="Pick one", list_rows=(ListRow("a", "Option A"),))

    result = await send_reply_spec(reply, "919876543210", send_text=send_text)

    assert result is True
    body = send_text.calls[0][0][1]
    assert "Option A" in body


# --- WA-14: media and links ---------------------------------------------------

from channel.replies import CtaLink, ReplyDocument  # noqa: E402

_PNG = b"\x89PNG card"
_BUTTONS = (ListRow("pdf_full", "Full list (PDF)"), ListRow("low", "Low stock only"))


async def test_image_with_buttons_is_one_button_message_with_image_header():
    send_button = _Recorder(True)
    send_image = _Recorder(True)
    send_text = _Recorder("unused")
    reply = ReplySpec(text="14 materials on site.", buttons=_BUTTONS, image=_PNG)

    result = await send_reply_spec(
        reply, "91", send_text=send_text, send_button=send_button, send_image=send_image
    )

    assert result is True
    assert send_image.calls == [] and send_text.calls == []
    assert len(send_button.calls) == 1
    assert send_button.calls[0][1]["header_image"] == _PNG
    assert send_button.calls[0][1]["buttons"] == _BUTTONS


async def test_image_alone_goes_with_the_text_as_its_caption():
    send_image = _Recorder(True)
    send_text = _Recorder("unused")
    reply = ReplySpec(text="Stock at Block A", image=_PNG)

    await send_reply_spec(reply, "91", send_text=send_text, send_image=send_image)

    assert send_text.calls == []
    args, kwargs = send_image.calls[0]
    assert args == ("91", _PNG)
    assert kwargs["caption"] == "Stock at Block A"


async def test_image_with_list_is_image_first_then_the_list():
    order: list[str] = []

    async def send_image(*args, **kwargs):
        order.append("image")
        assert "caption" not in kwargs
        return True

    async def send_list(*args, **kwargs):
        order.append("list")
        return True

    reply = ReplySpec(text="Pick a material", list_rows=(ListRow("a", "Cement"),), image=_PNG)

    await send_reply_spec(
        reply, "91", send_text=_Recorder("x"), send_list=send_list, send_image=send_image
    )

    assert order == ["image", "list"]


async def test_text_over_the_caption_limit_sends_image_separately_then_the_buttons():
    send_button = _Recorder(True)
    send_image = _Recorder(True)
    reply = ReplySpec(text="x" * 1025, buttons=_BUTTONS, image=_PNG)

    await send_reply_spec(
        reply, "91", send_text=_Recorder("x"), send_button=send_button, send_image=send_image
    )

    assert len(send_image.calls) == 1 and "caption" not in send_image.calls[0][1]
    assert "header_image" not in send_button.calls[0][1]


async def test_failed_merged_message_falls_back_to_plain_buttons():
    calls: list[dict] = []

    async def send_button(*args, **kwargs):
        calls.append(kwargs)
        return "header_image" not in kwargs  # the merged form fails

    reply = ReplySpec(text="Answer", buttons=_BUTTONS, image=_PNG)

    result = await send_reply_spec(reply, "91", send_text=_Recorder("x"), send_button=send_button)

    assert result is True
    assert len(calls) == 2
    assert "header_image" in calls[0] and "header_image" not in calls[1]


async def test_failed_captioned_image_falls_back_to_text():
    send_image = _Recorder(False)
    send_text = _Recorder("wamid.9")
    reply = ReplySpec(text="Stock at Block A", image=_PNG)

    result = await send_reply_spec(reply, "91", send_text=send_text, send_image=send_image)

    assert result == "wamid.9"
    assert send_text.calls[0][0] == ("91", "Stock at Block A")


async def test_image_is_dropped_not_lost_when_no_image_sender_is_wired():
    """Callers that only wire text (most fast paths) still deliver the
    answer: the text carries it by contract."""
    send_text = _Recorder("wamid.1")
    reply = ReplySpec(text="Stock at Block A", image=_PNG)

    result = await send_reply_spec(reply, "91", send_text=send_text)

    assert result == "wamid.1"
    assert send_text.calls[0][0] == ("91", "Stock at Block A")


async def test_document_is_sent_before_the_text():
    order: list[str] = []

    async def send_document(wa_id, data, *, filename, mime_type):
        order.append(f"doc:{filename}:{mime_type}")
        return True

    async def send_text(wa_id, body):
        order.append("text")
        return "wamid.2"

    reply = ReplySpec(text="All 47 items attached.", document=ReplyDocument(b"%PDF", "Stock.pdf"))

    result = await send_reply_spec(reply, "91", send_text=send_text, send_document=send_document)

    assert order == ["doc:Stock.pdf:application/pdf", "text"]
    assert result == "wamid.2"


async def test_document_without_a_document_sender_still_sends_the_text():
    send_text = _Recorder("wamid.3")
    reply = ReplySpec(text="Here it is", document=ReplyDocument(b"%PDF", "x.pdf"))

    await send_reply_spec(reply, "91", send_text=send_text)

    assert len(send_text.calls) == 1


async def test_cta_uses_the_link_button_sender():
    send_cta = _Recorder(True)
    reply = ReplySpec(text="DPR ready", cta=CtaLink("Open DPR", "https://e.x/dpr"))

    result = await send_reply_spec(reply, "91", send_text=_Recorder("x"), send_cta=send_cta)

    assert result is True
    assert send_cta.calls[0][1] == {"body": "DPR ready", "label": "Open DPR", "url": "https://e.x/dpr"}


async def test_cta_falls_back_to_text_with_the_url():
    send_text = _Recorder("wamid.4")
    reply = ReplySpec(text="DPR ready", cta=CtaLink("Open DPR", "https://e.x/dpr"))

    await send_reply_spec(reply, "91", send_text=send_text)

    assert send_text.calls[0][0][1] == "DPR ready\n\nOpen DPR: https://e.x/dpr"


async def test_image_with_cta_is_one_link_message_with_image_header():
    send_cta = _Recorder(True)
    send_image = _Recorder(True)
    reply = ReplySpec(text="DPR ready", cta=CtaLink("Open", "https://e.x"), image=_PNG)

    await send_reply_spec(
        reply, "91", send_text=_Recorder("x"), send_cta=send_cta, send_image=send_image
    )

    assert send_image.calls == []
    assert send_cta.calls[0][1]["header_image"] == _PNG
