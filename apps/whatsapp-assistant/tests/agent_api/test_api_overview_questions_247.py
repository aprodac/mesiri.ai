"""[247] (Ilan, 5 Nov, cor_83168ef0 / cor_bee2ae4a): "what can Mesiri do" and "how far is the project" were answered with
"Mesiri can't, given to the team" while work_progress, list_issues and day_summary exist. Now: the system context carries a
"What Mesiri does" block drawn from the tool list; SOP rules 11 / 12 map the two questions to it / to the read tools;
and the code runs a turn once more when it ended in "can't" or tell_the_team with no read tool looked at while a read tool
shares the topic. The end state is asserted (which tools were called, what was held), never the reply's wording.
"""

from __future__ import annotations

from typing import Any

from tests.agent_api.replaykit import RecordedApi, _real_tools
from tests.agent_api.test_api_lose_nothing_198 import Runs

from agent_api.agent import SOP, ApiAgent
from agent_api.reply_guard import read_tools_for
from agent_api.tools import ALLOWED, Allowed, build_tools, what_mesiri_does

SITE = "fee8e443-f6b7-4db5-892c-37814e9bc879"
PROJECT = "5b1ae34b-8856-4674-b2c4-f282fd57006f"
PROGRESS = ("work_progress", {"site_id": SITE})
ISSUES = ("list_issues", {"project_id": PROJECT})
SUMMARY = ("day_summary", {"project_id": PROJECT})
READS = {"work_progress", "list_issues", "day_summary"}
TEAM_PROGRESS = ("tell_the_team", {"kind": "missing_feature", "about": "Answer questions about project progress"})
DONE = {"items": [{"description": "Slab concrete", "quantity": 12, "unit": "cum", "date": "2026-11-04"}]}


def _api(done: Any = None) -> RecordedApi:
    api = RecordedApi()
    api.answers = {"GET /progress/activities": [done if done is not None else {"items": []}],
                   "GET /progress/issues": [{"items": []}], "GET /timeline/day-summary": [{"days": []}]}
    return api


async def _turn(model: Runs, text: str, api: RecordedApi | None = None) -> tuple[Any, RecordedApi]:
    api = api or _api(DONE)
    return await ApiAgent(model, _real_tools()).run(api, text, facts="Only one site: Asus garden. Use it."), api  # type: ignore[arg-type]


def _tools_called(turn: Any) -> list[str]:
    return [c["tool"] for c in turn.calls]


async def test_journey_how_far_is_the_project_reads_instead_of_telling_the_team() -> None:
    # Production: tell_the_team + "Mesiri can't do project progress". Now the same first answer is run once more.
    model = Runs([[TEAM_PROGRESS], "Mesiri cannot do project progress now; given to the team."],
                 [[PROGRESS, ISSUES, SUMMARY], "Slab concrete 12 cum done on 4 Nov. No open issues."])
    turn, api = await _turn(model, "Asus garden project ethra aayi?")
    assert model.calls == 2 and "work_progress" in model.prompts[1]
    assert set(_tools_called(turn)) == READS and "tell_the_team" not in _tools_called(turn)
    assert [m for m, p in api.seen] == ["GET"] * 3 and not turn.pending


async def test_the_reported_message_with_no_tool_at_all_is_sent_to_the_read_tools() -> None:
    model = Runs(["Ithu Mesiri-kk cheyyaan kazhiyilla; project progress feedback aayi team-nu kodukkaam."],
                 [[PROGRESS, ISSUES], "Slab concrete 12 cum aayi."])
    turn, _ = await _turn(model, "Ithil oru projectine evide muthal evide vare ethikkum? project progress ethra aayi")
    assert model.calls == 2 and set(_tools_called(turn)) == {"work_progress", "list_issues"}
    assert not [c for c in turn.calls if c.get("by") == "code"]


