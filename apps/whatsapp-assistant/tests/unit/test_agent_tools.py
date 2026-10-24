"""Request [40]: the agent's tools -- schemas, and the understanding each stands for."""

from __future__ import annotations

import pytest

from mesiri_contracts.assistant.enums import SemanticType
from runtime.agent import tools as t

SCOPE = t.ScopeLookup(
    projects=(("p-alpha", "Project Alpha"), ("p-beta", "Project Beta")),
    sites=(
        ("s-a1", "Site A1", "p-alpha"),
        ("s-a2", "Site A2", "p-alpha"),
        ("s-b1", "Site B1", "p-beta"),
        ("s-green", "Green Villa", "p-beta"),
    ),
)


def test_every_tool_has_a_unique_name_and_an_object_schema():
    specs = t.tool_specs()
    names = [s.name for s in specs]
    assert len(names) == len(set(names))
    for spec in specs:
        assert spec.description
        assert spec.parameters["type"] == "object"
        for required in spec.parameters.get("required", []):
            assert required in spec.parameters["properties"]


def test_the_plan_s_tools_all_exist():
    names = {s.name for s in t.tool_specs()}
    assert {
        "save_labour",
        "save_work_done",
        "save_material_receipt",
        "save_material_usage",
        "save_expense",
        "report_issue",
        "transfer_money",
        "undo_last",
        "ask_user",
        "query_labour",
        "query_materials",
        "query_work_log",
        "query_project",
        "query_expenses",
        "request_dpr",
    } <= names


def test_write_tools_are_all_real_tools():
    assert t.WRITE_TOOLS <= {s.name for s in t.tool_specs()}


def test_labour_maps_to_a_labour_update_with_the_workers_as_given():
    workers = [{"name": "Ravi", "trade": "mason"}, {"trade": "helper", "headcount": 12}]
    c = t.to_candidate("save_labour", {"workers": workers, "date": "yesterday"}, SCOPE)
    assert c.semantic_type is SemanticType.LABOUR_UPDATE
    assert c.fields["workers"] == workers
    assert c.fields["occurred_on"] == "yesterday"


@pytest.mark.parametrize(
    ("tool", "direction"),
    [("save_material_receipt", "received"), ("save_material_usage", "used")],
)
def test_material_tools_fix_the_direction(tool, direction):
    c = t.to_candidate(tool, {"material": "cement", "quantity": 40, "unit": "bags"}, SCOPE)
    assert c.semantic_type is SemanticType.MATERIAL_UPDATE
    assert c.fields["direction"] == direction
    assert c.fields["material_name"] == "cement"


def test_a_receipt_keeps_the_supplier_and_a_usage_keeps_the_work_item():
    r = t.to_candidate(
        "save_material_receipt",
        {"material": "cement", "quantity": 1, "unit": "bags", "supplier": "Sharma", "work_item": "x"},
        SCOPE,
    )
    u = t.to_candidate(
        "save_material_usage",
        {"material": "cement", "quantity": 1, "unit": "bags", "supplier": "Sharma", "work_item": "slab"},
        SCOPE,
    )
    assert r.fields.get("supplier") == "Sharma" and "work_item" not in r.fields
    assert u.fields.get("work_item") == "slab" and "supplier" not in u.fields


@pytest.mark.parametrize(
    ("tool", "args", "semantic"),
    [
        ("save_work_done", {"narrative": "plastering 180 sqm"}, SemanticType.GENERAL_SITE_UPDATE),
        ("save_expense", {"amount": 500}, SemanticType.EXPENSE),
        ("report_issue", {"issue_type": "WEATHER", "narrative": "rain"}, SemanticType.SITE_ISSUE),
        ("transfer_money", {"amount": 10}, SemanticType.TRANSFER),
        ("query_labour", {"date_range": "today"}, SemanticType.LABOUR_QUERY),
        ("query_materials", {"material": "steel"}, SemanticType.INVENTORY_QUERY),
        ("query_work_log", {}, SemanticType.ACTIVITY_QUERY),
        ("query_project", {}, SemanticType.PROJECT_DETAIL_QUERY),
        ("query_expenses", {"kind": "balance"}, SemanticType.FINANCE_QUERY),
        ("request_dpr", {}, SemanticType.DPR_REQUEST),
        ("undo_last", {"what": "expense"}, SemanticType.REVERSAL),
    ],
)
def test_each_tool_stands_for_its_classic_semantic_type(tool, args, semantic):
    assert t.to_candidate(tool, args, SCOPE).semantic_type is semantic


def test_finance_query_uses_the_classic_field_names():
    c = t.to_candidate(
        "query_expenses",
        {"kind": "expenses", "category": "diesel", "date_range": "this_week", "missing_receipts": True},
        SCOPE,
    )
    assert c.fields == {
        "query_kind": "expenses",
        "category_name": "diesel",
        "date_range": "this_week",
        "missing_receipts": True,
    }


def test_work_log_passes_the_day_asked_about():
    """V1 audit WRK-03: 'what was done yesterday?' reaches the seed as one day."""
    c = t.to_candidate("query_work_log", {"day": "yesterday"}, SCOPE)
    assert c.fields["day"] == "yesterday"


def test_the_latest_update_undo_and_ask_user_are_not_workflows():
    assert t.to_candidate("undo_last", {}, SCOPE) is None
    assert t.to_candidate("ask_user", {"question": "?"}, SCOPE) is None


def test_empty_values_are_left_out_so_nothing_reads_as_stated():
    c = t.to_candidate("save_work_done", {"narrative": "x", "location": "", "quantities": []}, SCOPE)
    assert c.fields == {"narrative": "x"}


def test_a_named_site_the_user_owns_becomes_its_id_and_brings_its_project():
    c = t.to_candidate("save_labour", {"workers": [{"headcount": 2}], "site": "green villa"}, SCOPE)
    assert c.fields["site_id"] == "s-green"
    assert "site_name" not in c.fields


def test_a_name_that_is_not_theirs_is_passed_as_said_for_the_pipeline_to_validate():
    # Another company's site is simply not in this sender's lookup.
    c = t.to_candidate("save_labour", {"workers": [{"headcount": 2}], "site": "Site Other"}, SCOPE)
    assert c.fields["site_name"] == "Site Other"
    assert "site_id" not in c.fields


def test_an_ambiguous_partial_name_is_not_guessed():
    assert SCOPE.site_id("Site") is None
    assert SCOPE.site_id("Site A1") == "s-a1"


def test_no_scope_is_added_when_the_user_named_none():
    c = t.to_candidate("save_labour", {"workers": [{"headcount": 2}]}, SCOPE)
    assert not ({"site_id", "site_name", "project_id", "project_name"} & set(c.fields))
