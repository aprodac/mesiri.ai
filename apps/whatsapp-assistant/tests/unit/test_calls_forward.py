"""WA-118 step 1: `calls` events reach the spike only when asked, and nothing else changes."""

from __future__ import annotations

import asyncio

import httpx
import pytest
from tests.conftest import sign_payload
from tests.fixtures.meta_payloads import text_webhook_payload

from ingress.calls_forward import has_calls_change

SPIKE = "http://127.0.0.1:8791/calls"


def calls_payload() -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [{"id": "1", "changes": [{"field": "calls", "value": {"calls": [{"id": "wacid.1", "event": "connect"}]}}]}],
    }


class Recorder:
    def __init__(self, *, fail: bool = False) -> None:
        self.sent: list[tuple[str, bytes, str]] = []
        self.fail = fail

    async def post(self, url, *, content, headers, timeout):
        if self.fail:
            raise httpx.ConnectError("spike is down")
        self.sent.append((url, content, headers["X-Hub-Signature-256"]))


async def post_signed(client, payload):
    signature, body = sign_payload(payload, "test-app-secret")
    response = await client.post(
        "/webhook",
        content=body,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": signature},
    )
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    return response, body, signature


def use_recorder(app, monkeypatch, recorder, url=SPIKE):
    container = app.state.container
    monkeypatch.setattr(container.settings, "calls_forward_url", url)
    monkeypatch.setattr(container, "http_client", recorder)


def test_has_calls_change() -> None:
    assert has_calls_change(calls_payload())
    assert not has_calls_change(text_webhook_payload())


@pytest.mark.asyncio
async def test_calls_event_is_forwarded_with_metas_body_and_signature(client, app, monkeypatch) -> None:
    recorder = Recorder()
    use_recorder(app, monkeypatch, recorder)

    response, body, signature = await post_signed(client, calls_payload())

    assert response.status_code == 200
    assert recorder.sent == [(SPIKE, body, signature)]


@pytest.mark.asyncio
async def test_nothing_is_forwarded_when_the_setting_is_empty(client, app, monkeypatch) -> None:
    recorder = Recorder()
    use_recorder(app, monkeypatch, recorder, url="")

    response, _, _ = await post_signed(client, calls_payload())

    assert response.status_code == 200
    assert recorder.sent == []


@pytest.mark.asyncio
async def test_a_message_is_never_forwarded_and_still_handled(client, app, monkeypatch) -> None:
    recorder = Recorder()
    use_recorder(app, monkeypatch, recorder)

    response, _, _ = await post_signed(client, text_webhook_payload())

    assert response.status_code == 200
    assert recorder.sent == []
    container = app.state.container
    await container.receiver.wait_until_idle()
    assert await container.message_store.get("wamid.text") is not None


@pytest.mark.asyncio
async def test_a_dead_spike_does_not_fail_the_webhook(client, app, monkeypatch) -> None:
    use_recorder(app, monkeypatch, Recorder(fail=True))

    response, _, _ = await post_signed(client, calls_payload())

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_a_bad_signature_is_not_forwarded(client, app, monkeypatch) -> None:
    recorder = Recorder()
    use_recorder(app, monkeypatch, recorder)
    _, body = sign_payload(calls_payload(), "test-app-secret")

    response = await client.post(
        "/webhook",
        content=body,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": "sha256=invalid"},
    )

    assert response.status_code == 403
    assert recorder.sent == []
