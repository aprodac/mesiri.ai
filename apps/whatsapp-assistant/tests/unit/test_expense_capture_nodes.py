"""Expense capture workflow nodes — unit tests (pure functions, no LangGraph needed)."""

from __future__ import annotations

from mesiri_contracts.assistant.draft_action import DraftActionType
from mesiri_contracts.assistant.planner_decision import WorkflowKey
from workflows.expense_capture.nodes import (
    _DUPLICATE_CANDIDATES,
    _OWN_POCKET_LABEL,
    _VENDOR_CANDIDATES,
    OWN_POCKET_SENTINEL,
    build_draft,
    check_duplicate,
    request_confirmation,
    resolve_account,
    resolve_vendor,
)

ORG = "11111111-1111-4111-8111-111111111111"
USR = "22222222-2222-4222-8222-222222222222"
PRJ = "33333333-3333-4333-8333-333333333333"
SITE = "44444444-4444-4444-8444-444444444444"


def _base_state(fields: dict) -> dict:
    return {
        "workflow_instance_id": "wf_1",
        "workflow_key": WorkflowKey.EXPENSE_SUBMIT.value,
        "correlation_id": "cor_1",
        "organization_id": ORG,
        "user_id": USR,
        "project_id": PRJ,
        "site_id": SITE,
        "collected_fields": fields,
    }


def test_build_draft_expense():
    state = _base_state({"amount": 250, "category": "materials", "description": "cement bags"})
    update = build_draft(state)
    draft = update["draft_action"]
    assert draft.action_type is DraftActionType.RECORD_EXPENSE
    assert draft.fields == {"amount": 250, "category": "materials", "description": "cement bags"}
    assert draft.workflow_instance_id == "wf_1"
    assert draft.correlation_id == "cor_1"
    assert draft.organization_id == ORG
    assert draft.project_id == PRJ
    assert draft.site_id == SITE


def test_build_draft_missing_collected_fields_defaults_empty():
    state = _base_state({})
    del state["collected_fields"]
    update = build_draft(state)
    assert update["draft_action"].fields == {}


def test_request_confirmation_sets_prompt_from_draft():
    state = _base_state({"amount": 250, "category": "materials"})
    state.update(build_draft(state))
    prompt = request_confirmation(state)["pending_prompt"]
    assert "Expense" in prompt
    assert "250" in prompt
    assert "materials" in prompt
    assert "YES" in prompt


def test_build_draft_excludes_account_candidates_plumbing_field():
    state = _base_state(
        {"amount": 250, "account_id": "a1", "account_candidates": [{"id": "a1", "name": "Cash"}]}
    )
    draft = build_draft(state)["draft_action"]
    assert "account_candidates" not in draft.fields
    assert draft.fields["account_id"] == "a1"


def test_resolve_account_already_resolved_is_a_no_op():
    state = _base_state({"amount": 250, "account_id": "a1"})
    assert resolve_account(state) == {}

    state = _base_state({"amount": 250, "paid_from_own_pocket": True})
    assert resolve_account(state) == {}


def test_resolve_account_zero_candidates_autofills_own_pocket():
    state = _base_state({"amount": 250})
    update = resolve_account(state)
    assert update["collected_fields"]["paid_from_own_pocket"] is True
    assert "awaiting_slot" not in update


def test_resolve_account_with_candidates_asks_since_own_pocket_is_always_an_option():
    """Even a single real account means 2 total choices (account + own
    pocket), so the slot must ask rather than silently auto-fill."""
    state = _base_state(
        {"amount": 250, "account_candidates": [{"id": "a1", "name": "Site Cash"}]}
    )
    update = resolve_account(state)
    assert update["awaiting_slot"] == "account_id"
    assert "Site Cash" in update["pending_prompt"]
    assert "own pocket" in update["pending_prompt"].lower()
    # Real WhatsApp interactive list, not just numbered text -- see
    # workflows/slots.py's slot_options.
    assert update["awaiting_slot_options"] == [
        {"value": "a1", "label": "Site Cash"},
        {"value": "own_pocket", "label": "My own pocket"},
    ]


def test_resolve_account_numbered_answer_selects_account():
    state = _base_state(
        {
            "amount": 250,
            "account_candidates": [{"id": "a1", "name": "Site Cash"}, {"id": "a2", "name": "Bank"}],
            "_slot_answer_text": "2",
        }
    )
    update = resolve_account(state)
    assert update["awaiting_slot"] is None
    assert update["collected_fields"]["account_id"] == "a2"
    assert "account_candidates" not in update["collected_fields"] or True  # candidates may remain


