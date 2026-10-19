"""Labour attendance workflow nodes — unit tests (pure functions, no LangGraph needed).

Mirrors tests/unit/test_expense_capture_nodes.py. The behaviour worth pinning
here is the re-entrant matching loop: the node has no memory between passes
(the graph is compiled without a checkpointer and re-invoked from scratch on
every inbound message), so every test that spans two messages threads
`collected_fields` and `awaiting_slot` through by hand exactly as
WorkflowRuntime.provide_input does.
"""

from __future__ import annotations

import pytest

from mesiri_contracts.assistant.draft_action import DraftActionType
from mesiri_contracts.assistant.planner_decision import WorkflowKey

# graph.py's router is a plain function, so it is importable and testable
# without LangGraph -- which the core suite runs without (it lives in the
# optional `workflow` dependency group, so the sibling integration test skips
# unless it is installed). build_labour_attendance_graph() itself imports
# LangGraph lazily, inside the function.
from workflows.labour_update.graph import _route_after_worker_matching
from workflows.labour_update.nodes import (
    SOMEONE_NEW_SENTINEL,
    WORKER_MATCH_SLOT_PREFIX,
    build_draft,
    match_workers,
    request_confirmation,
)

#: Attendance matching no longer asks anything: match_worker returns only
#: AUTO_MATCHED or NO_MATCH (exact full name AND exact trade, or nothing), so
#: the node's question path is currently unreachable.
#:
#: The node code and these tests are kept rather than deleted because the
#: rule was simplified for *this phase* -- an 80-row register upload produced
#: dozens of unanswerable "is this Ravi the same Ravi?" questions -- and
#: smarter matching is expected to want the question back. Skipped, not
#: commented out, so the gap is visible in every run: a skipped test is not a
#: passing test.
ASKING_IS_DISABLED = pytest.mark.skip(
    reason="attendance matching asks nothing in this phase -- see matching.match_worker"
)

ORG = "11111111-1111-4111-8111-111111111111"
USR = "22222222-2222-4222-8222-222222222222"
PRJ = "33333333-3333-4333-8333-333333333333"
SITE = "44444444-4444-4444-8444-444444444444"

RAVI_KUMAR = "55555555-5555-4555-8555-555555555555"
RAVI_S = "66666666-6666-4666-8666-666666666666"


def _base_state(fields: dict, **extra) -> dict:
    state = {
        "workflow_instance_id": "wf_1",
        "workflow_key": WorkflowKey.LABOUR_ATTENDANCE.value,
        "correlation_id": "cor_1",
        "organization_id": ORG,
        "user_id": USR,
        "project_id": PRJ,
        "site_id": SITE,
        "collected_fields": fields,
    }
    state.update(extra)
    return state


def _named(name: str, trade: str | None = None, **rest) -> dict:
    return {"worker_name": name, "trade": trade, "headcount": 1, **rest}


def _group(count: int, trade: str, **rest) -> dict:
    return {"worker_name": None, "trade": trade, "headcount": count, **rest}


# --- matching: the silent paths -------------------------------------------


def test_headcount_groups_never_ask():
    """A group names nobody, so there is nothing to match. P10's whole point:
    a site that reports counts must not be interrogated."""
    state = _base_state({"lines": [_group(12, "helper"), _group(4, "mason")]})
    update = match_workers(state)
    assert update["awaiting_slot"] is None
    assert "pending_prompt" not in update


def test_no_register_resolves_named_workers_as_temporary():
    """A brand-new organization has no register at all. Every named worker is
    a temporary worker, and no question is asked (P3 — temporary workers are
    first-class, not a degraded path)."""
    state = _base_state({"lines": [_named("Ravi", "mason"), _named("Arun", "painter")]})
    update = match_workers(state)
    assert update["awaiting_slot"] is None
    lines = update["collected_fields"]["lines"]
    assert [line["worker_id"] for line in lines] == [None, None]


