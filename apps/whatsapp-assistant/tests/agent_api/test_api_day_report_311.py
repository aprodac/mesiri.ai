"""WA-311 (live test, 15 Nov 17:01, test number): "Green Villa innathe report pdf ayakk" sent the WEEKLY report:
v3 had no way to send the person the day's DPR (send_dpr prepares sending it to others, after Save), so the model
took send_report. Now send_day_report reads the day's document (the dashboard's own page, as the person), prints it
with the DPR renderer and sends it: one PDF per site with anything that day, or the site they named.

Guards: a site with nothing that day is skipped (and said); a project id that is not an id is refused before
anything is read; a site the person cannot open is never sent; a day to come is refused.
"""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace
from typing import Any

from agent_api import documents

TODAY = dt.date(2026, 11, 15)
P, S1, S2, OTHER = ("11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222",
                    "33333333-3333-4333-8333-333333333333", "44444444-4444-4444-8444-444444444444")
CTX = SimpleNamespace(projects=[SimpleNamespace(id=P, name="Green Villa")],
                      sites=[SimpleNamespace(id=S1, name="Annex", project_id=P),
                             SimpleNamespace(id=S2, name="Main block", project_id=P)])
FULL = b"<html>Daily Progress Report Plinth beam shuttering 14 workers</html>"
EMPTY = (b"<html>No activities logged for this date. No attendance recorded for this date. "
         b"No material movements recorded for this date.</html>")


class _Client:
    def __init__(self, pages: dict[str, tuple[int, bytes]]) -> None:
        self.pages, self.read = pages, []

    async def fetch_bytes(self, path: str) -> tuple[int, bytes, dict[str, str]]:
        self.read.append(path)
        site = path.split("/site-days/")[1].split("/")[0]
        status, body = self.pages.get(site, (404, b""))
        return status, body, {}


class _Out:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def render(self, html: str) -> bytes:
        return b"%PDF " + html.encode()[:20]

    async def send(self, wa_id: str, data: bytes, *, filename: str, caption: str, mime_type: str, shows: str) -> bool:
        self.sent.append((filename, caption))
        return True


async def _send(client: Any, out: _Out, **arguments: Any) -> dict:
    return await documents.send_day_report(client, out.send, out.render, "91", CTX, TODAY, arguments)


async def test_live_todays_report_sends_each_site_with_work_as_a_pdf() -> None:
    client, out = _Client({S1: (200, FULL), S2: (200, EMPTY)}), _Out()
    result = await _send(client, out, project_id=P)
    assert client.read == [f"/dpr/site-days/{S1}/document?date=2026-11-15", f"/dpr/site-days/{S2}/document?date=2026-11-15"]
    assert out.sent == [("Daily-report-Green-Villa-Annex-15-Nov-2026.pdf", "Daily report · Annex · Sun 15 Nov")]
    assert result["status"].startswith("sent 1 daily report") and result["nothing_recorded_at"] == "Main block"


async def test_a_named_site_and_day_is_sent_even_when_quiet() -> None:
    client, out = _Client({S2: (200, EMPTY)}), _Out()
    result = await _send(client, out, project_id=P, site_id=S2, date="2026-11-14")
    assert client.read == [f"/dpr/site-days/{S2}/document?date=2026-11-14"] and len(out.sent) == 1
    assert "Sat 14 Nov" in out.sent[0][1] and result["status"].startswith("sent")


async def test_guard_nothing_anywhere_sends_nothing_and_says_so() -> None:
    out = _Out()
    result = await _send(_Client({S1: (200, EMPTY), S2: (200, EMPTY)}), out, project_id=P)
    assert out.sent == [] and result["status"].startswith("nothing sent")


async def test_guard_a_made_up_project_a_site_they_cannot_open_and_a_day_to_come() -> None:
    out = _Out()
    client = _Client({})
    assert (await _send(client, out, project_id="Green Villa"))["status"].startswith("not sent: say which project")
    assert client.read == []
    assert (await _send(_Client({OTHER: (403, b"")}), out, project_id=P, site_id=OTHER))["status"].startswith("not sent")
    assert (await _send(_Client({S1: (200, FULL)}), out, project_id=P, date="2026-11-20"))["status"].endswith(
        "has not come yet")
    assert out.sent == []


def test_the_sop_sends_the_days_report_to_them_and_send_dpr_to_others() -> None:
    from agent_api.agent import SOP

    assert "is `send_day_report`" in SOP and "`send_dpr` only when they ask to send the\n   project's DPR to others" in SOP


def test_the_day_document_routes_are_in_the_agents_api() -> None:
    from agent_api.app import build_api_app

    paths = build_api_app(None).openapi()["paths"]
    assert "/dpr/site-days/{site_id}/document" in paths and "/dpr/project-days/{project_id}/document" in paths
