"""BE-18: the AI summary of a frozen DPR -- made only from confirmed facts,
never carrying a number the report doesn't, and never holding the DPR up.
The AI is faked; no Postgres, no Playwright."""

from __future__ import annotations

import asyncio
import contextlib
import datetime
import json
import uuid

import pytest

import runtime.project_auto_dpr as sender
import runtime.render_pending_dpr_pdfs as render_module
from mesiri.application.projects import auto_dpr
from mesiri.infrastructure.postgres.repositories import dpr as dpr_repo_module
from mesiri.infrastructure.postgres.repositories import notifications as notifications_module
from mesiri.infrastructure.postgres.repositories import report_recipients as recipients_module
from mesiri_ai import usage
from runtime.dpr_summary import (
    USAGE_PURPOSE,
    DprSummaryWriter,
    ensure_summary,
    numbers_supported,
    summary_facts,
)

SITE_PAYLOAD = {
    "level": "SITE",
    "project_name": "Green Towers",
    "site_name": "Tower A",
    "report_date": "2026-10-19",
    "activities": [
        {
            "work_type": "plastering",
            "narrative": "Plastering 3rd floor",
            "status": "COMPLETED",
            "contractor": None,
            "quantities": [{"quantity": "120", "unit": "sqm"}],
            "review": "confirmed",
        },
        {
            "work_type": "tiling",
            "narrative": "Tiling 9th floor lobby",
            "status": "IN_PROGRESS",
            "quantities": [{"quantity": "45", "unit": "sqm"}],
            "review": "draft",
        },
    ],
    "issues": [
        {
            "issue_type": "material_delay",
            "severity": "MEDIUM",
            "narrative": "Sand delivery late",
            "status": "OPEN",
            "delay_duration_minutes": 120,
            "review": "confirmed",
        },
        {"issue_type": "safety", "narrative": "Fall near lift shaft", "review": "draft"},
    ],
    "labour": {"headcount": 18, "trades": [{"trade": "mason", "headcount": 6}], "total_cost": "14400"},
    "materials": [
        {"material_name": "Sand", "unit": "cft", "received": "300", "used": "0"},
        {"material_name": "Cement", "unit": "bag", "received": "0", "used": "0"},
    ],
    "conditions": {"weather": "sunny", "site_working": "full", "hours_lost": None},
    "late_entries": [{"report_date": "2026-10-17", "summary": "77 bags cement"}],
}

PROJECT_PAYLOAD = {
    "level": "PROJECT",
    "project_name": "Green Towers",
    "report_date": "2026-10-19",
    "sites": [
        {"site_name": "Tower A", "reported": True, "activity_count": 1, "open_issue_count": 1, "headcount": 18},
        {"site_name": "Tower B", "reported": False, "activity_count": 0, "open_issue_count": 0, "headcount": 0},
    ],
    "reported_site_count": 1,
    "total_site_count": 2,
    "issues": [{"issue_type": "material_delay", "narrative": "Sand late", "site_name": "Tower A"}],
    "labour": {"headcount": 18, "total_cost": "14400"},
    "materials": [],
}


class _FakeAI:
    def __init__(self, reply=None, *, raw=None, error=None, delay=0.0):
        self.reply = reply
        self.raw = raw
        self.error = error
        self.delay = delay
        self.prompts: list[str] = []
        self.scope_seen = None

    async def generate_json(self, system_prompt, user_prompt, *, correlation_id=None):
        self.prompts.append(user_prompt)
        self.scope_seen = usage._scope.get()
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return self.raw if self.raw is not None else json.dumps({"summary": self.reply})


# --- confirmed facts only ----------------------------------------------------


def test_facts_drop_drafts_money_and_late_entries():
    facts = summary_facts(SITE_PAYLOAD)
    text = json.dumps(facts)
    assert [w["description"] for w in facts["work"]] == ["Plastering 3rd floor"]
    assert [i["description"] for i in facts["issues"]] == ["Sand delivery late"]
    assert "Tiling" not in text and "lift shaft" not in text  # drafts
    assert "14400" not in text  # labour cost
    assert "77" not in text  # another day's late entry
    assert facts["workers_on_site"] == 18
    assert facts["issues"][0]["delay_hours"] == 2.0
    # A material that didn't move is not a fact of the day.
    assert [m["material"] for m in facts["materials"]] == ["Sand"]


def test_project_facts_name_the_sites_not_reported():
    facts = summary_facts(PROJECT_PAYLOAD)
    assert facts["not_reported_sites"] == ["Tower B"]
    assert [s["site"] for s in facts["sites"]] == ["Tower A"]
    assert "14400" not in json.dumps(facts)


# --- the invented-number guard ------------------------------------------------