def test_confident_match_is_applied_without_asking():
    """Same name, same trade, worked on this site before — enough corroboration
    to clear AUTO_ACCEPT, so P9 says don't ask."""
    state = _base_state(
        {
            "lines": [_named("Ravi Kumar", "mason")],
            "worker_candidates": [
                {
                    "worker_id": RAVI_KUMAR,
                    "name": "Ravi Kumar",
                    "trade": "mason",
                    "seen_on_site": True,
                }
            ],
        }
    )
    update = match_workers(state)
    assert update["awaiting_slot"] is None
    assert update["collected_fields"]["lines"][0]["worker_id"] == RAVI_KUMAR


@ASKING_IS_DISABLED
def test_part_of_a_name_alone_always_asks():
    """The P4 guarantee, seen from the workflow: one part of a name matching,
    with nothing corroborating it, must produce a question and never a silent
    match. `Ravi (Mason)` and `Ravi (Painter)` are different people, and first
    names collide constantly on a site.

    The boundary moved once, deliberately: a *full* name that identifies
    exactly one worker in the register is now recognised without asking (see
    matching._unique_full_name_match, and the pair of tests below). This
    still holds for everything short of that.
    """
    state = _base_state(
        {
            "lines": [_named("Ravi")],
            "worker_candidates": [{"worker_id": RAVI_KUMAR, "name": "Ravi Kumar"}],
        }
    )
    update = match_workers(state)
    assert update["awaiting_slot"] == f"{WORKER_MATCH_SLOT_PREFIX}0"
    assert update["collected_fields"]["lines"][0].get("worker_id") is None


@ASKING_IS_DISABLED
def test_a_full_name_shared_by_two_registered_workers_still_asks():
    """The other half of that boundary: the moment a full name stops picking
    out one person, it stops deciding on its own."""
    state = _base_state(
        {
            "lines": [_named("Ravi Kumar")],
            "worker_candidates": [
                {"worker_id": RAVI_KUMAR, "name": "Ravi Kumar", "trade": "mason"},
                {"worker_id": RAVI_S, "name": "Ravi Kumar", "trade": "painter"},
            ],
        }
    )
    update = match_workers(state)
    assert update["awaiting_slot"] == f"{WORKER_MATCH_SLOT_PREFIX}0"
    assert update["collected_fields"]["lines"][0].get("worker_id") is None


# --- matching: the question -----------------------------------------------


def _ambiguous_state(**fields) -> dict:
    return _base_state(
        {
            "lines": [_named("Ravi", "mason")],
            "worker_candidates": [
                {"worker_id": RAVI_KUMAR, "name": "Ravi Kumar", "trade": "mason"},
                {"worker_id": RAVI_S, "name": "Ravi S", "trade": "mason"},
            ],
            **fields,
        }
    )


@ASKING_IS_DISABLED
def test_question_offers_candidates_plus_someone_new():
    """"Someone new" is always last, and is what keeps a temporary worker
    recordable when none of the suggestions is right."""
    update = match_workers(_ambiguous_state())
    values = [option["value"] for option in update["awaiting_slot_options"]]
    assert values[-1] == SOMEONE_NEW_SENTINEL
    assert set(values[:-1]) == {RAVI_KUMAR, RAVI_S}


@ASKING_IS_DISABLED
def test_option_labels_are_bare_names_so_the_list_stays_tappable():
    """A WhatsApp row title over 24 characters makes the send side drop the
    whole list back to plain text, so reasons belong in the prompt body, not
    the label (see runtime/inbound_journey.py's _render_reply)."""
    update = match_workers(_ambiguous_state())
    for option in update["awaiting_slot_options"]:
        assert len(option["label"]) <= 24, option


@ASKING_IS_DISABLED
def test_prompt_shows_why_each_candidate_was_suggested():
    update = match_workers(_ambiguous_state())
    assert "same trade (mason)" in update["pending_prompt"]