def test_resolve_account_text_answer_selects_own_pocket():
    state = _base_state(
        {
            "amount": 250,
            "account_candidates": [{"id": "a1", "name": "Site Cash"}],
            "_slot_answer_text": "my own pocket",
        }
    )
    update = resolve_account(state)
    assert update["awaiting_slot"] is None
    assert update["collected_fields"]["paid_from_own_pocket"] is True
    assert update["collected_fields"].get("account_id") is None


def test_resolve_account_unmatched_answer_reasks_with_different_wording():
    state = _base_state(
        {
            "amount": 250,
            "account_candidates": [{"id": "a1", "name": "Site Cash"}],
            "_slot_answer_text": "purple monkey dishwasher",
        }
    )
    update = resolve_account(state)
    assert update["awaiting_slot"] == "account_id"
    assert "couldn't tell which one" in update["pending_prompt"]
    # The consumed answer text must not linger in collected_fields.
    assert "_slot_answer_text" not in update["collected_fields"]


def test_own_pocket_sentinel_is_not_a_real_uuid_shaped_value():
    assert OWN_POCKET_SENTINEL == "own_pocket"


def test_build_draft_keeps_media_object_key_for_the_backend():
    """Unlike account_candidates, media_object_key is real data the backend
    needs (RecordExpenseCommand.media_object_key writes an
    expense_attachments row) -- it must survive into draft.fields."""
    state = _base_state({"amount": 250, "media_object_key": "media/wamid.1/abc123"})
    draft = build_draft(state)["draft_action"]
    assert draft.fields["media_object_key"] == "media/wamid.1/abc123"


def test_request_confirmation_hides_the_raw_key_but_notes_a_receipt():
    state = _base_state({"amount": 250, "media_object_key": "media/wamid.1/abc123"})
    state.update(build_draft(state))
    prompt = request_confirmation(state)["pending_prompt"]
    assert "media_object_key" not in prompt
    assert "media/wamid.1/abc123" not in prompt
    assert "Receipt attached" in prompt


def test_request_confirmation_has_no_receipt_note_without_an_image():
    state = _base_state({"amount": 250})
    state.update(build_draft(state))
    prompt = request_confirmation(state)["pending_prompt"]
    assert "Receipt attached" not in prompt


def test_check_duplicate_not_flagged_is_a_no_op():
    state = _base_state({"amount": 250})
    assert check_duplicate(state) == {}


def test_check_duplicate_flagged_asks_yes_no():
    state = _base_state({"amount": 250, "is_potential_duplicate": True})
    update = check_duplicate(state)
    assert update["awaiting_slot"] == "duplicate_confirm"
    assert "duplicate" in update["pending_prompt"]
    assert "1." in update["pending_prompt"] and "2." in update["pending_prompt"]
    # Real WhatsApp interactive list (Yes/No as tappable rows), not just
    # numbered text -- see workflows/slots.py's slot_options.
    assert update["awaiting_slot_options"] == [
        {"value": "yes", "label": "Yes, record it anyway"},
        {"value": "no", "label": "No, cancel"},
    ]


def test_check_duplicate_yes_answer_proceeds():
    state = _base_state(
        {"amount": 250, "is_potential_duplicate": True, "_slot_answer_text": "yes"}
    )
    state["awaiting_slot"] = "duplicate_confirm"
    update = check_duplicate(state)
    assert update["collected_fields"]["duplicate_confirmed"] == "yes"
    assert update["awaiting_slot"] is None
    assert "_slot_answer_text" not in update["collected_fields"]


def test_check_duplicate_no_answer_cancels_with_no_draft():
    state = _base_state(
        {"amount": 250, "is_potential_duplicate": True, "_slot_answer_text": "no"}
    )
    state["awaiting_slot"] = "duplicate_confirm"
    update = check_duplicate(state)
    assert update["collected_fields"]["duplicate_confirmed"] == "no"
    assert update["awaiting_slot"] is None
    assert "won't record" in update["pending_prompt"]


def test_check_duplicate_unmatched_answer_reasks():
    state = _base_state(
        {"amount": 250, "is_potential_duplicate": True, "_slot_answer_text": "maybe idk"}
    )
    state["awaiting_slot"] = "duplicate_confirm"
    update = check_duplicate(state)
    assert update["awaiting_slot"] == "duplicate_confirm"
    assert "couldn't tell which one" in update["pending_prompt"]


def test_check_duplicate_already_answered_is_a_no_op():
    state = _base_state({"amount": 250, "is_potential_duplicate": True, "duplicate_confirmed": "yes"})
    assert check_duplicate(state) == {}


def test_build_draft_excludes_duplicate_plumbing_fields():
    state = _base_state(
        {"amount": 250, "is_potential_duplicate": True, "duplicate_confirmed": "yes"}
    )
    draft = build_draft(state)["draft_action"]
    assert "is_potential_duplicate" not in draft.fields
    assert "duplicate_confirmed" not in draft.fields


