"""PRC-20: a due weekly / monthly report rides the automations runner, built per person by the backend.

Guards: a SEND_PERIOD_REPORT automation never goes through the one-payload-for-everyone path (each person must get
their own access's report); it is marked run once; a failure leaves it unmarked so the next tick tries again; the
other actions keep their path. The PDF a notification carries keeps its own file name (the DPR keeps "DPR.pdf").
"""

from __future__ import annotations

import datetime

import pytest

from runtime import automation_runner
from runtime.send_pending_notifications import _document_filename


class _Automations:
    def __init__(self, rows):
        self.rows, self.marked = rows, []

    async def list_enabled(self):
        return self.rows

    async def mark_run(self, *, automation_id, ran_on):
        self.marked.append(automation_id)


class _Notifications:
    def __init__(self):
        self.claimed = []

    async def claim(self, **kw):
        self.claimed.append(kw)
        return "n1"


def _row(action, **extra):
    return {"id": f"a-{action}", "organization_id": "00000000-0000-0000-0000-000000000001", "action": action,
            "audience": "SELF", "created_by": "00000000-0000-0000-0000-0000000000aa", "frequency": "DAILY",
            "day_of_week": None, "time_of_day": "00:00", "timezone": "UTC", "last_run_on": None, "project_id": None,
            "site_id": None, "message": "Hello", **extra}


@pytest.fixture
def wired(monkeypatch):
    autos, notes, sent = _Automations([]), _Notifications(), []
    monkeypatch.setattr("mesiri.infrastructure.postgres.repositories.automations.PostgresAutomationRepository",
                        lambda conn: autos)
    monkeypatch.setattr("mesiri.infrastructure.postgres.repositories.notifications.PostgresNotificationRepository",
                        lambda conn: notes)

    async def audience(*, db, compliance_query, automation):
        return [automation["created_by"]]

    monkeypatch.setattr("runtime.automation_audience.resolve_audience", audience)

    async def report(conn, automation, recipients):
        sent.append((automation["id"], recipients))
        return {"queued": len(recipients), "skipped": 0}

    monkeypatch.setattr(automation_runner, "_send_period_report", report)
    return autos, notes, sent


async def test_a_due_report_is_built_per_person_by_the_backend(wired):
    autos, notes, sent = wired
    autos.rows = [_row("SEND_PERIOD_REPORT", frequency="WEEKLY",
                       day_of_week=datetime.datetime.now(datetime.UTC).weekday()), _row("REMINDER")]
    fired = await automation_runner._queue_due_automations(object(), db=object())
    assert fired == 2
    assert sent == [("a-SEND_PERIOD_REPORT", ["00000000-0000-0000-0000-0000000000aa"])]
    # Only the reminder went through the shared one-payload claim.
    assert [c["rule_key"] for c in notes.claimed] == ["automation:a-REMINDER"]
    assert autos.marked == ["a-SEND_PERIOD_REPORT", "a-REMINDER"]


async def test_a_failed_report_is_not_marked_run(wired, monkeypatch):
    autos, _, _ = wired

    async def boom(conn, automation, recipients):
        raise RuntimeError("storage down")

    monkeypatch.setattr(automation_runner, "_send_period_report", boom)
    autos.rows = [_row("SEND_PERIOD_REPORT", frequency="WEEKLY",
                       day_of_week=datetime.datetime.now(datetime.UTC).weekday())]
    assert await automation_runner._queue_due_automations(object(), db=object()) == 0
    assert autos.marked == []


def test_a_notification_names_its_own_pdf_and_the_dpr_keeps_its_name():
    assert _document_filename({"document_filename": "Villa-Kakkanad-week-45.pdf"}) == "Villa-Kakkanad-week-45.pdf"
    assert _document_filename({}) == "DPR.pdf"
    assert _document_filename({"document_filename": "../etc/passwd"}) == "DPR.pdf"
    assert _document_filename({"document_filename": "report.exe"}) == "DPR.pdf"