@ASKING_IS_DISABLED
def test_trade_change_question_names_both_trades():
    """P4's explicit requirement. A bare "which of these?" invites the user to
    pick the familiar name without noticing the discrepancy — which is exactly
    how two workers' histories get merged.

    Note the exact name: a *partial* name plus a trade mismatch, corroborated
    by prior history on this site, also clears the ask threshold — see
    test_partial_name_with_changed_trade_and_site_history_asks."""
    state = _base_state(
        {
            "lines": [_named("Ravi Kumar", "carpenter")],
            "worker_candidates": [
                {
                    "worker_id": RAVI_KUMAR,
                    "name": "Ravi Kumar",
                    "trade": "mason",
                    "seen_on_site": True,
                }
            ],
        }
    )
    prompt = match_workers(state)["pending_prompt"]
    assert "mason" in prompt
    assert "carpenter" in prompt
    assert "updated trade" in prompt


@ASKING_IS_DISABLED
def test_partial_name_with_changed_trade_and_site_history_asks():
    """A *partial* name plus a trade mismatch, corroborated by having worked
    this site before: "Ravi, carpenter" against a registered "Ravi Kumar,
    mason" who has worked here already. That combination — same first name,
    known to this site — is real evidence it might be the same person, so it
    asks rather than silently splitting the history. (A partial name with
    *nothing* else corroborating it still asks too, just more weakly — see
    test_workforce_matching.py — but never silently resolves to a new
    worker; only a genuinely unrelated name does that.)"""
    state = _base_state(
        {
            "lines": [_named("Ravi", "carpenter")],
            "worker_candidates": [
                {
                    "worker_id": RAVI_KUMAR,
                    "name": "Ravi Kumar",
                    "trade": "mason",
                    "seen_on_site": True,
                }
            ],
        }
    )
    update = match_workers(state)
    assert update["awaiting_slot"] is not None


@ASKING_IS_DISABLED
def test_duplicate_candidate_names_are_disambiguated_by_trade():
    """The one case where a bare name genuinely cannot identify the choice."""
    state = _base_state(
        {
            "lines": [_named("Ravi")],
            "worker_candidates": [
                {"worker_id": RAVI_KUMAR, "name": "Ravi", "trade": "mason"},
                {"worker_id": RAVI_S, "name": "Ravi", "trade": "painter"},
            ],
        }
    )
    labels = [option["label"] for option in match_workers(state)["awaiting_slot_options"]]
    assert "Ravi (mason)" in labels
    assert "Ravi (painter)" in labels


# --- matching: answering, across two passes -------------------------------


def _answer(previous: dict, text: str) -> dict:
    """Re-enter the node the way WorkflowRuntime.provide_input does: merge the
    raw answer into the persisted collected_fields and re-invoke with the
    stored awaiting_slot. Nothing else survives between passes."""
    fields = dict(previous["collected_fields"])
    fields["_slot_answer_text"] = text
    return match_workers(_base_state(fields, awaiting_slot=previous["awaiting_slot"]))


@ASKING_IS_DISABLED
def test_answering_by_number_resolves_the_line():
    asked = match_workers(_ambiguous_state())
    resolved = _answer(asked, "1")
    assert resolved["awaiting_slot"] is None
    assert resolved["collected_fields"]["lines"][0]["worker_id"] == RAVI_KUMAR


@ASKING_IS_DISABLED
def test_answering_by_name_resolves_the_line():
    asked = match_workers(_ambiguous_state())
    resolved = _answer(asked, "Ravi S")
    assert resolved["collected_fields"]["lines"][0]["worker_id"] == RAVI_S


def test_answering_someone_new_records_a_temporary_worker():
    """P1: this must leave worker_id unset and write nothing to the register.
    The register is not touched anywhere in this module — promotion is a
    separate, explicitly confirmed act."""
    asked = match_workers(_ambiguous_state())
    resolved = _answer(asked, "Someone new")
    line = resolved["collected_fields"]["lines"][0]
    assert resolved["awaiting_slot"] is None
    assert line["worker_id"] is None


@ASKING_IS_DISABLED
def test_unmatched_answer_re_asks_the_same_line():
    asked = match_workers(_ambiguous_state())
    again = _answer(asked, "no idea honestly")
    assert again["awaiting_slot"] == asked["awaiting_slot"]
    assert "couldn't tell which one" in again["pending_prompt"]


def test_the_answer_text_never_leaks_into_the_draft():
    asked = match_workers(_ambiguous_state())
    resolved = _answer(asked, "1")
    assert "_slot_answer_text" not in resolved["collected_fields"]


