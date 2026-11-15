"""Live, Aprodac, 15 Nov 16:14 (after WA-306): "orachcha motham progress report" still came as text, "PDF ?" got
"no tool named send_report", a send to "self" failed at Save, and the card said only "📤 Send: *Send report* · Annex".

1. Production never gave the WhatsApp service its document sender, so every file tool (DOC-05 send_document, PRC-20
   send_report, WA-306's code-sent weekly PDF) was missing there; the tests passed theirs in by hand.
2. A report to send got the chat's working site (Annex), so the monthly report went as one site's.
3. recipient_user_ids ["self"] was held; only real ids go (none: the person asking, the API's default).
4. The card names the report: "Weekly report · Green Villa · 9 – 15 Nov 2026 · to you".
"""

from __future__ import annotations

import ast
import datetime as dt
from pathlib import Path
from types import SimpleNamespace

from tests.agent_api.replaykit import _real_tools

from agent_api.agent import PendingWrite, site_scoped
from agent_api.documents import ROLLING_WEEK_TOOLS, report_words, rolling_week
from agent_api.receipts import caption_lines, slip_for

SRC = Path(__file__).resolve().parents[2] / "src"
CTX = SimpleNamespace(projects=[SimpleNamespace(id="p1", name="Green Villa")],
                      sites=[SimpleNamespace(id="s1", name="Annex", project_id="p1")], timezone="Asia/Kolkata")


def _keywords_of_api_whatsapp(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "ApiWhatsApp"]
    assert calls, path
    return {k.arg for c in calls for k in c.keywords}


def test_live_production_gives_the_service_its_document_and_image_senders() -> None:
    keywords = _keywords_of_api_whatsapp(SRC / "runtime" / "message_journey.py")
    assert {"send_document", "send_image", "receipt_builder"} <= keywords


def test_live_a_report_to_send_never_takes_the_chats_site() -> None:
    tools = _real_tools()
    assert not site_scoped(tools["send_report_to"]) and not site_scoped(tools["schedule_report"])
    assert site_scoped(tools["record_receipt"])  # guard: a delivery still does


def test_a_send_with_no_week_named_is_the_last_seven_days() -> None:
    assert "send_report_to" in ROLLING_WEEK_TOOLS
    out = rolling_week({"scope": "project", "period": "week"}, dt.date(2026, 11, 15))
    assert (out["date_from"], out["date_to"]) == ("2026-11-09", "2026-11-15")


def _card(tool: str, body: dict) -> str:
    entry = PendingWrite(tool, "POST", "/reports/send", {}, body, "x", "k")
    return caption_lines(slip_for([entry], CTX, ({}, {})))[0]


def test_live_the_card_names_the_report_its_project_dates_and_who() -> None:
    week = _card("send_report_to", {"scope": "project", "project_id": "p1", "period": "custom",
                                    "date_from": "2026-11-09", "date_to": "2026-11-15"})
    assert week == "1. 📤 Send: *Weekly report* · Green Villa · 9 – 15 Nov 2026 · to you"
    month = _card("send_report_to", {"scope": "project", "project_id": "p1", "period": "month", "date": "2026-11-15",
                                     "recipient_names": ["Sajan", "Adarsh"]})
    assert month == "1. 📤 Send: *Monthly report* · Green Villa · November 2026 · to Sajan, Adarsh"
    every = _card("schedule_report", {"frequency": "WEEKLY", "day_of_week": 0, "time_of_day": "08:00"})
    assert every == "1. 📤 Send: *Weekly report* · All projects · every Mon 08:00 · to you"


def test_report_words_for_a_month_the_api_picks() -> None:
    assert report_words({"period": "month"}) == ("Monthly report", "last month")
    assert report_words({"period": "week", "date": "2026-11-04"}) == ("Weekly report", "2 – 8 Nov 2026")
