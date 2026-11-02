"""TM-33: the "Is this how you want it?" preview route. It lets the team bot message a customer, so every guard is
tested: off by default, the bot's token only, a real PNG, the recipient read from the request itself, v3 companies
only, the 24-hour window, once per request."""

from __future__ import annotations

import base64
import datetime as dt
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mesiri.infrastructure.redis.client import FakeRedis
from runtime import previews

TOKEN = "k" * 40
CID = "cor_0123456789abcdef0123456789abcdef"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


class _Sender:
    def __init__(self, header_ok: bool = True) -> None:
        self.header_ok = header_ok
        self.buttons: list[dict[str, Any]] = []
        self.images: list[bytes] = []

    async def send_button(self, wa_id: str, **kw: Any) -> bool:
        if kw.get("header_image") is not None and not self.header_ok:
            return False
        self.buttons.append({"wa_id": wa_id, **kw})
        return True

    async def send_image(self, wa_id: str, image: bytes, **kw: Any) -> bool:
        self.images.append(image)
        return True


class _Settings:
    def __init__(self, mode: str) -> None:
        self.mode = mode

    async def get(self, *, organization_id: str, key: str) -> str:
        return self.mode


def _app(monkeypatch, *, mode: str = "api", last_hours: float = 1.0, row: bool = True, sender: _Sender | None = None):
    monkeypatch.setenv("MESIRI_PREVIEWS", "on")
    monkeypatch.setenv("MESIRI_TEAMMATE_API_TOKEN", TOKEN)
    from mesiri.bootstrap.settings import get_settings

    get_settings.cache_clear()

    async def request_row(db: Any, cid: str):
        if not row:
            return None
        return {"sender_wa_id": "919876543210", "organization_id": "org-1", "body_text": "mesiri bad ux, too many buttons",
                "last_at": dt.datetime.now(dt.UTC) - dt.timedelta(hours=last_hours)}

    monkeypatch.setattr(previews, "_request_row", request_row)
    sender = sender or _Sender()
    trace = SimpleNamespace(log_stage=_async_noop)
    app = FastAPI()
    app.include_router(previews.router)
    app.state.container = SimpleNamespace(material_db=None, org_settings_query=_Settings(mode), redis_client=FakeRedis(),
                                          whatsapp_sender=sender, trace_logger=trace)
    return TestClient(app), sender


async def _async_noop(**kw: Any) -> None:
    return None


def _post(client: TestClient, token: str = TOKEN, png: bytes = PNG, cid: str = CID):
    return client.post("/teammate-api/preview", headers={"authorization": f"Bearer {token}"},
                       json={"correlation_id": cid, "image_base64": base64.b64encode(png).decode(), "caption": "Two buttons, not five", "request_ref": "#012345"})


def test_off_by_default_answers_404(monkeypatch) -> None:
    client, sender = _app(monkeypatch)
    monkeypatch.delenv("MESIRI_PREVIEWS")
    assert _post(client).status_code == 404 and sender.buttons == []


def test_the_preview_goes_to_the_person_who_asked_once(monkeypatch) -> None:
    client, sender = _app(monkeypatch)
    assert _post(client).json() == {"sent": True}
    (sent,) = sender.buttons
    assert sent["wa_id"] == "919876543210" and sent["header_image"] == PNG
    assert [b.id for b in sent["buttons"]] == [f"preview_ok:{CID}", f"preview_change:{CID}"]
    assert "Is this how you want it?" in sent["body"] and "#012345" in sent["body"]
    assert _post(client).status_code == 409  # once per request
    assert len(sender.buttons) == 1


@pytest.mark.parametrize(("kwargs", "call", "status"), [
    ({}, {"token": "wrong" * 8}, 401),
    ({}, {"png": b"GIF89a not a png"}, 400),
    ({}, {"cid": "cor_x'; DROP"}, 422),
    ({"row": False}, {}, 404),
    ({"mode": "classic"}, {}, 403),
    ({"last_hours": 24.0}, {}, 409),
])
def test_guards(monkeypatch, kwargs, call, status) -> None:
    client, sender = _app(monkeypatch, **kwargs)
    assert _post(client, **call).status_code == status
    assert sender.buttons == []


def test_a_failed_image_header_sends_the_picture_then_the_question(monkeypatch) -> None:
    client, sender = _app(monkeypatch, sender=_Sender(header_ok=False))
    assert _post(client).json() == {"sent": True}
    assert sender.images == [PNG] and len(sender.buttons) == 1 and "header_image" not in sender.buttons[0]


def test_taps_parse_and_change_it_is_feedback() -> None:
    assert previews.parse_tap(f"preview_ok:{CID}") == (True, CID)
    assert previews.parse_tap(f"preview_change:{CID}") == (False, CID)
    assert previews.parse_tap("preview_ok:../x") is None
    (call,) = previews.tap_trace(False, CID)["calls"]
    assert call["tool"] == "tell_the_team" and call["args"]["kind"] == "bad_ux"
    assert previews.tap_trace(True, CID)["calls"][0]["tool"] == "preview_confirmed"
    assert all(len(b.title) <= 20 for lang in ("english", "malayalam", "hindi") for b in previews.preview_buttons(CID, lang))