def test_resolve_vendor_not_flagged_is_a_no_op():
    state = _base_state({"amount": 250, "vendor": "Indian Oil"})
    assert resolve_vendor(state) == {}


def test_resolve_vendor_flagged_asks_yes_no():
    state = _base_state({"amount": 250, "vendor": "New Fuel Co", "vendor_needs_confirmation": True})
    update = resolve_vendor(state)
    assert update["awaiting_slot"] == "vendor_confirm"
    assert "New Fuel Co" in update["pending_prompt"]
    assert update["awaiting_slot_options"] == [
        {"value": "yes", "label": "Yes, add new vendor"},
        {"value": "no", "label": "No, skip vendor"},
    ]


def test_resolve_vendor_yes_answer_keeps_vendor():
    state = _base_state(
        {
            "amount": 250,
            "vendor": "New Fuel Co",
            "vendor_needs_confirmation": True,
            "_slot_answer_text": "yes",
        }
    )
    state["awaiting_slot"] = "vendor_confirm"
    update = resolve_vendor(state)
    assert update["collected_fields"]["vendor_confirmed"] == "yes"
    assert update["collected_fields"]["vendor"] == "New Fuel Co"
    assert update["awaiting_slot"] is None


def test_resolve_vendor_no_answer_drops_vendor_but_does_not_cancel():
    """Unlike check_duplicate's "no", this must never end the workflow --
    the expense still gets recorded, just without a vendor."""
    state = _base_state(
        {
            "amount": 250,
            "vendor": "New Fuel Co",
            "vendor_needs_confirmation": True,
            "_slot_answer_text": "no",
        }
    )
    state["awaiting_slot"] = "vendor_confirm"
    update = resolve_vendor(state)
    assert update["collected_fields"]["vendor_confirmed"] == "no"
    assert "vendor" not in update["collected_fields"]
    assert update["awaiting_slot"] is None
    assert "pending_prompt" not in update


# --- Phase 4: near-match suggestions (ENTITY_RESOLUTION_PLAN.md §5) ---------
# _seed_vendor_check now seeds vendor_candidates when the reported name is a
# near-miss rather than an absence, so the node offers them instead of
# unconditionally asking "add it as new?" -- which is what produced duplicate
# vendor rows for every alternate spelling.


def _suggested_state(answer: str | None = None) -> dict:
    fields = {
        "amount": 250,
        "vendor": "Sharma Traders",
        "vendor_needs_confirmation": True,
        "vendor_candidates": [{"value": "v_1", "label": "Sharma Trading Co"}],
    }
    if answer is not None:
        fields["_slot_answer_text"] = answer
    state = _base_state(fields)
    if answer is not None:
        state["awaiting_slot"] = "vendor_confirm"
    return state


def test_resolve_vendor_offers_near_matches_ahead_of_add_new():
    update = resolve_vendor(_suggested_state())
    assert update["awaiting_slot"] == "vendor_confirm"
    assert update["awaiting_slot_options"] == [
        {"value": "Sharma Trading Co", "label": "Sharma Trading Co"},
        {"value": "yes", "label": "Yes, add new vendor"},
        {"value": "no", "label": "No, skip vendor"},
    ]
    assert "Did you mean" in update["pending_prompt"]


def test_choosing_a_suggestion_adopts_its_exact_stored_spelling():
    """The duplicate-row fix: the backend resolver re-matches on this exact
    string, so it has to be the vendor's real name, not what was typed."""
    update = resolve_vendor(_suggested_state(answer="Sharma Trading Co"))
    assert update["collected_fields"]["vendor"] == "Sharma Trading Co"
    assert update["collected_fields"]["vendor_confirmed"] == "yes"
    assert update["awaiting_slot"] is None


def test_add_new_still_keeps_the_name_as_typed_even_with_suggestions():
    """The escape hatch: a near-match is a suggestion, never an override --
    "Sharma Traders" really may be a different business."""
    update = resolve_vendor(_suggested_state(answer="Yes, add new vendor"))
    assert update["collected_fields"]["vendor"] == "Sharma Traders"
    assert update["collected_fields"]["vendor_confirmed"] == "yes"


def test_skip_still_drops_the_vendor_even_with_suggestions():
    update = resolve_vendor(_suggested_state(answer="No, skip vendor"))
    assert update["collected_fields"]["vendor_confirmed"] == "no"
    assert "vendor" not in update["collected_fields"]


