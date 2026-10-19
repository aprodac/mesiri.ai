"""Worker promotion workflow node — unit tests (pure function, no LangGraph needed).

Mirrors tests/unit/test_labour_update_nodes.py's style: the node is re-entrant
and has no memory between passes, so tests spanning two messages thread
`collected_fields` and `awaiting_slot` through by hand, exactly as
WorkflowRuntime.provide_input does.
"""

from __future__ import annotations

import pytest

from workflows.worker_promotion.nodes import (
    DUPLICATE_SLOT,
    PROMOTION_SLOT,
    WORKERS_TO_CREATE,
    offer_and_promote,
)

AJITH = {"name": "Ajith", "trade": "mason", "daily_wage": "800"}
NIYAS = {"name": "Niyas", "trade": "helper", "daily_wage": "600"}
RAHUL = {"name": "Rahul", "trade": "painter", "daily_wage": "700"}


def _base_state(fields: dict, **extra) -> dict:
    state = {
        "workflow_instance_id": "wf_promo_1",
        "workflow_key": "labour.worker_promotion",
        "correlation_id": "cor_1",
        "organization_id": "org1",
        "user_id": "usr1",
        "project_id": "prj1",
        "site_id": "site1",
        "collected_fields": fields,
    }
    state.update(extra)
    return state


def _queued(result: dict) -> list[dict]:
    """The workers the node decided to add.

    The node is pure and never writes -- it lists them under
    WORKERS_TO_CREATE and runtime/inbound_journey.py performs the inserts.
    """
    return list(result["collected_fields"].get(WORKERS_TO_CREATE) or [])


def _names(result: dict) -> list[str]:
    return [w["name"] for w in _queued(result)]


def _answer(workers: list[dict], text: str, *, slot: str = PROMOTION_SLOT, **extra) -> dict:
    fields = {"promotable_workers": workers, "_slot_answer_text": text, **extra}
    return offer_and_promote(_base_state(fields, awaiting_slot=slot))


# ---------------------------------------------------------------------------
# Pass 1 — the offer
# ---------------------------------------------------------------------------


def test_no_promotable_workers_completes_silently():
    """The guard: this workflow is only ever reached with at least one named
    temp worker seeded by the caller. An empty list means the caller made a
    mistake -- bail neutrally rather than sending an empty offer."""
    result = offer_and_promote(_base_state({"promotable_workers": []}))
    assert result["awaiting_slot"] is None
    assert result["pending_prompt"] is None


def test_offer_lists_every_named_worker_with_trade():
    result = offer_and_promote(
        _base_state({"promotable_workers": [AJITH, NIYAS, RAHUL]})
    )

    prompt = result["pending_prompt"]
    assert result["awaiting_slot"] == PROMOTION_SLOT
    assert prompt.startswith("Quick check so your worker list stays clean 👇")
    assert "*Ajith*, *Niyas* and *Rahul* are new names" in prompt
    assert [o["label"] for o in result["awaiting_slot_options"]] == [
        "Add all",
        "Choose",
        "Not now",
    ]


def test_offer_for_two_says_both_and_for_one_just_add():
    two = offer_and_promote(_base_state({"promotable_workers": [AJITH, RAHUL]}))
    one = offer_and_promote(_base_state({"promotable_workers": [AJITH]}))

    assert two["awaiting_slot_options"][0]["label"] == "Add both"
    assert [o["label"] for o in one["awaiting_slot_options"]] == ["Add", "Not now"]
    assert "*Ajith* is a new name" in one["pending_prompt"]


def test_choose_asks_for_names_built_from_the_real_ones():
    """"Choose" shows how to answer with the names actually on screen -- no
    numbers, which are easy to mis-key once a report has a dozen workers."""
    result = _answer([AJITH, RAHUL], "Choose")

    assert result["awaiting_slot"] == PROMOTION_SLOT
    assert "e.g. Ajith, Rahul" in result["pending_prompt"]
    picked = offer_and_promote(
        _base_state(
            {**result["collected_fields"], "_slot_answer_text": "Rahul"},
            awaiting_slot=PROMOTION_SLOT,
        )
    )
    assert _names(picked) == ["Rahul"]


@pytest.mark.parametrize("tap", ["promo_all", "Add both", "add", "Add all", "yes"])
def test_the_add_button_adds_everyone_however_it_arrives(tap):
    assert _names(_answer([AJITH, RAHUL], tap)) == ["Ajith", "Rahul"]


@pytest.mark.parametrize("tap", ["promo_none", "Not now", "nobody", "skip"])
def test_the_not_now_button_adds_nobody(tap):
    result = _answer([AJITH, RAHUL], tap)
    assert _queued(result) == []
    assert result["awaiting_slot"] is None


