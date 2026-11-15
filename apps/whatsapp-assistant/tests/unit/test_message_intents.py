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
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

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
    summarise,
)
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
    assert one((msg(1, status="failed", reply=None, error_code="AI_UNAVAILABLE", minutes_ago=60), None))["ending"] == FAILED
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


# ── the route ───────────────────────────────────────────────────────────────


@dataclass
class FakeMessageLogger:
    rows: list[dict[str, Any]] = field(default_factory=list)
    asked: dict[str, Any] = field(default_factory=dict)

    async def list_for_map(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.asked = kwargs
        return self.rows


@dataclass
class FakeTraceLogger:
    turns: dict[str, dict[str, Any]] = field(default_factory=dict)

    async def get_turns(self, correlation_ids: list[str]) -> dict[str, dict[str, Any]]:
        return {cid: self.turns[cid] for cid in correlation_ids if cid in self.turns}


def _token(*, role: str, org: str | None) -> str:
    payload = {"sub": "user_1", "org": org, "role": role, "exp": datetime.now(UTC) + timedelta(hours=1)}
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
    assert logger.asked["since"] < now - timedelta(days=13) and logger.asked["limit"] == 10001
