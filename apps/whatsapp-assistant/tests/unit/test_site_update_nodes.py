"""Activity Creation & Continuation (site_update) workflow nodes — tests.

Covers the merged resolver (docs/execution/ACTIVITY_RESOLUTION_AND_
CORRECTION_PLAN.md) that replaced two separate workflows
(site_update + activity_continuation). Proves the three failure modes the
old code had are fixed:

  F1 (wrong target) -- a work_type clash with the only open activity now
  asks instead of silently appending to it (test_clash_with_only_open_
  activity_asks_and_offers_new_work_option), and an exact match wins even
  with other candidates present (test_resolve_target_auto_matches_exact_
  work_type_over_other_open_candidates).

  F2 (dead end) -- no open activities now falls through to activity
  creation instead of a "nothing to continue" message with no draft
  (test_no_open_activities_falls_through_to_creation).

  F3 (silent duplicate) -- update_kind no longer decides create-vs-continue
  on its own; a continuation-shaped message with an open matching activity
  appends rather than creating a second one
  (test_single_open_activity_continuation_wording_auto_matches).

See test_activity_matching.py for the pure scoring-function tests this
node-level layer wraps.
"""

from __future__ import annotations

from mesiri_contracts.assistant.draft_action import DraftActionType
from mesiri_contracts.assistant.planner_decision import WorkflowKey
from workflows.site_update.nodes import (
    _TARGET_SLOT_NAME,
    NEW_ACTIVITY_SENTINEL,
    UNCLEAR_TARGET_IS_NEW_KEY,
    build_draft,
    request_confirmation,
    resolve_target,
)

ORG = "11111111-1111-4111-8111-111111111111"
USR = "22222222-2222-4222-8222-222222222222"
PRJ = "33333333-3333-4333-8333-333333333333"
SITE = "44444444-4444-4444-8444-444444444444"
PLASTERING_ID = "55555555-5555-4555-8555-555555555555"
BLOCKWORK_ID = "66666666-6666-4666-8666-666666666666"


def _base_state(fields: dict) -> dict:
    return {
        "workflow_instance_id": "wf_1",
        "workflow_key": WorkflowKey.SITE_UPDATE.value,
        "correlation_id": "cor_1",
        "organization_id": ORG,
        "user_id": USR,
        "project_id": PRJ,
        "site_id": SITE,
        "collected_fields": fields,
    }


def _candidate(activity_id: str, work_type: str | None, narrative: str | None) -> dict:
    return {"activity_id": activity_id, "work_type": work_type, "narrative": narrative}


# --- resolve_target -----------------------------------------------------------


def test_no_open_activities_falls_through_to_creation():
    """F2 fixed: nothing seeded to compare against -> resolves immediately,
    no activity_id set, no question asked."""
    state = _base_state({"work_type": "plastering", "narrative": "finished plastering"})
    update = resolve_target(state)
    assert update.get("awaiting_slot") is None
    assert "activity_id" not in update["collected_fields"]


def test_resolve_target_auto_matches_exact_work_type_over_other_open_candidates():
    """F1 fixed: an exact work_type match wins even with a more-recently-
    touched, non-matching candidate also open."""
    state = _base_state(
        {
            "work_type": "plastering",
            "narrative": "finished plastering",
            "_open_activity_candidates": [
                _candidate(BLOCKWORK_ID, "blockwork", "Block A"),
                _candidate(PLASTERING_ID, "plastering", "2nd floor"),
            ],
        }
    )
    update = resolve_target(state)
    assert update["collected_fields"]["activity_id"] == PLASTERING_ID
    assert update["collected_fields"]["activity_summary"] == "plastering — 2nd floor"
    assert update.get("awaiting_slot") is None


def test_clash_with_only_open_activity_asks_and_offers_new_work_option():
    """F1's other half fixed: a stated work_type that conflicts with the
    only open activity no longer silently appends to it."""
    state = _base_state(
        {
            "work_type": "plastering",
            "narrative": "finished plastering",
            "_open_activity_candidates": [_candidate(BLOCKWORK_ID, "blockwork", "Block A")],
        }
    )
    update = resolve_target(state)
    assert update["awaiting_slot"] == _TARGET_SLOT_NAME
    values = {opt["value"] for opt in update["awaiting_slot_options"]}
    assert BLOCKWORK_ID in values
    assert NEW_ACTIVITY_SENTINEL in values
    assert "Which work is this about?" in update["pending_prompt"]


