"""LW-07 (wages and advances on WhatsApp, plan docs/plans/wages-and-labour-plan.md, approved by Ilan 9 Nov 2026).

v3: the feature is the dashboard's own routes in ALLOWED plus SOP rule 22. Guarded here: the tools exist against the
real API; the writes are confirmed writes that always say they came from WhatsApp; who is paid decides the tool (a
worker or labour team is an advance on wages, a supplier or subcontractor stays rule 4's pay_supplier); and the new
descriptions do not pull unrelated questions into wages (the topic guard of [247] matches description words).
"""

from __future__ import annotations

from tests.agent_api.replaykit import _real_tools

from agent_api.agent import SOP
from agent_api.reply_guard import read_tools_for
from agent_api.tools import ALLOWED

WRITES = ("give_labour_advance", "approve_wage_sheet", "pay_wages")
READS = ("labour_teams", "labour_advance_balances", "wage_sheet")


def test_tools_are_built_from_the_real_api() -> None:
    tools = _real_tools()
    for name in WRITES:
        assert tools[name].is_write, name
    for name in READS:
        assert not tools[name].is_write, name


def test_writes_from_whatsapp_say_so_and_wait_for_the_person() -> None:
    by_name = {a.name: a for a in ALLOWED}
    for name in WRITES:
        assert "Saved only after the person confirms." in by_name[name].description, name
    for name in ("give_labour_advance", "pay_wages"):
        assert ("source", "whatsapp") in by_name[name].fixed and "source" in by_name[name].hide, name


def test_who_is_paid_decides_the_tool() -> None:
    assert "22. Wages and advances" in SOP
    rule = SOP[SOP.index("22. Wages and advances"):]
    assert "give_labour_advance" in rule and "pay_supplier" in rule
    # Rule 4 (paying a supplier) now sends a worker or labour team to rule 22, so "advance" alone never decides.
    assert "never a worker or a labour team: that is rule 22" in SOP


def test_wage_questions_find_the_wage_tools() -> None:
    tools = _real_tools()
    assert "wage_sheet" in read_tools_for("what do I pay this week in wages", tools)
    assert "labour_advance_balances" in read_tools_for("how much advance is outstanding", tools)


def test_guard_unrelated_questions_do_not_pull_in_wages() -> None:
    tools = _real_tools()
    for topic in ("send my invoice to the client by email", "post our brochure on instagram",
                  "Mesiri cannot post on Instagram; passed to the team."):
        assert not set(read_tools_for(topic, tools)) & set(READS), topic