# --- matching: many workers, one question at a time -----------------------


@ASKING_IS_DISABLED
def test_one_question_per_pass_and_the_loop_terminates():
    """The behaviour the whole design exists for: three ambiguous workers are
    asked about one at a time, in order, and the loop ends resolved."""
    state = _base_state(
        {
            "lines": [_named("Ravi"), _named("Arun"), _named("Suresh")],
            "worker_candidates": [
                {"worker_id": "w-ravi", "name": "Ravi"},
                {"worker_id": "w-arun", "name": "Arun"},
                {"worker_id": "w-suresh", "name": "Suresh"},
            ],
        }
    )
    current = match_workers(state)
    slots_asked = []
    for _ in range(10):
        if current["awaiting_slot"] is None:
            break
        slots_asked.append(current["awaiting_slot"])
        current = _answer(current, "1")
    assert slots_asked == [f"{WORKER_MATCH_SLOT_PREFIX}{i}" for i in range(3)]
    assert current["awaiting_slot"] is None
    assert [line["worker_id"] for line in current["collected_fields"]["lines"]] == [
        "w-ravi",
        "w-arun",
        "w-suresh",
    ]


@ASKING_IS_DISABLED
def test_resolvable_lines_are_settled_before_the_first_question():
    """P9: nine confident matches plus one ambiguity is one question, not ten
    round trips. The confident lines are already resolved in the same pass
    that asks about the ambiguous one."""
    state = _base_state(
        {
            "lines": [
                _named("Ravi Kumar", "mason"),
                _named("Arun", "painter"),
                _group(12, "helper"),
            ],
            "worker_candidates": [
                {
                    "worker_id": RAVI_KUMAR,
                    "name": "Ravi Kumar",
                    "trade": "mason",
                    "seen_on_site": True,
                },
                {"worker_id": "w-arun", "name": "Arun"},
            ],
        }
    )
    update = match_workers(state)
    assert update["awaiting_slot"] == f"{WORKER_MATCH_SLOT_PREFIX}1"
    assert update["collected_fields"]["lines"][0]["worker_id"] == RAVI_KUMAR


def test_mixed_named_and_headcount_lines_survive_together():
    """P10: one attendance may freely mix both forms, with no mode to choose."""
    state = _base_state({"lines": [_named("Ravi", "mason"), _group(12, "helper")]})
    lines = match_workers(state)["collected_fields"]["lines"]
    assert lines[0]["worker_name"] == "Ravi"
    assert lines[1]["headcount"] == 12


def test_missing_lines_key_is_not_invented():
    state = _base_state({"notes": "everyone showed up"})
    update = match_workers(state)
    assert update["awaiting_slot"] is None
    assert "lines" not in update["collected_fields"]


def test_malformed_lines_do_not_crash_the_report():
    state = _base_state({"lines": ["not a dict", _named("Ravi", "mason")]})
    update = match_workers(state)
    assert update["awaiting_slot"] is None
    assert len(update["collected_fields"]["lines"]) == 1


# --- routing ---------------------------------------------------------------


def test_route_continues_when_nothing_is_being_asked():
    assert _route_after_worker_matching({"awaiting_slot": None}) == "continue"
    assert _route_after_worker_matching({}) == "continue"


def test_route_asks_on_any_line_index():
    """Prefix-matched, not an exact slot name: the second worker's question is
    `worker_match:1`, and one edge has to serve every line."""
    for index in (0, 1, 7, 42):
        assert (
            _route_after_worker_matching({"awaiting_slot": f"{WORKER_MATCH_SLOT_PREFIX}{index}"})
            == "ask_slot"
        )


def test_route_ignores_another_workflows_slot():
    """The bug expense_capture's `_route_after_account_resolution` documents: a
    stale awaiting_slot from a different question must not re-trigger this
    edge."""
    assert _route_after_worker_matching({"awaiting_slot": "account_id"}) == "continue"
    assert _route_after_worker_matching({"awaiting_slot": "duplicate_confirm"}) == "continue"