def test_add_with_a_name_adds_only_that_worker():
    assert _names(_answer([AJITH, RAHUL], "add Ajith")) == ["Ajith"]


def test_offer_never_carries_a_draft_action():
    """This node only runs after RECORD_LABOUR_ATTENDANCE already confirmed
    and saved -- it must never itself produce something to confirm."""
    result = offer_and_promote(_base_state({"promotable_workers": [AJITH]}))
    assert result.get("draft_action") is None


# ---------------------------------------------------------------------------
# Pass 2 — resolving names
# ---------------------------------------------------------------------------


def test_all_creates_every_worker():
    result = _answer([AJITH, NIYAS], "all")

    assert _names(result) == ["Ajith", "Niyas"]
    assert "Ajith, Niyas" in result["pending_prompt"]
    assert result["awaiting_slot"] is None


def test_none_creates_nobody_and_says_they_stay_temporary():
    result = _answer([AJITH, NIYAS], "none")

    assert _queued(result) == []
    assert "temporary workers" in result["pending_prompt"]
    assert result["awaiting_slot"] is None


def test_selecting_by_name_creates_only_those_named():
    result = _answer([AJITH, NIYAS, RAHUL], "Ajith, Rahul")

    assert _names(result) == ["Ajith", "Rahul"]


def test_name_selection_is_case_and_separator_insensitive():
    for reply in ("ajith and rahul", "AJITH, RAHUL", "  ajith   rahul  "):
        assert _names(_answer([AJITH, NIYAS, RAHUL], reply)) == ["Ajith", "Rahul"], reply


def test_a_multi_word_name_is_matched_as_a_whole():
    ravi_kumar = {"name": "Ravi Kumar", "trade": "mason"}

    assert _names(_answer([ravi_kumar, NIYAS], "Ravi Kumar")) == ["Ravi Kumar"]


def test_a_name_read_in_capitals_is_selected_by_any_casing():
    """OCR routinely returns attendance sheets in block capitals, so the name
    on the list and the name the supervisor types rarely agree on case."""
    shouty = {"name": "AJITH KUMAR", "trade": "mason"}
    for reply in ("AJITH KUMAR", "ajith kumar", "Ajith Kumar", "  ajith   KUMAR "):
        assert _names(_answer([shouty, NIYAS], reply)) == ["AJITH KUMAR"], reply


def test_a_first_name_selects_the_one_worker_it_identifies():
    """Typing "Ajith" for a listed "Ajith Kumar" is the natural reply --
    rejecting it made the question feel broken."""
    ajith_kumar = {"name": "Ajith Kumar", "trade": "mason"}

    assert _names(_answer([ajith_kumar, NIYAS], "Ajith")) == ["Ajith Kumar"]


def test_a_first_name_shared_by_two_listed_workers_re_asks():
    """The guard on the rule above: promoting the wrong person is worse than
    asking twice."""
    result = _answer([{"name": "Ajith Kumar"}, {"name": "Ajith Nair"}], "Ajith")

    assert _queued(result) == []
    assert result["awaiting_slot"] == PROMOTION_SLOT


def test_a_reply_mixing_a_full_name_and_a_first_name_keeps_both():
    """"Ajith and Niyas" matches Niyas in full and Ajith only in part. An
    earlier version stopped at the first pass and silently dropped Ajith."""
    result = _answer([{"name": "Ajith Kumar"}, NIYAS], "Ajith and Niyas")

    assert _names(result) == ["Ajith Kumar", "Niyas"]


def test_the_daily_wage_from_attendance_is_carried_into_the_register():
    queued = _queued(_answer([AJITH], "Ajith"))

    assert queued[0]["daily_wage"] == "800"
    assert queued[0]["trade"] == "mason"


@pytest.mark.parametrize(
    "reply",
    [
        "all",
        "save all",          # the one that was reported, and the most natural
        "Save All",
        "SAVE ALL",
        "add all",
        "save them all",
        "yes save all",
        "add them all please",
        "everyone",
        "yes",
        "ok",
    ],
)
def test_saying_yes_is_understood_however_it_is_phrased(reply):
    """Reported from testing: "save all" was rejected. The accepted answers
    were a fixed list of exact phrasings, which can never be complete -- the
    verb around the answer is now treated as noise instead."""
    assert _names(_answer([AJITH, NIYAS], reply)) == ["Ajith", "Niyas"], reply