def test_numbers_from_the_facts_pass():
    facts = summary_facts(SITE_PAYLOAD)
    assert numbers_supported(
        "Plastering on the 3rd floor of Tower A was completed (120 sqm). 18 workers were on site. "
        "The sand delivery was 2 hours late.",
        facts,
    )


@pytest.mark.parametrize(
    "summary",
    [
        "20 workers were on site.",  # not the 18 reported
        "Plastering covered 240 sqm.",  # a doubled quantity
        "Labour cost was 14,400.",  # money is not in the facts
        "Two sites reported.",  # a number word the facts don't use
        "Tiling on the 9th floor started.",  # from a draft
    ],
)
def test_a_number_not_in_the_facts_is_rejected(summary):
    assert not numbers_supported(summary, summary_facts(SITE_PAYLOAD))


# --- the writer ---------------------------------------------------------------


async def test_a_good_summary_is_returned_and_costed_to_the_company():
    org = uuid.uuid4()
    ai = _FakeAI("Plastering on the 3rd floor was completed. 18 workers were on site.")
    summary = await DprSummaryWriter(ai).write(SITE_PAYLOAD, organization_id=org)
    assert summary == "Plastering on the 3rd floor was completed. 18 workers were on site."
    assert ai.scope_seen.organization_id == str(org)
    assert ai.scope_seen.purpose == USAGE_PURPOSE
    # Only the confirmed facts went to the AI.
    assert "Tiling" not in ai.prompts[0]


@pytest.mark.parametrize(
    "ai",
    [
        _FakeAI("25 workers were on site."),  # invented number
        _FakeAI(error=RuntimeError("provider down")),
        _FakeAI("never mind", delay=1.0),  # too slow
        _FakeAI(raw="{not json"),
        _FakeAI(""),
        _FakeAI("A sentence. " * 20),  # far past 5 sentences
    ],
)
async def test_any_failure_means_no_summary(ai):
    writer = DprSummaryWriter(ai, timeout_seconds=0.05)
    assert await writer.write(SITE_PAYLOAD, organization_id=uuid.uuid4()) is None


async def test_an_existing_summary_is_never_regenerated():
    ai = _FakeAI("18 workers were on site.")

    async def store(**_):
        raise AssertionError("must not store")

    got = await ensure_summary(
        DprSummaryWriter(ai), store, version_id=uuid.uuid4(), organization_id=uuid.uuid4(),
        payload=SITE_PAYLOAD, existing="Typed by the engineer.",
    )
    assert got == "Typed by the engineer." and ai.prompts == []


async def test_a_failed_store_means_no_summary():
    async def store(**_):
        raise RuntimeError("db gone")

    got = await ensure_summary(
        DprSummaryWriter(_FakeAI("18 workers were on site.")), store, version_id=uuid.uuid4(),
        organization_id=uuid.uuid4(), payload=SITE_PAYLOAD, existing=None,
    )
    assert got is None


# --- the PDFs -----------------------------------------------------------------


def test_the_pdf_shows_the_summary_under_the_header_escaped():
    pytest.importorskip("jinja2")
    from channel.dpr_document.data import build_document_data
    from channel.dpr_document.template import render_html

    html = render_html(
        build_document_data(code="DPR-1", payload=SITE_PAYLOAD, summary="18 workers <b>on</b> site.")
    )
    assert "Summary" in html
    assert "18 workers &lt;b&gt;on&lt;/b&gt; site." in html
    assert html.index('class="summary"') < html.index('class="meta"')


def test_no_summary_block_without_a_summary():
    pytest.importorskip("jinja2")
    from channel.dpr_document.data import build_document_data
    from channel.dpr_document.template import render_html

    assert 'class="summary"' not in render_html(build_document_data(code="DPR-1", payload=SITE_PAYLOAD))


# --- the send path ------------------------------------------------------------


class _Conn:
    @contextlib.asynccontextmanager
    async def begin_nested(self):
        yield


class _Repo:
    report: dict = {}
    stored: list = []

    def __init__(self, conn):
        pass

    async def get_report_for_pdf(self, *, organization_id, report_id):
        return type(self).report

    async def set_rendered_object_key(self, *, version_id, object_key):
        pass

    async def set_narrative_summary(self, *, version_id, summary):
        type(self).stored.append(summary)
        return summary


class _Nobody:
    claims: list = []

    def __init__(self, conn):
        pass

    async def claim(self, **kwargs):
        type(self).claims.append(kwargs)

    async def list_active(self, **_):
        return []


