"""BE-09: save first, confirm later -- review states, confirming, rejecting
through each module's own undo, and what the DPR shows (fake connection, no
Postgres)."""

from __future__ import annotations

import datetime
import uuid

import pytest

from mesiri.application.dpr import fact_review
from mesiri.application.dpr.assembly import build_site_report_payload
from mesiri.application.dpr.fact_review import (
    CONFIRMED,
    DRAFT,
    REJECTED,
    FactReviewError,
)
from mesiri.infrastructure.postgres.repositories.fact_reviews import PostgresFactReviewRepository

ORG = uuid.uuid4()
PROJECT = uuid.uuid4()
SITE = uuid.uuid4()
DAY = datetime.date(2026, 10, 13)


# ---------------------------------------------------------------------------
# Pure rules
# ---------------------------------------------------------------------------


def test_a_fact_with_no_review_row_is_confirmed():
    assert fact_review.state_of(None) == CONFIRMED


def test_confirming_a_draft_changes_it_and_repeating_is_harmless():
    assert fact_review.check_confirm(DRAFT) is True
    assert fact_review.check_confirm(CONFIRMED) is False


def test_a_rejected_fact_cannot_be_confirmed():
    with pytest.raises(FactReviewError):
        fact_review.check_confirm(REJECTED)


@pytest.mark.parametrize("state", [CONFIRMED, REJECTED])
def test_only_drafts_are_rejected(state):
    with pytest.raises(FactReviewError):
        fact_review.check_reject(state)


def test_review_counts_per_section():
    counts = fact_review.review_counts(
        {
            fact_review.ACTIVITY: {"a1": DRAFT, "a2": CONFIRMED},
            fact_review.LABOUR_REPORT: {"l1": DRAFT},
            fact_review.MATERIAL_RECEIPT: {"r1": DRAFT},
            fact_review.MATERIAL_USAGE: {"u1": DRAFT},
        }
    )
    assert counts == {"activities": 1, "issues": 0, "labour_reports": 1, "materials": 2, "total": 4}


# ---------------------------------------------------------------------------
# Fake connection
# ---------------------------------------------------------------------------


class _Result:
    def __init__(self, rows=None):
        self._rows = rows or []
        self.rowcount = 1

    def mappings(self):
        return self

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return self._rows


class _Conn:
    def __init__(self, answers=None):
        self.answers = answers or {}
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, statement, params=None):
        sql = str(statement)
        self.calls.append((sql, params or {}))
        for fragment, result in self.answers.items():
            if fragment in sql:
                return result
        return _Result()

    def appended(self):
        return [p for sql, p in self.calls if "INSERT INTO fact_reviews" in sql]


LOCATED = {"project_id": PROJECT, "site_id": SITE, "fact_date": DAY}


def _conn(*, latest_state=None, day_status=None):
    answers = {
        # _locate, for any fact type
        "AS fact_date FROM": _Result([LOCATED]),
        "SELECT DISTINCT ON (fact_id) fact_id, state": _Result(
            [{"fact_id": FACT, "state": latest_state}] if latest_state else []
        ),
    }
    if day_status:
        answers["SELECT id, status::text AS status FROM daily_reports"] = _Result(
            [{"id": uuid.uuid4(), "status": day_status}]
        )
    return _Conn(answers)


FACT = uuid.uuid4()


# ---------------------------------------------------------------------------
# States, drafts, confirming
# ---------------------------------------------------------------------------


async def test_states_default_to_confirmed_and_take_the_latest_row():
    other = uuid.uuid4()
    conn = _conn(latest_state=DRAFT)

    states = await PostgresFactReviewRepository(conn).states_for(fact_review.ACTIVITY, [FACT, other])

    assert states == {FACT: DRAFT, other: CONFIRMED}
    assert "ORDER BY fact_id, created_at DESC" in conn.calls[0][0]


async def test_states_for_no_facts_reads_nothing():
    conn = _Conn()
    assert await PostgresFactReviewRepository(conn).states_for(fact_review.ACTIVITY, []) == {}
    assert conn.calls == []


async def test_an_unknown_fact_type_is_refused():
    with pytest.raises(FactReviewError):
        await PostgresFactReviewRepository(_Conn()).states_for("expense", [FACT])


async def test_marking_a_draft_copies_where_and_when_it_happened():
    conn = _conn()
    extraction_id = uuid.uuid4()

    await PostgresFactReviewRepository(conn).mark_draft(
        organization_id=ORG, fact_type=fact_review.LABOUR_REPORT, fact_id=FACT, extraction_id=extraction_id
    )

    [row] = conn.appended()
    assert row["state"] == DRAFT
    assert (row["project_id"], row["site_id"], row["fact_date"]) == (PROJECT, SITE, DAY)
    assert row["extraction_id"] == extraction_id
    assert "labour_attendance_reports" in conn.calls[0][0]
    assert "clock_timestamp()" in next(sql for sql, _ in conn.calls if "INSERT INTO fact_reviews" in sql)


