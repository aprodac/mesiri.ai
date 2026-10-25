"""SS-04: WhatsApp signup for unknown numbers (no database)."""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import pytest

from interactions.signup_state import SignupState, SignupStateStore
from mesiri.application.organizations.create_company import (
    CompanyCreationError,
    CreatedCompany,
)
from mesiri.infrastructure.redis.client import FakeRedis
from mesiri_contracts.assistant.enums import InputModality
from runtime import signup_journey as sj

WA_ID = "919876543210"


class _Sender:
    def __init__(self) -> None:
        self.texts: list[str] = []
        self.buttons: list[tuple[str, list[str]]] = []
        self.headers: list = []
        self.images: list = []

    async def send_text(self, to, body):
        self.texts.append(body)
        return True

    async def send_button(self, to, *, body, buttons, header_image=None):
        self.buttons.append((body, [b.id for b in buttons]))
        self.headers.append(header_image)
        return True

    async def send_image(self, to, image, *, caption=None):
        self.images.append((image, caption))
        return True


class _Tx:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *exc):
        return None


class _Db:
    def transaction(self):
        return _Tx()


def _text(text: str, *, profile: str | None = "Suresh Kumar"):
    return SimpleNamespace(
        sender=SimpleNamespace(wa_id=WA_ID, profile_name=profile),
        modality=InputModality.TEXT,
        text=text,
        metadata={},
    )


def _tap(reply_id: str):
    return SimpleNamespace(
        sender=SimpleNamespace(wa_id=WA_ID, profile_name="Suresh Kumar"),
        modality=InputModality.INTERACTIVE,
        text=None,
        metadata={"interactive_reply_id": reply_id},
    )


def _voice():
    return SimpleNamespace(
        sender=SimpleNamespace(wa_id=WA_ID, profile_name="Suresh Kumar"),
        modality=InputModality.VOICE,
        text=None,
        metadata={},
    )


def _created(new) -> CreatedCompany:
    return CreatedCompany(
        organization_id=uuid.uuid4(),
        name=new.name,
        deployment_type="SaaS",
        db_route="shared-cluster-01",
        status="trial",
        signup_source="whatsapp",
        timezone="Asia/Kolkata",
        created_at=dt.datetime(2026, 10, 15, 6, tzinfo=dt.UTC),
        trial_started_at=dt.datetime(2026, 10, 15, 6, tzinfo=dt.UTC),
        trial_ends_at=dt.datetime(2026, 10, 22, 6, tzinfo=dt.UTC),
        owner_user_id=uuid.uuid4(),
        owner_email=None,
        owner_whatsapp_number=WA_ID,
        project_id=uuid.uuid4(),
        site_id=uuid.uuid4(),
        materials_seeded=19,
    )


@pytest.fixture
def journey(monkeypatch):
    sender = _Sender()
    created_with: list = []
    outcome: dict = {}

    async def fake_create(conn, new, *, now=None):
        created_with.append(new)
        if "error" in outcome:
            raise outcome["error"]
        return _created(new)

    guard: dict = {"refuse": None, "calls": []}

    async def fake_check_signup(conn, attempt, *, now=None):
        guard["calls"].append(attempt)
        if guard["refuse"]:
            raise sj.SignupRefused(guard["refuse"], reason="previous_trial")

    monkeypatch.setattr(sj, "create_company", fake_create)
    monkeypatch.setattr(sj, "check_signup", fake_check_signup)
    j = sj.SignupJourney(
        sender=sender,
        store=SignupStateStore(FakeRedis()),
        db=_Db(),
    )
    enabled = {"on": True}

    async def fake_enabled():
        return enabled["on"]

    j.signup_enabled = fake_enabled  # type: ignore[method-assign]
    return SimpleNamespace(
        j=j, sender=sender, created_with=created_with,
        outcome=outcome, enabled=enabled, guard=guard,
    )  # fmt: skip


async def test_switched_off_leaves_the_old_reply_to_the_caller(journey) -> None:
    journey.enabled["on"] = False
    assert await journey.j.handle(_text("Hi")) is None
    assert journey.sender.texts == [] and journey.sender.buttons == []


