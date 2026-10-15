"""BE-25: every sent WhatsApp message, and Meta's pricing for it, reaches
the cost recorder."""

from __future__ import annotations

import httpx
import pytest

from channel.whatsapp import usage as message_usage
from channel.whatsapp.outbound import WhatsAppSender


class _Sink:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.priced: list[dict] = []

    async def record_whatsapp_sent(self, **kwargs) -> None:
        self.sent.append(kwargs)

    async def record_whatsapp_pricing(self, **kwargs) -> None:
        self.priced.append(kwargs)


@pytest.fixture
def sink():
    s = _Sink()
    message_usage.set_sink(s)
    yield s
    message_usage.set_sink(None)


def _sender(status: int = 200) -> WhatsAppSender:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"messages": [{"id": "wamid.1"}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return WhatsAppSender(client=client, access_token="token", phone_number_id="PNID")


def test_category_estimate() -> None:
    assert message_usage.category_for({"type": "text"}) == "service"
    assert message_usage.category_for({"type": "interactive"}) == "service"
    assert (
        message_usage.category_for(
            {"type": "template", "template": {"name": "mesiri_login_code"}}
        )
        == "authentication"
    )
    assert (
        message_usage.category_for(
            {"type": "template", "template": {"name": "mesiri_dpr_delivery"}}
        )
        == "utility"
    )


@pytest.mark.asyncio
async def test_a_sent_reply_is_reported_as_service(sink) -> None:
    assert await _sender().send_text("919876543210", "Saved: 40 bags cement")
    await message_usage.drain()
    assert sink.sent == [
        {
            "wamid": "wamid.1",
            "recipient": "919876543210",
            "category": "service",
            "operation": "send_text",
        }
    ]


@pytest.mark.asyncio
async def test_a_sent_template_is_reported_with_its_category(sink) -> None:
    await _sender().send_template(
        "919876543210", name="mesiri_login_code", language="en", body_params=("123456",)
    )
    await message_usage.drain()
    assert [(s["category"], s["operation"]) for s in sink.sent] == [
        ("authentication", "send_template")
    ]


@pytest.mark.asyncio
async def test_a_rejected_send_is_not_reported(sink) -> None:
    assert not await _sender(status=400).send_text("919876543210", "hi")
    await message_usage.drain()
    assert sink.sent == []


@pytest.mark.asyncio
async def test_meta_pricing_on_statuses_is_passed_on(sink) -> None:
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "statuses": [
                                {
                                    "id": "wamid.1",
                                    "status": "delivered",
                                    "recipient_id": "919876543210",
                                    "pricing": {
                                        "billable": False,
                                        "pricing_model": "PMP",
                                        "category": "service",
                                        "type": "free_customer_service",
                                    },
                                },
                                # No pricing (e.g. "read"): nothing to report.
                                {"id": "wamid.1", "status": "read"},
                            ]
                        },
                    }
                ]
            }
        ]
    }
    message_usage.report_pricing(payload)
    await message_usage.drain()
    assert sink.priced == [
        {
            "wamid": "wamid.1",
            "recipient": "919876543210",
            "category": "service",
            "billable": False,
        }
    ]


@pytest.mark.asyncio
async def test_no_sink_reports_nothing() -> None:
    message_usage.set_sink(None)
    assert await _sender().send_text("919876543210", "hi")
    message_usage.report_pricing({"entry": []})