def test_save_first_company_gets_unclear_work_saved_as_new_work():
    """WA-03 quiet daytime: the same clash, for a company that saves first,
    is not asked -- it becomes new work, and the flag never reaches the
    draft."""
    state = _base_state(
        {
            "work_type": "plastering",
            "narrative": "finished plastering",
            "_open_activity_candidates": [_candidate(BLOCKWORK_ID, "blockwork", "Block A")],
            UNCLEAR_TARGET_IS_NEW_KEY: True,
        }
    )
    update = resolve_target(state)
    assert update.get("awaiting_slot") is None
    assert "activity_id" not in update["collected_fields"]
    assert UNCLEAR_TARGET_IS_NEW_KEY not in update["collected_fields"]

    draft = build_draft({**state, "collected_fields": update["collected_fields"]})["draft_action"]
    assert draft.action_type is DraftActionType.CREATE_ACTIVITY
    assert not any(k.startswith("_") for k in draft.fields)


def test_save_first_flag_never_overrides_a_clear_match():
    state = _base_state(
        {
            "work_type": "plastering",
            "_open_activity_candidates": [
                _candidate(PLASTERING_ID, "plastering", "2nd floor"),
                _candidate(BLOCKWORK_ID, "blockwork", "Block A"),
            ],
            UNCLEAR_TARGET_IS_NEW_KEY: True,
        }
    )
    update = resolve_target(state)
    assert update["collected_fields"]["activity_id"] == PLASTERING_ID


def test_single_open_activity_continuation_wording_auto_matches():
    """F3 fixed: a continuation-shaped message (update_kind present, no
    restated work_type) with exactly one open activity appends to it
    without asking -- the one deliberate exception to "ask readily",
    since there is nothing to disambiguate against."""
    state = _base_state(
        {
            "update_kind": "progress",
            "narrative": "another 40 sqm done",
            "_open_activity_candidates": [_candidate(PLASTERING_ID, "plastering", "2nd floor")],
        }
    )
    update = resolve_target(state)
    assert update["collected_fields"]["activity_id"] == PLASTERING_ID


def test_no_work_type_no_continuation_hint_asks_rather_than_guessing():
    state = _base_state(
        {
            "narrative": "180 sqm done",
            "_open_activity_candidates": [_candidate(PLASTERING_ID, "plastering", "2nd floor")],
        }
    )
    update = resolve_target(state)
    assert update["awaiting_slot"] == _TARGET_SLOT_NAME


def test_answering_with_a_number_resolves_to_that_activity():
    state = _base_state(
        {
            "narrative": "180 sqm done",
            "_open_activity_candidates": [
                _candidate(BLOCKWORK_ID, "blockwork", "Block A"),
                _candidate(PLASTERING_ID, "plastering", "2nd floor"),
            ],
            "_slot_answer_text": "2",
        }
    )
    update = resolve_target(state)
    assert update["collected_fields"]["activity_id"] == PLASTERING_ID
    assert update["awaiting_slot"] is None


def test_answering_this_is_new_work_proceeds_to_creation():
    state = _base_state(
        {
            "narrative": "180 sqm done",
            "_open_activity_candidates": [_candidate(PLASTERING_ID, "plastering", "2nd floor")],
            "_slot_answer_text": "this is new work",
        }
    )
    update = resolve_target(state)
    assert "activity_id" not in update["collected_fields"]
    assert update["awaiting_slot"] is None


def test_answering_new_work_wrapped_in_justification_still_resolves():
    """Regression: "New cause it's 3rd floor" wasn't a substring of "This is
    new work" (or vice versa), so match_slot_answer returned None and the
    user got re-asked the identical question. A bare "new" anywhere in the
    reply now resolves to the escape hatch even when wrapped in extra words."""
    state = _base_state(
        {
            "narrative": "180 sqm done",
            "_open_activity_candidates": [_candidate(PLASTERING_ID, "plastering", "2nd floor")],
            "_slot_answer_text": "New cause it's 3rd floor",
        }
    )
    update = resolve_target(state)
    assert "activity_id" not in update["collected_fields"]
    assert update["awaiting_slot"] is None


