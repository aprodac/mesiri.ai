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


async def test_receipt_reply_goes_as_a_button_message_with_the_image_header():
    send_button = _Recorder(True)
    send_image = _Recorder(True)
    reply = ReplySpec(
        text="Saved",
        buttons=(ListRow("save_undo", "Undo"),),
        header_image=b"png-bytes",
    )

    await send_reply_spec(
        reply, "919876543210", send_text=_Recorder(True), send_button=send_button, send_image=send_image
    )

    assert send_button.calls[0][1]["header_image"] == b"png-bytes"
    assert send_image.calls == []  # not a second, separate image
