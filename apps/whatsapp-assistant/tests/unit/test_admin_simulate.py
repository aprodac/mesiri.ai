"""The control panel's test message (admin /simulate) runs the real message
handler with a capturing sender (ARCH-06): what the handler sends -- text,
buttons, a list -- comes back as the simulation's replies."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import admin.system_graph_router as sg
from channel.replies import ListRow
from mesiri.domains.shared.auth import require_platform_admin

ORG = uuid.uuid4()
USR = uuid.uuid4()


def _client(monkeypatch, handler_factory) -> TestClient:  # noqa: ANN001
    async def wa_id(org_id, user_id):  # noqa: ANN001
        return "919876543210"

    async def resolve(reader, wa):  # noqa: ANN001
        return SimpleNamespace(organization_id=ORG, org_active=True, user_id=str(USR), full_name="Ravi")

    monkeypatch.setattr(sg, "_lookup_user_wa_id", wa_id)
    monkeypatch.setattr("context.live_identity.resolve_sender", resolve)
    app = FastAPI()
    app.include_router(sg.router)
    app.dependency_overrides[require_platform_admin] = lambda: {"role": "PLATFORM_ADMIN"}
    app.state.container = SimpleNamespace(actor_reader=object(), simulate_handler=handler_factory)
    return TestClient(app)


def _body(text: str) -> dict:
    return {"organization_id": str(ORG), "user_id": str(USR), "text": text}


def test_the_real_handler_runs_and_its_replies_come_back(monkeypatch):
    seen: dict = {}

    def factory(sender):  # noqa: ANN001
        async def on_normalized(message, raw):  # noqa: ANN001
            seen["text"] = message.text
            await sender.mark_as_read("wamid")  # anything else the handler calls is quiet
            await sender.send_text(message.sender.wa_id, "Received or used?")
            await sender.send_button(
                message.sender.wa_id, body="Which one?", buttons=[ListRow("r", "Received"), ListRow("u", "Used")]
            )

        return on_normalized

    res = _client(monkeypatch, factory).post("/admin/system-graph/simulate", json=_body("50 bags cement"))
    assert res.status_code == 200, res.text
    data = res.json()
    assert seen["text"] == "50 bags cement"
    assert data["routed_via"] == "message_journey"
    assert data["replies"][0] == "Received or used?"
    assert [s["type"] for s in data["structured_replies"]] == ["text", "buttons"]
    assert [b["title"] for b in data["structured_replies"][1]["buttons"]] == ["Received", "Used"]


def test_a_handler_failure_is_shown_not_raised(monkeypatch):
    def factory(sender):  # noqa: ANN001
        async def on_normalized(message, raw):  # noqa: ANN001
            raise RuntimeError("model down")

        return on_normalized

    res = _client(monkeypatch, factory).post("/admin/system-graph/simulate", json=_body("hi"))
    assert res.status_code == 200
    assert res.json()["replies"] == ["[error: RuntimeError]"]


@pytest.mark.parametrize("handler", [None])
def test_without_the_handler_wired_it_says_so(monkeypatch, handler):
    res = _client(monkeypatch, handler).post("/admin/system-graph/simulate", json=_body("hi"))
    assert res.status_code == 503