def test_unrecognized_answer_reasks_with_same_candidates():
    state = _base_state(
        {
            "narrative": "180 sqm done",
            "_open_activity_candidates": [_candidate(PLASTERING_ID, "plastering", "2nd floor")],
            "_slot_answer_text": "blah unrelated text",
        }
    )
    update = resolve_target(state)
    assert update["awaiting_slot"] == _TARGET_SLOT_NAME
    assert "Sorry, I didn't catch that" in update["pending_prompt"]


def test_already_resolved_activity_id_is_a_no_op():
    """A remembered activity_id already seeded (memory hit, revalidated) by
    runtime/inbound_journey.py's `_seed_open_activity` short-circuits this
    node entirely -- no scoring, no candidates needed."""
    state = _base_state({"activity_id": PLASTERING_ID, "narrative": "done"})
    update = resolve_target(state)
    assert update["collected_fields"]["activity_id"] == PLASTERING_ID


# --- build_draft ---------------------------------------------------------


def test_build_draft_creates_new_activity_when_no_target_resolved():
    state = _base_state(
        {
            "work_type": "plastering",
            "narrative": "180 sqm plastering done",
            "quantities": [{"work_type": "plastering", "quantity": 180, "unit": "sqm"}],
        }
    )
    update = build_draft(state)
    draft = update["draft_action"]
    assert draft.action_type is DraftActionType.CREATE_ACTIVITY
    assert draft.fields["work_type"] == "plastering"


def test_build_draft_maps_creation_fields_verbatim_no_validation():
    state = _base_state({"quantities": "not-a-list", "work_type": None})
    update = build_draft(state)
    draft = update["draft_action"]
    # Shape-mapping only -- nothing here rejects a malformed quantities value
    # or a missing work_type. domains/progress/validation.py is where that's
    # decided, not this node.
    assert draft.fields["quantities"] == "not-a-list"
    assert draft.fields["work_type"] is None


def test_build_draft_appends_progress_update_when_activity_id_resolved():
    state = _base_state(
        {
            "activity_id": PLASTERING_ID,
            "activity_summary": "plastering — 2nd floor",
            "update_kind": "COMPLETED",
            "narrative": "finished plastering",
        }
    )
    update = build_draft(state)
    draft = update["draft_action"]
    assert draft.action_type is DraftActionType.ADD_PROGRESS_UPDATE
    assert draft.fields["activity_id"] == PLASTERING_ID


def test_build_draft_folds_first_quantities_entry_into_singular_quantity_and_unit():
    """The fix alongside the merge: general_site_update extraction only ever
    fills the plural `quantities` array, but AddProgressUpdateCommand reads
    a singular `quantity`/`unit` -- so a continuation message stating an
    amount via that array used to be silently dropped. See
    workflows/site_update/nodes.py's `_build_continuation_draft`
    docstring."""
    state = _base_state(
        {
            "activity_id": PLASTERING_ID,
            "update_kind": "PROGRESS",
            "narrative": "another 40 sqm done",
            "quantities": [{"work_type": "plastering", "quantity": 40, "unit": "sqm"}],
        }
    )
    update = build_draft(state)
    draft = update["draft_action"]
    assert draft.fields["quantity"] == 40
    assert draft.fields["unit"] == "sqm"
    assert "quantities" not in draft.fields


def test_build_draft_continuation_with_no_quantities_leaves_quantity_unset():
    state = _base_state(
        {"activity_id": PLASTERING_ID, "update_kind": "COMPLETED", "narrative": "finished"}
    )
    update = build_draft(state)
    draft = update["draft_action"]
    assert draft.fields.get("quantity") is None