async def test_an_unknown_fact_cannot_be_marked():
    conn = _Conn({"AS fact_date FROM": _Result([])})
    with pytest.raises(FactReviewError):
        await PostgresFactReviewRepository(conn).mark_draft(
            organization_id=ORG, fact_type=fact_review.ACTIVITY, fact_id=FACT
        )


async def test_confirming_a_draft_appends_a_confirmation():
    conn = _conn(latest_state=DRAFT)
    actor = uuid.uuid4()

    changed = await PostgresFactReviewRepository(conn).confirm(
        organization_id=ORG, fact_type=fact_review.ACTIVITY, fact_id=FACT, actor_user_id=actor
    )

    assert changed is True
    [row] = conn.appended()
    assert row["state"] == CONFIRMED and row["actor_user_id"] == actor


async def test_confirming_an_already_confirmed_fact_writes_nothing():
    conn = _conn()  # no review row: confirmed
    changed = await PostgresFactReviewRepository(conn).confirm(
        organization_id=ORG, fact_type=fact_review.ACTIVITY, fact_id=FACT, actor_user_id=None
    )
    assert changed is False
    assert conn.appended() == []


async def test_the_days_drafts_are_confirmed_together():
    a, b = uuid.uuid4(), uuid.uuid4()
    conn = _Conn(
        {
            "WHERE state = 'draft'": _Result(
                [
                    {"fact_type": "activity", "fact_id": a, **LOCATED},
                    {"fact_type": "labour_report", "fact_id": b, **LOCATED},
                ]
            )
        }
    )

    count = await PostgresFactReviewRepository(conn).confirm_drafts_for_day(
        organization_id=ORG, site_id=SITE, report_date=DAY, actor_user_id=None
    )

    assert count == 2
    assert [(r["fact_type"], r["state"]) for r in conn.appended()] == [
        ("activity", CONFIRMED),
        ("labour_report", CONFIRMED),
    ]


# ---------------------------------------------------------------------------
# Rejecting -- always through the owning module's own undo
# ---------------------------------------------------------------------------


@pytest.fixture
def undo_calls(monkeypatch):
    calls: list[tuple[str, dict]] = []

    from mesiri.domains.materials import router as materials_router
    from mesiri.infrastructure.postgres.repositories import progress, workforce

    async def void_activity(self, **kwargs):
        calls.append(("void_activity", kwargs))
        return None

    async def cancel_issue(self, organization_id, issue_id, notes):
        calls.append(("cancel_issue", {"issue_id": issue_id, "notes": notes}))
        return True

    async def void_attendance_report(self, **kwargs):
        calls.append(("void_attendance_report", kwargs))
        return None

    async def reverse_material_record(conn, **kwargs):
        calls.append(("reverse_material_record", kwargs))
        return uuid.uuid4()

    monkeypatch.setattr(progress.PostgresProgressReadRepository, "void_activity", void_activity)
    monkeypatch.setattr(progress.PostgresProgressReadRepository, "cancel_issue", cancel_issue)
    monkeypatch.setattr(
        workforce.PostgresWorkforceReadRepository, "void_attendance_report", void_attendance_report
    )
    monkeypatch.setattr(materials_router, "reverse_material_record", reverse_material_record)
    return calls


@pytest.mark.parametrize(
    ("fact_type", "undo"),
    [
        (fact_review.ACTIVITY, "void_activity"),
        (fact_review.SITE_ISSUE, "cancel_issue"),
        (fact_review.LABOUR_REPORT, "void_attendance_report"),
        (fact_review.MATERIAL_RECEIPT, "reverse_material_record"),
        (fact_review.MATERIAL_USAGE, "reverse_material_record"),
    ],
)
async def test_rejecting_a_draft_uses_its_modules_own_undo_then_records_why(fact_type, undo, undo_calls):
    conn = _conn(latest_state=DRAFT)

    await PostgresFactReviewRepository(conn).reject(
        organization_id=ORG, fact_type=fact_type, fact_id=FACT, actor_user_id=None, reason=" wrong site "
    )

    assert [name for name, _ in undo_calls] == [undo]
    if fact_type == fact_review.MATERIAL_RECEIPT:
        assert undo_calls[0][1]["kind"] == "receipt"
    if fact_type == fact_review.MATERIAL_USAGE:
        assert undo_calls[0][1]["kind"] == "usage"
    [row] = conn.appended()
    assert (row["state"], row["note"]) == (REJECTED, "wrong site")


async def test_a_reason_is_required_to_reject(undo_calls):
    with pytest.raises(FactReviewError):
        await PostgresFactReviewRepository(_conn(latest_state=DRAFT)).reject(
            organization_id=ORG, fact_type=fact_review.ACTIVITY, fact_id=FACT, actor_user_id=None, reason=" "
        )
    assert undo_calls == []


async def test_a_confirmed_fact_is_not_rejected_here(undo_calls):
    with pytest.raises(FactReviewError):
        await PostgresFactReviewRepository(_conn()).reject(
            organization_id=ORG, fact_type=fact_review.ACTIVITY, fact_id=FACT, actor_user_id=None, reason="x"
        )
    assert undo_calls == []


