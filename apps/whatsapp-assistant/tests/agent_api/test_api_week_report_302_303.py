"""[302] / [303] (15 Nov, Ilan's voice notes): "orazhchathe mottham progress report" on a Sunday got "Week 45: 2 - 8
Nov", the week before last, as text; on Aprodac the same ask came back as a text list of per-site work. A week nobody
named is now the last 7 days ending today (the code puts the dates on the read and on the PDF), the report is the
PDF (``send_report``), and the PDF and its caption say "Weekly report" with the dates.

Siblings: the read (`period_report`), the all-projects read (`portfolio_report`), the PDF (`send_report`). Guards: a
named week ("last week": a date) and a month keep the API's own dates; the dashboard's default is untouched.
"""

from __future__ import annotations

import datetime as dt
import uuid
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Response
from tests.agent_api.replaykit import _real_tools
from tests.agent_api.standin import ACTOR

from agent_api import documents
from agent_api.agent import ApiAgent
from agent_api.client import ApiClient
from mesiri.domains.organizations.settings import WORKING_DAY_STARTS_DEFAULT, working_day
from mesiri.domains.shared.auth import get_current_user
from mesiri_ai.fakes import FakeToolCallingProvider

PROJECT = str(uuid.uuid4())
SUNDAY = dt.date(2026, 11, 15)


def _app(read: list) -> FastAPI:
    app = FastAPI()

    @app.get("/reports/period/pdf")
    async def period_pdf(project_id: str, period: str = "week", date: str | None = None, date_from: str | None = None,
                         date_to: str | None = None, jwt: dict = Depends(get_current_user)):
        read.append(("period_pdf", period, date, date_from, date_to))
        return Response(content=b"%PDF-1.4", media_type="application/pdf",
                        headers={"Content-Disposition": 'attachment; filename="mesiri-villa-week-2026-11-09.pdf"'})

    @app.get("/reports/period")
    async def period(project_id: str, period: str = "week", date: str | None = None, date_from: str | None = None,
                     date_to: str | None = None, jwt: dict = Depends(get_current_user)):
        read.append(("period", period, date, date_from, date_to))
        return {"headline": {"lead": "Steady week.", "facts": []}, "kpis": [], "needs_you": []}

    return app


class _Sender:
    def __init__(self) -> None:
        self.sent: list[tuple] = []

    async def __call__(self, wa_id, data, *, filename, caption=None, mime_type="application/pdf", shows=None):
        self.sent.append((filename, caption))
        return True


# -- the window -----------------------------------------------------------------------------------------------------

def test_a_week_nobody_named_is_the_last_seven_days_ending_today() -> None:
    out = documents.rolling_week({"scope": "project", "period": "week"}, SUNDAY)
    assert (out["period"], out["date_from"], out["date_to"]) == ("custom", "2026-11-09", "2026-11-15")
    assert documents.rolling_week({"project_id": PROJECT}, SUNDAY)["date_from"] == "2026-11-09"  # period left out


def test_guard_a_named_week_or_a_month_keeps_its_dates() -> None:
    last_week = {"period": "week", "date": "2026-11-04"}
    month = {"period": "month"}
    custom = {"period": "custom", "date_from": "2026-11-01", "date_to": "2026-11-10"}
    for args in (last_week, month, custom):
        assert documents.rolling_week(args, SUNDAY) == args


def test_the_caption_names_the_dates() -> None:
    args = documents.rolling_week({"period": "week"}, SUNDAY)
    assert documents.report_caption(args) == "Weekly report · 9 – 15 Nov 2026"
    assert documents.report_caption({"period": "week", "date": "2026-11-04"}) == ""


def test_the_tools_that_take_the_window_are_real_report_routes() -> None:
    tools = _real_tools()
    assert {"period_report", "portfolio_report"} <= set(tools)
    assert documents.ROLLING_WEEK_TOOLS == {"period_report", "portfolio_report", documents.SEND_REPORT}


# -- the reported message -------------------------------------------------------------------------------------------

