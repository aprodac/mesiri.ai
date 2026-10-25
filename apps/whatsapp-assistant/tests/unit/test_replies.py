"""channel/replies.py — the planner-leg reply renderers.

Before these existed, CLARIFY and DIRECT_REPLY were computed by the Planner,
logged, and dropped; every such message fell through to format_reply()'s
developer diagnostic. These tests pin the replies a user actually receives.
"""

from __future__ import annotations

from channel.replies import (
    CATEGORY_ROWS,
    IMAGE_PURPOSE_ROWS,
    IMAGE_PURPOSE_SEMANTIC_HINT,
    render_batch_overflow_reply,
    render_capability_answer,
    render_category_prompt,
    render_clarify_reply,
    render_direct_reply,
    render_evidence_attached_reply,
    render_image_purpose_picker,
    render_member_candidate_picker,
    render_member_create_declined_reply,
    render_member_create_offer,
    render_member_not_found_reply,
    render_no_open_activity_for_evidence_reply,
    render_no_projects_reply,
    render_project_picker,
    render_understanding_failed_reply,
    render_unsupported_reply,
)
from mesiri_contracts.assistant.canonical_event import CanonicalEventType
from mesiri_contracts.assistant.planner_decision import PlannerDecisionType
from mesiri_contracts.assistant.v2.planner_decision import PlannerDecisionV2

_ORG = "11111111-1111-1111-1111-111111111111"
_USER = "22222222-2222-2222-2222-222222222222"


def _decision(
    decision_type: PlannerDecisionType,
    reason: CanonicalEventType,
    missing: list[str] | None = None,
) -> PlannerDecisionV2:
    return PlannerDecisionV2(
        correlation_id="cor_1",
        source_message_id="msg_1",
        decision_type=decision_type,
        reason=reason,
        organization_id=_ORG,
        user_id=_USER,
        missing_fields=missing or [],
    )


def test_clarify_names_a_single_missing_field_in_plain_words():
    reply = render_clarify_reply(
        _decision(
            PlannerDecisionType.CLARIFY, CanonicalEventType.CLARIFICATION_REQUIRED, ["quantity"]
        )
    )
    assert "how much" in reply
    assert "quantity" not in reply  # schema names must not leak to the user


def test_clarify_joins_several_missing_fields_readably():
    reply = render_clarify_reply(
        _decision(
            PlannerDecisionType.CLARIFY,
            CanonicalEventType.CLARIFICATION_REQUIRED,
            ["quantity", "unit"],
        )
    )
    assert "how much" in reply and "and" in reply


def test_clarify_with_no_missing_fields_still_asks_something():
    """Defensive: a CLARIFY should always carry missing_fields, but an empty
    question is worse than a generic one."""
    reply = render_clarify_reply(
        _decision(PlannerDecisionType.CLARIFY, CanonicalEventType.CLARIFICATION_REQUIRED, [])
    )
    assert reply.strip()


def test_first_message_offers_examples_of_what_mesiri_can_record():
    """Only the first-ever greeting spells out examples in the text body --
    a returning user gets the short "what are you reporting" prompt and
    relies on the tappable menu instead (see test_first_message_gets_...)."""
    reply = render_direct_reply(
        _decision(PlannerDecisionType.DIRECT_REPLY, CanonicalEventType.UNRECOGNIZED),
        is_first_message=True,
    )
    assert "cement" in reply.text


def test_greeting_carries_the_tiered_menu_category_rows_and_nothing_else():
    """Only the greeting/unrecognized reply ever carries a menu -- and it's
    exactly the top level of the tiered menu (workflows/registry.py's
    iter_menu_categories()), not the retired flat 5-row v1 list."""
    reply = render_direct_reply(
        _decision(PlannerDecisionType.DIRECT_REPLY, CanonicalEventType.UNRECOGNIZED)
    )
    assert reply.list_rows == CATEGORY_ROWS
    assert [row.title for row in reply.list_rows] == [
        "Material",
        "Site Progress",
        "Labour",
        "Money",
        "Projects & Team",
        "Reminders",
        "My Profile",
    ]
    assert reply.list_button_label


def test_greeting_is_time_aware_in_the_users_timezone():
    reply = render_direct_reply(
        _decision(PlannerDecisionType.DIRECT_REPLY, CanonicalEventType.UNRECOGNIZED),
        timezone="Asia/Kolkata",
    )
    assert any(g in reply.text for g in ("Good morning", "Good afternoon", "Good evening"))


