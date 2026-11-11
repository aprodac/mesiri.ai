"""WA-277 (round 5b, `give_daily_reports`): a link alone is not the answer when a tool gives the thing in the chat.

On the real model "Give daily reports" was answered with the reports page's link and no report; SOP rule 6's line
did not move it, nor did a note beside the link. The link is held back once: its result names the tools that
give it here; asked again in the same turn, it is given.

Guards: a page no tool gives in the chat is given at once; a tool the turn does not have is never named; the
link asked a second time is given and reaches the person.
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


async def _turn(script: list, tools: dict):  # noqa: ANN202
    client = ApiClient(ACTOR, app=stand_in_api([]))
    try:
        return await ApiAgent(FakeToolCallingProvider(script), tools).run(client, "give daily reports")
    finally:
        await client.close()


def _links(turn) -> list[dict]:  # noqa: ANN001
    return [c["result"] for c in turn.calls if c["tool"] == "web_link"]


async def test_the_reports_link_is_held_back_once_and_names_the_tool() -> None:
    turn = await _turn([[("web_link", {"page": "reports"})], "Here."], build_tools(build_api_app(None).openapi()))
    (result,) = _links(turn)
    assert "url" not in result and "`day_summary`" in result["note"]
    assert "/reports" not in turn.reply


async def test_guard_the_link_asked_again_is_given() -> None:
    turn = await _turn([[("web_link", {"page": "reports"})], [("web_link", {"page": "reports"})], "Here."],
                       build_tools(build_api_app(None).openapi()))
    first, second = _links(turn)
    assert "url" not in first and second["url"].endswith("/reports") and "/reports" in turn.reply


async def test_guard_a_page_with_no_tool_in_chat_is_only_the_link() -> None:
    (result,) = _links(await _turn([[("web_link", {"page": "project", "project_id": PROJECT})], "Here."], {}))
    assert "note" not in result and "/projects/" in result["url"]
