"""UX-26: Tell Mesiri in a sample company. Its person has no WhatsApp number (SS-66d), so they talk to Mesiri with a
sender id that names them and can never be a phone; the assistant's own API calls carry the sample's mark and date.

Guards: real numbers in every common spelling are never taken for a sample id; nothing is ever sent to a sample id,
even outside a sandbox request; a real request's assistant token carries no sample mark."""

from __future__ import annotations

import datetime as dt
import uuid

import httpx
import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_api.client import Actor, token_for
from channel.whatsapp.outbound import WhatsAppSender
from mesiri.domains.identity.auth_service import ALGORITHM, SECRET_KEY
from mesiri.domains.shared import sandbox_gate


def test_a_sample_id_names_its_person_and_is_never_a_phone() -> None:
    who = uuid.uuid4()
    wa = sandbox_gate.sample_sender_id(who)
    assert wa.isdigit() and wa.startswith("0000") and len(wa) == 43  # a phone has at most 15 digits
    assert sandbox_gate.sample_sender_user(wa) == who
    assert sandbox_gate.sample_sender_user(f"+{wa}") == who
    assert sandbox_gate.sample_sender_user(sandbox_gate.sample_sender_id(uuid.UUID(int=0))) == uuid.UUID(int=0)


@pytest.mark.parametrize("number", [
    "919876543210", "+91 98765 43210", "0091 98765 43210", "00919876543210", "098765 43210", "0000000000",
    "", None, "group:12345", "0000" + "9" * 39,  # too large for a user id
])
def test_real_numbers_are_never_a_sample_id(number) -> None:  # noqa: ANN001
    assert sandbox_gate.sample_sender_user(number) is None


def _sender(posted: list) -> WhatsAppSender:
    def meta(request: httpx.Request) -> httpx.Response:
        posted.append(request.url.path)
        return httpx.Response(200, json={"messages": [{"id": "wamid.1"}]})

    return WhatsAppSender(client=httpx.AsyncClient(transport=httpx.MockTransport(meta)), access_token="t",
                          phone_number_id="1")


async def test_nothing_is_ever_sent_to_a_sample_id_even_outside_a_sandbox_request() -> None:
    posted: list = []
    sender = _sender(posted)
    assert await sender.send_text(sandbox_gate.sample_sender_id(uuid.uuid4()), "hello") is False
    assert posted == []
    assert await sender.send_text("919800000001", "hello") is True  # the guard: a real number still goes
    assert len(posted) == 1


def _app(seen: list) -> FastAPI:
    app = FastAPI()
    app.middleware("http")(sandbox_gate.sandbox_gate_middleware)

    @app.post("/tell")
    async def tell() -> dict:
        token = token_for(Actor(user_id=str(uuid.uuid4()), organization_id=str(uuid.uuid4()), role="ADMIN"))
        claims = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        seen.append(claims)
        return {}

    return app


def _token(**extra) -> str:  # noqa: ANN003
    claims = {"sub": "u", "org": "o", "role": "ADMIN", "exp": dt.datetime.now(dt.UTC) + dt.timedelta(hours=1), **extra}
    return jwt.encode(claims, SECRET_KEY, algorithm=ALGORITHM)


def test_the_assistants_calls_carry_the_samples_mark_and_date() -> None:
    seen: list = []
    TestClient(_app(seen)).post("/tell", headers={"Authorization": f"Bearer {_token(sandbox='real-co', today='2026-11-14')}"})
    assert seen[0]["sandbox"] == "real-co" and seen[0]["today"] == "2026-11-14"
    assert sandbox_gate.current_sandbox() is None  # the mark ends with the request


def test_a_real_requests_assistant_token_has_no_sample_mark() -> None:
    seen: list = []
    TestClient(_app(seen)).post("/tell", headers={"Authorization": f"Bearer {_token()}"})
    assert "sandbox" not in seen[0] and "today" not in seen[0]
