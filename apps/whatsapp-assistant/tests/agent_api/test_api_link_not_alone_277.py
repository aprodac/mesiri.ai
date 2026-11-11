"""WA-277 (round 5b, `give_daily_reports`): a link alone is not the answer when a tool gives the thing in the chat.

On the real model "Give daily reports" was answered with the reports page's link and no report; SOP rule 6's line
did not move it. The link's own result now names the tools that give it here, where the model reads it mid-turn.

Guards: a page no tool gives in the chat gets no note; a tool the turn does not have is never named; the link
itself is still built and still reaches the person.
"""

from __future__ import annotations

from tests.agent_api.standin import ACTOR, PROJECT, stand_in_api

from agent_api.agent import ApiAgent
from agent_api.app import build_api_app
from agent_api.client import ApiClient
from agent_api.links import IN_CHAT, PAGES, in_chat_note
from agent_api.tools import ALLOWED, build_tools
from mesiri_ai.fakes import FakeToolCallingProvider


def test_every_in_chat_page_and_tool_exists() -> None:
    names = {a.name for a in ALLOWED}
    assert set(IN_CHAT) <= set(PAGES)
    assert {tool for tools in IN_CHAT.values() for tool in tools} <= names


def test_the_note_names_only_tools_the_turn_has() -> None:
    assert "`day_summary` / `send_dpr`" in in_chat_note("reports", {"day_summary": 1, "send_dpr": 1})
    note = in_chat_note("reports", {"day_summary": 1})
    assert "`day_summary`" in note and "send_dpr" not in note


def test_guard_no_note_without_a_tool_or_for_another_page() -> None:
    assert in_chat_note("reports", {}) == ""
    assert in_chat_note("team", {"day_summary": 1, "send_dpr": 1}) == ""


async def _results(calls: list, tools: dict) -> list[dict]:
    client = ApiClient(ACTOR, app=stand_in_api([]))
    try:
        turn = await ApiAgent(FakeToolCallingProvider([calls, "Here."]), tools).run(client, "give daily reports")
    finally:
        await client.close()
    return [c["result"] for c in turn.calls if c["tool"] == "web_link"] + [{"reply": turn.reply}]


async def test_the_reports_link_tells_the_model_which_tool_gives_the_report() -> None:
    tools = build_tools(build_api_app(None).openapi())
    result, reply = await _results([("web_link", {"page": "reports"})], tools)
    assert "`day_summary`" in result["note"] and result["url"].endswith("/reports")
    assert "/reports" in reply["reply"]


async def test_guard_a_page_with_no_tool_in_chat_is_only_the_link() -> None:
    result, _ = await _results([("web_link", {"page": "project", "project_id": PROJECT})], {})
    assert "note" not in result and "/projects/" in result["url"]