@pytest.mark.parametrize(
    "reply",
    ["none", "no", "skip", "no thanks", "dont save", "nobody", "not now", "cancel"],
)
def test_saying_no_is_understood_however_it_is_phrased(reply):
    result = _answer([AJITH, NIYAS], reply)
    assert _queued(result) == [], reply
    assert result["awaiting_slot"] is None, reply


@pytest.mark.parametrize(
    "reply", ["all except Ajith", "everyone but Niyas", "save all without Ajith"]
)
def test_an_exclusion_is_re_asked_rather_than_inverted(reply):
    """"All except Ajith" names who to leave *out*, and every other branch
    here reads names as who to put in -- so this would otherwise have
    selected exactly the person the user excluded. A wrongly added worker
    can't be undone from WhatsApp, so it asks again instead."""
    result = _answer([AJITH, NIYAS], reply)

    assert _queued(result) == [], reply
    assert result["awaiting_slot"] == PROMOTION_SLOT, reply


def test_a_worker_whose_name_reads_like_a_keyword_is_still_selectable():
    """The keyword check must never shadow a real name on the list."""
    ok_the_worker = {"name": "Ok", "trade": "mason"}

    assert _names(_answer([ok_the_worker, NIYAS], "Ok")) == ["Ok"]


def test_a_reply_naming_nobody_recognisable_re_asks():
    result = _answer([AJITH], "Suresh")

    assert _queued(result) == []
    assert result["awaiting_slot"] == PROMOTION_SLOT
    assert result["pending_prompt"].startswith("No worries.")
    assert "*Ajith*" in result["pending_prompt"]
    assert result["awaiting_slot_options"], "the re-ask carries the buttons again"


def test_the_queued_workers_are_plain_json_safe_data():
    """The node's output is persisted with model_dump_json() between
    messages, so everything it hands back has to survive that round trip.

    An earlier version seeded a create-callable into these fields instead.
    It could not serialize at all, so saving the paused state raised, the
    run was recorded as failed, and the offer never reached the user --
    silently, on every single report.
    """
    import json

    result = _answer([AJITH, NIYAS], "all")
    json.dumps(result["collected_fields"])  # must not raise
    assert _queued(result) == [
        {"name": "Ajith", "trade": "mason", "daily_wage": "800"},
        {"name": "Niyas", "trade": "helper", "daily_wage": "600"},
    ]


# ---------------------------------------------------------------------------
# Duplicate prevention — the point of the whole feature
# ---------------------------------------------------------------------------

REGISTER = [
    {
        "worker_id": "w-existing",
        "name": "Ajith Kumar",
        "trade": "mason",
        "contractor": None,
        "since": "2026-10-02",
    }
]


def test_a_likely_existing_worker_is_not_created_without_asking():
    """"Ajith, mason" against registered "Ajith Kumar, mason" -- creating a
    second record here is exactly the duplicate this step exists to stop."""
    result = _answer([AJITH], "Ajith", _register=REGISTER)

    assert _queued(result) == []
    assert result["awaiting_slot"] == DUPLICATE_SLOT
    prompt = result["pending_prompt"]
    assert prompt.startswith("Quick check so your worker list stays clean 👇")
    assert "*Ajith* looks like *Ajith Kumar* who's already in your list" in prompt
    assert "(mason, since 2 Oct)" in prompt
    assert prompt.endswith("Is it the same person?")
    assert [o["label"] for o in result["awaiting_slot_options"]] == [
        "Same person",
        "New person",
        "Skip",
    ]


def test_confirming_a_look_alike_is_a_different_person_creates_them():
    asked = _answer([AJITH], "Ajith", _register=REGISTER)

    resumed = offer_and_promote(
        _base_state(
            {**asked["collected_fields"], "_slot_answer_text": "dup_new"},
            awaiting_slot=DUPLICATE_SLOT,
        )
    )

    assert _names(resumed) == ["Ajith"]
    # "Made permanent", not "Added": recording the attendance already gave
    # Ajith a register row marked temporary, and promotion flips that same row
    # rather than inserting a second one.
    assert "Made permanent in your Worker Register: Ajith" in resumed["pending_prompt"]
    assert resumed["awaiting_slot"] is None


def _dup_reply(asked: dict, text: str) -> dict:
    return offer_and_promote(
        _base_state(
            {**asked["collected_fields"], "_slot_answer_text": text},
            awaiting_slot=DUPLICATE_SLOT,
        )
    )


@pytest.mark.parametrize("text", ["none", "Skip", "dup_skip", "nobody", "cancel", "3"])
def test_skipping_the_duplicate_question_creates_nobody(text):
    asked = _answer([AJITH], "Ajith", _register=REGISTER)

    resumed = _dup_reply(asked, text)

    assert _queued(resumed) == []
    assert resumed["awaiting_slot"] is None
    assert "I'll keep *Ajith* as a separate name for now" in resumed["pending_prompt"]
    assert "Worker Register" in resumed["pending_prompt"]


