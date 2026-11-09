"""PRC-19 / PRC-20 (9 Nov 2026): weekly and monthly reports on WhatsApp.

"Send me last week's report": the model calls `send_report`; the code fetches the PDF through the dashboard's own
route as the person (their access, their rupees) and sends it in the chat. "How did last week go": `period_report`
(read). "Send it to Sajan" / "every Monday": `send_report_to` / `schedule_report`, the dashboard's routes, which
wait for Save. Guards: a project the person cannot open is never sent; a made-up id is refused before anything is
fetched; a failed send is not called sent; the reads prepare nothing.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, Response
from tests.agent_api.replaykit import _real_tools
from tests.agent_api.standin import ACTOR

from agent_api import documents
from agent_api.agent import ApiAgent
from agent_api.client import ApiClient
from agent_api.tools import ALLOWED, build_tools
from mesiri.domains.shared.auth import get_current_user
from mesiri_ai.fakes import FakeToolCallingProvider

PROJECT, HIDDEN = str(uuid.uuid4()), str(uuid.uuid4())


def _app(read: list) -> FastAPI:
    app = FastAPI()

    @app.get("/reports/period/pdf")
    async def period_pdf(project_id: str, period: str = "week", date: str | None = None,
                         jwt: dict = Depends(get_current_user)):
        read.append(("period_pdf", project_id, period, date))
        if project_id == HIDDEN:
            return Response(status_code=404)
        return Response(content=b"%PDF-1.4 week", media_type="application/pdf",
                        headers={"Content-Disposition": 'attachment; filename="mesiri-villa-week-2026-11-02.pdf"'})

    @app.get("/reports/portfolio/pdf")
    async def portfolio_pdf(period: str = "week", jwt: dict = Depends(get_current_user)):
        read.append(("portfolio_pdf", period))
        return Response(content=b"%PDF-1.4 all", media_type="application/pdf",
                        headers={"Content-Disposition": 'attachment; filename="mesiri-all-projects-month-2026-10.pdf"'})

    @app.get("/reports/period")
    async def period(project_id: str, period: str = "week", jwt: dict = Depends(get_current_user)):
        read.append(("period", project_id, period))
        return {"headline": {"lead": "Work is behind plan.", "facts": ["Finishes is 3 days late."]},
                "kpis": [{"label": "Man-days", "value": "18"}], "needs_you": [{"title": "RA-3 unpaid 47 days"}]}

    return app


class _Sender:
    def __init__(self, ok: bool = True) -> None:
        self.sent: list[tuple] = []
        self.ok = ok

    async def __call__(self, wa_id, data, *, filename, caption=None, mime_type="application/pdf", shows=None):
        self.sent.append((wa_id, data, filename, mime_type))
        return self.ok


def test_the_report_tools_are_the_dashboards_routes() -> None:
    tools = _real_tools()
    assert (tools["period_report"].method, tools["period_report"].path) == ("GET", "/reports/period")
    assert (tools["portfolio_report"].method, tools["portfolio_report"].path) == ("GET", "/reports/portfolio")
    assert not tools["period_report"].is_write and not tools["portfolio_report"].is_write
    assert tools["send_report_to"].is_write and tools["schedule_report"].is_write
    assert "recipient_names" in tools["send_report_to"].body_fields


async def test_send_me_last_weeks_report_sends_the_pdf_as_the_person() -> None:
    read: list = []
    app = _app(read)
    client = ApiClient(ACTOR, app=app)
    sender = _Sender()
    script = [[(documents.SEND_REPORT, {"scope": "project", "project_id": PROJECT, "period": "week"})],
              "Sent: last week's report for Villa Kakkanad."]
    try:
        turn = await ApiAgent(FakeToolCallingProvider(script), {}).run(
            client, "last week report ayakku", actions={documents.SEND_REPORT: (
                documents.REPORT_TOOL, lambda a: documents.send_report(client, sender, "919800000000", a))})
    finally:
        await client.close()
    assert read == [("period_pdf", PROJECT, "week", None)] and turn.pending == []
    assert sender.sent == [("919800000000", b"%PDF-1.4 week", "mesiri-villa-week-2026-11-02.pdf", "application/pdf")]


async def test_all_projects_monthly_goes_through_the_brief_route() -> None:
    read: list = []
    client = ApiClient(ACTOR, app=_app(read))
    sender = _Sender()
    try:
        out = await documents.send_report(client, sender, "91", {"scope": "portfolio", "period": "month"})
    finally:
        await client.close()
    assert out["status"] == "sent to their WhatsApp" and read == [("portfolio_pdf", "month")]


async def test_a_project_they_cannot_open_or_a_made_up_id_is_never_sent() -> None:
    read: list = []
    client = ApiClient(ACTOR, app=_app(read))
    sender = _Sender()
    try:
        hidden = await documents.send_report(client, sender, "91", {"scope": "project", "project_id": HIDDEN,
                                                                    "period": "week"})
        made_up = await documents.send_report(client, sender, "91", {"scope": "project", "project_id": "Villa",
                                                                     "period": "week"})
        no_project = await documents.send_report(client, sender, "91", {"scope": "project", "period": "week"})
        failed = await documents.send_report(client, _Sender(ok=False), "91",
                                             {"scope": "project", "project_id": PROJECT, "period": "month"})
    finally:
        await client.close()
    assert "cannot open" in hidden["status"] and made_up["status"].startswith("not sent: say which project")
    assert no_project["status"].startswith("not sent") and failed["status"].startswith("not sent")
    assert sender.sent == [] and [r[0] for r in read] == ["period_pdf", "period_pdf"]  # never fetched a made-up id


async def test_how_did_last_week_go_only_reads() -> None:
    read: list = []
    app = _app(read)
    client = ApiClient(ACTOR, app=app)
    tools = build_tools(app.openapi(), tuple(a for a in ALLOWED if a.name == "period_report"))
    try:
        turn = await ApiAgent(FakeToolCallingProvider([[("period_report", {"project_id": PROJECT, "period": "week"})],
                                                       "Work is behind plan; RA-3 is unpaid."]), tools).run(
            client, "how did last week go at villa")
    finally:
        await client.close()
    assert read == [("period", PROJECT, "week")] and turn.pending == []


def test_report_path_keeps_only_what_the_route_takes() -> None:
    path = documents.report_path({"scope": "project", "project_id": PROJECT, "period": "month",
                                  "date": "2026-10-15T00:00", "junk": "x"})
    assert path == f"/reports/period/pdf?period=month&date=2026-10-15&project_id={PROJECT}"
    assert documents.report_path({"scope": "portfolio", "period": "year"}) is None
    assert documents.report_path({"scope": "client", "period": "week"}) is None


def test_the_sop_rule_for_reports() -> None:
    sop = " ".join((Path(__file__).resolve().parents[2] / "src/agent_api/SOP.md").read_text(encoding="utf-8").split())
    assert "23. Weekly and monthly reports" in sop
    for tool in ("`send_report`", "`period_report`", "`portfolio_report`", "`send_report_to`", "`schedule_report`"):
        assert tool in sop
    assert "never a figure it does not have" in sop and "Both wait for Save" in sop