def test_build_draft_excludes_resolution_plumbing_fields_from_the_draft():
    state = _base_state(
        {
            "work_type": "plastering",
            "narrative": "x",
            "_open_activity_candidates": [_candidate(PLASTERING_ID, "plastering", "2nd floor")],
            "_target_resolved": True,
        }
    )
    update = build_draft(state)
    draft = update["draft_action"]
    assert "_open_activity_candidates" not in draft.fields
    assert "_target_resolved" not in draft.fields


# --- request_confirmation: creation shape --------------------------------


def test_confirmation_shows_location_name_but_not_raw_location():
    """The AI extracts a free-text `location` (e.g. "Block A"), and there is
    no `location_name` seeded upstream in V1 (work-package/location
    resolution isn't wired yet). The hidden-field list only hides
    `location_name`, not `location` itself, so today the raw value falls
    through the generic key:value loop and is shown to the user even though
    nothing downstream persists it. Out of scope for this change -- tracked
    separately (module audit finding B)."""
    state = _base_state({"location": "Block A", "narrative": "Started blockwork"})
    state.update(build_draft(state))
    prompt = request_confirmation(state)["pending_prompt"]
    assert "location: Block A" in prompt


def test_confirmation_hides_location_name_when_seeded():
    state = _base_state({"location_name": "Block A / Level 2", "narrative": "x"})
    state.update(build_draft(state))
    prompt = request_confirmation(state)["pending_prompt"]
    assert "Location: Block A / Level 2" in prompt
    assert "location_name:" not in prompt


def test_confirmation_renders_quantities_and_date():
    state = _base_state(
        {
            "work_type": "plastering",
            "narrative": "Plastering on 2nd floor",
            "occurred_date": "2026-07-28",
            "occurred_date_source": "stated",
            "quantities": [{"work_type": "plastering", "quantity": 180, "unit": "sqm"}],
        }
    )
    state.update(build_draft(state))
    prompt = request_confirmation(state)["pending_prompt"]
    assert "Date: 28 Jul 2026" in prompt
    assert "(assumed today)" not in prompt
    assert "180 sqm plastering" in prompt


def test_confirmation_marks_inferred_date():
    state = _base_state({"occurred_date": "2026-07-29", "occurred_date_source": "inferred_at_confirmation"})
    state.update(build_draft(state))
    prompt = request_confirmation(state)["pending_prompt"]
    assert "(assumed today)" in prompt


# --- request_confirmation: continuation shape -----------------------------


def test_continuation_confirmation_shows_seeded_activity_summary_and_narrative():
    state = _base_state(
        {
            "activity_id": PLASTERING_ID,
            "activity_summary": "blockwork — Block A",
            "update_kind": "COMPLETED",
            "narrative": "finished plastering",
        }
    )
    state.update(build_draft(state))
    prompt = request_confirmation(state)["pending_prompt"]
    assert "Activity: blockwork — Block A" in prompt
    assert '"finished plastering"' in prompt
    assert "Completed" in prompt


def test_continuation_confirmation_labels_by_update_kind():
    for kind, label in (
        ("STARTED", "Started"),
        ("PROGRESS", "Progress update"),
        ("PAUSED", "Paused"),
        ("RESUMED", "Resumed"),
        ("COMPLETED", "Completed"),
        ("NOTE", "Note"),
    ):
        state = _base_state({"activity_id": PLASTERING_ID, "update_kind": kind})
        state.update(build_draft(state))
        prompt = request_confirmation(state)["pending_prompt"]
        assert label in prompt


def test_continuation_confirmation_defaults_to_progress_update_label_for_unknown_kind():
    state = _base_state({"activity_id": PLASTERING_ID, "update_kind": "SOMETHING_UNRECOGNIZED"})
    state.update(build_draft(state))
    prompt = request_confirmation(state)["pending_prompt"]
    assert "Progress update" in prompt


def test_continuation_confirmation_shows_folded_quantity():
    state = _base_state(
        {
            "activity_id": PLASTERING_ID,
            "update_kind": "PROGRESS",
            "quantities": [{"work_type": "plastering", "quantity": 40, "unit": "sqm"}],
        }
    )
    state.update(build_draft(state))
    prompt = request_confirmation(state)["pending_prompt"]
    assert "40 sqm" in prompt
