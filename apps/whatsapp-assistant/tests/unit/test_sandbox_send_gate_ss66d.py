"""SS-66d: a send started while handling a learning-sandbox request never reaches WhatsApp; the same send from a real
company's request still goes out (the guard). The mark comes from the request's token (the ``sandbox`` claim)."""

from __future__ import annotations

import asyncio
import datetime as dt

import httpx
import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from channel.whatsapp.outbound import WhatsAppSender
from mesiri.domains.identity.auth_service import ALGORITHM, SECRET_KEY
from mesiri.domains.shared import sandbox_gate


def _token(**extra) -> str:  # noqa: ANN003
    claims = {"sub": "u", "org": "o", "role": "ADMIN", "exp": dt.datetime.now(dt.UTC) + dt.timedelta(hours=1), **extra}
    return jwt.encode(claims, SECRET_KEY, algorithm=ALGORITHM)


def _app(posted: list) -> FastAPI:
    def meta(request: httpx.Request) -> httpx.Response:
        posted.append(request.url.path)
        return httpx.Response(200, json={"messages": [{"id": "wamid.1"}]})

    sender = WhatsAppSender(client=httpx.AsyncClient(transport=httpx.MockTransport(meta)), access_token="t",
                            phone_number_id="1")
    app = FastAPI()
    app.middleware("http")(sandbox_gate.sandbox_gate_middleware)

    @app.post("/approve")
    async def approve() -> dict:
        # A send started by the request, and one from a task it starts (tasks inherit the mark).
        first = await sender.send_text("919800000001", "Your request was approved")
        second = await asyncio.create_task(sender.send_text("919800000001", "And again"))
        return {"sent": [first, second]}

    return app


@pytest.mark.parametrize(("claims", "sent"), [({"sandbox": "real-company"}, False), ({}, True)])
def test_sandbox_request_sends_nothing_real_request_sends(claims, sent) -> None:  # noqa: ANN001
    posted: list = []
    out = TestClient(_app(posted)).post("/approve", headers={"Authorization": f"Bearer {_token(**claims)}"})
    assert out.json() == {"sent": [sent, sent]}
    assert bool(posted) is sent


def test_the_mark_ends_with_the_request() -> None:
    posted: list = []
    TestClient(_app(posted)).post("/approve", headers={"Authorization": f"Bearer {_token(sandbox='x')}"})
    assert sandbox_gate.sending_blocked() is False


@pytest.mark.parametrize("header", [None, "Bearer not-a-token", "Basic abc"])
def test_no_or_bad_token_is_not_a_sandbox(header) -> None:  # noqa: ANN001
    assert sandbox_gate.is_sandbox_token(header) is False