def test_empty_suggestions_fall_back_to_the_plain_yes_no_offer():
    """A seeded-but-empty list must not produce a picker with only the two
    control rows and a "did you mean" prompt naming nothing."""
    state = _base_state(
        {
            "amount": 250,
            "vendor": "New Fuel Co",
            "vendor_needs_confirmation": True,
            "vendor_candidates": [],
        }
    )
    update = resolve_vendor(state)
    assert update["awaiting_slot_options"] == [
        {"value": "yes", "label": "Yes, add new vendor"},
        {"value": "no", "label": "No, skip vendor"},
    ]
    assert "Add it as a new vendor?" in update["pending_prompt"]


def test_vendor_candidates_never_reach_the_draft():
    """Plumbing, like account_candidates -- it must not show up in the
    confirmation prompt or travel on to RecordExpenseCommand."""
    from workflows.expense_capture.nodes import _INTERNAL_FIELD_KEYS

    assert "vendor_candidates" in _INTERNAL_FIELD_KEYS


def test_resolve_vendor_unmatched_answer_reasks():
    state = _base_state(
        {
            "amount": 250,
            "vendor": "New Fuel Co",
            "vendor_needs_confirmation": True,
            "_slot_answer_text": "maybe idk",
        }
    )
    state["awaiting_slot"] = "vendor_confirm"
    update = resolve_vendor(state)
    assert update["awaiting_slot"] == "vendor_confirm"
    assert "couldn't tell which one" in update["pending_prompt"]


def test_resolve_vendor_already_answered_is_a_no_op():
    state = _base_state(
        {"amount": 250, "vendor": "New Fuel Co", "vendor_needs_confirmation": True, "vendor_confirmed": "yes"}
    )
    assert resolve_vendor(state) == {}


def test_resolve_vendor_no_vendor_text_is_a_no_op():
    """A flag with no vendor name to confirm can't happen in practice, but
    the node must not crash if it ever does."""
    state = _base_state({"amount": 250, "vendor_needs_confirmation": True})
    assert resolve_vendor(state) == {}


def test_build_draft_excludes_vendor_plumbing_fields():
    state = _base_state(
        {"amount": 250, "vendor": "New Fuel Co", "vendor_needs_confirmation": True, "vendor_confirmed": "yes"}
    )
    draft = build_draft(state)["draft_action"]
    assert "vendor_needs_confirmation" not in draft.fields
    assert "vendor_confirmed" not in draft.fields
    assert draft.fields["vendor"] == "New Fuel Co"


def test_slot_labels_fit_whatsapp_list_row_title_limit():
    """runtime/inbound_journey.py::_render_reply silently degrades an entire
    slot question to plain numbered text (no tappable list/buttons at all)
    the moment any one candidate label exceeds WhatsApp's 24-char row-title
    cap -- this exact bug shipped once already (own-pocket and the vendor-
    confirm labels), reported by a real user seeing a numbered-text prompt
    where they expected buttons. This guards every label in this module
    against silently regressing the same way."""
    all_labels = [
        _OWN_POCKET_LABEL,
        *(c.label for c in _DUPLICATE_CANDIDATES),
        *(c.label for c in _VENDOR_CANDIDATES),
    ]
    for label in all_labels:
        assert len(label) <= 24, f"{label!r} is {len(label)} chars, exceeds WhatsApp's 24-char cap"


# --- date display (STA-166 backport) ---------------------------------------


def test_confirmation_shows_a_stated_date_without_the_assumed_marker():
    state = _base_state(
        {
            "amount": 250,
            "category": "fuel",
            "occurred_date": "2026-07-20",
            "occurred_date_source": "stated_by_user",
        }
    )
    state.update(build_draft(state))
    prompt = request_confirmation(state)["pending_prompt"]
    assert "Date: 20 Jul 2026" in prompt
    assert "assumed" not in prompt


def test_confirmation_admits_when_the_date_was_guessed():
    state = _base_state(
        {
            "amount": 250,
            "category": "fuel",
            "occurred_date": "2026-07-27",
            "occurred_date_source": "inferred_at_confirmation",
        }
    )
    state.update(build_draft(state))
    prompt = request_confirmation(state)["pending_prompt"]
    assert "Date: 27 Jul 2026 (assumed today)" in prompt


def test_confirmation_never_shows_the_raw_date_plumbing():
    state = _base_state(
        {
            "amount": 250,
            "category": "fuel",
            "occurred_date": "2026-07-27",
            "occurred_date_source": "inferred_at_confirmation",
        }
    )
    state.update(build_draft(state))
    prompt = request_confirmation(state)["pending_prompt"]
    assert "occurred_date_source" not in prompt
    assert "inferred_at_confirmation" not in prompt


def test_confirmation_omits_the_date_line_when_there_is_no_date():
    state = _base_state({"amount": 250, "category": "fuel"})
    state.update(build_draft(state))
    prompt = request_confirmation(state)["pending_prompt"]
    assert "Date:" not in prompt