async def test_full_signup_creates_a_trial_company(journey) -> None:
    await journey.j.handle(_text("Hi"))
    body, ids = journey.sender.buttons[0]
    assert "Hi Suresh Kumar" in body
    assert ids == [sj.START_TRIAL_ID, sj.IN_COMPANY_ID]

    assert await journey.j.handle(_tap(sj.START_TRIAL_ID)) == sj.ASK_COMPANY
    assert await journey.j.handle(_text("  Suresh   Builders ")) == sj.ASK_SITE
    await journey.j.handle(_text("Green Villa, Kakkanad"))
    done = await journey.j.handle(_tap(sj.CONFIRM_ID))

    new = journey.created_with[0]
    assert new.name == "Suresh Builders"
    assert new.owner_name == "Suresh Kumar"
    assert new.owner_phone == WA_ID
    assert new.project_name == new.site_name == "Green Villa, Kakkanad"
    assert new.start_as == "trial" and new.signup_source == "whatsapp"
    assert new.auto_dpr is True
    assert "Suresh Builders" in done and "22 Oct" in done

    # The signup is over: a further message starts afresh, not a second company.
    await journey.j.handle(_text("Hi"))
    assert len(journey.created_with) == 1
    assert len(journey.sender.buttons) == 3  # welcome, the confirm card, welcome again


async def test_no_profile_name_asks_for_it(journey) -> None:
    await journey.j.handle(_tap(sj.START_TRIAL_ID))
    await journey.j.handle(_text("Acme", profile=None))
    assert await journey.j.handle(_text("Site 1", profile=None)) == sj.ASK_OWNER_NAME
    await journey.j.handle(_text("Asha", profile=None))
    await journey.j.handle(_tap(sj.CONFIRM_ID))
    assert journey.created_with[0].owner_name == "Asha"


async def test_in_a_company_points_to_the_admin(journey) -> None:
    reply = await journey.j.handle(_tap(sj.IN_COMPANY_ID))
    assert f"+{WA_ID}" in reply
    assert journey.created_with == []


async def test_cancel_stops_and_creates_nothing(journey) -> None:
    await journey.j.handle(_tap(sj.START_TRIAL_ID))
    await journey.j.handle(_text("Acme"))
    assert await journey.j.handle(_text("Cancel")) == sj.CANCELLED_MESSAGE
    assert journey.created_with == []


async def test_voice_note_mid_signup_asks_to_type(journey) -> None:
    await journey.j.handle(_tap(sj.START_TRIAL_ID))
    reply = await journey.j.handle(_voice())
    assert reply.startswith("Please type") and sj.ASK_COMPANY in reply


async def test_overlong_answer_is_asked_again(journey) -> None:
    await journey.j.handle(_tap(sj.START_TRIAL_ID))
    reply = await journey.j.handle(_text("x" * 121))
    assert "under 120" in reply
    assert await journey.j.handle(_text("Acme")) == sj.ASK_SITE


@pytest.mark.parametrize(
    ("conflict", "expected"), [(True, sj.ALREADY_SET_UP_MESSAGE), (False, sj.FAILED_MESSAGE)]
)
async def test_refused_creation(journey, conflict, expected) -> None:
    journey.outcome["error"] = CompanyCreationError("nope", conflict=conflict)
    await journey.j.handle(_tap(sj.START_TRIAL_ID))
    await journey.j.handle(_text("Acme"))
    await journey.j.handle(_text("Site 1"))
    assert await journey.j.handle(_tap(sj.CONFIRM_ID)) == expected


async def test_database_failure_says_sorry(journey) -> None:
    journey.outcome["error"] = RuntimeError("db down")
    await journey.j.handle(_tap(sj.START_TRIAL_ID))
    await journey.j.handle(_text("Acme"))
    await journey.j.handle(_text("Site 1"))
    assert await journey.j.handle(_tap(sj.CONFIRM_ID)) == sj.FAILED_MESSAGE


# --- SS-09 guardrails ---------------------------------------------------------


