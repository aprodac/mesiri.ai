"""WA-04: the evening gap-check's wording, its taps, and which sites the
scheduler step messages. Backend calls are faked; the real-Postgres run is
tests/integration/test_site_day_review_e2e.py."""

from __future__ import annotations

import contextlib
import datetime as dt
import uuid
from types import SimpleNamespace

import pytest

import runtime.site_day_review as review
from backend.ports import ActorIdentity, SiteSummary
from mesiri.application.projects import auto_dpr
from mesiri.infrastructure.postgres.repositories import notifications as notifications_module

DAY = dt.date(2026, 10, 15)
SITE = uuid.UUID("11111111-1111-1111-1111-111111111111")
PROJECT = uuid.UUID("22222222-2222-2222-2222-222222222222")
ORG = uuid.UUID("33333333-3333-3333-3333-333333333333")


# --- wording ------------------------------------------------------------------


def test_time_labels():
    assert review.time_label("21:00") == "9:00 pm"
    assert review.time_label("12:30") == "12:30 pm"
    assert review.time_label("00:15") == "12:15 am"
    assert review.time_label("07:05") == "7:05 am"


def test_a_site_named_after_its_project_is_not_repeated():
    assert review.site_label("Block A", "Green Towers") == "Block A (Green Towers)"
    assert review.site_label("Green Towers", "green towers") == "Green Towers"
    assert review.site_label("Block A", None) == "Block A"


def test_one_missing_section():
    text = review.gap_check_message(
        site_name="Block A",
        project_name="Green Towers",
        missing={"blocking": ["labour"], "optional": ["materials"]},
        deadline="21:00",
    )
    assert text == (
        "📋 *Block A* (Green Towers): today's report is missing the *labour count*.\n"
        "Send it here (text, voice note or photo) before *9:00 pm* so the report goes out complete.\n"
        "Site closed today? Tap below."
    )


def test_two_missing_sections_and_no_photos():
    text = review.gap_check_message(
        site_name="Green Towers",
        project_name="Green Towers",
        missing={"blocking": ["work_done", "labour"], "optional": ["photos"]},
        deadline="20:00",
    )
    assert text.splitlines() == [
        "📋 *Green Towers*: today's report is missing the *work done* and the *labour count*.",
        "Send them here (text, voice note or photo) before *8:00 pm* so the report goes out complete.",
        "No photos yet either. Send one or two if you can.",
        "Site closed today? Tap below.",
    ]


def test_the_payload_carries_the_button_and_the_template():
    payload = review.gap_check_payload(
        site_id=SITE,
        site_name="Block A",
        project_name="Green Towers",
        missing={"blocking": ["work_done", "labour"], "optional": []},
        deadline="21:00",
        report_date=DAY,
    )
    assert payload["buttons"] == [
        {"id": f"sdr:closed:{SITE}:20261015", "title": "Site closed today"}
    ]
    assert payload["template"] == {
        "name": "mesiri_site_day_review",
        "body_params": [
            "Block A (Green Towers)",
            "Work done and labour count are missing.",
            "9:00 pm",
        ],
        "button_payloads": [f"sdr:open:{SITE}:20261015"],
    }


def test_tap_ids_round_trip_and_reject_junk():
    tap = review.tap_id(review.CLOSED, SITE, DAY)
    assert len(tap) <= 256  # Meta's button id limit
    assert review.parse_tap(tap) == ("closed", str(SITE), DAY)
    assert review.parse_tap("sdr:delete:x:20261015") is None
    assert review.parse_tap("sdr:open:x:2026-10-15") is None
    assert review.parse_tap("sdr:open:x") is None
    assert review.parse_tap("setup_q:time:19:00") is None


# --- taps -----------------------------------------------------------------------


def _actor(*sites: SiteSummary) -> ActorIdentity:
    return ActorIdentity(
        user_id=str(uuid.uuid4()),
        full_name="Ravi",
        role="SITE_ENGINEER",
        organization_id=str(ORG),
        org_name="Acme",
        org_active=True,
        sites=list(sites),
    )


def _tap(value: str):
    return SimpleNamespace(metadata={"interactive_reply_id": value})


async def test_other_taps_are_not_ours():
    assert await review.SiteDayReview(db=None).handle_tap(_tap("setup_q:site_no"), _actor()) is None
    assert await review.SiteDayReview(db=None).handle_tap(SimpleNamespace(metadata={}), _actor()) is None


