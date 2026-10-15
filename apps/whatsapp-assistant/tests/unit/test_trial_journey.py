"""SS-08: what people hear on WhatsApp as a trial ends, and the read-only guard."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.ports import ActorIdentity
from mesiri.domains.organizations import trial_notices as notices
from mesiri.domains.shared import trial_guard
from mesiri_contracts.assistant.enums import InputModality
from runtime import trial_journey as tj

ORG = str(uuid.uuid4())


def _actor(role="ADMIN") -> ActorIdentity:
    return ActorIdentity(
        user_id=str(uuid.uuid4()),
        full_name="Suresh",
        role=role,
        organization_id=ORG,
        org_name="Suresh Builders",
        org_active=False,
    )


def _text(text):
    return SimpleNamespace(modality=InputModality.TEXT, text=text, metadata={})


def _tap(reply_id):
    return SimpleNamespace(
        modality=InputModality.INTERACTIVE, text=None, metadata={"interactive_reply_id": reply_id}
    )


class _Tx:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *exc):
        return None


class _Db:
    def transaction(self):
        return _Tx()


class _Notifier:
    def __init__(self):
        self.posts = []

    async def post(self, text, *, images=None):
        self.posts.append(text)
        return True


@pytest.fixture
def journey(monkeypatch):
    state = {"status": "expired", "requests": 0}

    async def fake_details(conn, org_id):
        return {
            "company": "Suresh Builders",
            "effective_status": state["status"],
            "end_day": "22 Oct",
            "retention_days": 30,
            "owner_name": "Suresh",
        }

    async def fake_record(conn, org_id, *, user_id, via):
        state["requests"] += 1
        return state["requests"] == 1

    monkeypatch.setattr(tj, "expiry_details", fake_details)
    monkeypatch.setattr(tj, "record_continue_request", fake_record)
    notifier = _Notifier()
    return SimpleNamespace(
        j=tj.TrialJourney(db=_Db(), notifier=notifier), state=state, notifier=notifier
    )


async def test_expired_owner_hears_the_trial_ended_with_a_continue_button(journey) -> None:
    reply = await journey.j.handle_inactive(_text("hi"), _actor())
    assert "ended on *22 Oct*" in reply.text and "30 days" in reply.text
    assert [b.id for b in reply.buttons] == [notices.CONTINUE_TAP]


async def test_expired_member_is_pointed_to_the_owner(journey) -> None:
    reply = await journey.j.handle_inactive(_text("10 masons today"), _actor("SITE_ENGINEER"))
    assert reply.text == (
        "The Mesiri free trial for Suresh Builders has ended. Please ask Suresh to continue."
    )
    assert not reply.buttons


async def test_suspended_company_keeps_the_generic_reply(journey) -> None:
    journey.state["status"] = "suspended"
    assert await journey.j.handle_inactive(_text("hi"), _actor()) is None


async def test_continue_after_expiry_is_recorded_once_and_the_team_told(journey) -> None:
    first = await journey.j.handle_inactive(_tap(notices.CONTINUE_TAP), _actor())
    assert first.text == notices.CONTINUE_RECEIVED
    assert len(journey.notifier.posts) == 1 and "Suresh Builders" in journey.notifier.posts[0]
    again = await journey.j.handle_inactive(_text("CONTINUE"), _actor())
    assert again.text == notices.CONTINUE_ALREADY
    assert len(journey.notifier.posts) == 1


async def test_continue_during_the_trial_answers_the_reminder(journey) -> None:
    journey.state["status"] = "trial"
    reply = await journey.j.handle_continue(_text("Continue"), _actor())
    assert reply.text == notices.CONTINUE_RECEIVED


@pytest.mark.parametrize("status", ["active", "expired"])
async def test_continue_is_not_intercepted_outside_a_running_trial(journey, status) -> None:
    # A paying company's "continue" goes to the normal journey; an expired one
    # is answered by handle_inactive instead.
    journey.state["status"] = status
    assert await journey.j.handle_continue(_text("continue"), _actor()) is None


async def test_only_the_owner_can_continue(journey) -> None:
    journey.state["status"] = "trial"
    assert await journey.j.handle_continue(_text("continue"), _actor("SITE_ENGINEER")) is None


async def test_other_messages_are_not_continue(journey) -> None:
    journey.state["status"] = "trial"
    assert await journey.j.handle_continue(_text("continue the slab work"), _actor()) is None


# -- the read-only guard -----------------------------------------------------------


def _guarded_app(monkeypatch, *, expired: bool) -> TestClient:
    async def fake_expired(request, organization_id):
        return expired

    monkeypatch.setattr(trial_guard, "_trial_expired", fake_expired)
    monkeypatch.setattr(
        trial_guard, "organization_from_token", lambda h: uuid.UUID(ORG) if h else None
    )
    app = FastAPI()
    app.middleware("http")(trial_guard.trial_guard_middleware)

    @app.get("/projects")
    async def read():
        return {"ok": True}

    @app.post("/projects")
    async def write():
        return {"ok": True}

    @app.post("/auth/login")
    async def login():
        return {"ok": True}

    @app.post("/company/trial/continue")
    async def cont():
        return {"ok": True}

    return TestClient(app)


def test_expired_company_can_read_but_not_change(monkeypatch) -> None:
    client = _guarded_app(monkeypatch, expired=True)
    auth = {"Authorization": "Bearer t"}
    assert client.get("/projects", headers=auth).status_code == 200
    blocked = client.post("/projects", headers=auth)
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["code"] == "TRIAL_EXPIRED"
    assert client.post("/auth/login", headers=auth).status_code == 200
    assert client.post("/company/trial/continue", headers=auth).status_code == 200


def test_no_token_or_live_company_passes(monkeypatch) -> None:
    client = _guarded_app(monkeypatch, expired=True)
    assert client.post("/projects").status_code == 200  # no token: not the guard's call
    client = _guarded_app(monkeypatch, expired=False)
    assert client.post("/projects", headers={"Authorization": "Bearer t"}).status_code == 200