def test_greeting_falls_back_to_hello_on_unknown_timezone():
    """A wrong 'Good morning' at 9pm is worse than no time of day at all."""
    for tz in (None, "Not/AZone"):
        reply = render_direct_reply(
            _decision(PlannerDecisionType.DIRECT_REPLY, CanonicalEventType.UNRECOGNIZED),
            timezone=tz,
        )
        assert reply.text.startswith("Hello")


def test_first_message_gets_introduced_returning_user_does_not():
    """A returning user who already knows what Mesiri does shouldn't be
    re-introduced on every 'hi' -- only the first-ever message explains what
    the assistant is."""
    first = render_direct_reply(
        _decision(PlannerDecisionType.DIRECT_REPLY, CanonicalEventType.UNRECOGNIZED),
        is_first_message=True,
    )
    returning = render_direct_reply(
        _decision(PlannerDecisionType.DIRECT_REPLY, CanonicalEventType.UNRECOGNIZED),
        is_first_message=False,
    )
    assert "I'm Mesiri" in first.text
    assert "I'm Mesiri" not in returning.text
    # Both still offer the same tappable menu -- only the copy differs.
    assert first.list_rows == returning.list_rows == CATEGORY_ROWS


def test_question_gets_capability_answer_not_a_greeting():
    """An unmatched question ("what can you do?") gets an actual answer, and
    then the menu.

    The menu is deliberate, reversing the earlier "a question that's already
    understood as a question doesn't need one" rule. That rule assumed the
    reply already told the user everything -- true when there was one
    hardcoded sentence to tell, false now that there are 24 workflows behind
    seven categories. Withholding the menu here just makes the user type
    "menu" as their next message.
    """
    reply = render_direct_reply(
        _decision(PlannerDecisionType.DIRECT_REPLY, CanonicalEventType.GENERAL_QUESTION_ASKED)
    )
    assert "send me what happened" in reply.text
    assert not reply.text.startswith(("Hello", "Good "))
    assert reply.list_rows == CATEGORY_ROWS


def test_category_prompt_is_deterministic_per_row_and_distinct():
    prompts = {render_category_prompt(row.id) for row in CATEGORY_ROWS}
    assert None not in prompts
    assert len(prompts) == len(CATEGORY_ROWS)  # no two categories share a prompt


def test_category_prompt_is_none_for_an_unknown_row_id():
    """A stale button from an old message, or a tampered payload, must not
    produce a reply at all -- the caller falls through to the normal journey."""
    assert render_category_prompt("cat_does_not_exist") is None


def test_unsupported_is_distinct_from_not_understood():
    """Telling someone who reported an expense that we 'couldn't make out' their
    message sends them rephrasing a message that was never the problem."""
    assert render_unsupported_reply() != render_understanding_failed_reply()
    assert "couldn't make out" not in render_unsupported_reply()


def test_project_picker_lists_every_project_with_prefixed_row_ids():
    reply = render_project_picker([("prj_1", "Site A", "Kochi"), ("prj_2", "Site B", None)])
    assert reply.list_rows is not None
    assert [row.id for row in reply.list_rows] == ["proj_prj_1", "proj_prj_2"]
    assert [row.title for row in reply.list_rows] == ["Site A", "Site B"]


def test_project_picker_caps_at_ten_rows():
    projects = [(f"prj_{i}", f"Project {i}", None) for i in range(15)]
    reply = render_project_picker(projects)
    assert reply.list_rows is not None
    assert len(reply.list_rows) == 10


def test_no_projects_reply_is_distinct_from_the_picker():
    assert render_no_projects_reply() != render_project_picker([]).text


def test_image_purpose_picker_offers_every_kind_of_photo_a_site_sends():
    reply = render_image_purpose_picker()
    assert reply.list_rows == IMAGE_PURPOSE_ROWS
    row_ids = [row.id for row in reply.list_rows]
    # Material Delivery leads: a supplier's invoice is the most common piece of
    # paper photographed on a site, and before it existed such a photo could
    # only be filed as an Expense -- recording the money while stock never moved.
    assert row_ids == [
        "img_material_invoice",
        "img_expense",
        "img_attendance",
        "img_site_update",
    ]