async def test_a_malformed_tap_has_expired():
    reply = await review.SiteDayReview(db=None).handle_tap(_tap("sdr:closed:zz"), _actor())
    assert reply.text == review.EXPIRED


async def test_a_site_the_person_is_not_on_is_refused():
    reply = await review.SiteDayReview(db=None).handle_tap(
        _tap(review.tap_id(review.CLOSED, SITE, DAY)),
        _actor(SiteSummary(id=str(uuid.uuid4()), name="Other", project_id=str(PROJECT))),
    )
    assert reply.text == review.NOT_YOUR_SITE


class _Db:
    @contextlib.asynccontextmanager
    async def transaction(self):
        yield object()


async def test_site_closed_marks_the_day_no_work(monkeypatch):
    calls = []

    class _Repo:
        def __init__(self, conn):
            pass

        async def set_site_day_conditions(self, **kwargs):
            calls.append(kwargs)

    from mesiri.infrastructure.postgres.repositories import dpr as dpr_module

    monkeypatch.setattr(dpr_module, "PostgresDprRepository", _Repo)
    reply = await review.SiteDayReview(db=_Db()).handle_tap(
        _tap(review.tap_id(review.CLOSED, SITE, DAY)),
        _actor(SiteSummary(id=str(SITE), name="Block A", project_id=str(PROJECT))),
    )
    assert reply.text == review.CLOSED_DONE.format(site="Block A")
    assert calls == [
        {
            "organization_id": ORG,
            "project_id": PROJECT,
            "site_id": SITE,
            "report_date": DAY,
            "changes": {"site_working": "none"},
        }
    ]


async def test_site_closed_on_a_confirmed_day_says_so(monkeypatch):
    from mesiri.application.dpr import site_day
    from mesiri.infrastructure.postgres.repositories import dpr as dpr_module

    class _Repo:
        def __init__(self, conn):
            pass

        async def set_site_day_conditions(self, **kwargs):
            raise site_day.InvalidSiteDayTransition("frozen")

    monkeypatch.setattr(dpr_module, "PostgresDprRepository", _Repo)
    reply = await review.SiteDayReview(db=_Db()).handle_tap(
        _tap(review.tap_id(review.CLOSED, SITE, DAY)),
        _actor(SiteSummary(id=str(SITE), name="Block A", project_id=str(PROJECT))),
    )
    assert reply.text == review.ALREADY_CONFIRMED.format(site="Block A")


# --- the scheduler step -----------------------------------------------------------


class _Conn:
    def __init__(self, messaged=()):
        self.messaged = list(messaged)

    @contextlib.asynccontextmanager
    async def begin_nested(self):
        yield

    async def execute(self, *args, **kwargs):
        rows = [{"site_id": s} for s in self.messaged]
        return SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: rows))


def _day(name, status, blocking, *, has_facts=True, stale=False, site_id=None):
    now = dt.datetime(2026, 10, 15, 13, 30, tzinfo=dt.UTC)
    return {
        "site_id": site_id or uuid.uuid4(),
        "site_name": name,
        "daily_report_id": uuid.uuid4(),
        "status": status,
        "missing_sections": {"blocking": blocking, "optional": []},
        "day_updated_at": now - dt.timedelta(hours=1),
        "last_fact_at": now if stale else None,
        "has_facts": has_facts,
    }


@pytest.fixture
def world(monkeypatch):
    state = {"days": [], "claims": [], "refreshed": [], "refresh_to": None}
    project = {
        "id": PROJECT,
        "organization_id": ORG,
        "name": "Green Towers",
        "report_date": DAY,
        "send_deadline": "21:00",
    }

    async def window(conn, *, now_utc):
        return [project]

    async def days(conn, **kwargs):
        return state["days"]

    async def refresh(conn, *, site_id, **kwargs):
        state["refreshed"].append(site_id)
        return state["refresh_to"]

    async def recipients(conn, db, **kwargs):
        return ["44444444-4444-4444-4444-444444444444"]

    async def for_confirm(conn, **kwargs):
        return {
            "daily_report_id": uuid.uuid4(),
            "status": "READY",
            "payload": {"activity_count": 1, "labour": {"headcount": 9}},
            "drafts": state.get("drafts", []),
        }

    class _Notifications:
        def __init__(self, conn):
            pass

        async def claim(self, **kwargs):
            state["claims"].append(kwargs)
            return uuid.uuid4()

    monkeypatch.setattr(auto_dpr, "projects_in_review_window", window)
    monkeypatch.setattr(auto_dpr, "site_days_for_review", days)
    monkeypatch.setattr(auto_dpr, "refresh_site_day", refresh)
    monkeypatch.setattr(auto_dpr, "site_day_for_confirm", for_confirm)
    monkeypatch.setattr(review, "_recipients", recipients)
    monkeypatch.setattr(notifications_module, "PostgresNotificationRepository", _Notifications)
    return state