@pytest.mark.parametrize("text", ["same", "Same person", "yes same", "dup_same", "yes", "1"])
def test_same_person_adds_nobody_and_says_so(text):
    asked = _answer([AJITH], "Ajith", _register=REGISTER)

    resumed = _dup_reply(asked, text)

    assert _queued(resumed) == []
    assert resumed["awaiting_slot"] is None
    assert "already in your list as *Ajith Kumar*" in resumed["pending_prompt"]


@pytest.mark.parametrize("text", ["new", "New person", "different", "no", "dup_new", "2"])
def test_new_person_is_added(text):
    asked = _answer([AJITH], "Ajith", _register=REGISTER)

    assert _names(_dup_reply(asked, text)) == ["Ajith"]


def test_an_unclear_reply_re_asks_the_same_look_alike_with_the_buttons():
    asked = _answer([AJITH], "Ajith", _register=REGISTER)

    again = _dup_reply(asked, "hmm maybe")

    assert again["awaiting_slot"] == DUPLICATE_SLOT
    assert again["pending_prompt"].startswith("No worries. Just tap one:")
    assert "*Ajith*" in again["pending_prompt"] and "*Ajith Kumar*" in again["pending_prompt"]
    assert len(again["awaiting_slot_options"]) == 3


def test_look_alikes_are_asked_one_at_a_time_and_at_most_three():
    register = [
        {"worker_id": f"w{i}", "name": f"{n} Kumar", "trade": "mason", "contractor": None}
        for i, n in enumerate(["Ajith", "Niyas", "Rahul", "Sabu"])
    ]
    four = [
        {"name": n, "trade": "mason"} for n in ["Ajith", "Niyas", "Rahul", "Sabu"]
    ]
    asked = _answer(four, "all", _register=register)
    for _ in range(3):
        assert asked["awaiting_slot"] == DUPLICATE_SLOT
        asked = _dup_reply(asked, "new")

    assert asked["awaiting_slot"] is None
    assert _names(asked) == ["Ajith", "Niyas", "Rahul"]
    assert "*Sabu*" in asked["pending_prompt"], "the fourth stays temporary, and is said so"


def test_a_mixed_batch_ends_with_one_write_and_one_summary():
    """Only the look-alike waits for an answer; the clean names ride along
    and the whole batch is handed over together at the end, so the user
    gets one closing summary covering both halves rather than two partial
    ones."""
    asked = _answer([AJITH, RAHUL], "all", _register=REGISTER)

    assert asked["awaiting_slot"] == DUPLICATE_SLOT
    assert _queued(asked) == [], "nothing is handed over while a question is open"

    resumed = offer_and_promote(
        _base_state(
            {**asked["collected_fields"], "_slot_answer_text": "New person"},
            awaiting_slot=DUPLICATE_SLOT,
        )
    )

    assert _names(resumed) == ["Rahul", "Ajith"]
    assert "Rahul" in resumed["pending_prompt"]
    assert "Ajith" in resumed["pending_prompt"]


def test_an_empty_register_never_triggers_the_duplicate_question():
    """Day one: nobody is registered, so every named worker is genuinely new
    and the extra question would be pure friction."""
    result = _answer([AJITH], "all", _register=[])

    assert _names(result) == ["Ajith"]
    assert result["awaiting_slot"] is None


def test_a_different_trade_still_asks_rather_than_assuming_a_new_person():
    """"Ajith, painter" vs registered "Ajith Kumar, mason": people do change
    trade, so this is a question, not a silent second record.

    This is the case matching.ASK misses -- the trade penalty drags a real
    partial-name signal under the attendance threshold. Promotion screens at
    a lower bar precisely so it lands here instead (see _DUPLICATE_SUSPICION).
    """
    result = _answer(
        [{"name": "Ajith", "trade": "painter"}], "Ajith", _register=REGISTER
    )

    assert _queued(result) == []
    assert result["awaiting_slot"] == DUPLICATE_SLOT


def test_a_genuinely_different_name_is_created_with_no_extra_question():
    """The other half of the trade-off: the duplicate screen must not turn
    every promotion into an interrogation. A name sharing nothing with any
    register entry is written straight away, however much else matches."""
    result = _answer(
        [{"name": "Niyas", "trade": "mason"}], "Niyas", _register=REGISTER
    )

    assert _names(result) == ["Niyas"]
    assert result["awaiting_slot"] is None