async def test_guardrails_are_checked_on_tap_and_before_creating(journey) -> None:
    await journey.j.handle(_tap(sj.START_TRIAL_ID))
    await journey.j.handle(_text("Suresh Builders"))
    await journey.j.handle(_text("Green Villa, Kakkanad"))
    await journey.j.handle(_tap(sj.CONFIRM_ID))
    assert [(a.phone, a.signup_source, a.ip_address) for a in journey.guard["calls"]] == [
        (WA_ID, "whatsapp", None),
        (WA_ID, "whatsapp", None),
    ]
    assert len(journey.created_with) == 1


async def test_refused_on_tap_says_why_and_asks_nothing(journey) -> None:
    journey.guard["refuse"] = "This number has already had a free trial."
    reply = await journey.j.handle(_tap(sj.START_TRIAL_ID))
    assert reply == "This number has already had a free trial."
    # Back to the start: the next message is the welcome again, not a question.
    assert await journey.j._store.get(WA_ID) is None
    assert journey.created_with == []


async def test_refused_at_create_creates_nothing(journey) -> None:
    await journey.j.handle(_tap(sj.START_TRIAL_ID))
    await journey.j.handle(_text("Suresh Builders"))
    journey.guard["refuse"] = "We're getting a lot of sign-ups right now."
    await journey.j.handle(_text("Green Villa, Kakkanad"))
    reply = await journey.j.handle(_tap(sj.CONFIRM_ID))
    assert reply == "We're getting a lot of sign-ups right now."
    assert journey.created_with == []


class _Renderer:
    def __init__(self, fail=False):
        self.fail = fail
        self.html: list[str] = []

    async def render_png(self, html):
        if self.fail:
            raise RuntimeError("no chromium")
        self.html.append(html)
        return b"png"


def _with_renderer(journey, renderer):
    journey.j._renderer = renderer
    return renderer


async def test_steps_are_numbered(journey) -> None:
    assert sj.ASK_COMPANY.startswith("*Step 1 of 2*")
    assert sj.ASK_SITE.startswith("*Step 2 of 2*")


async def test_welcome_card_rides_as_the_buttons_header(journey) -> None:
    renderer = _with_renderer(journey, _Renderer())
    await journey.j.handle(_text("Hi"))
    assert journey.sender.headers == [b"png"]
    assert journey.sender.buttons[0][1] == [sj.START_TRIAL_ID, sj.IN_COMPANY_ID]
    assert "Tell me what happened" in renderer.html[0]


async def test_site_ready_card_replaces_the_text(journey) -> None:
    renderer = _with_renderer(journey, _Renderer())
    await journey.j.handle(_tap(sj.START_TRIAL_ID))
    await journey.j.handle(_text("Suresh Builders"))
    await journey.j.handle(_text("Green Villa, Kakkanad"))
    await journey.j.handle(_tap(sj.CONFIRM_ID))
    assert journey.sender.images == [(b"png", "Your free trial runs until *22 Oct*.")]
    assert journey.sender.texts == [sj.ASK_COMPANY, sj.ASK_SITE]  # no plain done-text
    assert "Green Villa is live." in renderer.html[0]
    assert "Suresh Builders" in renderer.html[0] and "9 pm" in renderer.html[0]


async def test_malayalam_names_get_the_malayalam_ready_card(journey) -> None:
    renderer = _with_renderer(journey, _Renderer())
    await journey.j.handle(_tap(sj.START_TRIAL_ID))
    await journey.j.handle(_text("സുരേഷ് ബിൽഡേഴ്സ്"))
    await journey.j.handle(_text("Green Villa"))
    await journey.j.handle(_tap(sj.CONFIRM_ID))
    assert "തയ്യാറായി" in renderer.html[0]


