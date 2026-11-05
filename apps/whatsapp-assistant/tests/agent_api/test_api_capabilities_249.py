"""[249] (5 Nov, Ilan, 10:06 and 12:19): "what can Mesiri do" was answered with tool names ("(record\\_receipt)") and
so long that WhatsApp folded it behind "Read more" (it read as cut off). The block the model reads has no tool names,
SOP rule 11 caps the answer at 6 short lines, and the code cuts any tool name from a reply.

Guards: ordinary words and words in brackets stay; a reply with no tool name is unchanged.
"""

from __future__ import annotations

from tests.agent_api.standin import ACTOR, stand_in_api

from agent_api.agent import ApiAgent
from agent_api.client import ApiClient
from agent_api.reply_guard import without_tool_names
from agent_api.tools import ALLOWED, build_tools, what_mesiri_does
from mesiri_ai.fakes import FakeToolCallingProvider

REPORTED = ("*Record cheyyaan:* Material ethunnathum (record\\_receipt), upayogikkunnathum (record\\_usage) ennivayokke.\n"
            "*Ask cheyyaan:* Stock levels (stock\\_levels), issues (list\\_issues).")


def test_the_block_the_model_reads_names_no_tool() -> None:
    from agent_api.app import build_api_app

    tools = build_tools(build_api_app(None).openapi())
    block = what_mesiri_does(tools)
    assert "at most 6 short lines" in block
    assert not [name for name in tools if "_" in name and name in block]


def test_tool_names_are_cut_from_the_words() -> None:
    names = {"record_receipt", "record_usage", "stock_levels", "list_issues", "web_link"}
    assert without_tool_names(REPORTED, names) == ("*Record cheyyaan:* Material ethunnathum, upayogikkunnathum "
                                                   "ennivayokke.\n*Ask cheyyaan:* Stock levels, issues.")
    assert without_tool_names("Use `web_link` for the page", names) == "Use for the page"


def test_guard_ordinary_brackets_and_plain_replies_stay() -> None:
    names = {"record_receipt"}
    assert without_tool_names("Record cheyyaan (receipts, usage, transfer) okke", names) == (
        "Record cheyyaan (receipts, usage, transfer) okke")
    assert without_tool_names("30 bags cement ready.", names) == "30 bags cement ready."


async def test_a_reply_with_tool_names_reaches_them_without() -> None:
    app = stand_in_api([])
    client = ApiClient(ACTOR, app=app)
    try:
        tools = build_tools(app.openapi(), tuple(a for a in ALLOWED if a.name == "record_receipt"))
        tools["record_usage"] = tools["record_receipt"]  # the names the reply used are tools the agent has
        tools["stock_levels"] = tools["list_issues"] = tools["record_receipt"]
        turn = await ApiAgent(FakeToolCallingProvider([REPORTED]), tools).run(
            client, "Mesiri-kku enthokke cheyyaan pattum?")
    finally:
        await client.close()
    assert "\\_" not in turn.reply and "record_receipt" not in turn.reply and "Material ethunnathum" in turn.reply
