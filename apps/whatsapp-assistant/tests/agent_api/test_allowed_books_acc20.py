"""ACC-20 (10 Nov 2026): "cash balance?", "profit this month", "GST this month", "TDS to pay" on WhatsApp are the
Accounts pages' own reads (v3: ALLOWED lines + an SOP rule), never a workflow. Sibling: the cash flow and a project's
profit. Guards: every books tool is a GET (nothing is posted from WhatsApp), the figures come from the tools (never
worked out from expenses), and "who owes us" stays `receivables`.
"""

from __future__ import annotations

from pathlib import Path

from tests.agent_api.replaykit import _real_tools

from agent_api.app import API_ROUTERS
from agent_api.tools import ALLOWED

SOP = (Path(__file__).resolve().parents[2] / "src/agent_api/SOP.md").read_text(encoding="utf-8")
BOOKS = {"books_home": "/accounts/home", "profit_and_loss": "/accounts/pl", "cash_bank_book": "/accounts/cash-bank",
         "cash_flow": "/accounts/cash-flow", "gst_summary": "/accounts/gst", "tds_register": "/accounts/tds"}


def test_the_books_reads_are_gets_on_the_real_accounts_routes() -> None:
    assert "mesiri.domains.accounts.router" in API_ROUTERS
    by = {a.name: a for a in ALLOWED}
    for name, path in BOOKS.items():
        assert (by[name].method, by[name].path) == ("GET", path)
    tools = _real_tools()
    assert {"date_from", "date_to", "project_id", "site_id"} <= set(tools["profit_and_loss"].query_params)
    assert {"date_from", "date_to"} <= set(tools["gst_summary"].query_params)
    assert "project_id" in tools["books_home"].query_params
    assert all(tools[n].is_write is False for n in BOOKS)


def test_the_sop_maps_the_questions_to_the_tools() -> None:
    rule = SOP[SOP.index("27. The books (ACC-20)"):]
    for said, tool in (('"Cash balance?"', "`books_home`"), ('"Profit this month"', "`profit_and_loss`"),
                       ('"GST this month"', "`gst_summary`"), ('"TDS to pay"', "`tds_register`"),
                       ('"cash flow"', "`cash_flow`")):
        assert said in rule and tool in rule


def test_guard_no_entry_is_posted_from_whatsapp_and_no_figure_is_made_up() -> None:
    assert not any(a.path.startswith("/accounts") and a.method != "GET" for a in ALLOWED)
    rule = SOP[SOP.index("27. The books (ACC-20)"):]
    assert "never worked out from expenses" in rule and "never guess a figure" in rule
    assert "\"Who owes us\" stays `receivables`" in rule
