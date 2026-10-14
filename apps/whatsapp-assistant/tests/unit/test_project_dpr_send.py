"""BE-16: the WhatsApp side sends a due project DPR -- renders the PDF if
needed, notifies each recipient, marks it sent; one project's failure
does not stop the others. Backend calls are faked; no Postgres, no
Playwright."""

from __future__ import annotations

import contextlib
import datetime
import uuid

import pytest

import runtime.project_auto_dpr as sender
import runtime.render_pending_dpr_pdfs as render_module
from mesiri.application.projects import auto_dpr
from mesiri.infrastructure.postgres.repositories import dpr as dpr_repo_module
from mesiri.infrastructure.postgres.repositories import notifications as notifications_module

TODAY = datetime.date(2026, 10, 13)


class _Conn:
    def __init__(self):
        self.savepoints = 0
        self.rolled_back = 0

    @contextlib.asynccontextmanager
    async def begin_nested(self):
        self.savepoints += 1
        try:
            yield
        except Exception:
            self.rolled_back += 1
            raise


class _Repo:
    reports: dict = {}
    keys_set: list = []

    def __init__(self, conn):
        pass

    async def get_report_for_pdf(self, *, organization_id, report_id):
        return type(self).reports.get(report_id)

    async def set_rendered_object_key(self, *, version_id, object_key):
        type(self).keys_set.append((version_id, object_key))


class _Notifications:
    claims: list = []

    def __init__(self, conn):
        pass

    async def claim(self, **kwargs):
        type(self).claims.append(kwargs)


@pytest.fixture
def world(monkeypatch):
    state = {"due": [], "targets": {}, "sent": [], "rendered": [], "fail_render_for": set()}
    _Repo.reports = {}
    _Repo.keys_set = []
    _Notifications.claims = []

    async def no_letterhead(*_args):
        # This fake world has no company rows; the letterhead (BE-19) has its
        # own tests in test_dpr_letterhead*.py.
        return None

    monkeypatch.setattr("channel.dpr_document.letterhead.load_letterhead", no_letterhead)

    async def due_project_sends(conn, *, now_utc):
        return state["due"]

    async def finalize_project_dpr(conn, *, organization_id, project_id, report_date):
        return state["targets"].get(project_id)

    async def mark_project_dpr_sent(conn, *, project_id, report_date, daily_report_id):
        state["sent"].append(project_id)

    async def render_and_store_version(**kwargs):
        if kwargs["daily_report_id"] in state["fail_render_for"]:
            raise RuntimeError("chromium crashed")
        state["rendered"].append(kwargs["version_id"])
        return f"dpr/{kwargs['daily_report_id']}/{kwargs['version_id']}.pdf"

    async def recipients(db, *, organization_id, project_id):
        return [str(uuid.uuid4()), str(uuid.uuid4())]

    monkeypatch.setattr(auto_dpr, "due_project_sends", due_project_sends)
    monkeypatch.setattr(auto_dpr, "finalize_project_dpr", finalize_project_dpr)
    monkeypatch.setattr(auto_dpr, "mark_project_dpr_sent", mark_project_dpr_sent)
    monkeypatch.setattr(render_module, "render_and_store_version", render_and_store_version)
    monkeypatch.setattr(sender, "_project_dpr_recipients", recipients)
    monkeypatch.setattr(dpr_repo_module, "PostgresDprRepository", _Repo)
    monkeypatch.setattr(notifications_module, "PostgresNotificationRepository", _Notifications)
    return state


def _project(state, *, reason="all_confirmed", rendered_key=None, payload=None):
    project_id = uuid.uuid4()
    report_id = uuid.uuid4()
    state["due"].append(
        {"id": project_id, "organization_id": uuid.uuid4(), "report_date": TODAY, "reason": reason}
    )
    state["targets"][project_id] = {"daily_report_id": report_id, "site_id": None, "level": "PROJECT"}
    _Repo.reports[report_id] = {
        "version_id": uuid.uuid4(),
        "code": "DPR-P-1",
        "payload": payload or {"level": "PROJECT", "total_site_count": 2, "reported_site_count": 2},
        "rendered_object_key": rendered_key,
    }
    return project_id, report_id


async def _send(conn=None):
    return await sender.send_due_project_dprs(
        conn or _Conn(), db=None, renderer=object(), object_storage=object()
    )


async def test_a_due_project_is_rendered_sent_to_each_recipient_and_marked_sent(world):
    project_id, report_id = _project(world)

    assert await _send() == 1

    assert len(world["rendered"]) == 1
    assert len(_Repo.keys_set) == 1
    assert world["sent"] == [project_id]
    assert len(_Notifications.claims) == 2
    first, second = _Notifications.claims
    assert first["subject_id"] != second["subject_id"]  # one slot per recipient
    assert first["payload"]["document_object_key"] == f"dpr/{report_id}/{_Repo.reports[report_id]['version_id']}.pdf"
    assert first["payload"]["message"] == "Today's DPR (DPR-P-1) is attached."


async def test_an_already_rendered_pdf_is_not_rendered_again(world):
    _project(world, rendered_key="dpr/existing.pdf")

    await _send()

    assert world["rendered"] == []
    assert _Notifications.claims[0]["payload"]["document_object_key"] == "dpr/existing.pdf"


async def test_the_message_says_how_many_sites_did_not_report(world):
    _project(
        world,
        reason="deadline",
        payload={"level": "PROJECT", "total_site_count": 3, "reported_site_count": 1},
    )

    await _send()

    assert _Notifications.claims[0]["payload"]["message"] == (
        "Today's DPR (DPR-P-1) is attached. 2 of 3 sites not reported."
    )


async def test_one_failing_project_is_rolled_back_and_the_others_still_go(world):
    _, bad_report = _project(world)
    good_project, _ = _project(world)
    world["fail_render_for"].add(bad_report)
    conn = _Conn()

    assert await _send(conn) == 1

    assert world["sent"] == [good_project]
    assert conn.rolled_back == 1


async def test_nothing_due_builds_nothing(world, monkeypatch):
    def _boom(*_args, **_kwargs):
        raise AssertionError("renderer must not be built when nothing is due")

    monkeypatch.setattr("channel.dpr_document.render.DprPdfRenderer", _boom)

    assert await sender.send_due_project_dprs(_Conn(), db=None) == 0