def test_registry_maps_the_labour_attendance_key():
    """Pinned without compiling, so the core suite checks the wiring even
    though it runs without LangGraph installed."""
    from workflows.registry import WorkflowCategory, get_definition, is_implemented

    assert is_implemented(WorkflowKey.LABOUR_ATTENDANCE)
    definition = get_definition(WorkflowKey.LABOUR_ATTENDANCE)
    assert definition is not None
    assert definition.category is WorkflowCategory.LABOUR


# --- build_draft -----------------------------------------------------------


def test_build_draft_uses_the_labour_action_type():
    state = _base_state({"lines": [_group(12, "helper")], "occurred_date": "2026-07-26"})
    draft = build_draft(state)["draft_action"]
    assert draft.action_type is DraftActionType.RECORD_LABOUR_ATTENDANCE
    assert draft.organization_id == ORG
    assert draft.project_id == PRJ
    assert draft.site_id == SITE


def test_build_draft_excludes_seeded_candidates_and_bookkeeping():
    """`worker_candidates` is plumbing and `worker_match_resolved` is how the
    node kept its place — neither is a business field, and both would be
    rejected by RecordLabourAttendanceCommand's `extra: forbid` models."""
    state = _base_state(
        {
            "lines": [_named("Ravi", "mason")],
            "worker_candidates": [{"worker_id": RAVI_KUMAR, "name": "Ravi Kumar"}],
        }
    )
    matched = match_workers(state)
    state["collected_fields"] = matched["collected_fields"]
    draft = build_draft(state)["draft_action"]
    assert "worker_candidates" not in draft.fields
    assert all("worker_match_resolved" not in line for line in draft.fields["lines"])


def test_build_draft_keeps_the_resolved_worker_id():
    state = _base_state(
        {
            "lines": [_named("Ravi Kumar", "mason")],
            "worker_candidates": [
                {
                    "worker_id": RAVI_KUMAR,
                    "name": "Ravi Kumar",
                    "trade": "mason",
                    "seen_on_site": True,
                }
            ],
        }
    )
    state["collected_fields"] = match_workers(state)["collected_fields"]
    draft = build_draft(state)["draft_action"]
    assert draft.fields["lines"][0]["worker_id"] == RAVI_KUMAR


# --- request_confirmation --------------------------------------------------


def _preview(fields: dict) -> str:
    state = _base_state(fields)
    state.update(build_draft(state))
    return request_confirmation(state)["pending_prompt"]


def test_preview_renders_named_and_headcount_lines_differently():
    prompt = _preview(
        {
            "lines": [
                _named("Ravi Kumar", "mason", daily_wage="800"),
                _group(12, "helper", daily_wage="600"),
            ]
        }
    )
    assert "Ravi Kumar — Mason — ₹800" in prompt
    assert "12 × Helper — ₹600 each" in prompt


def test_preview_totals_headcount_and_cost():
    prompt = _preview(
        {
            "lines": [
                _named("Ravi Kumar", "mason", daily_wage="800"),
                _group(12, "helper", daily_wage="600"),
            ]
        }
    )
    assert "13 workers" in prompt
    assert "₹8,000" in prompt  # 800 + 12*600


def test_preview_shows_project_and_site_by_name_when_seeded():
    """A bare UUID is worse than saying nothing, so names are shown only when
    the caller supplied them."""
    prompt = _preview(
        {
            "lines": [_group(4, "mason")],
            "project_name": "Riverside Tower",
            "site_name": "Site B",
        }
    )
    assert "Riverside Tower" in prompt
    assert "Site B" in prompt


def test_preview_omits_project_and_site_when_not_seeded():
    prompt = _preview({"lines": [_group(4, "mason")]})
    assert "Project:" not in prompt
    assert PRJ not in prompt


def test_preview_never_dumps_the_raw_lines_list():
    """The failure this formatter exists to prevent."""
    prompt = _preview({"lines": [_named("Ravi", "mason")]})
    assert "worker_name" not in prompt
    assert "lines:" not in prompt


