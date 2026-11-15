"""[305] (15 Nov, live: an owner tapped Continue with Mesiri, then asked "When will i get" and got the trial-ended
message with its button again): once a continue request is open, every message hears that the request is with us,
and the team is reminded at most once every 3 hours."""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import pytest

from backend.ports import ActorIdentity
from mesiri.domains.organizations import trial_notices as notices
from mesiri_contracts.assistant.enums import InputModality
from runtime import trial_journey as tj

ORG = str(uuid.uuid4())


def _actor(role="ADMIN") -> ActorIdentity:
    return ActorIdentity(user_id=str(uuid.uuid4()), full_name="Ravi", role=role, organization_id=ORG,
                         org_name="Rolla Builders", org_active=False)


def _text(text):
    return SimpleNamespace(modality=InputModality.TEXT, text=text, metadata={})


def _tap(reply_id):
    return SimpleNamespace(modality=InputModality.INTERACTIVE, text=None, metadata={"interactive_reply_id": reply_id})


def _document():
    return SimpleNamespace(modality=InputModality.DOCUMENT, text=None, metadata={"filename": "BOQ.docx"})


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
        self.posts: list[str] = []

    async def post(self, text, *, images=None):
        self.posts.append(text)
        return True


@pytest.fixture
def journey(monkeypatch):
    state = {"open": False, "nudges_due": 0}

    async def fake_details(conn, org_id):
        return {
            "company": "Rolla Builders", "effective_status": "expired", "end_day": "12 Nov", "retention_days": 30,
            "owner_name": "Ravi", "open_request": {"status": "open"} if state["open"] else None,
            "asked_day": "15 Nov" if state["open"] else None, "safe_until": "12 Dec",
        }

    async def fake_record(conn, org_id, *, user_id, via):
        added = not state["open"]
        state["open"] = True
        return added

    async def fake_nudge(conn, org_id):
        if state["nudges_due"] > 0:
            state["nudges_due"] -= 1
            return True
        return False

    monkeypatch.setattr(tj, "expiry_details", fake_details)
    monkeypatch.setattr(tj, "record_continue_request", fake_record)
    monkeypatch.setattr(tj, "continue_nudge_due", fake_nudge)
    notifier = _Notifier()
    return SimpleNamespace(j=tj.TrialJourney(db=_Db(), notifier=notifier), state=state, notifier=notifier)


async def test_a_question_after_continue_hears_the_request_is_with_us(journey) -> None:
    """The reported message: Continue, then "When will i get"."""
    first = await journey.j.handle_inactive(_tap(notices.CONTINUE_TAP), _actor())
    assert first is not None and first.text == notices.CONTINUE_RECEIVED
    reply = await journey.j.handle_inactive(_text("When will i get"), _actor())
    assert reply is not None
    assert "We have your request from *15 Nov*" in reply.text and "safe until *12 Dec*" in reply.text
    assert "trial ended" not in reply.text
    assert not reply.buttons  # never the Continue button again
    assert len(journey.notifier.posts) == 1  # the first request only; no reminder this soon


@pytest.mark.parametrize("message", [_document(), _text(""), _tap(notices.CONTINUE_TAP), _text("continue")])
async def test_siblings_a_file_an_empty_message_and_continue_again(journey, message) -> None:
    journey.state["open"] = True
    reply = await journey.j.handle_inactive(message, _actor())
    assert reply is not None and reply.text.startswith("👍 We have your request from")
    assert not reply.buttons


async def test_the_team_is_reminded_when_the_rate_limit_allows(journey) -> None:
    journey.state.update(open=True, nudges_due=1)
    await journey.j.handle_inactive(_text("When will i get"), _actor())
    await journey.j.handle_inactive(_text("any update?"), _actor())
    assert len(journey.notifier.posts) == 1
    assert "still waiting for the continue call" in journey.notifier.posts[0]


async def test_guard_no_open_request_keeps_the_trial_ended_message_and_button(journey) -> None:
    reply = await journey.j.handle_inactive(_text("hi"), _actor())
    assert reply is not None and "free trial ended" in reply.text
    assert [b.id for b in reply.buttons] == [notices.CONTINUE_TAP]


async def test_guard_a_member_still_asks_the_owner(journey) -> None:
    journey.state["open"] = True
    reply = await journey.j.handle_inactive(_text("hi"), _actor(role="SITE_ENGINEER"))
    assert reply is not None and "We have your request" not in reply.text


def test_nudge_is_due_once_per_three_hours() -> None:
    now = dt.datetime(2026, 11, 15, 15, 0, tzinfo=dt.UTC)
    requests, added = notices.add_continue_request([], user_id="u", via="whatsapp", now=now)
    assert added
    request = notices.open_continue_request(requests)
    assert request is not None and not notices.nudge_due(request, now + dt.timedelta(minutes=1))
    assert notices.nudge_due(request, now + dt.timedelta(hours=3))
    marked = notices.open_continue_request(notices.with_nudged(requests, now + dt.timedelta(hours=3)))
    assert marked is not None and not notices.nudge_due(marked, now + dt.timedelta(hours=4))
    assert notices.nudge_due({"status": "open"}, now)  # a request from before [305] has no clock: one reminder