@pytest.fixture
def send_world(monkeypatch):
    state = {"rendered": [], "sent": []}
    project_id, report_id = uuid.uuid4(), uuid.uuid4()
    _Repo.stored = []
    _Nobody.claims = []
    _Repo.report = {
        "version_id": uuid.uuid4(),
        "code": "DPR-P-1",
        "payload": PROJECT_PAYLOAD,
        "workflow_status": "APPROVED",
        "rendered_object_key": None,
        "narrative_summary": None,
    }

    async def due(conn, *, now_utc):
        return [{"id": project_id, "organization_id": uuid.uuid4(),
                 "report_date": datetime.date(2026, 10, 19), "reason": "all_confirmed"}]

    async def finalize(conn, **_):
        return {"daily_report_id": report_id, "site_id": None, "level": "PROJECT"}

    async def mark_sent(conn, *, project_id, **_):
        state["sent"].append(project_id)

    async def render(**kwargs):
        state["rendered"].append(kwargs.get("summary"))
        return "dpr/x.pdf"

    async def no_letterhead(*_):
        return None

    async def recipients(db, **_):
        return [str(uuid.uuid4())]

    monkeypatch.setattr("channel.dpr_document.letterhead.load_letterhead", no_letterhead)
    monkeypatch.setattr(auto_dpr, "due_project_sends", due)
    monkeypatch.setattr(auto_dpr, "finalize_project_dpr", finalize)
    monkeypatch.setattr(auto_dpr, "mark_project_dpr_sent", mark_sent)
    monkeypatch.setattr(render_module, "render_and_store_version", render)
    monkeypatch.setattr(sender, "_project_dpr_recipients", recipients)
    monkeypatch.setattr(dpr_repo_module, "PostgresDprRepository", _Repo)
    monkeypatch.setattr(notifications_module, "PostgresNotificationRepository", _Nobody)
    monkeypatch.setattr(recipients_module, "PostgresReportRecipientRepository", _Nobody)
    return state


async def _send(writer):
    return await sender.send_due_project_dprs(
        _Conn(), db=None, renderer=object(), object_storage=object(), summary_writer=writer
    )


async def test_the_sent_pdf_carries_the_summary(send_world):
    writer = DprSummaryWriter(_FakeAI("1 of 2 sites reported; Tower B was not reported. 18 workers were on site."))
    assert await _send(writer) == 1
    assert _Repo.stored == ["1 of 2 sites reported; Tower B was not reported. 18 workers were on site."]
    assert send_world["rendered"] == _Repo.stored


async def test_an_ai_failure_still_sends_the_dpr_without_a_summary(send_world):
    assert await _send(DprSummaryWriter(_FakeAI(error=RuntimeError("down")))) == 1
    assert send_world["rendered"] == [None]
    assert len(send_world["sent"]) == 1 and len(_Nobody.claims) == 1
    assert _Repo.stored == []


async def test_a_draft_version_gets_no_summary(send_world):
    _Repo.report["workflow_status"] = "DRAFT"
    ai = _FakeAI("18 workers were on site.")
    assert await _send(DprSummaryWriter(ai)) == 1
    assert ai.prompts == [] and send_world["rendered"] == [None]


async def test_an_already_rendered_frozen_pdf_is_re_rendered_once_with_its_new_summary(send_world):
    _Repo.report["rendered_object_key"] = "dpr/old.pdf"
    assert await _send(DprSummaryWriter(_FakeAI("18 workers were on site."))) == 1
    assert send_world["rendered"] == ["18 workers were on site."]


async def test_an_already_rendered_pdf_with_a_summary_is_not_rendered_again(send_world):
    _Repo.report["rendered_object_key"] = "dpr/old.pdf"
    _Repo.report["narrative_summary"] = "Already there."
    ai = _FakeAI("18 workers were on site.")
    assert await _send(DprSummaryWriter(ai)) == 1
    assert send_world["rendered"] == [] and ai.prompts == []


# --- the render cron ------------------------------------------------------------


class _Db:
    @contextlib.asynccontextmanager
    async def transaction(self):
        yield object()


async def test_the_cron_writes_a_summary_for_a_frozen_version_only(monkeypatch):
    monkeypatch.setattr(dpr_repo_module, "PostgresDprRepository", _Repo)
    _Repo.stored = []
    row = {"version_id": uuid.uuid4(), "organization_id": uuid.uuid4(), "narrative_summary": None}
    writer = DprSummaryWriter(_FakeAI("18 workers were on site."))

    draft = await render_module._summary_for({**row, "frozen": False}, SITE_PAYLOAD, db=_Db(), writer=writer)
    frozen = await render_module._summary_for({**row, "frozen": True}, SITE_PAYLOAD, db=_Db(), writer=writer)

    assert draft is None
    assert frozen == "18 workers were on site." and _Repo.stored == [frozen]
