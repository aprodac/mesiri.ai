"""BE-47: the dashboard's "Download PDF" is the PDF WhatsApp sent, or one
printed now from the same template -- never the old plain fpdf report (audit
DPR-09, ISS-07, ISS-13). Access mirrors the DPR pages; nothing is stored."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import channel.dpr_document.day_document as day_document
import channel.dpr_document.letterhead as letterhead_module
from dpr_preview import router as preview
from mesiri.domains.projects.router import get_auth_context
from mesiri.infrastructure.objectstorage.dependency import get_object_storage
from mesiri.infrastructure.postgres.dependency import get_db_conn

ORG = uuid.uuid4()
PROJECT = uuid.uuid4()
SITE = uuid.uuid4()
REPORT = uuid.uuid4()

PAYLOAD = {
    "project_name": "Skyline",
    "site_name": "Tower 1",
    "report_date": "2026-10-24",
    "activities": [{"work_type": "slab_shuttering", "narrative": "5th floor", "status": "IN_PROGRESS"}],
    "issues": [
        {
            "issue_type": "EQUIPMENT_BREAKDOWN",
            "severity": "HIGH",
            "narrative": "മിക്സർ കേടായി",
            "status": "OPEN",
        }
    ],
    "activity_count": 1,
}


def _report(**over):
    row = {
        "id": REPORT,
        "code": "DPR-0007",
        "report_date": "2026-10-24",
        "workflow_status": "DRAFT",
        "project_id": PROJECT,
        "site_id": SITE,
        "project_name": "Skyline",
        "site_name": "Tower 1",
        "version_id": uuid.uuid4(),
        "payload": dict(PAYLOAD),
        "rendered_object_key": None,
        "narrative_summary": None,
    }
    row.update(over)
    return row


class FakeRenderer:
    def __init__(self):
        self.html: list[str] = []

    async def render_pdf(self, html: str) -> bytes:
        self.html.append(html)
        return b"%PDF-fresh"


class FakeStorage:
    def __init__(self):
        self.read: list[str] = []
        self.written: list[str] = []

    async def get_object(self, key):
        self.read.append(key)
        return SimpleNamespace(data=b"%PDF-stored")

    async def put_object(self, key, *_a, **_k):  # pragma: no cover - must not happen
        self.written.append(key)


@pytest.fixture
def setup(monkeypatch):
    state = SimpleNamespace(report=_report(), denied=False, asked=[])
    renderer, storage = FakeRenderer(), FakeStorage()

    class FakeRepo:
        def __init__(self, conn):
            pass

        async def get_report_for_pdf(self, *, organization_id, report_id, version_id):
            state.asked.append((organization_id, report_id, version_id))
            return state.report

    async def no_letterhead(*_):
        return None

    def denied(auth, project_id, site_id):
        state.denied_args = (project_id, site_id)
        return state.denied

    monkeypatch.setattr(preview, "PostgresDprRepository", FakeRepo)
    monkeypatch.setattr(preview, "_site_denied", denied)
    monkeypatch.setattr(letterhead_module, "load_letterhead", no_letterhead)
    monkeypatch.setattr(day_document, "shared_renderer", lambda: renderer)
    app = FastAPI()
    app.include_router(preview.router)
    app.dependency_overrides[get_auth_context] = lambda: SimpleNamespace(organization_id=ORG)
    app.dependency_overrides[get_db_conn] = lambda: object()
    app.dependency_overrides[get_object_storage] = lambda: storage
    return SimpleNamespace(client=TestClient(app), state=state, renderer=renderer, storage=storage)


def test_the_pdf_whatsapp_sent_is_served_as_is(setup):
    setup.state.report = _report(rendered_object_key="dpr/r/v.pdf", workflow_status="PUBLISHED")

    res = setup.client.get(f"/dpr/daily-reports/{REPORT}/document.pdf")

    assert res.status_code == 200
    assert res.content == b"%PDF-stored"
    assert res.headers["content-type"] == "application/pdf"
    assert 'filename="DPR-0007.pdf"' in res.headers["content-disposition"]
    assert setup.storage.read == ["dpr/r/v.pdf"]
    assert setup.renderer.html == []


def test_without_a_stored_pdf_it_is_printed_from_the_whatsapp_template(setup):
    res = setup.client.get(f"/dpr/daily-reports/{REPORT}/document.pdf")

    assert res.status_code == 200 and res.content == b"%PDF-fresh"
    [html] = setup.renderer.html
    assert "Daily Progress Report" in html and "Tower 1" in html
    assert "മിക്സർ കേടായി" in html  # Malayalam kept (the fpdf report crashed)
    assert "EQUIPMENT_BREAKDOWN" not in html  # a plain label, not the code
    assert day_document.DRAFT_CODE in html  # a draft says so
    assert setup.storage.written == []  # never stored (BE-43)


def test_a_confirmed_report_prints_its_code(setup):
    setup.state.report = _report(workflow_status="APPROVED")

    setup.client.get(f"/dpr/daily-reports/{REPORT}/document.pdf")

    assert "DPR-0007" in setup.renderer.html[0]
    assert day_document.DRAFT_CODE not in setup.renderer.html[0]


def test_an_older_version_is_asked_for_by_id(setup):
    version = uuid.uuid4()

    setup.client.get(f"/dpr/daily-reports/{REPORT}/document.pdf", params={"version_id": str(version)})

    assert setup.state.asked == [(ORG, REPORT, version)]


def test_no_access_to_the_site_is_not_found(setup):
    setup.state.denied = True

    res = setup.client.get(f"/dpr/daily-reports/{REPORT}/document.pdf")

    assert res.status_code == 404
    assert setup.state.denied_args == (PROJECT, SITE)
    assert setup.renderer.html == [] and setup.storage.read == []


def test_a_report_with_no_version_is_not_found(setup):
    setup.state.report = None

    assert setup.client.get(f"/dpr/daily-reports/{REPORT}/document.pdf").status_code == 404


def test_an_issue_from_an_earlier_day_says_when_it_was_reported():
    # BE-51 (audit ISS-04): still-open issues stay on the next day's DPR.
    from channel.dpr_document.data import build_document_data
    from channel.dpr_document.template import render_html

    payload = {
        **PAYLOAD,
        "issues": [],
        "carried_issues": [
            {"issue_type": "EQUIPMENT_BREAKDOWN", "severity": "HIGH", "narrative": "Crane breakdown",
             "status": "OPEN", "reported_on": "2026-10-20"},
        ],
        "open_issue_count": 1,
    }
    html = render_html(build_document_data(code="DPR-1", payload=payload), None)

    assert "Crane breakdown" in html and "reported 20 Oct" in html
    assert "No issues reported for this date" not in html