async def test_signup_falls_back_to_text_when_the_renderer_raises(journey) -> None:
    _with_renderer(journey, _Renderer(fail=True))
    await journey.j.handle(_text("Hi"))
    assert journey.sender.headers == [None]  # same buttons, no image
    await journey.j.handle(_tap(sj.START_TRIAL_ID))
    await journey.j.handle(_text("Suresh Builders"))
    await journey.j.handle(_text("Green Villa, Kakkanad"))
    done = await journey.j.handle(_tap(sj.CONFIRM_ID))
    assert journey.sender.images == []
    assert journey.sender.texts[-1] == done and "Suresh Builders" in done and "22 Oct" in done
    assert len(journey.created_with) == 1  # signup was never blocked


async def test_signup_falls_back_to_text_when_the_image_send_fails(journey) -> None:
    _with_renderer(journey, _Renderer())

    async def refuse(to, image, *, caption=None):
        return False

    journey.sender.send_image = refuse
    await journey.j.handle(_tap(sj.START_TRIAL_ID))
    await journey.j.handle(_text("Acme"))
    await journey.j.handle(_text("Site 1"))
    done = await journey.j.handle(_tap(sj.CONFIRM_ID))
    assert journey.sender.texts[-1] == done


# --- SET-03: names are checked, then confirmed ---------------------------------


@pytest.mark.parametrize(
    "bad", ["ok", "hi", "Hello", "what is this?", "start free trial", "x", "123", "yes",
            "this is a very long sentence that is clearly not a company name at all"]
)  # fmt: skip
async def test_set03_a_non_name_is_not_taken_as_the_company(journey, bad) -> None:
    await journey.j.handle(_tap(sj.START_TRIAL_ID))
    reply = await journey.j.handle(_text(bad))
    assert reply.startswith("That doesn't look like a company name")
    assert sj.ASK_COMPANY in reply
    assert await journey.j._store.get(WA_ID) == SignupState(stage="company")
    assert await journey.j.handle(_text("Suresh Builders")) == sj.ASK_SITE


async def test_set03_a_non_name_is_not_taken_as_the_site(journey) -> None:
    await journey.j.handle(_tap(sj.START_TRIAL_ID))
    await journey.j.handle(_text("Suresh Builders"))
    reply = await journey.j.handle(_text("ok"))
    assert reply.startswith("That doesn't look like a site name")
    assert journey.created_with == []


async def test_set03_typed_words_stand_in_for_the_welcome_buttons(journey) -> None:
    await journey.j.handle(_text("Hi"))
    assert await journey.j.handle(_text("yes")) == sj.ASK_COMPANY  # not the welcome again
    await journey.j.handle(_text("cancel"))
    assert await journey.j.handle(_text("start free trial")) == sj.ASK_COMPANY


async def test_set03_the_names_are_confirmed_before_anything_is_created(journey) -> None:
    await journey.j.handle(_tap(sj.START_TRIAL_ID))
    await journey.j.handle(_text("Suresh Builders"))
    body = await journey.j.handle(_text("Green Villa, Kakkanad"))
    assert "*Company:* Suresh Builders" in body and "*Site:* Green Villa, Kakkanad" in body
    assert journey.sender.buttons[-1][1] == [sj.CONFIRM_ID, sj.EDIT_ID]
    assert journey.created_with == []


async def test_set03_edit_starts_the_names_again(journey) -> None:
    await journey.j.handle(_tap(sj.START_TRIAL_ID))
    await journey.j.handle(_text("Suresh Buildrs"))
    await journey.j.handle(_text("Green Villa"))
    assert await journey.j.handle(_tap(sj.EDIT_ID)) == sj.ASK_COMPANY
    await journey.j.handle(_text("Suresh Builders"))
    await journey.j.handle(_text("Green Villa"))
    await journey.j.handle(_text("yes"))  # typed Looks good
    assert [n.name for n in journey.created_with] == ["Suresh Builders"]


async def test_set03_other_text_at_the_confirm_card_asks_again(journey) -> None:
    await journey.j.handle(_tap(sj.START_TRIAL_ID))
    await journey.j.handle(_text("Suresh Builders"))
    await journey.j.handle(_text("Green Villa"))
    reply = await journey.j.handle(_text("what is this?"))
    assert reply.startswith(sj.CONFIRM_REMINDER)
    assert journey.created_with == []