async def test_sibling_malayalam_script_and_english_ask_the_same() -> None:
    for words in ("പണി എത്ര ആയി", "how is Green Villa going?"):
        model = Runs([[TEAM_PROGRESS], "I can't do project progress."], [[PROGRESS, ISSUES], "Slab done."])
        turn, _ = await _turn(model, words)
        assert "tell_the_team" not in _tools_called(turn) and "work_progress" in _tools_called(turn)


async def test_a_project_with_nothing_recorded_gets_the_read_and_no_cant() -> None:
    model = Runs([[TEAM_PROGRESS], "Mesiri can't do project progress."],
                 [[PROGRESS, ISSUES, SUMMARY], "Nothing is recorded yet. Send e.g. \"Slab concrete 12 cum done\"."])
    turn, api = await _turn(model, "how far is the new project?", _api())
    assert set(_tools_called(turn)) == READS and not turn.pending
    assert "tell_the_team" not in _tools_called(turn)


async def test_guard_a_really_missing_feature_still_reaches_the_team() -> None:
    team = ("tell_the_team", {"kind": "missing_feature", "about": "send my invoice to the client by email"})
    model = Runs([[team], "Mesiri cannot email invoices yet; passed to the team."], ["never reached"])
    turn, _ = await _turn(model, "send my invoice to the client by email")
    assert model.calls == 1 and _tools_called(turn) == ["tell_the_team"]


async def test_guard_a_topic_match_that_still_reads_nothing_keeps_the_team_told() -> None:
    model = Runs([[TEAM_PROGRESS], "Can't do project progress."], [[TEAM_PROGRESS], "Passed to the team."])
    turn, _ = await _turn(model, "project progress")
    assert model.calls == 2 and _tools_called(turn) == ["tell_the_team"]


async def test_guard_a_turn_that_already_read_is_left_alone() -> None:
    model = Runs([[PROGRESS], "Slab concrete 12 cum done. I can't see issues for it."], ["never reached"])
    await _turn(model, "how far is the project?")
    assert model.calls == 1


async def test_what_can_mesiri_do_is_in_the_system_context_and_writes_nothing() -> None:
    seen: list[str] = []

    class Spy(Runs):
        async def run_tools(self, system: str, *args: Any, **kwargs: Any) -> Any:
            seen.append(system)
            return await super().run_tools(system, *args, **kwargs)

    model = Spy(["Mesiri records attendance, work, materials, issues and expenses; answers progress, stock and attendance; "
                 "sends the daily report."])
    turn, api = await _turn(model, "Mesiri-kku enthokke cheyyaam?")
    block = what_mesiri_does(_real_tools())
    assert block in seen[0]
    # [249]: the block is in plain words (the model copied tool names into its answer); every group is there.
    assert all(head in block for head in ("Record (", "Ask (", "Reports ("))
    assert not any(name in block for name in ("record_attendance", "record_receipt", "work_progress", "send_dpr"))
    assert turn.calls == [] and not turn.pending and api.seen == [] and model.calls == 1


def test_the_block_follows_the_tool_list() -> None:
    extra = Allowed("list_snags", "GET", "/progress/issues", "Snag list per site.")
    tools = build_tools(__import__("agent_api.app", fromlist=["x"]).build_api_app(None).openapi(), (*ALLOWED, extra))
    block = what_mesiri_does(tools)
    assert "- Snag list per site" in block and "list_snags" not in block  # [249]: by its words, never its name


def test_the_sop_maps_both_questions() -> None:
    assert "What Mesiri does" in SOP and "work_progress" in SOP and "list_issues" in SOP and "day_summary" in SOP


def test_topic_comes_from_the_tools_not_a_word_list() -> None:
    tools = _real_tools()
    assert "work_progress" in read_tools_for("Answer questions about project progress", tools)
    assert "stock_levels" in read_tools_for("how much cement stock is left", tools)
    assert read_tools_for("send my invoice to the client by email", tools) == []