async def test_each_day_gets_the_message_it_calls_for(world):
    gap = _day("Block A", "NEEDS_DETAILS", ["labour"])
    ready = _day("Block B", "READY", [])
    silent = _day("Block C", "NEEDS_DETAILS", ["work_done", "labour"], has_facts=False)
    world["days"] = [gap, ready, silent, _day("Block D", "APPROVED", [])]

    assert await review.queue_site_day_reviews(_Conn(), db=None) == 3
    gap_claim, confirm, reminder = world["claims"]
    # WA-05: a ready day -> the confirmation, with Confirm all.
    assert confirm["rule_key"] == f"site_day_confirm:{ready['site_id']}"
    assert [b["title"] for b in confirm["payload"]["buttons"]] == ["Confirm all", "Fix something"]
    assert gap_claim["rule_key"] == f"site_day_gap:{gap['site_id']}"
    assert gap_claim["site_id"] == gap["site_id"]
    assert gap_claim["occurred_on"] == DAY
    assert "missing the *labour count*" in gap_claim["payload"]["message"]
    # WA-06: nothing sent at all -> the no-update reminder.
    assert reminder["rule_key"] == f"site_day_no_update:{silent['site_id']}"
    assert "No update has come in today for *Block C*" in reminder["payload"]["message"]


def test_no_update_reminder_payload_and_template():
    site = uuid.uuid4()
    payload = review.no_update_payload(
        site_id=site,
        site_name="Block A",
        project_name="Green Towers",
        deadline="21:00",
        report_date=DAY,
    )
    closed = review.tap_id(review.CLOSED, site, DAY)
    assert payload["message"] == (
        "📋 No update has come in today for *Block A* (Green Towers).\n"
        "Send today's work, labour and photos here (text, voice note or photo) "
        "before *9:00 pm* so the report goes out.\n"
        "Site closed today? Tap below."
    )
    assert payload["buttons"] == [{"id": closed, "title": "Site closed today"}]
    assert payload["template"] == {
        "name": "mesiri_site_no_update",
        "body_params": ["Block A (Green Towers)", "9:00 pm"],
        "button_payloads": [closed],
    }
    # The template's tap is the same "site closed" tap the message's button sends.
    assert review.parse_tap(closed) == (review.CLOSED, str(site), DAY)


async def test_a_site_already_reminded_today_is_not_reminded_again(world):
    silent = _day("Block C", "NEEDS_DETAILS", ["work_done", "labour"], has_facts=False)
    world["days"] = [silent]

    assert await review.queue_site_day_reviews(_Conn(messaged=[str(silent["site_id"])]), db=None) == 0
    assert world["claims"] == []


async def test_a_site_already_gap_checked_today_is_not_asked_again(world):
    gap = _day("Block A", "NEEDS_DETAILS", ["labour"])
    world["days"] = [gap]

    assert await review.queue_site_day_reviews(_Conn(messaged=[str(gap["site_id"])]), db=None) == 0
    assert world["claims"] == []


async def test_a_changed_day_is_refreshed_before_deciding(world):
    stale = _day("Block A", "NEEDS_DETAILS", ["labour"], stale=True)
    world["days"] = [stale]
    world["refresh_to"] = {"status": "READY", "missing_sections": {"blocking": [], "optional": []}}

    assert await review.queue_site_day_reviews(_Conn(), db=None) == 1
    assert world["refreshed"] == [stale["site_id"]]
    # Ready now: no gap-check, the confirmation instead.
    assert [c["rule_key"] for c in world["claims"]] == [f"site_day_confirm:{stale['site_id']}"]


