"""admin.intents + the /admin/message-map/intents route (SA-39 phase 1) -- fakes only, no DB, no live app.

Conversations are built the way production records them (``inbound_messages`` rows + ``agent_api_turn``
traces, checked on 11 days of live data on 15 Nov 2026): a card that collects lines over several
messages, one Save or Cancel that ends all of them, taps with no trace, questions answered by a short
message. For every rule: the reported shape, a sibling, and the case that must not change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import jwt
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import admin.message_map_router as map_router
from admin.intents import (
    ABANDONED,
    ASKED_ANSWERED,
    CANCELLED,
    CHANGED_BEFORE_SAVE,
    COMPLAINED,
    CORRECTED_AFTER_SAVE,
    FAILED,
    FINISHED,
    FINISHED_AFTER_QUESTION,
    MEMORY,
    ONE_THING,
    OPEN,
    READ_ANSWER,
    SEVERAL_THINGS,
    UNSURE,
    UNSURE_REASONS,
    VOICE,
    build_intents,
    capability_name,
)
from admin.intents_patterns import SPLIT_FLOOR, after_failure, causes, leaks, script_of, splits
from admin.intents_playbook import best_case, playbook
from admin.intents_summary import fix_first, plain_reason, summarise
from admin.message_map_router import router
from mesiri.domains.identity.auth_service import ALGORITHM, SECRET_KEY

NOW = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
READY = {"status": "ready, NOT saved"}


def msg(n: int, text: str = "20 bag cement vannu", *, kind: str = "text", reply: str | None = "ok",
        status: str = "completed", minutes_ago: float = 120, sender: str = "919000001234", **extra: Any) -> dict[str, Any]:
    at = NOW - timedelta(minutes=minutes_ago)
    return {
        "id": f"00000000-0000-4000-8000-{n:012d}", "correlation_id": f"cor_{n}", "sender_wa_id": sender,
        "organization_id": "org", "organization_name": "Acme Builders", "message_type": kind, "body_text": text,
        "assistant_reply": reply, "processing_status": status, "error_code": None,
        "received_at": at, "processed_at": at, "sender_name": "Ravi", "sender_role": "SITE_ENGINEER", **extra,
    }


def call(tool: str, **result: Any) -> dict[str, Any]:
    return {"tool": tool, "args": {}, "result": result}


def saved(*tools: str, status: int = 201, **extra: Any) -> dict[str, Any]:
    return {"calls": [], "save_results": [{"tool": t, "status": status, "summary": t, **extra} for t in tools]}


def intents_of(*steps: tuple[dict[str, Any], dict[str, Any] | None], now: datetime = NOW) -> list[dict[str, Any]]:
    messages = [m for m, _turn in steps]
    turns = {m["correlation_id"]: turn for m, turn in steps if turn is not None}
    return build_intents(messages, turns, now=now)["intents"]


def one(*steps: tuple[dict[str, Any], dict[str, Any] | None]) -> dict[str, Any]:
    (intent,) = intents_of(*steps)
    return intent


# ── a card nobody saved no longer counts as working ─────────────────────────


def test_a_card_then_save_is_one_finished_intent():
    intent = one((msg(1, minutes_ago=60), {"calls": [call("record_receipt", **READY)]}),
                 (msg(2, "Save", kind="interactive", minutes_ago=59), saved("record_receipt")))
    assert (intent["ending"], intent["capability"], intent["section"]) == (FINISHED, "record_receipt", "materials")
    assert intent["journeys"] == [ONE_THING]
    assert len(intent["messages"]) == 2


def test_a_card_left_without_save_is_abandoned_once_the_conversation_is_over():
    intent = one((msg(1, minutes_ago=60), {"calls": [call("record_receipt", **READY)]}))
    assert (intent["ending"], intent["reason"]) == (ABANDONED, "The card was never saved")


def test_a_card_in_a_conversation_still_going_is_open_and_left_out_of_the_counts():
    intent = one((msg(1, minutes_ago=5), {"calls": [call("record_receipt", **READY)]}))
    assert intent["ending"] == OPEN
    assert summarise([intent])["totals"]["intents"] == 0


def test_a_read_in_the_same_message_does_not_finish_a_card_that_was_cancelled():
    """Production 13 Nov: stock read + receipt on the card, then 'cancel all'. It was cancelled, not finished."""
    intent = one((msg(1, minutes_ago=60), {"calls": [call("list_receipts", status=200), call("record_receipt", **READY)]}),
                 (msg(2, "cancel all", minutes_ago=59), {"calls": [], "cancelled": [{"tool": "record_receipt"}],
                                                          "typed_cancel": True}))
    assert intent["ending"] == CANCELLED
    assert READ_ANSWER not in intent["journeys"]


def test_a_read_alone_is_finished_as_a_question_answered_from_the_records():
    intent = one((msg(1, "how much cement?", kind="voice", minutes_ago=60), {"calls": [call("stock_check", status=200)]}))
    assert intent["ending"] == FINISHED
    assert intent["journeys"] == [READ_ANSWER, VOICE]


# ── the card is shared: one Save ends every intent waiting on it ────────────


def test_one_save_ends_two_intents_on_the_same_card_and_is_counted_as_shared():
    steps = ((msg(1, "20 bag cement vannu", minutes_ago=60), {"calls": [call("record_receipt", **READY)]}),
             (msg(2, "5 mason vannu", minutes_ago=59), {"calls": [call("record_attendance", **READY)]}),
             (msg(3, "Save", kind="interactive", minutes_ago=58), saved("record_receipt", "record_attendance")))
    built = build_intents([m for m, _ in steps], {m["correlation_id"]: t for m, t in steps}, now=NOW)
    assert [(i["capability"], i["ending"]) for i in built["intents"]] == [
        ("record_receipt", FINISHED), ("record_attendance", FINISHED)]
    assert built["links"]["shared_card"] == 1


def test_a_refused_save_line_fails_only_the_intent_that_prepared_it():
    steps = ((msg(1, minutes_ago=60), {"calls": [call("record_receipt", **READY)]}),
             (msg(2, "send report to ravi", minutes_ago=59), {"calls": [call("send_report_to", **READY)]}),
             (msg(3, "Save", kind="interactive", minutes_ago=58),
              {"save_results": [{"tool": "record_receipt", "status": 201},
                                {"tool": "send_report_to", "status": 422, "reason": "Input should be a valid UUID"}]}))
    endings = {i["capability"]: (i["ending"], i["reason"]) for i in intents_of(*steps)}
    assert endings == {"record_receipt": (FINISHED, ""), "send_report_to": (FAILED, "Input should be a valid UUID")}


def test_a_cancel_tap_ends_every_waiting_intent_as_cancelled():
    steps = ((msg(1, minutes_ago=60), {"calls": [call("record_receipt", **READY)]}),
             (msg(2, "3 carpenter", minutes_ago=59), {"calls": [call("record_attendance", **READY)]}),
             (msg(3, "Cancel", kind="interactive", minutes_ago=58), {"calls": [], "cancelled": [{"tool": "x"}]}))
    assert [i["ending"] for i in intents_of(*steps)] == [CANCELLED, CANCELLED]


# ── several things, changes, corrections, memory ────────────────────────────


def test_one_message_with_several_lines_changed_by_a_typed_follow_up():
    """Production 13 Nov: five lines, then 'cement 45 bags not 40, and remove ...', then Save."""
    lines = [call("record_receipt", **READY), call("record_attendance", **READY), call("report_issue", **READY)]
    intent = one((msg(1, minutes_ago=60), {"calls": lines}),
                 (msg(2, "cement 45 not 40", minutes_ago=59),
                  {"calls": [call("change_ready_entry", status="changed in the ready list, NOT saved"),
                             call("drop_ready_entries", status=None)]}),
                 (msg(3, "Save", kind="interactive", minutes_ago=58), saved("record_receipt", "record_attendance")))
    assert intent["ending"] == FINISHED
    assert intent["journeys"] == [CHANGED_BEFORE_SAVE, SEVERAL_THINGS, MEMORY]


def test_a_typed_cancel_is_not_a_memory_follow_up():
    intent = one((msg(1, minutes_ago=60), {"calls": [call("record_receipt", **READY)]}),
                 (msg(2, "cancel", minutes_ago=59), {"calls": [], "cancelled": [{"tool": "record_receipt"}]}))
    assert MEMORY not in intent["journeys"]


def test_a_correction_of_a_saved_entry_is_its_own_intent_and_marks_the_one_it_corrected():
    steps = ((msg(1, "6 mason vannu", minutes_ago=60), {"calls": [call("record_attendance", **READY)]}),
             (msg(2, "Save", kind="interactive", minutes_ago=59), saved("record_attendance")),
             (msg(3, "alla, 4 mason aanu", minutes_ago=58), {"calls": [call("correct_saved_entry", **READY)]}),
             (msg(4, "Save", kind="interactive", minutes_ago=57), saved("record_attendance")))
    first, correction = intents_of(*steps)
    assert (first["ending"], first["corrected_later"], first["journeys"]) == (FINISHED, True, [ONE_THING])
    assert (correction["ending"], correction["capability"]) == (FINISHED, "correct_saved_entry")
    assert correction["journeys"] == [CORRECTED_AFTER_SAVE]


def test_an_undo_tool_is_a_correction_too():
    intent = one((msg(1, "that usage was wrong", minutes_ago=60),
                  {"calls": [call("list_usage", status=200), call("undo_usage", **READY)]}),
                 (msg(2, "Save", kind="interactive", minutes_ago=59), saved("undo_usage")))
    assert intent["journeys"] == [CORRECTED_AFTER_SAVE]


# ── Mesiri asks, the person answers ─────────────────────────────────────────


def test_a_short_answer_to_a_question_continues_the_intent():
    """Production: '10 bag cement arrived' -> which site? -> 'ys' -> ready -> Save."""
    intent = one((msg(1, minutes_ago=60), {"calls": [call("record_receipt", error="Which site is this for? Nothing is prepared.")]}),
                 (msg(2, "ys", minutes_ago=59), {"calls": [call("record_receipt", **READY)]}),
                 (msg(3, "Save", kind="interactive", minutes_ago=58), saved("record_receipt")))
    assert intent["ending"] == FINISHED_AFTER_QUESTION
    assert intent["journeys"] == [ASKED_ANSWERED, MEMORY]


def test_a_tap_answering_a_question_continues_it():
    intent = one((msg(1, minutes_ago=60), {"calls": [call("record_receipt", status="held: the code asks which site")],
                                           "asked": "Which site?"}),
                 (msg(2, "Green Villa", kind="interactive", minutes_ago=59), {"calls": [call("record_receipt", **READY)]}),
                 (msg(3, "Save", kind="interactive", minutes_ago=58), saved("record_receipt")))
    assert (intent["ending"], intent["journeys"]) == (FINISHED_AFTER_QUESTION, [ASKED_ANSWERED])


def test_a_question_never_answered_is_abandoned():
    intent = one((msg(1, minutes_ago=60), {"calls": [call("record_receipt", status="held: which site")], "asked": "Which site?"}))
    assert (intent["ending"], intent["reason"]) == (ABANDONED, "A question was never answered")


def test_a_new_request_after_a_question_starts_its_own_intent():
    steps = ((msg(1, minutes_ago=60), {"calls": [call("record_receipt", status="held: which site")], "asked": "Which site?"}),
             (msg(2, "how many workers today?", minutes_ago=59), {"calls": [call("labour_attendance", status=200)]}))
    assert [(i["capability"], i["ending"]) for i in intents_of(*steps)] == [
        ("record_receipt", ABANDONED), ("labour_attendance", FINISHED)]


# ── failures, complaints, not sure ──────────────────────────────────────────


def test_an_outage_fails_the_intent_and_a_refusal_the_model_recovered_from_does_not():
    outage = one((msg(1, status="failed", reply=None, error_code="AI_UNAVAILABLE", minutes_ago=60), None))
    assert (outage["ending"], outage["reason"]) == (FAILED, "AI unavailable")  # a code reads as words in every list
    recovered = one((msg(2, minutes_ago=60), {"calls": [call("record_receipt", error="'Tata steel' is not in the list."),
                                                       call("add_material", **READY)]}),
                    (msg(3, "Save", kind="interactive", minutes_ago=59), saved("add_material")))
    assert (recovered["ending"], recovered["capability"]) == (FINISHED, "add_material")


def test_a_refusal_keeps_its_reason():
    intent = one((msg(1, minutes_ago=60), {"calls": [call("record_receipt", error="'TMT' is not in the company's material list. No.")]}))
    assert (intent["ending"], intent["reason"]) == (FAILED, "… is not in the company's material list.")


def test_a_complaint_marks_the_intent_and_an_idea_does_not():
    bad = {"tool": "tell_the_team", "args": {"kind": "wrong_reply"}, "result": {"status": "Passed to the team."}}
    idea = {"tool": "tell_the_team", "args": {"kind": "idea"}, "result": {"status": "Passed to the team."}}
    complaint = one((msg(1, "wrong!", minutes_ago=60), {"calls": [bad]}))
    assert (complaint["ending"], complaint["capability"], complaint["journeys"]) == (COMPLAINED, "tell_the_team", [])
    assert one((msg(2, "a darker card", minutes_ago=60), {"calls": [idea]}))["ending"] == UNSURE


def test_not_sure_says_why_from_the_record():
    asked_back = one((msg(1, "cancel", reply="What should I cancel?", minutes_ago=60), {"calls": []}))
    waiting = one((msg(2, "ok", minutes_ago=60), {"calls": [], "pending": ["20 bags"]}))
    talk = one((msg(3, "hi", reply="Hello!", minutes_ago=60), {"calls": []}))
    assert asked_back["reason"] == UNSURE_REASONS["asked_back"]
    assert waiting["reason"] == UNSURE_REASONS["card_waiting"]
    assert (talk["ending"], talk["capability"], talk["reason"]) == (UNSURE, "_talk", UNSURE_REASONS["talk"])


def test_messages_with_no_trace_in_a_row_are_one_intent():
    """Sign-up: taps and answers the code handles itself, no v3 trace. One intent, not five."""
    steps = [(msg(n, text, kind=kind, minutes_ago=60 - n), None) for n, text, kind in (
        (1, "Hi", "text"), (2, "Set up my company", "interactive"), (3, "New India", "text"),
        (4, "Green villa", "text"), (5, "Looks good", "interactive"))]
    intent = one(*steps)
    assert (intent["capability"], intent["ending"], len(intent["messages"])) == ("_no_record", UNSURE, 5)
    assert intent["reason"] == UNSURE_REASONS["no_record"]


def test_a_new_conversation_starts_after_thirty_minutes_of_silence():
    steps = ((msg(1, minutes_ago=200), {"calls": [call("record_receipt", **READY)]}),
             (msg(2, "Save", kind="interactive", minutes_ago=100), saved("record_receipt")))
    first, second = intents_of(*steps)
    assert first["ending"] == ABANDONED and first["conversation"] != second["conversation"]


def test_two_people_never_share_an_intent():
    steps = ((msg(1, minutes_ago=60), {"calls": [call("record_receipt", **READY)]}),
             (msg(2, "Save", kind="interactive", minutes_ago=59, sender="919000009999"), saved("record_receipt")))
    assert sorted(i["ending"] for i in intents_of(*steps)) == sorted([ABANDONED, UNSURE])


# ── capability names and the summary ────────────────────────────────────────


def test_a_capability_is_named_from_the_tool_description_in_plain_words():
    assert capability_name("record_receipt").startswith("A material receipt")
    assert "_" not in capability_name("record_receipt")
    long = capability_name("set_unit_conversion")  # cut at 80 characters: ends on a whole word, says so
    assert long.endswith(" …") and len(long) <= 82
    assert capability_name("_talk") == "Talk with no tool used"
    assert capability_name("a_tool_that_does_not_exist") == "A tool that does not exist"


def test_every_tool_of_the_assistant_gets_a_plain_name():
    from agent_api.tools import ALLOWED

    for allowed in ALLOWED:
        name = capability_name(allowed.name)
        assert name, allowed.name
        if "_" in allowed.name:  # a one-word name ("rfq") is also a plain word
            assert allowed.name not in name, allowed.name


def test_summarise_counts_endings_per_module_and_capability_and_names_the_widest_drop():
    steps = ((msg(1, "20 bag cement", minutes_ago=300), {"calls": [call("record_receipt", **READY)]}),
             (msg(2, "Save", kind="interactive", minutes_ago=299), saved("record_receipt")),
             (msg(3, "10 bag sand", minutes_ago=200), {"calls": [call("record_receipt", **READY)]}),
             (msg(4, "hello", minutes_ago=100), {"calls": []}))
    messages = {m["id"]: m for m, _ in steps}
    out = summarise(intents_of(*steps), messages)
    assert out["totals"]["intents"] == 3 and out["totals"][FINISHED] == 1 and out["totals"][ABANDONED] == 1
    materials = next(s for s in out["sections"] if s["key"] == "materials")
    (receipt,) = materials["capabilities"]
    assert (receipt["count"], receipt["finished"], receipt["tool"]) == (2, 1, "record_receipt")
    assert receipt["phrasings"] == ["10 bag sand", "20 bag cement"]
    assert receipt["top_reasons"] == [{"reason": "The card was never saved", "count": 1}]
    assert receipt["intents"][0].startswith(msg(3)["id"])  # the failure first
    assert [s["count"] for s in out["funnel"]["steps"]] == [3, 2, 2, 1]
    assert out["funnel"]["widest_drop"] == {"at": "A tool was called", "lost": 1}


def test_fix_first_is_one_line_per_cause_across_capabilities_largest_first():
    refused = "'TMT' is not in the company's material list. Nothing is prepared."
    steps = ((msg(1, "tmt vannu", minutes_ago=400), {"calls": [call("record_receipt", error=refused)]}),
             (msg(2, "tmt used", minutes_ago=300), {"calls": [call("record_usage", error=refused)]}),
             (msg(3, "hi", minutes_ago=200, status="failed", reply=None, error_code="AI_UNAVAILABLE"), None),
             (msg(4, "Set up my company", kind="interactive", minutes_ago=100), None))  # sign-up: not a problem
    first, second = fix_first(intents_of(*steps))
    assert first["line"] == "2 requests failed: … is not in the company's material list."
    assert [c["key"] for c in first["capabilities"]] == ["record_receipt", "record_usage"]
    assert first["intents"][0].startswith(msg(2)["id"])  # newest first
    assert second["line"] == "1 request failed: AI unavailable"


def test_fix_first_says_a_reply_with_nothing_done_in_plain_words():
    (problem,) = fix_first(intents_of((msg(1, "cancel", reply="What should I cancel?", minutes_ago=60), {"calls": []})))
    assert problem["line"] == "1 request: Mesiri replied with a question of its own and used no tool"


def test_an_error_code_reads_as_words_and_a_sentence_is_left_alone():
    assert plain_reason("AI_UNAVAILABLE") == "AI unavailable"
    assert plain_reason("PROVIDER_TIMEOUT") == "Provider timeout"
    assert plain_reason("Issue not found") == "Issue not found"


def test_an_intent_carries_its_first_words_and_who_sent_them():
    intent = one((msg(1, "20  bag\ncement vannu", minutes_ago=60), {"calls": [call("stock_check", status=200)]}))
    assert (intent["text"], intent["sender_name"], intent["sender_role"]) == ("20 bag cement vannu", "Ravi", "SITE_ENGINEER")


# ── how a request is linked (phase 3 additions) ─────────────────────────────


def test_an_answer_to_a_question_asked_in_words_continues_the_request():
    """Production: '10 bag cement arrived' -> a reply that ends in a question (no `asked` in the trace) -> 'ys'."""
    intent = one((msg(1, "10 bag cement arrived", reply="Already saved at 9:50. Save it again?", minutes_ago=60),
                  {"calls": [call("record_receipt", error="Already saved at 09:50: 10 bags Cement.")]}),
                 (msg(2, "ys", minutes_ago=59), {"calls": [call("record_receipt", **READY)]}),
                 (msg(3, "Save", kind="interactive", minutes_ago=58), saved("record_receipt")))
    assert (intent["ending"], len(intent["messages"])) == (FINISHED_AFTER_QUESTION, 3)
    assert ASKED_ANSWERED in intent["journeys"] and ONE_THING not in intent["journeys"]


def test_a_question_in_words_beside_a_card_does_not_swallow_the_next_request():
    steps = ((msg(1, minutes_ago=60, reply="Ready. Anything else?"), {"calls": [call("record_receipt", **READY)]}),
             (msg(2, "how many workers?", minutes_ago=59), {"calls": [call("labour_attendance", status=200)]}))
    assert [i["capability"] for i in intents_of(*steps)] == ["record_receipt", "labour_attendance"]


def test_one_thing_means_the_first_message_put_it_on_the_card():
    later = one((msg(1, "hi", reply="Hello", minutes_ago=60), {"calls": []}),
                (msg(2, "Save", kind="interactive", minutes_ago=59), saved("record_receipt")))
    assert ONE_THING not in later["journeys"]


def test_a_card_change_sent_after_save_marks_the_saved_request_as_corrected_later():
    """Production 7 Nov: Save, then 'alla, 6 mason aanu' that only tried change_ready_entry (refused)."""
    intent = one((msg(1, "8 mason vannu", minutes_ago=60), {"calls": [call("record_attendance", **READY)]}),
                 (msg(2, "Save", kind="interactive", minutes_ago=59), saved("record_attendance")),
                 (msg(3, "alla, 6 mason aanu", minutes_ago=58),
                  {"calls": [call("change_ready_entry", error="Nothing is waiting: that record is already saved.")]}))
    assert intent["corrected_later"] is True
    assert CHANGED_BEFORE_SAVE not in intent["journeys"]


# ── the Playbook: the best real request per journey ─────────────────────────


def _receipt(n: int, minutes_ago: int, *, extra: list[dict[str, Any]] | None = None, reply_s: float = 5.0):
    ready = msg(n, minutes_ago=minutes_ago)
    ready["processed_at"] = ready["received_at"] + timedelta(seconds=reply_s)
    tap = msg(n + 1, "Save", kind="interactive", minutes_ago=minutes_ago - 1)
    return [(ready, {"calls": [*(extra or []), call("record_receipt", **READY)]}), (tap, saved("record_receipt"))]


def test_the_best_case_is_the_cleanest_real_request_and_the_rate_is_beside_it():
    refused_first = [call("record_receipt", error="'TMT' is not in the company's material list.")]
    steps = (*_receipt(1, 400, extra=refused_first), *_receipt(3, 300, reply_s=20.0), *_receipt(5, 200, reply_s=4.0),
             (msg(7, minutes_ago=100), {"calls": [call("record_receipt", **READY)]}))  # never saved
    intents = intents_of(*steps)
    best = best_case(intents, ONE_THING)
    assert best is not None and best["messages"][0] == msg(5)["id"]  # no refusal, the fastest reply
    (module,) = playbook(intents)
    (receipt,) = module["capabilities"]
    one_thing = next(j for j in receipt["journeys"] if j["key"] == ONE_THING)
    assert (one_thing["count"], one_thing["same_end"], one_thing["best"]) == (3, 3, best["id"])


def test_a_journey_with_no_clean_request_says_so():
    corrected = (*_receipt(1, 300), (msg(3, "alla, 30 aanu", minutes_ago=298),
                                     {"calls": [call("correct_saved_entry", **READY)]}))
    (module,) = [m for m in playbook(intents_of(*corrected)) if m["key"] == "materials"]
    one_thing = next(j for j in module["capabilities"][0]["journeys"] if j["key"] == ONE_THING)
    assert one_thing["best"] is None and module["missing"] >= 1


def test_a_cancelled_best_case_holds_its_own_cancel():
    shared = ((msg(1, "20 bag cement", minutes_ago=60), {"calls": [call("record_receipt", **READY)]}),
              (msg(2, "10 bag sand", minutes_ago=59), {"calls": [call("record_receipt", **READY)]}),
              (msg(3, "Cancel", kind="interactive", minutes_ago=58), {"calls": [], "cancelled": [{"tool": "x"}]}))
    best = best_case(intents_of(*shared), "cancelled")
    assert best is not None and msg(3)["id"] in best["messages"]


def test_the_playbook_leaves_out_talk_failures_and_team_feedback():
    tell = {"tool": "tell_the_team", "args": {"kind": "idea"}, "result": {"status": "Passed to the team."}}
    steps = ((msg(1, "hi", minutes_ago=300), {"calls": []}), (msg(2, "idea", minutes_ago=200), {"calls": [tell]}),
             (msg(3, status="failed", reply=None, error_code="AI_UNAVAILABLE", minutes_ago=100), None))
    assert playbook(intents_of(*steps)) == []


# ── Patterns: connections between failures ──────────────────────────────────

REFUSED = "'TMT' is not in the company's material list. Nothing is prepared."


def test_a_cause_is_counted_once_across_capabilities_with_its_trend_and_fix_actions():
    now = intents_of((msg(1, minutes_ago=400), {"calls": [call("record_receipt", error=REFUSED)]}),
                     (msg(2, minutes_ago=300), {"calls": [call("record_usage", error=REFUSED)]}),
                     (msg(3, minutes_ago=200), {"calls": [call("record_receipt", error=REFUSED)]}))
    before = intents_of((msg(9, minutes_ago=2000), {"calls": [call("record_receipt", error=REFUSED)]}))
    (cause,), gone = causes(now, before)
    assert (cause["count"], cause["before"], cause["trend"]) == (3, 1, "steady")
    assert [c["key"] for c in cause["capabilities"]] == ["record_receipt", "record_usage"]
    assert cause["correlation_ids"][0] == "cor_3" and cause["replay"] == "python3 scripts/replay_to_test.py cor_3"
    assert gone == []


def test_a_new_cause_and_a_gone_one_are_named():
    now = intents_of((msg(1, status="failed", reply=None, error_code="AI_UNAVAILABLE", minutes_ago=60), None))
    before = intents_of((msg(9, minutes_ago=2000), {"calls": [call("record_receipt", error=REFUSED)]}))
    (cause,), (gone,) = causes(now, before)
    assert cause["trend"] == "new"
    assert gone["line"] == "1 request failed: … is not in the company's material list."


def test_a_request_passed_to_the_team_carries_the_team_request_reference():
    """TM-21: the ref is made from the correlation id (release_notes.request_ref), never matched by text."""
    bad = {"tool": "tell_the_team", "args": {"kind": "wrong_reply"}, "result": {"status": "Passed to the team."}}
    row = msg(1, "wrong!", minutes_ago=60, correlation_id="cor_a83f12aa00")
    (cause,), _ = causes(intents_of((row, {"calls": [bad]})), [])
    assert cause["team_refs"] == ["#a83f12"]


def test_where_a_flow_leaks_is_its_widest_drop():
    steps = (*_receipt(1, 400), (msg(3, minutes_ago=300), {"calls": [call("record_receipt", **READY)]}),
             (msg(4, minutes_ago=200), {"calls": [call("record_receipt", **READY)]}))
    (leak,) = leaks(intents_of(*steps))
    assert [s["count"] for s in leak["steps"]] == [3, 3, 3, 1]
    assert leak["widest_drop"] == {"at": "Saved, sent or answered", "lost": 2} and leak["lost"] == 2


def test_a_split_is_shown_only_when_two_groups_pass_the_floor():
    typed = [(msg(n, minutes_ago=1000 - 40 * n), {"calls": [call("stock_check", status=200)]}) for n in range(SPLIT_FLOOR)]
    voice = [(msg(100 + n, kind="voice", minutes_ago=999 - 40 * n), {"calls": [call("stock_check", status=200)]})
             for n in range(SPLIT_FLOOR)]
    photo = [(msg(300, kind="image", minutes_ago=5000), {"calls": [call("stock_check", status=200)]})]
    by_how = next(s for s in splits(intents_of(*typed, *voice, *photo)) if s["key"] == "how")
    assert sorted(g["name"] for g in by_how["groups"]) == ["Typed", "Voice note"] and by_how["hidden"] == 1
    assert [s["key"] for s in splits(intents_of(*typed, *photo))] == []


def test_the_script_is_read_from_the_letters():
    assert script_of("20 bag cement vannu")[0] == "latin"
    assert script_of("ഇന്ന് 50 ചാക്ക് സിമന്റ് വന്നു")[0] == "malayalam"
    assert script_of("आज तीन कारपेंटर आये")[0] == "devanagari"
    assert script_of("Main Block mein aaj 3 carpenter aaye")[0] == "latin"  # Hinglish in Latin letters
    assert script_of("")[0] == "none"


def test_after_a_failure_the_person_tries_again_moves_on_or_stops():
    steps = ((msg(1, "20 bag cement vannu", minutes_ago=60), {"calls": [call("record_receipt", error=REFUSED)]}),
             (msg(2, "20 bag cement vannu", minutes_ago=59), {"calls": [call("record_receipt", error=REFUSED)]}),
             (msg(3, "how many workers?", minutes_ago=58), {"calls": [call("labour_attendance", status=200)]}))
    intents = intents_of(*steps)
    rows = {m["id"]: m for m, _t in steps}
    kinds = {k["key"]: k["count"] for k in after_failure(intents, rows)["kinds"]}
    assert kinds == {"repeated": 1, "said_wrong": 0, "moved_on": 1, "stopped": 0}
    alone = intents_of((msg(9, minutes_ago=60), {"calls": [call("record_receipt", error=REFUSED)]}))
    assert {k["key"]: k["count"] for k in after_failure(alone, {})["kinds"]}["stopped"] == 1


# ── the route ───────────────────────────────────────────────────────────────


@dataclass
class FakeMessageLogger:
    rows: list[dict[str, Any]] = field(default_factory=list)
    asked: dict[str, Any] = field(default_factory=dict)

    async def list_for_map(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.asked = kwargs
        return self.rows

    async def list_around(self, message_id: Any, **_: Any) -> list[dict[str, Any]]:
        return [r for r in self.rows if str(r["id"]) == str(message_id)]


@dataclass
class FakePins:
    """The pins store, in memory; records what each write was asked to audit."""

    pins: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    audited: list[tuple[str, str, str | None]] = field(default_factory=list)
    broken: bool = False

    async def list(self) -> dict[tuple[str, str], dict[str, Any]]:
        if self.broken:
            raise RuntimeError("relation what_works_pins does not exist")
        return dict(self.pins)

    async def pin(self, *, capability: str, journey: str, message_id: Any, note: str | None, actor: Any) -> None:
        self.pins[(capability, journey)] = {"message_id": str(message_id), "note": note, "by": actor.label, "at": None}
        self.audited.append(("what_works.pinned", f"{capability}/{journey}", actor.label))

    async def unpin(self, *, capability: str, journey: str, actor: Any) -> bool:
        if self.pins.pop((capability, journey), None) is None:
            return False
        self.audited.append(("what_works.unpinned", f"{capability}/{journey}", actor.label))
        return True


@pytest.fixture(autouse=True)
def pins(monkeypatch: pytest.MonkeyPatch) -> FakePins:
    store = FakePins()
    monkeypatch.setattr(map_router, "_pin_store", lambda: store)
    return store


@dataclass
class FakeTraceLogger:
    turns: dict[str, dict[str, Any]] = field(default_factory=dict)

    async def get_turns(self, correlation_ids: list[str]) -> dict[str, dict[str, Any]]:
        return {cid: self.turns[cid] for cid in correlation_ids if cid in self.turns}


def _token(*, role: str, org: str | None) -> str:
    payload = {"sub": "user_1", "org": org, "role": role, "name": "Ilan",
               "exp": datetime.now(UTC) + timedelta(hours=1)}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def _client(rows: list[dict[str, Any]], turns: dict[str, dict[str, Any]]) -> tuple[AsyncClient, FakeMessageLogger]:
    app = FastAPI()
    app.include_router(router)
    logger = FakeMessageLogger(rows=rows)
    app.state.container = SimpleNamespace(message_logger=logger, trace_logger=FakeTraceLogger(turns=turns))
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test"), logger


async def test_the_intents_route_is_for_platform_admins_only():
    client, _ = _client([], {})
    async with client:
        assert (await client.get("/admin/message-map/intents")).status_code == 401
        tenant_admin = {"Authorization": f"Bearer {_token(role='ADMIN', org='org_1')}"}
        assert (await client.get("/admin/message-map/intents", headers=tenant_admin)).status_code == 403


async def test_the_intents_route_splits_this_window_from_the_one_before():
    now = datetime.now(UTC)

    def at(row: dict[str, Any], days_ago: float) -> dict[str, Any]:
        when = now - timedelta(days=days_ago)
        return {**row, "received_at": when, "processed_at": when}

    rows = [at(msg(1), 1), at(msg(2, "Save", kind="interactive"), 1 - 1 / 1440), at(msg(3, "hi"), 10)]
    turns = {"cor_1": {"calls": [call("record_receipt", **READY)]}, "cor_2": saved("record_receipt"), "cor_3": {"calls": []}}
    client, logger = _client(rows, turns)
    admin = {"Authorization": f"Bearer {_token(role='ADMIN', org=None)}"}
    async with client:
        resp = await client.get("/admin/message-map/intents?days=7", headers=admin)
    assert resp.status_code == 200
    body = resp.json()
    assert body["window"]["days"] == 7 and body["truncated"] is False
    assert body["totals"]["intents"] == 1 and body["totals"][FINISHED] == 1
    assert body["previous"]["totals"]["intents"] == 1 and body["previous"]["totals"][UNSURE] == 1
    assert body["sections"][0]["capabilities"][0]["phrasings"] == ["20 bag cement vannu"]
    (intent,) = body["intents"]
    assert intent["ending"] == FINISHED and intent["messages"] == [rows[0]["id"], rows[1]["id"]]
    assert intent["text"] == "20 bag cement vannu" and "sender" not in intent  # never the phone number
    assert body["fix_first"] == []
    assert body["playbook"][0]["capabilities"][0]["journeys"][0]["best"] == intent["id"]
    assert body["patterns"]["causes"] == [] and body["patterns"]["split_floor"] == 10
    assert intent["correlation_ids"] == ["cor_1", "cor_2"]
    assert logger.asked["since"] < now - timedelta(days=13) and logger.asked["limit"] == 10001


# ── pinning the model example (phase 5, decision D3) ────────────────────────


def test_a_pinned_request_is_the_example_and_the_clean_runs_are_offered():
    steps = (*_receipt(1, 400, reply_s=30.0), *_receipt(3, 300, reply_s=4.0))
    intents = intents_of(*steps)
    pin = {("record_receipt", ONE_THING): {"message_id": msg(1)["id"], "note": None, "by": "Ilan", "at": None}}
    one_thing = next(j for j in playbook(intents, pin)[0]["capabilities"][0]["journeys"] if j["key"] == ONE_THING)
    assert one_thing["best"].startswith(msg(1)["id"])  # pinned beats the faster scored pick
    assert one_thing["pinned"]["in_window"] is True and one_thing["pinned"]["by"] == "Ilan"
    assert one_thing["candidates"][0].startswith(msg(3)["id"]) and len(one_thing["candidates"]) == 2


def test_a_pin_outside_the_window_says_so_and_the_scored_pick_shows():
    intents = intents_of(*_receipt(3, 300))
    pin = {("record_receipt", ONE_THING): {"message_id": "gone-message", "note": None, "by": "Ilan", "at": None}}
    one_thing = next(j for j in playbook(intents, pin)[0]["capabilities"][0]["journeys"] if j["key"] == ONE_THING)
    assert one_thing["pinned"]["in_window"] is False and one_thing["best"].startswith(msg(3)["id"])


async def test_pin_and_unpin_are_for_platform_admins_only(pins: FakePins):
    client, _ = _client([msg(1)], {})
    url = "/admin/message-map/pins/record_receipt/one_thing"
    tenant_admin = {"Authorization": f"Bearer {_token(role='ADMIN', org='org_1')}"}
    async with client:
        assert (await client.put(url, json={"message_id": msg(1)["id"]})).status_code == 401
        assert (await client.put(url, json={"message_id": msg(1)["id"]}, headers=tenant_admin)).status_code == 403
        assert (await client.delete(url, headers=tenant_admin)).status_code == 403
    assert pins.pins == {} and pins.audited == []


async def test_a_pin_is_stored_audited_and_shown_and_an_unpin_brings_back_the_score(pins: FakePins):
    now = datetime.now(UTC)
    rows = [{**msg(1), "received_at": now - timedelta(hours=2), "processed_at": now - timedelta(hours=2)},
            {**msg(2, "Save", kind="interactive"), "received_at": now - timedelta(hours=2) + timedelta(seconds=30),
             "processed_at": now - timedelta(hours=2) + timedelta(seconds=31)}]
    turns = {"cor_1": {"calls": [call("record_receipt", **READY)]}, "cor_2": saved("record_receipt")}
    client, _ = _client(rows, turns)
    admin = {"Authorization": f"Bearer {_token(role='ADMIN', org=None)}"}
    url = "/admin/message-map/pins/record_receipt/one_thing"
    async with client:
        resp = await client.put(url, json={"message_id": rows[0]["id"], "note": " the clearest "}, headers=admin)
        assert resp.status_code == 200 and resp.json()["pinned"] is True
        assert pins.pins[("record_receipt", "one_thing")]["note"] == "the clearest"
        assert pins.audited == [("what_works.pinned", "record_receipt/one_thing", "Ilan")]

        body = (await client.get("/admin/message-map/intents?days=7", headers=admin)).json()
        journey = body["playbook"][0]["capabilities"][0]["journeys"][0]
        assert body["pins_ok"] is True and journey["pinned"]["in_window"] is True

        assert (await client.delete(url, headers=admin)).status_code == 200
        assert (await client.delete(url, headers=admin)).status_code == 404  # nothing pinned any more
        assert pins.audited[-1] == ("what_works.unpinned", "record_receipt/one_thing", "Ilan")


async def test_a_pin_must_name_a_real_journey_capability_and_message():
    client, _ = _client([msg(1)], {})
    admin = {"Authorization": f"Bearer {_token(role='ADMIN', org=None)}"}
    body = {"message_id": msg(1)["id"]}
    async with client:
        assert (await client.put("/admin/message-map/pins/record_receipt/flying", json=body, headers=admin)).status_code == 404
        assert (await client.put("/admin/message-map/pins/no_such_tool/one_thing", json=body, headers=admin)).status_code == 404
        assert (await client.put("/admin/message-map/pins/tell_the_team/one_thing", json=body, headers=admin)).status_code == 404
        missing = {"message_id": "00000000-0000-4000-8000-000000000099"}
        assert (await client.put("/admin/message-map/pins/record_receipt/one_thing", json=missing, headers=admin)).status_code == 404
        too_long = {"message_id": msg(1)["id"], "note": "x" * 301}
        assert (await client.put("/admin/message-map/pins/record_receipt/one_thing", json=too_long, headers=admin)).status_code == 422


async def test_the_page_still_opens_when_the_pins_cannot_be_read(pins: FakePins):
    pins.broken = True
    client, _ = _client([], {})
    admin = {"Authorization": f"Bearer {_token(role='ADMIN', org=None)}"}
    async with client:
        resp = await client.get("/admin/message-map/intents", headers=admin)
    assert resp.status_code == 200 and resp.json()["pins_ok"] is False


def test_pin_and_unpin_are_known_audit_actions():
    from mesiri.domains.audit.actions import ACTIONS

    assert {"what_works.pinned", "what_works.unpinned"} <= ACTIONS
