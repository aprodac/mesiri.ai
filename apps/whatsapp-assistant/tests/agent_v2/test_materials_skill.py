"""Request 174: the materials skill's tools, rules file and figure check."""

from __future__ import annotations

from agent_v2.agents.main import SKILL_PATH, system_prompt
from agent_v2.skills.materials import tools as skill
from runtime.agent import tools as classic


def test_the_tools_are_todays_specs_under_the_v2_names():
    by_name = {s.name: s for s in skill.specs()}
    assert set(by_name) == {
        "draft_receipt", "draft_usage", "draft_stock_count", "transfer", "change_line", "remove_line",
        "stock_for", "ask", "catalog_match", "material_request_not_available",
    }
    old = {s.name: s for s in classic.tool_specs()}
    for v2_name, old_name in skill.CLASSIC_NAME.items():
        if v2_name == skill.REMOVE_LINE:
            continue  # v2's own (the classic model has no such tool)
        mine = dict(by_name[v2_name].parameters["properties"])
        for key in skill.ACCOUNT_KEYS:
            mine.pop(key)
        if v2_name == skill.CHANGE_LINE:
            mine["card_id"] = old[old_name].parameters["properties"]["card_id"]
            mine["item_index"] = old[old_name].parameters["properties"]["item_index"]
        assert mine == old[old_name].parameters["properties"]  # one place owns the arguments


def test_v2_can_only_reach_material_tools_of_the_old_toolbox():
    assert set(skill.CLASSIC_NAME.values()) == {
        classic.SAVE_MATERIAL_RECEIPT, classic.SAVE_MATERIAL_USAGE, classic.ADJUST_STOCK,
        classic.QUERY_MATERIALS, classic.ASK_USER, classic.TRANSFER_MATERIAL, classic.UPDATE_PENDING_CARD,
        classic.REMOVE_CARD_LINE,
    }


def test_the_rules_file_is_the_prompt_and_states_the_rules():
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert text.strip() in system_prompt()
    for rule in ("Never invent a material", "Every number in the message", "stock count", "Save"):
        assert rule.lower() in text.lower(), rule
    assert "hand_back" not in system_prompt()  # request 180: no routing, every message is v2's


def test_the_general_rules_are_in_the_prompt_and_cover_the_cases_of_plan_180():
    from agent_v2.agents.main import GENERAL_SKILL_PATH

    general = GENERAL_SKILL_PATH.read_text(encoding="utf-8")
    assert general.strip() in system_prompt()
    for rule in ("EVERY part", "complaints", "no data for", "Greetings", "never say anything is saved"):
        assert rule.lower() in general.lower(), rule


def test_v2_gets_the_existing_record_and_read_tools_with_todays_specs_and_no_admin_tools():
    from agent_v2.agents.main import GENERAL_TOOLS, all_specs

    names = {s.name for s in all_specs()}
    assert GENERAL_TOOLS <= names
    assert {"save_labour", "save_work_done", "save_expense", "report_issue", "set_site_conditions",
            "query_work_log", "query_project", "query_open_needs", "request_dpr"} <= names
    assert not names & {"create_site", "create_project", "add_member", "get_join_code", "set_reply_language"}
    old = {s.name: s for s in classic.tool_specs()}
    assert all(s.parameters == old[s.name].parameters for s in all_specs() if s.name in GENERAL_TOOLS)


def test_figures_are_read_plainly():
    assert skill.figures("1,500 brick, 2.50 load, 176") == {"1500", "2.5", "176"}


def test_a_figure_on_no_call_is_unplaced():
    calls = [("draft_receipt", {"material": "cement", "quantity": 50, "unit": "bags"})]
    assert skill.unplaced_figures("176 and 50 bag cement vannu", calls) == ["176"]
    assert skill.unplaced_figures("50 bag cement vannu", calls) == []


def test_a_figure_in_the_question_is_asked_about_not_unplaced():
    assert skill.unplaced_figures("176 cement", [], "What is 176 for?") == []


def test_a_figure_inside_a_name_counts_as_carried():
    calls = [("draft_receipt", {"material": "20mm metal", "quantity": 2, "unit": "load"})]
    assert skill.unplaced_figures("20mm metal 2 load vannu", calls) == []
