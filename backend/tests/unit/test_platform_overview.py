"""SA-18: the Overview's rules, without a database -- when a DPR is late,
what needs attention and in what order, the onboarding funnel and which
companies have gone quiet."""

from __future__ import annotations

import datetime as dt
import uuid

from mesiri.application.organizations.companies_overview import CompanyOverview, SetupProgress
from mesiri.application.organizations.platform_overview import (
    attention_items,
    company_counts,
    company_lists,
    late_dprs,
    onboarding_funnel,
)

NOW = dt.datetime(2026, 10, 27, 16, 0, tzinfo=dt.UTC)  # 21:30 in India


def _company(name: str, **kw) -> CompanyOverview:
    setup = kw.pop(
        "setup",
        SetupProgress(has_team=True, has_site=True, first_update_at=None, first_dpr_sent_at=None),
    )
    base = dict(
        id=uuid.uuid4(),
        name=name,
        deployment_type="saas",
        db_route="default",
        status="trial",
        effective_status="trial",
        trial_started_at=NOW - dt.timedelta(days=1),
        trial_ends_at=NOW + dt.timedelta(days=13),
        trial_days_left=13,
        converted_at=None,
        signup_source="whatsapp",
        created_at=NOW - dt.timedelta(days=1),
        updated_at=None,
        setup=setup,
    )
    return CompanyOverview(**{**base, **kw})


def _project(deadline: str, last_sent: dt.date | None, tz: str = "Asia/Kolkata") -> dict:
    return {
        "id": uuid.uuid4(),
        "name": "Tower A",
        "organization_id": uuid.uuid4(),
        "organization_name": "Acme",
        "reporting_timezone": tz,
        "dpr_send_deadline": deadline,
        "dpr_last_sent_on": last_sent,
    }


def test_a_dpr_is_late_only_past_its_own_deadline_plus_grace() -> None:
    today = dt.date(2026, 10, 27)
    projects = [
        _project("21:00", None),  # 21:30 local: past 21:00 + 30 min grace -> late
        _project("21:00", today),  # sent today
        _project("21:15", None),  # inside the grace -> due, not late
        _project("22:00", None),  # not due yet
        _project("21:00", None, "UTC"),  # 16:00 in UTC: not due yet
        _project("bad", None),  # a bad deadline reads 21:00 -> late
    ]

    late, due, sent = late_dprs(projects, NOW)

    assert [p["dpr_send_deadline"] for p in late] == ["21:00", "bad"]
    assert (due, sent) == (4, 1)


def test_attention_is_ranked_critical_first_and_names_the_companies() -> None:
    asked = _company("Asked", open_continue_requests=1)
    ending = _company("Ending", trial_days_left=2)
    quiet_trial = _company("No Update", trial_started_at=NOW - dt.timedelta(days=4))
    stuck = _company(
        "Stuck",
        created_at=NOW - dt.timedelta(days=5),
        setup=SetupProgress(
            has_team=False, has_site=True, first_update_at=NOW, first_dpr_sent_at=None
        ),
    )
    letterhead = _company("Letterhead", open_branding_requests=2)
    late = [_project("21:00", None)]

    items = attention_items(
        [asked, ending, quiet_trial, stuck, letterhead],
        now=NOW,
        failed_24h=3,
        unanswered={"count": 0, "oldest": None},
        late=late,
    )

    keys = [i["key"] for i in items]
    assert keys[:2] == ["failed", "late_dpr"]  # critical first; no unanswered row at 0
    assert {"continue", "trial_ending", "at_risk", "setup_stuck", "branding"} <= set(keys)
    by_key = {i["key"]: i for i in items}
    assert by_key["failed"]["link"] == "/logs?status=failed"
    assert by_key["continue"]["companies"][0]["name"] == "Asked"
    assert by_key["continue"]["link"] == f"/organizations/{asked.id}"
    assert by_key["trial_ending"]["companies"][0]["note"] == "2 days left"
    assert by_key["at_risk"]["companies"][0]["note"] == "day 5 of trial"
    assert by_key["setup_stuck"]["companies"][0]["note"] == "no site reporter yet"
    assert by_key["branding"]["link"] == "/branding-requests"


def test_nothing_to_do_is_an_empty_list() -> None:
    assert (
        attention_items(
            [_company("Fine")],
            now=NOW,
            failed_24h=0,
            unanswered={"count": 0, "oldest": None},
            late=[],
        )
        == []
    )


def test_counts_and_funnel() -> None:
    paying = _company(
        "Paying",
        status="active",
        effective_status="active",
        converted_at=NOW - dt.timedelta(days=2),
        trial_days_left=None,
        setup=SetupProgress(True, True, NOW, NOW),
    )
    old = _company("Old", effective_status="expired", trial_started_at=NOW - dt.timedelta(days=60))
    new = _company("New", setup=SetupProgress(False, True, None, None))

    counts = company_counts([paying, old, new], NOW)
    funnel = onboarding_funnel([paying, old, new], NOW)

    assert (counts["total"], counts["active"], counts["trial"], counts["expired"]) == (3, 1, 1, 1)
    assert (counts["new_trials_7d"], counts["converted_30d"]) == (2, 1)
    assert funnel == {
        "started": 2,
        "has_site": 2,
        "has_team": 1,
        "first_update": 1,
        "first_dpr": 1,
        "converted": 1,
    }


def test_most_active_and_gone_quiet() -> None:
    busy, quiet, never, expired = (_company(n) for n in ("Busy", "Quiet", "Never", "Expired"))
    never = _company("Never", created_at=NOW - dt.timedelta(days=6))
    expired = _company("Expired", effective_status="expired")
    activity = [
        {
            "organization_id": busy.id,
            "messages": 40,
            "people": 3,
            "dprs_sent": 5,
            "last_message_at": NOW - dt.timedelta(hours=1),
        },
        {
            "organization_id": quiet.id,
            "messages": 0,
            "people": 0,
            "dprs_sent": 0,
            "last_message_at": NOW - dt.timedelta(days=4),
        },
        {
            "organization_id": expired.id,
            "messages": 0,
            "people": 0,
            "dprs_sent": 0,
            "last_message_at": NOW - dt.timedelta(days=9),
        },
    ]

    active, gone = company_lists([busy, quiet, never, expired], activity, NOW)

    assert [r["name"] for r in active] == ["Busy"]
    assert active[0]["messages_7d"] == 40 and active[0]["dprs_7d"] == 5
    # Quietest first; an expired trial isn't "quiet", it's over.
    assert [(r["name"], r["quiet_days"]) for r in gone] == [("Never", 6), ("Quiet", 4)]
