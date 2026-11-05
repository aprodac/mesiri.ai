"""[228]: after Save, each saved record gets a link to its dashboard page (built from ids already returned).

ACCEPTANCE (Ilan, "20 bag M sand Tower A-il vannu" -> Save): the Saved reply carries a link that opens that
record's page on https://app.whatsapp.mesiri.ai; every write tool has a page or is marked "no page"; several
lines give one short link per site-and-day (more than three: one link to a list); no token in the URL; asking
for the link afterwards (``web_link``) gives the same address.
"""

from __future__ import annotations

import re
import uuid

import pytest
from tests.agent_api.standin import ACTOR, PROJECT, SITE, stand_in_api, two_receipts_model
from tests.agent_api.test_api_whatsapp_119 import CTX, Harness, _message, _stand_in_tools  # noqa: F401

from agent_api.agent import ApiAgent, PendingWrite, WriteResult
from agent_api.client import ApiClient
from agent_api.links import DEFAULT_DASHBOARD_URL, PAGES, build_link
from agent_api.record_links import MAX_LINKS, RECORD_PAGES, record_link, with_links, write_tools
from agent_api.whatsapp import _saved_text
from mesiri_ai.fakes import FakeToolCallingProvider

BASE = "https://app.whatsapp.mesiri.ai"
TODAY = "2026-11-04"


@pytest.fixture(autouse=True)
def _production_base(monkeypatch):
    monkeypatch.delenv("MESIRI_DASHBOARD_URL", raising=False)


def _entry(tool: str, path: str = "/x", body: dict | None = None) -> PendingWrite:
    return PendingWrite(tool=tool, method="POST", path=path, params={}, body=body or {}, summary=tool,
                        idempotency_key="k")


def test_the_dashboard_base_is_the_live_app_address() -> None:
    assert DEFAULT_DASHBOARD_URL == BASE
    assert build_link({"page": "today"}, today=TODAY)["url"] == BASE + "/today"


def test_every_write_tool_has_a_page_or_is_marked_no_page() -> None:
    assert set(write_tools()) == set(RECORD_PAGES)
    for tool, page in RECORD_PAGES.items():
        assert page is None or page in PAGES, tool


def test_each_record_kind_links_to_its_own_page() -> None:
    site = {"site_id": SITE, "project_id": PROJECT}
    day = f"{BASE}/reports/2026-11-01/sites/{uuid.UUID(SITE)}"
    for tool, body in [
        ("record_receipt", {**site, "occurred_date": "2026-11-01"}),
        ("record_usage", {**site, "occurred_date": "2026-11-01"}),
        ("record_transfer", {"from_site_id": SITE, "to_site_id": str(uuid.uuid4()), "occurred_date": "2026-11-01"}),
        ("record_work", {**site, "activity_date": "2026-11-01"}),
        ("report_issue", {**site, "date": "2026-11-01"}),
        ("record_attendance", {**site, "date": "2026-11-01"}),
    ]:
        assert record_link(tool, "/x", body, {"id": "r"}, today=TODAY) == day, tool
    expense = str(uuid.uuid4())
    assert record_link("record_expense", "/expenses", {}, {"id": expense}, today=TODAY) == \
        f"{BASE}/finance/expenses/{expense}"
    assert record_link("create_project", "/projects", {}, {"id": PROJECT}, today=TODAY) == \
        f"{BASE}/projects/{uuid.UUID(PROJECT)}"
    assert record_link("add_site", f"/projects/{PROJECT}/sites", {}, {"id": SITE}, today=TODAY) == \
        f"{BASE}/projects/{uuid.UUID(PROJECT)}"
    assert record_link("set_unit_conversion", "/materials/m/unit-conversions", {}, {}, today=TODAY) == \
        f"{BASE}/materials"


def test_a_kind_with_no_page_or_a_missing_id_gets_no_link() -> None:
    assert record_link("undo_receipt", "/x", {}, {"id": "r"}, today=TODAY) is None
    assert record_link("set_reply_language", "/me/reply-language", {}, {}, today=TODAY) is None
    assert record_link("record_expense", "/expenses", {}, {}, today=TODAY) is None  # no id came back
    assert record_link("record_receipt", "/x", {"occurred_date": "2026-11-01"}, {}, today=TODAY) is None  # no site


def test_a_link_never_carries_a_token() -> None:
    url = record_link("record_receipt", "/x", {"site_id": SITE, "occurred_date": "2026-11-01"}, {}, today=TODAY)
    assert url and "?" not in url and not re.search(r"token|jwt|key|auth", url, re.I)


def test_saved_text_is_unchanged_without_a_link() -> None:
    ok = WriteResult(_entry("undo_receipt"), 200, {})
    assert _saved_text([ok]) == "Saved.\n✅ undo_receipt"
    assert _saved_text([ok], today=TODAY) == "Saved.\n✅ undo_receipt"  # no page: no link line


def test_a_failed_line_gets_no_link() -> None:
    body = {"site_id": SITE, "occurred_date": "2026-11-01"}
    bad = WriteResult(_entry("record_receipt", body=body), 422, {"detail": "no"})
    assert "🔗" not in _saved_text([bad], today=TODAY)


def test_one_link_per_site_and_day_and_one_list_link_beyond_three() -> None:
    lines = ["a", "b"]
    assert with_links(lines, ["u1", "u1"], today=TODAY) == ["a", "🔗 u1", "b"]
    assert with_links(lines, ["u1", "u2"], today=TODAY) == ["a", "🔗 u1", "b", "🔗 u2"]
    many = [f"l{i}" for i in range(MAX_LINKS + 1)]
    out = with_links(many, [f"u{i}" for i in range(MAX_LINKS + 1)], today=TODAY)
    assert out == many + [f"🔗 {BASE}/today"]


async def test_the_whole_journey_message_save_then_ask_for_the_link() -> None:
    h = Harness(two_receipts_model())
    await h.service.handle(_message("50 bag cement, 50 TMT vannu"), CTX)
    assert "🔗" not in h.sent[-1].text  # nothing saved yet, nothing to open
    save, _edit, _cancel = h.buttons()
    await h.service.handle(_message("Save", tap=save), CTX)
    reply = h.sent[-1].text
    posted = [p for m, p, *_ in h.seen if m == "POST"]
    assert posted == ["/materials/inflows", "/materials/inflows"]  # what was saved: two receipts
    link = f"{BASE}/reports/2026-11-01/sites/{uuid.UUID(SITE)}"
    assert reply.count("🔗") == 1 and f"🔗 {link}" in reply  # both lines are the same site and day: one link
    assert reply.startswith("Saved.\n✅ 50 bags cement, Green Villa")  # wording otherwise unchanged
    # "link to that entry" afterwards: the read tool builds the same address from the same table.
    model = FakeToolCallingProvider([
        [("web_link", {"page": "site_day", "site_id": SITE, "date": "2026-11-01"})], "Here it is.",
    ])
    client = ApiClient(ACTOR, app=stand_in_api([]))
    try:
        turn = await ApiAgent(model, {}).run(client, "link to today's M sand entry")
    finally:
        await client.close()
    assert link in turn.reply