async def test_an_unsure_item_holds_back_confirm_all(world):
    world["days"] = [_day("Block B", "READY", [])]
    world["drafts"] = [{"confidence": "low", "fields": {}}]

    assert await review.queue_site_day_reviews(_Conn(), db=None) == 1
    payload = world["claims"][0]["payload"]
    assert [b["title"] for b in payload["buttons"]] == ["Fix something"]
    assert "• 1 item I wasn't sure I read right" in payload["message"]


async def test_one_failing_project_does_not_stop_the_tick(world, monkeypatch):
    async def boom(conn, **kwargs):
        raise RuntimeError("db hiccup")

    monkeypatch.setattr(auto_dpr, "site_days_for_review", boom)
    assert await review.queue_site_day_reviews(_Conn(), db=None) == 0


# --- WA-05: the confirmation -------------------------------------------------


_READY = {
    "activity_count": 3,
    "labour": {"headcount": 17},
    "materials": [{"name": "cement"}, {"name": "sand"}],
    "open_issue_count": 1,
    "evidence_count": 1,
}


def test_confirm_message_for_a_clean_day():
    text = review.confirm_message(
        site_name="Block A", project_name="Green Towers", payload=_READY, holds={}, deadline="21:00"
    )
    assert text.splitlines()[:6] == [
        "📋 *Block A* (Green Towers): today's report is ready.",
        "• Work: 3 items",
        "• Labour: 17 workers",
        "• Materials: 2 entries",
        "• Issues: 1 open",
        "• Photos: 1",
    ]
    assert text.endswith("Tap *Confirm all* if it's right. It goes out with the project report at *9:00 pm*.")
    buttons = review.confirm_buttons(SITE, DAY, holds={})
    assert [(b.id, b.title) for b in buttons] == [
        (f"sdr:confirm:{SITE}:20261015", "Confirm all"),
        (f"sdr:fix:{SITE}:20261015", "Fix something"),
    ]


def test_confirm_message_with_holds_offers_only_fix_and_warns_on_stock():
    holds = {"possible_duplicate": 1, "low_confidence": 2, "date_guessed": 1}
    text = review.confirm_message(
        site_name="Block A",
        project_name=None,
        payload={**_READY, "stock_flags": 1},
        holds=holds,
        deadline="21:00",
    )
    assert "⚠️ 1 material is more than the stock on record." in text
    assert "• 1 work item may be a repeat" in text
    assert "• 2 items I wasn't sure I read right" in text
    assert "• 1 forwarded item didn't say which day it was" in text
    assert "Confirm all" not in text
    assert [b.title for b in review.confirm_buttons(SITE, DAY, holds=holds)] == ["Fix something"]


def test_confirm_message_for_a_closed_site():
    text = review.confirm_message(
        site_name="Block B",
        project_name="Block B",
        payload={"conditions": {"site_working": "none"}},
        holds={},
        deadline="21:00",
    )
    assert text.splitlines()[:2] == ["📋 *Block B*: today's report is ready.", "• Site closed today, no work"]


def test_confirm_payload_goes_as_the_review_template_outside_the_window():
    payload = review.confirm_payload(
        site_id=SITE,
        site_name="Block A",
        project_name="Green Towers",
        day_payload=_READY,
        holds={"low_confidence": 1},
        deadline="21:00",
        report_date=DAY,
    )
    assert payload["buttons"] == [{"id": f"sdr:fix:{SITE}:20261015", "title": "Fix something"}]
    assert payload["template"]["name"] == "mesiri_site_day_review"
    assert payload["template"]["body_params"] == [
        "Block A (Green Towers)",
        "Some items need a look before you confirm.",
        "9:00 pm",
    ]
    assert payload["template"]["button_payloads"] == [f"sdr:open:{SITE}:20261015"]


def test_item_taps_round_trip():
    fact = uuid.uuid4()
    tap = review.item_tap_id(review.REMOVE, SITE, DAY, "activity", fact)
    assert len(tap) <= 200  # WhatsApp's reply id limit
    assert review.parse_item_tap(tap) == ("rm", str(SITE), DAY, "activity", str(fact))
    assert review.parse_tap(tap) is None
    assert review.parse_item_tap(f"sdr:confirm:{SITE}:20261015") is None
    assert review.parse_item_tap(f"sdr:drop:{SITE}:20261015:activity:{fact}") is None
    assert review.parse_tap(f"sdr:confirm:{SITE}:20261015") == ("confirm", str(SITE), DAY)
