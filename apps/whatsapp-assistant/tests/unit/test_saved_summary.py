"""Request 57, A2/B3: replies say what was saved, from the saved data."""

from __future__ import annotations

import pytest

from interactions.response_handler import render_execution_reply
from interactions.saved_summary import render_saved, summarise_draft
from mesiri_contracts.application.results.execution_result import ExecutionResult, ExecutionStatus
from mesiri_contracts.assistant.draft_action import DraftActionType
from mesiri_contracts.assistant.v2.draft_action import DraftActionV2
from runtime.reply_language import localize_saved_lines


def _draft(action: DraftActionType, fields: dict) -> DraftActionV2:
    return DraftActionV2(
        draft_id="draft_1",
        correlation_id="cor_1",
        workflow_instance_id="wf_1",
        action_type=action,
        organization_id="11111111-1111-4111-8111-111111111111",
        user_id="22222222-2222-4222-8222-222222222222",
        fields=fields,
    )


@pytest.mark.parametrize(
    ("action", "fields", "expected"),
    [
        (
            DraftActionType.RECORD_LABOUR_ATTENDANCE,
            {"lines": [{"trade": "mason", "headcount": 6}, {"trade": "helper", "headcount": 10}]},
            "16 workers (6 mason, 10 helper)",
        ),
        (
            DraftActionType.RECORD_LABOUR_ATTENDANCE,
            {"lines": [{"worker_name": "Ravi", "trade": "mason", "headcount": 1}]},
            "1 worker (1 mason)",
        ),
        (
            DraftActionType.CREATE_ACTIVITY,
            {"work_type": "plastering", "location": "2nd floor", "progress_percent": 40,
             "narrative": "Plastering 2nd floor 40% aayi"},
            "Plastering, 2nd floor: 40%",
        ),
        (
            DraftActionType.CREATE_ACTIVITY,
            {"work_type": "plastering", "quantities": [{"quantity": 180, "unit": "sqm"}]},
            "Plastering: 180 sqm",
        ),
        (
            DraftActionType.RECORD_MATERIAL_RECEIPT,
            {"material_name": "cement", "quantity": 25, "unit": "bags"},
            "Cement in: 25 bags",
        ),
        (
            DraftActionType.RECORD_MATERIAL_USAGE,
            {"material_name": "cement", "quantity": "5.0", "unit": "bags"},
            "Cement used: 5 bags",
        ),
        (
            DraftActionType.RECORD_EXPENSE,
            {"amount": "4500", "category": "transport"},
            "Expense ₹4500 (Transport)",
        ),
        (
            DraftActionType.RECORD_SITE_ISSUE,
            {"issue_type": "WEATHER", "narrative": "rain stopped work"},
            "Issue (weather): rain stopped work",
        ),
        (
            DraftActionType.RECORD_SITE_ISSUE,
            {"issue_type": "OTHER", "narrative": "Question for your engineer: Can we pour the slab tomorrow?"},
            "Question for your engineer: Can we pour the slab tomorrow?",
        ),
    ],
)
def test_summary_is_built_from_the_saved_fields_not_the_message(action, fields, expected):
    assert summarise_draft(_draft(action, fields)) == expected


def test_the_senders_raw_words_never_appear():
    summary = summarise_draft(
        _draft(
            DraftActionType.RECORD_LABOUR_ATTENDANCE,
            {"narrative": "6 mason, 10 helper vannu",
             "lines": [{"trade": "mason", "headcount": 6}, {"trade": "helper", "headcount": 10}]},
        )
    )
    assert "vannu" not in summary


def test_render_saved_one_line_or_bullets():
    assert render_saved(["12 workers"]) == "✅ Saved: 12 workers"
    assert render_saved(["12 workers", "Cement in: 25 bags"]) == (
        "✅ Saved:\n• 12 workers\n• Cement in: 25 bags"
    )
    assert render_saved([]) == ""


def test_execution_reply_says_what_was_saved_else_the_generic_thanks():
    ok = ExecutionResult(status=ExecutionStatus.SUCCEEDED, idempotency_key="k", material_row_id="r")
    draft = _draft(DraftActionType.RECORD_MATERIAL_RECEIPT, {"material_name": "cement", "quantity": 25, "unit": "bags"})
    assert render_execution_reply(ok, draft) == "✅ Saved: Cement in: 25 bags"
    assert render_execution_reply(ok) == "✅ Recorded. Thank you."
    unknown = _draft(DraftActionType.CREATE_PROJECT, {"name": "X"})
    assert render_execution_reply(ok, unknown) == "✅ Recorded. Thank you."


def test_label_words_follow_the_senders_language_but_numbers_and_trades_do_not():
    text = "✅ Saved:\n• 16 workers (6 mason, 10 helper)\n• Cement in: 25 bags\n\nWrong? Reply UNDO."
    ml = localize_saved_lines(text, "Malayalam", "native")
    assert "• 16 തൊഴിലാളികൾ (6 mason, 10 helper)" in ml
    assert "• Cement വന്നു: 25 bags" in ml
    assert ml.endswith("Wrong? Reply UNDO.")
    # English letters (Manglish) and English stay as written.
    assert localize_saved_lines(text, "Malayalam", "latin") == text
    assert localize_saved_lines(text, None, "native") == text
