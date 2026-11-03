"""TM-69: the person who asked hears that they were understood and where their request is. The route lets the team
bot message a customer, so its guards are the preview route's (shared code) and tested here again: off by default,
the bot's token only, the recipient from the request, v3 only, the 24-hour window, each stage once; plus the bot's
line (no links / phone numbers / @mentions), the wording in their language, and the open requests Mesiri remembers."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mesiri.infrastructure.redis.client import FakeRedis
from runtime import previews, request_progress
from runtime.release_notes import ReleaseNote, live_correlation_ids

TOKEN = "k" * 40
CID = "cor_0123456789abcdef0123456789abcdef"
LINE = "Primer-um athinte drum size-um add aayi, pakshe Green Villa-il vanna 2 drum save aayilla: avide stock 40 L kuravaanu."


class _Sender:
    def __init__(self) -> None:
        self.texts: list[tuple[str, str]] = []

    async def send_text(self, wa_id: str, body: str) -> bool:
        self.texts.append((wa_id, body))
        return True


class _Settings:
    def __init__(self, mode: str) -> None:
        self.mode = mode

    async def get(self, *, organization_id: str, key: str) -> str:
        return self.mode


def _app(monkeypatch, *, mode: str = "api", last_hours: float = 1.0, body_text: str = "2 drum primer vannu", switch: str = "on"):
    monkeypatch.setenv("MESIRI_PREVIEWS", switch)
    monkeypatch.setenv("MESIRI_TEAMMATE_API_TOKEN", TOKEN)
    from mesiri.bootstrap.settings import get_settings

    get_settings.cache_clear()

    async def request_row(db: Any, cid: str):
        return {"sender_wa_id": "919876543210", "organization_id": "org-1", "body_text": body_text,
                "last_at": dt.datetime.now(dt.UTC) - dt.timedelta(hours=last_hours)}

    monkeypatch.setattr(previews, "_request_row", request_row)
    sender = _Sender()
    traces: list[dict[str, Any]] = []

    async def log_stage(**kw: Any) -> None:
        traces.append(kw)

    app = FastAPI()
    app.include_router(request_progress.router)
    app.state.container = SimpleNamespace(material_db=None, org_settings_query=_Settings(mode), redis_client=FakeRedis(),
                                          whatsapp_sender=sender, trace_logger=SimpleNamespace(log_stage=log_stage))
    return TestClient(app), sender, traces


def _post(client: TestClient, token: str = TOKEN, **body: Any):
    payload = {"correlation_id": CID, "stage": "understood", "line": LINE, "request_ref": "#012345", **body}
    return client.post("/teammate-api/progress", headers={"authorization": f"Bearer {token}"}, json=payload)


def test_understood_says_their_problem_back_then_the_fixed_words_in_their_language(monkeypatch):
    client, sender, traces = _app(monkeypatch)
    r = _post(client)
    assert r.status_code == 200 and r.json() == {"sent": True}
    wa, text = sender.texts[0]
    assert wa == "919876543210"  # read from the request, never given by the bot
    assert text.startswith(LINE)
    assert "Team ithu ippo sheriyaakkunnu" in text and text.endswith("#012345")  # Manglish, from their message
    assert traces[0]["stage"] == "request_progress" and traces[0]["stage_payload"]["stage"] == "understood"


def test_again_tells_what_was_found_and_never_asks_a_question_back(monkeypatch):
    client, sender, _ = _app(monkeypatch, body_text="Send the report")
    r = _post(client, stage="again", round=2, line="The new primer saved, but the receipt still went to the old site list.")
    assert r.status_code == 200
    text = sender.texts[0][1]
    assert text.startswith("Update: the first fix wasn't fully right. Here's what we found:")
    assert "still went to the old site list" in text and "The team is fixing it now" in text


def test_slow_needs_no_line_and_is_honest(monkeypatch):
    client, sender, _ = _app(monkeypatch, body_text="Send the report")
    assert _post(client, stage="slow", line="").status_code == 200
    assert sender.texts[0][1].startswith("⏳ Still working on #012345")


def test_each_stage_once_and_each_fix_round_once(monkeypatch):
    client, sender, _ = _app(monkeypatch)
    assert _post(client).status_code == 200
    assert _post(client).status_code == 409
    assert _post(client, stage="again", round=2).status_code == 200
    assert _post(client, stage="again", round=2).status_code == 409
    assert _post(client, stage="again", round=3).status_code == 200
    assert len(sender.texts) == 3


@pytest.mark.parametrize("line", ["See https://evil.example.com now", "Call 98765 43210 for help", "Ask @ravi", ""])
def test_the_bots_line_is_checked(monkeypatch, line):
    client, sender, _ = _app(monkeypatch)
    assert _post(client, line=line).status_code == 400
    assert sender.texts == []


def test_guards_shared_with_previews(monkeypatch):
    client, sender, _ = _app(monkeypatch, switch="off")
    assert _post(client).status_code == 404
    client, sender, _ = _app(monkeypatch)
    assert _post(client, token="wrong").status_code == 401
    client, sender, _ = _app(monkeypatch, mode="classic")
    assert _post(client).status_code == 403
    client, sender, _ = _app(monkeypatch, last_hours=30)
    assert _post(client).status_code == 409
    assert sender.texts == []


def test_open_requests_context_lists_what_the_team_is_on():
    rows = [{"correlation_id": CID, "created_at": dt.datetime(2026, 11, 3, 11, 20, tzinfo=dt.UTC), "stage": "understood",
             "line": LINE, "ref": "#012345"}]
    block = request_progress.context_block(rows)
    assert block.startswith("OPEN REQUESTS")
    assert "#012345 being fixed (since 03 Nov 11:20 UTC): Primer-um" in block
    assert request_progress.context_block([]) == ""


def test_a_shipped_note_closes_the_request():
    note = ReleaseNote(id="primer-receipt", date=dt.date(2026, 11, 3), correlation_ids=(CID,), message="works")
    assert live_correlation_ids([note]) == {CID}
    assert live_correlation_ids([]) == set()