def test_image_purpose_picker_leaves_out_switched_off_modules():
    # WA-65 (audit PHO-08): Expense is not offered when Finance is off.
    from workflows.registry import set_enabled_modules

    set_enabled_modules(["dpr", "materials", "labour"])
    try:
        row_ids = [row.id for row in render_image_purpose_picker().list_rows]
        assert row_ids == ["img_material_invoice", "img_attendance", "img_site_update"]
        set_enabled_modules(["dpr"])
        assert [row.id for row in render_image_purpose_picker().list_rows] == ["img_site_update"]
    finally:
        set_enabled_modules(None)


def test_expense_and_material_rows_are_told_apart_by_their_descriptions():
    """Both are pieces of paper from a supplier, so the titles alone cannot
    separate them. Getting this wrong double-counts spend."""
    rows = {row.id: row for row in IMAGE_PURPOSE_ROWS}

    assert "invoice" in rows["img_material_invoice"].description.lower()
    assert "paid" in rows["img_expense"].description.lower()


def test_image_purpose_semantic_hint_covers_every_row():
    row_ids = {row.id for row in IMAGE_PURPOSE_ROWS}
    assert set(IMAGE_PURPOSE_SEMANTIC_HINT.keys()) == row_ids
    assert IMAGE_PURPOSE_SEMANTIC_HINT["img_material_invoice"] == "material_invoice"
    assert IMAGE_PURPOSE_SEMANTIC_HINT["img_expense"] == "expense"
    assert IMAGE_PURPOSE_SEMANTIC_HINT["img_attendance"] == "labour_update"
    assert IMAGE_PURPOSE_SEMANTIC_HINT["img_site_update"] == "general_site_update"


def test_evidence_attached_reply_is_one_message_for_the_whole_batch():
    reply = render_evidence_attached_reply(count=3, activity_summary="Plastering — Block A")
    assert "3 photos" in reply
    assert "Plastering — Block A" in reply


def test_evidence_attached_reply_singular_and_no_summary_fallback():
    assert "1 photo " in render_evidence_attached_reply(count=1, activity_summary=None)
    assert "photos" not in render_evidence_attached_reply(count=1, activity_summary=None)


def test_no_open_activity_for_evidence_reply_is_honest_not_silent():
    reply = render_no_open_activity_for_evidence_reply()
    assert "no activity in progress" in reply.lower()


def test_batch_overflow_reply_names_the_remaining_count():
    reply = render_batch_overflow_reply(held_count=4, remaining_count=3)
    assert "4 photos" in reply
    assert "3 photos" in reply


# ---------------------------------------------------------------------------
# Capability help (see runtime/capability_help.py for the matching side)
# ---------------------------------------------------------------------------


def test_one_confident_match_is_answered_directly_not_as_a_one_row_list():
    """Making someone tap a single-row list to learn one thing is a wasted
    round trip -- the answer is short enough to just be the answer."""
    reply = render_capability_answer(["finance.transfer"])
    assert "Transfer Money" in reply.text
    # The registry's example, so help teaches the phrasing that actually works.
    assert "Company Account" in reply.text
    assert reply.list_rows is None


def test_several_matches_become_a_tappable_picker():
    reply = render_capability_answer(["finance.transfer", "finance.petty_cash"])
    assert reply.list_rows is not None
    assert [r.id for r in reply.list_rows] == ["wf_finance.transfer", "wf_finance.petty_cash"]


def test_suggestion_rows_reuse_the_menu_tap_ids():
    """The whole reason help needs no plumbing of its own: a suggested row is
    a menu row, so tapping it runs render_category_prompt exactly as a tap
    from the category menu would."""
    reply = render_capability_answer(["finance.transfer", "expense.submit"])
    assert reply.list_rows is not None
    for row in reply.list_rows:
        assert render_category_prompt(row.id) is not None


def test_no_matches_falls_back_to_the_capability_overview():
    for empty in (None, [], "garbage", {}):
        reply = render_capability_answer(empty)
        assert "send me what happened" in reply.text
        assert reply.list_rows == CATEGORY_ROWS


def test_an_unrecognized_key_is_ignored_rather_than_crashing():
    """Metadata is a plain dict that survived a round trip through Pydantic --
    it is not a trusted source of WorkflowKey values."""
    reply = render_capability_answer(["finance.teleport", "finance.transfer"])
    assert "Transfer Money" in reply.text


def test_a_system_only_workflow_is_never_suggested():
    assert render_capability_answer(["labour.worker_promotion"]).list_rows == CATEGORY_ROWS


