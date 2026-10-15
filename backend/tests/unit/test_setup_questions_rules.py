"""SS-14: daily setup question rules and branding requests (no database)."""

from __future__ import annotations

import datetime as dt

import pytest

from mesiri.domains.organizations import settings as org_settings
from mesiri.domains.organizations import setup_questions as rules

CREATED = dt.date(2026, 10, 15)
NOW = dt.datetime(2026, 10, 15, 10, tzinfo=dt.UTC)


def _next(progress, day_offset=0):
    return rules.next_question(
        progress, today=CREATED + dt.timedelta(days=day_offset), company_created_on=CREATED
    )


def test_questions_come_in_order_one_a_day() -> None:
    progress: dict = {}
    assert _next(progress) == rules.BRANDING
    progress = rules.record(progress, rules.BRANDING, rules.ASKED, today=CREATED)
    assert _next(progress) is None  # one a day
    assert _next(progress, 1) == rules.REPORT_TIME  # asked, never answered: not asked again
    progress = rules.record(
        progress, rules.REPORT_TIME, rules.SKIPPED, today=CREATED + dt.timedelta(days=1)
    )
    assert _next(progress, 1) == rules.MORE_SITES  # skipping doesn't use up the day
    progress = rules.record(
        progress, rules.MORE_SITES, rules.ANSWERED, today=CREATED + dt.timedelta(days=2)
    )
    assert _next(progress, 3) is None  # all done


def test_nothing_after_the_ask_window() -> None:
    assert _next({}, rules.ASK_WITHIN_DAYS) == rules.BRANDING
    assert _next({}, rules.ASK_WITHIN_DAYS + 1) is None


def test_bad_stored_progress_starts_over() -> None:
    assert _next("garbage") == rules.BRANDING


def test_record_rejects_unknown_question() -> None:
    with pytest.raises(ValueError):
        rules.record({}, "favourite_colour", rules.ASKED, today=CREATED)


def test_branding_files_collect_into_one_open_request() -> None:
    requests, started = rules.add_branding_files(
        [], object_key="a.jpg", content_type="image/jpeg", sent_by="u1", now=NOW
    )
    assert started and len(requests) == 1
    requests, started = rules.add_branding_files(
        requests, object_key="b.jpg", content_type="image/jpeg", sent_by="u1", now=NOW
    )
    assert not started
    assert [f["object_key"] for f in requests[0]["files"]] == ["a.jpg", "b.jpg"]
    assert requests[0]["status"] == rules.OPEN


def test_a_done_request_is_announced_once_and_new_files_start_a_new_one() -> None:
    requests, _ = rules.add_branding_files(
        [], object_key="a.jpg", content_type=None, sent_by="u1", now=NOW
    )
    assert rules.request_to_announce(requests) is None  # still open
    requests[0] = {**requests[0], "status": rules.DONE, "done_at": NOW.isoformat()}
    finished = rules.request_to_announce(requests)
    assert finished is not None
    requests = rules.mark_announced(requests, finished["id"])
    assert rules.request_to_announce(requests) is None

    requests, started = rules.add_branding_files(
        requests, object_key="c.jpg", content_type=None, sent_by="u1", now=NOW
    )
    assert started and len(requests) == 2


@pytest.mark.parametrize("key", [org_settings.SETUP_PROGRESS, org_settings.BRANDING_REQUESTS])
def test_generic_settings_api_refuses_the_assistant_keys(key) -> None:
    with pytest.raises(ValueError, match="own page"):
        org_settings.validate(key, {})
