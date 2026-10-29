"""WEB-27: the DPR as a live document -- the PDF's own HTML, filled from the
day as it stands now. Access mirrors the DPR pages; nothing is written."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dpr_preview import router as preview
from mesiri.domains.projects.router import get_auth_context
from mesiri.infrastructure.objectstorage.dependency import get_object_storage
from mesiri.infrastructure.postgres.dependency import get_db_conn

ORG = uuid.uuid4()
PROJECT = uuid.uuid4()
SITE = uuid.uuid4()
DAY = "2026-10-24"

SITE_PAYLOAD = {
    "project_name": "Skyline",
    "site_name": "Tower 1",
    "report_date": DAY,
    "activities": [
        {
            "work_type": "slab_shuttering",
            "narrative": "5th floor <b>east</b>",
            "status": "IN_PROGRESS",
        },
        {
            "work_type": "tiling",
            "narrative": "Cancelled tiling",
            "status": "PLANNED",
            "review": "rejected",
        },
    ],
    "activity_count": 2,
    "labour": {"headcount": 24, "trades": [{"trade": "mason", "headcount": 24}]},
}
ITEMS = [
    {"section": "work", "review": "draft", "title": "Slab shuttering"},
    {"section": "work", "review": "rejected", "title": "Tiling"},
]
PROJECT_PAYLOAD = {
    "level": "PROJECT",
    "project_name": "Skyline",
    "report_date": DAY,
    "sites": [{"site_name": "Tower 1", "reported": True, "headcount": 24}],
    "reported_site_count": 1,
    "total_site_count": 1,
}


class FakeRepo:
    calls: list[str] = []
    site: dict | None = {"project_id": PROJECT}

    def __init__(self, conn):
        pass

    async def find_site(self, *, organization_id, site_id):
        return self.site

    async def assemble_site_day(self, **_):
        return dict(SITE_PAYLOAD), list(ITEMS)

    async def get_current_summary(self, **_):
        return "All on track."

    async def get_current_payload(self, **_):
        FakeRepo.calls.append("sent")
        return dict(PROJECT_PAYLOAD)

    async def assemble_project_report_payload(self, *, preview, **_):
        assert preview is True  # the preview writes nothing
        FakeRepo.calls.append("preview")
        return dict(PROJECT_PAYLOAD), []


@pytest.fixture
def client(monkeypatch):
    FakeRepo.calls = []
    FakeRepo.site = {"project_id": PROJECT}
    state = SimpleNamespace(report=None, denied=False)

    async def report_row(conn, org_id, project_id, report_date, site_id=None):
        return state.report

    async def no_letterhead(*_):
        return None

    monkeypatch.setattr(preview, "PostgresDprRepository", FakeRepo)
    # The day itself is read through Day Facts (request 143), from the same repository.
    from mesiri.infrastructure.postgres.repositories import dpr as dpr_repo

    monkeypatch.setattr(dpr_repo, "PostgresDprRepository", FakeRepo)
    monkeypatch.setattr(preview, "_report_row", report_row)
    monkeypatch.setattr(preview, "_letterhead", no_letterhead)
    monkeypatch.setattr(preview, "_site_denied", lambda auth, p, s: state.denied)
    monkeypatch.setattr(preview, "_resolve_project_ids", lambda auth, p: (set(), state.denied))
    app = FastAPI()
    app.include_router(preview.router)
    app.dependency_overrides[get_auth_context] = lambda: SimpleNamespace(organization_id=ORG)
    app.dependency_overrides[get_db_conn] = lambda: object()
    app.dependency_overrides[get_object_storage] = lambda: None
    c = TestClient(app)
    c.state = state
    return c


def test_site_document_is_the_live_day_without_what_was_cancelled(client):
    res = client.get(f"/dpr/site-days/{SITE}/document", params={"date": DAY})
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/html")
    assert res.headers["cache-control"] == "no-store"
    html = res.text
    assert "Daily Progress Report" in html and "Tower 1" in html
    assert preview.LIVE_CODE in html
    assert "Slab Shuttering" in html
    assert "Cancelled tiling" not in html
    assert "5th floor &lt;b&gt;east&lt;/b&gt;" in html  # escaped, never markup


def test_site_document_carries_the_code_once_confirmed(client):
    client.state.report = {"id": uuid.uuid4(), "code": "DPR-20261024-T1", "status": "approved"}
    html = client.get(f"/dpr/site-days/{SITE}/document", params={"date": DAY}).text
    assert "DPR-20261024-T1" in html
    assert preview.LIVE_CODE not in html
    assert "All on track." in html


def test_a_draft_report_row_still_reads_as_live(client):
    client.state.report = {"id": uuid.uuid4(), "code": "DPR-20261024-T1", "status": "draft"}
    html = client.get(f"/dpr/site-days/{SITE}/document", params={"date": DAY}).text
    assert preview.LIVE_CODE in html
    assert "DPR-20261024-T1" not in html


@pytest.mark.parametrize("case", ["unknown", "no_project", "denied"])
def test_site_document_is_404_outside_the_callers_sites(client, case):
    if case == "unknown":
        FakeRepo.site = None
    elif case == "no_project":
        FakeRepo.site = {"project_id": None}
    else:
        client.state.denied = True
    res = client.get(f"/dpr/site-days/{SITE}/document", params={"date": DAY})
    assert res.status_code == 404


def test_project_document_previews_until_sent(client):
    html = client.get(f"/dpr/project-days/{PROJECT}/document", params={"date": DAY}).text
    assert FakeRepo.calls == ["preview"]
    assert preview.PROJECT_PREVIEW_CODE in html
    assert "Project report" in html
    assert "Sites Reporting" in html


def test_project_document_is_as_sent_once_sent(client):
    client.state.report = {"id": uuid.uuid4(), "code": "DPR-20261024-P", "status": "published"}
    html = client.get(f"/dpr/project-days/{PROJECT}/document", params={"date": DAY}).text
    assert FakeRepo.calls == ["sent"]
    assert "DPR-20261024-P" in html
    assert "All on track." in html


def test_project_document_is_404_for_a_project_out_of_scope(client):
    client.state.denied = True
    res = client.get(f"/dpr/project-days/{PROJECT}/document", params={"date": DAY})
    assert res.status_code == 404


def test_a_bad_date_is_rejected(client):
    assert client.get(f"/dpr/site-days/{SITE}/document", params={"date": "soon"}).status_code == 422