async def test_nothing_is_rejected_on_a_confirmed_day(undo_calls):
    conn = _conn(latest_state=DRAFT, day_status="APPROVED")
    with pytest.raises(FactReviewError):
        await PostgresFactReviewRepository(conn).reject(
            organization_id=ORG, fact_type=fact_review.LABOUR_REPORT, fact_id=FACT, actor_user_id=None, reason="x"
        )
    assert undo_calls == []
    assert conn.appended() == []


async def test_a_module_refusing_its_undo_stops_the_rejection(monkeypatch):
    from mesiri.infrastructure.postgres.repositories import progress

    async def refuse(self, **kwargs):
        return "activity not found"

    monkeypatch.setattr(progress.PostgresProgressReadRepository, "void_activity", refuse)
    conn = _conn(latest_state=DRAFT)

    with pytest.raises(FactReviewError, match="activity not found"):
        await PostgresFactReviewRepository(conn).reject(
            organization_id=ORG, fact_type=fact_review.ACTIVITY, fact_id=FACT, actor_user_id=None, reason="x"
        )
    assert conn.appended() == []


async def test_an_extraction_records_what_the_ai_read():
    conn = _Conn()

    extraction_id = await PostgresFactReviewRepository(conn).record_extraction(
        organization_id=ORG,
        extracted={"workers": 16, "trade": "mason"},
        correlation_id="c-1",
        model="gemini-2.5-flash",
        confidence="high",
    )

    sql, params = conn.calls[0]
    assert "INSERT INTO extractions" in sql
    assert params["id"] == extraction_id
    assert params["model"] == "gemini-2.5-flash" and params["confidence"] == "high"
    assert '"workers": 16' in params["extracted"]


# ---------------------------------------------------------------------------
# What the DPR shows
# ---------------------------------------------------------------------------


def test_the_payload_marks_drafts_and_counts_them():
    draft_activity, confirmed_activity, issue = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    payload = build_site_report_payload(
        project_name="P",
        site_name="S",
        report_date=DAY,
        activity_rows=[{"id": draft_activity}, {"id": confirmed_activity}],
        quantities_by_activity={},
        evidence_count_by_activity={},
        issue_rows=[{"id": issue, "status": "OPEN"}],
        review_states={
            fact_review.ACTIVITY: {draft_activity: DRAFT, confirmed_activity: CONFIRMED},
            fact_review.SITE_ISSUE: {issue: DRAFT},
        },
    )

    assert [a["review"] for a in payload["activities"]] == [DRAFT, CONFIRMED]
    assert payload["issues"][0]["review"] == DRAFT
    assert payload["drafts"]["total"] == 2


def test_a_payload_without_review_states_is_all_confirmed():
    payload = build_site_report_payload(
        project_name="P",
        site_name="S",
        report_date=DAY,
        activity_rows=[{"id": uuid.uuid4()}],
        quantities_by_activity={},
        evidence_count_by_activity={},
        issue_rows=[],
    )
    assert payload["activities"][0]["review"] == CONFIRMED
    assert payload["drafts"]["total"] == 0


async def test_confirming_a_day_confirms_its_drafts_and_rebuilds_the_version(monkeypatch):
    from mesiri.infrastructure.postgres.repositories import dpr as dpr_module
    from mesiri.infrastructure.postgres.repositories import fact_reviews as reviews_module

    report_id = uuid.uuid4()
    conn = _Conn(
        {
            "level::text AS level": _Result(
                [
                    {
                        "project_id": PROJECT,
                        "site_id": SITE,
                        "report_date": DAY,
                        "level": "SITE",
                        "status": "IN_REVIEW",
                    }
                ]
            )
        }
    )
    repo = dpr_module.PostgresDprRepository(conn)
    events: list[str] = []

    async def confirm_drafts_for_day(self, **kwargs):
        events.append("confirm_drafts")
        return 2

    async def assemble(**kwargs):
        events.append("assemble")
        return {"activity_count": 1}

    async def create_version(*, daily_report_id, payload):
        events.append("create_version")
        return {"id": uuid.uuid4()}

    monkeypatch.setattr(
        reviews_module.PostgresFactReviewRepository, "confirm_drafts_for_day", confirm_drafts_for_day
    )
    monkeypatch.setattr(repo, "assemble_site_report_payload", assemble)
    monkeypatch.setattr(repo, "create_version", create_version)

    assert await repo.approve_report(organization_id=ORG, user_id=uuid.uuid4(), report_id=report_id, notes=None)
    assert events == ["confirm_drafts", "assemble", "create_version"]


async def test_the_dpr_leaves_out_withdrawn_issues_and_reversed_materials():
    import inspect

    from mesiri.infrastructure.postgres.repositories.dpr import PostgresDprRepository

    source = inspect.getsource(PostgresDprRepository.assemble_site_report_payload)
    assert "status != 'CANCELLED'" in source
    assert "mm.reversal_of_movement_id IS NULL" in source
    assert "r.reversal_of_movement_id = mm.id" in source