def test_a_restricted_match_is_dropped_for_a_role_that_cannot_use_it():
    """Second line of defence -- capability_help.py already filters its
    catalogue by role, but these keys arrive via decision metadata."""
    reply = render_capability_answer(
        ["project.add_member", "project.detail_query"], role="SITE_ENGINEER"
    )
    assert reply.list_rows is not None
    assert [r.id for r in reply.list_rows] == ["wf_project.detail_query"]


# ---------------------------------------------------------------------------
# Member-name resolution (see runtime/entity_resolution/member_resolution.py)
# ---------------------------------------------------------------------------


def test_member_candidate_picker_lists_candidates_plus_someone_else():
    from workflows.entities import Candidate

    reply = render_member_candidate_picker(
        "Hysam", (Candidate(entity_id="u1", display_name="Hisham"),)
    )
    assert reply.list_rows is not None
    ids = [r.id for r in reply.list_rows]
    assert ids == ["member_u1", "member_none"]
    assert reply.list_rows[0].title == "Hisham"
    assert reply.list_rows[-1].title == "Someone else"


def test_member_candidate_picker_caps_at_nine_plus_someone_else():
    from workflows.entities import Candidate

    candidates = tuple(Candidate(entity_id=f"u{i}", display_name=f"Person {i}") for i in range(12))
    reply = render_member_candidate_picker("X", candidates)
    assert reply.list_rows is not None
    assert len(reply.list_rows) == 10  # WhatsApp's own 10-row cap
    assert reply.list_rows[-1].id == "member_none"


def test_member_create_offer_has_yes_and_no_buttons():
    reply = render_member_create_offer("Hysam")
    assert reply.buttons is not None
    assert {b.id for b in reply.buttons} == {"membernew_yes", "membernew_no"}
    assert "Hysam" in reply.text


def test_member_create_declined_reply_names_the_person():
    assert "Hysam" in render_member_create_declined_reply("Hysam")


def test_member_not_found_reply_is_distinct_from_the_create_offer():
    text = render_member_not_found_reply("Hysam")
    assert "Hysam" in text
    assert "admin" in text.lower()


# --- Overview vs smalltalk (request [65]) ---------------------------------------


def test_the_overview_says_tell_ask_and_get_reports_and_keeps_the_menu():
    reply = render_capability_answer([])
    assert "send me what happened" in reply.text
    assert "how many workers today?" in reply.text
    assert "today's summary" in reply.text
    assert "voice note" in reply.text
    assert reply.list_rows == CATEGORY_ROWS


_SMALLTALK = ("are you hardcoded", "you sound like a bot", "what are your features?", "lol", "")


def test_smalltalk_is_one_short_line_with_no_menu():
    for text in _SMALLTALK:
        reply = render_capability_answer([], kind="smalltalk", question=text)
        assert not reply.list_rows and not reply.buttons
        assert "\n" not in reply.text


def test_smalltalk_is_deterministic_per_text_and_varies_across_texts():
    first = render_capability_answer(None, kind="smalltalk", question="are you hardcoded")
    again = render_capability_answer(None, kind="smalltalk", question=" Are you hardcoded ")
    assert first.text == again.text
    seen = {
        render_capability_answer(None, kind="smalltalk", question=f"msg {i}").text
        for i in range(40)
    }
    assert len(seen) >= 3


def test_an_unknown_kind_is_answered_as_a_capability_question():
    for kind in (None, "capability", "garbage", 5):
        reply = render_capability_answer([], kind=kind, question="what can you do")
        assert reply.list_rows == CATEGORY_ROWS


def test_every_new_text_has_malayalam_and_hindi_wording():
    from channel import replies
    from runtime.reply_language import localize_fixed_reply

    texts = [replies._OVERVIEW_INTRO, replies._OVERVIEW_OUTRO, *replies._SMALLTALK_REPLIES]
    for lang in ("malayalam", "hindi"):
        for text in texts:
            assert localize_fixed_reply(text, lang, "native") != text


def test_smalltalk_uses_the_model_reply_when_there_is_one_and_the_fixed_line_otherwise():
    spoken = render_capability_answer([], kind="smalltalk", question="hmm", smalltalk_reply="No, I read what you write.")
    assert spoken.text == "No, I read what you write."
    assert render_capability_answer([], kind="smalltalk", question="hmm").text