def test_preview_notes_an_attached_attendance_sheet():
    prompt = _preview({"lines": [_group(4, "mason")], "attachment_object_keys": ["obj/1.jpg"]})
    assert "Attendance sheet attached" in prompt
    assert "obj/1.jpg" not in prompt


def test_preview_asks_for_confirmation():
    """P2: nothing is persisted before this gate."""
    prompt = _preview({"lines": [_group(4, "mason")]})
    assert "Reply YES to confirm or NO to cancel." in prompt


def test_preview_omits_cost_when_no_wages_are_known():
    """P9: a wage-less report is a legitimate fast capture, not an error."""
    prompt = _preview({"lines": [_group(4, "mason")]})
    assert "Total:" not in prompt
    assert "4 workers" in prompt


def test_preview_shows_the_original_spelling_beside_a_transliterated_name():
    """Confirmation is the one moment anyone is looking, and the supervisor is
    better placed than we are to catch a wrong transliteration -- but only if
    they can see what was written on the sheet."""
    prompt = _preview(
        {
            "lines": [
                {
                    "worker_name": "Ravi",
                    "worker_name_original": "രവി",
                    "trade": "mason",
                    "headcount": 1,
                }
            ]
        }
    )
    assert "Ravi (രവി)" in prompt


def test_preview_does_not_repeat_a_latin_name():
    prompt = _preview({"lines": [_named("Ravi", "mason")]})
    assert "Ravi (Ravi)" not in prompt
    assert "Ravi" in prompt


def test_preview_never_shows_recorded_via_as_a_raw_field():
    """recorded_via is provenance for the command, not something a
    supervisor confirming a headcount needs to see."""
    prompt = _preview({"lines": [_group(4, "mason")], "recorded_via": "whatsapp_voice"})
    assert "recorded_via" not in prompt


# --- the date is visible before anything is saved -------------------------


def test_preview_shows_the_date():
    """Attendance is append-only: a wrong date can't be edited afterwards,
    only superseded. Confirmation is the only cheap moment to catch it."""
    prompt = _preview(
        {
            "lines": [_group(4, "mason")],
            "occurred_date": "2026-07-20",
            "occurred_date_source": "stated_by_user",
        }
    )
    assert "Date: 20 Jul 2026" in prompt
    assert "assumed" not in prompt


def test_preview_admits_when_the_date_was_guessed():
    """A guess presented as fact is what let "yesterday 12 masons worked" get
    filed under today without anyone noticing."""
    prompt = _preview(
        {
            "lines": [_group(4, "mason")],
            "occurred_date": "2026-07-27",
            "occurred_date_source": "inferred_at_confirmation",
        }
    )
    assert "Date: 27 Jul 2026 (assumed today)" in prompt


def test_preview_never_shows_the_raw_date_plumbing():
    """"occurred_date_source: inferred_at_confirmation" means nothing to a
    supervisor -- the date line says it in words instead."""
    prompt = _preview(
        {
            "lines": [_group(4, "mason")],
            "occurred_date": "2026-07-27",
            "occurred_date_source": "inferred_at_confirmation",
        }
    )
    assert "occurred_date" not in prompt
    assert "inferred_at_confirmation" not in prompt


def test_preview_omits_the_date_line_when_there_is_no_date():
    """An older draft persisted before dating shipped must still render."""
    assert "Date:" not in _preview({"lines": [_group(4, "mason")]})


# --- recognising permanent workers ----------------------------------------


def test_a_registered_worker_is_recognised_and_the_rest_stay_temporary():
    """The reported scenario, end to end at the node.

    Register holds one permanent worker, Ilan Usman. Attendance names him
    plus two people nobody has recorded before. Ilan must be linked to his
    register entry silently -- no question during the report -- while Rahul
    and Niyas pass through as temporary workers.

    That `worker_id` is what keeps Ilan out of the promotion offer
    afterwards: the follow-up only collects lines whose worker_id is still
    None (see runtime/inbound_journey.py's _maybe_trigger_worker_promotion).
    Before this, Ilan was offered for promotion again on every single report.
    """
    state = _base_state(
        {
            "lines": [
                _named("Ilan Usman", "carpenter"),
                _named("Rahul", "helper"),
                _named("Niyas", "mason"),
            ],
            "worker_candidates": [
                {"worker_id": RAVI_KUMAR, "name": "Ilan Usman", "trade": "carpenter"}
            ],
        }
    )
    update = match_workers(state)

    assert update["awaiting_slot"] is None, "recognising a known worker must not ask"
    lines = update["collected_fields"]["lines"]
    assert lines[0]["worker_id"] == RAVI_KUMAR
    assert lines[1]["worker_id"] is None
    assert lines[2]["worker_id"] is None