async def test_a_weeks_report_sends_the_pdf_of_the_last_seven_days_with_its_dates() -> None:
    read: list = []
    client = ApiClient(ACTOR, app=_app(read))
    sender = _Sender()
    try:
        out = await documents.send_report(client, sender, "91", {"scope": "project", "project_id": PROJECT,
                                                                  "period": "week"}, today=SUNDAY)
    finally:
        await client.close()
    assert out["status"] == "sent to their WhatsApp"
    assert read == [("period_pdf", "custom", None, "2026-11-09", "2026-11-15")]
    assert sender.sent == [("mesiri-villa-week-2026-11-09.pdf", "Weekly report · 9 – 15 Nov 2026")]


async def test_the_read_of_a_week_goes_out_with_the_last_seven_days() -> None:
    """The model's `period_report` with period week and no date (what it sent on 15 Nov)."""
    read: list = []
    client = ApiClient(ACTOR, app=_app(read))
    script = [[("period_report", {"project_id": PROJECT, "period": "week"})], "Steady week."]
    try:
        await ApiAgent(FakeToolCallingProvider(script), _real_tools()).run(
            client, "orazhchathe mottham progress report")
    finally:
        await client.close()
    today = working_day(dt.datetime.now(ZoneInfo("Asia/Kolkata")), WORKING_DAY_STARTS_DEFAULT)
    assert read == [("period", "custom", None, (today - dt.timedelta(days=6)).isoformat(), today.isoformat())]


async def test_guard_last_week_named_keeps_its_date_on_the_read() -> None:
    read: list = []
    client = ApiClient(ACTOR, app=_app(read))
    script = [[("period_report", {"project_id": PROJECT, "period": "week", "date": "2026-11-04"})], "Last week."]
    try:
        await ApiAgent(FakeToolCallingProvider(script), _real_tools()).run(client, "kazhinja aazhcha engane poyi")
    finally:
        await client.close()
    assert read == [("period", "week", "2026-11-04", None, None)]


def test_the_sop_sends_a_weeks_progress_report_as_the_pdf() -> None:
    from agent_api.agent import SOP

    assert "orazhchathe" in SOP and "the code sends the last 7 days ending today" in SOP
    assert "is rule 23: the PDF" in SOP


# -- live, 15 Nov 15:42 (Aprodac): "orachcha motham progress report" was answered as text with period_report ------

async def test_a_week_nobody_named_sends_the_pdf_even_when_the_model_only_reads() -> None:
    read: list = []
    client = ApiClient(ACTOR, app=_app(read))
    sender = _Sender()
    actions = {documents.SEND_REPORT: (documents.REPORT_TOOL,
                                       lambda a: documents.send_report(client, sender, "91", a, today=SUNDAY))}
    script = [[("period_report", {"project_id": PROJECT, "period": "week"})],
              [(documents.SEND_REPORT, {"scope": "project", "project_id": PROJECT, "period": "week"})],
              "The weekly report (9 - 15 Nov) is above."]
    try:
        turn = await ApiAgent(FakeToolCallingProvider(script), _real_tools()).run(
            client, "orachcha motham progress report", actions=actions)
    finally:
        await client.close()
    assert [r[0] for r in read] == ["period_pdf", "period"]  # the PDF first, then the figures for the summary
    assert len(sender.sent) == 1 and sender.sent[0][1] == "Weekly report · 9 – 15 Nov 2026"
    assert "already SENT the weekly report PDF" in turn.calls[0]["result"]["note"]
    assert turn.calls[1]["result"]["status"].startswith("already sent")  # never a second copy


async def test_guard_a_named_week_read_sends_no_pdf() -> None:
    read: list = []
    client = ApiClient(ACTOR, app=_app(read))
    sender = _Sender()
    actions = {documents.SEND_REPORT: (documents.REPORT_TOOL,
                                       lambda a: documents.send_report(client, sender, "91", a, today=SUNDAY))}
    script = [[("period_report", {"project_id": PROJECT, "period": "week", "date": "2026-11-04"})], "Last week."]
    try:
        await ApiAgent(FakeToolCallingProvider(script), _real_tools()).run(
            client, "kazhinja aazhcha engane poyi", actions=actions)
    finally:
        await client.close()
    assert sender.sent == [] and [r[0] for r in read] == ["period"]