def test_a_registered_worker_is_recognised_when_the_sheet_omits_the_trade():
    """Attendance sheets routinely list names with no trade column, and
    workers are often added from the dashboard without one. Neither should
    turn a known worker back into a stranger."""
    state = _base_state(
        {
            "lines": [{"worker_name": "Ilan Usman", "trade": None, "headcount": 1}],
            "worker_candidates": [
                {"worker_id": RAVI_KUMAR, "name": "Ilan Usman", "trade": None}
            ],
        }
    )
    update = match_workers(state)

    assert update["awaiting_slot"] is None
    assert update["collected_fields"]["lines"][0]["worker_id"] == RAVI_KUMAR


# --- a register upload, the case the rule was simplified for ---------------


def test_an_eighty_worker_upload_asks_nothing_and_splits_cleanly():
    """The scenario this phase exists for. An Excel-sized report used to
    produce dozens of "is this Ravi the same Ravi?" questions, which nobody
    can answer inside WhatsApp -- the report simply stalled.

    55 exact name+trade matches link silently; 25 unknown names become
    temporary workers and are what the promotion step offers; a headcount
    group belongs to neither. One pass, no questions.
    """
    trades = ["mason", "helper", "carpenter", "painter"]
    register = [
        {"worker_id": f"w{i}", "name": f"Worker {i}", "trade": trades[i % 4]}
        for i in range(55)
    ]
    lines = [_named(f"Worker {i}", trades[i % 4]) for i in range(55)]
    lines += [_named(f"New Person {i}", "helper") for i in range(25)]
    lines += [_group(12, "helper")]

    update = match_workers(
        _base_state({"lines": lines, "worker_candidates": register})
    )

    assert update["awaiting_slot"] is None, "a register upload must ask nothing"
    resolved = update["collected_fields"]["lines"]
    matched = [line for line in resolved if line.get("worker_id")]
    new_named = [
        line for line in resolved if line.get("worker_name") and not line.get("worker_id")
    ]

    assert len(matched) == 55
    assert len(new_named) == 25


def test_a_matched_worker_carries_an_id_so_promotion_skips_them():
    """The link between the two halves: the promotion step collects only
    lines whose worker_id is still None (see inbound_journey's
    _maybe_trigger_worker_promotion), so an exact match disappearing from
    that list is a consequence of being matched, not a separate filter."""
    register = [{"worker_id": RAVI_KUMAR, "name": "Ravi Kumar", "trade": "mason"}]
    update = match_workers(
        _base_state(
            {
                "lines": [_named("Ravi Kumar", "mason"), _named("Ajmal", "helper")],
                "worker_candidates": register,
            }
        )
    )

    lines = update["collected_fields"]["lines"]
    assert lines[0]["worker_id"] == RAVI_KUMAR, "matched -- never offered for promotion"
    assert lines[1]["worker_id"] is None, "unmatched -- this is what gets offered"


def test_a_trade_change_becomes_a_new_worker_rather_than_a_question():
    """Deliberate consequence of the simplified rule, recorded so it is not
    mistaken for a regression: the same person reported under a different
    trade no longer asks, it becomes a temporary worker. The promotion step's
    duplicate screen is what surfaces it afterwards."""
    register = [{"worker_id": RAVI_KUMAR, "name": "Ravi Kumar", "trade": "mason"}]
    update = match_workers(
        _base_state(
            {"lines": [_named("Ravi Kumar", "carpenter")], "worker_candidates": register}
        )
    )

    assert update["awaiting_slot"] is None
    assert update["collected_fields"]["lines"][0]["worker_id"] is None
