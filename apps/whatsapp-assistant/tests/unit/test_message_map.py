"""admin.message_map + admin.message_map_router (SA-38) -- fakes only, no DB, no live app.

The filing rules are checked on turns shaped like the ones production records (``agent_api_turn``):
what counts as working, what counts as broken, what is left as "not sure", and that the page is
platform-admin only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import jwt
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from admin.message_map import (
    BROKEN,
    UNSURE,
    WORKS,
    build_map,
    build_thread,
    classify,
    reason_kind,
    section_of,
)
from admin.message_map_router import router
from mesiri.domains.identity.auth_service import ALGORITHM, SECRET_KEY

NOW = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)


def msg(n: int, text: str = "20 bag cement vannu", *, kind: str = "text", reply: str | None = "ok",
        status: str = "completed", minutes_ago: int = 60, sender: str = "919000001234", **extra: Any) -> dict[str, Any]:
    return {
        "id": f"00000000-0000-4000-8000-{n:012d}", "correlation_id": f"cor_{n}", "sender_wa_id": sender,
        "organization_id": "org", "organization_name": "Acme Builders", "message_type": kind, "body_text": text,
        "assistant_reply": reply, "processing_status": status, "error_code": None,
        "received_at": NOW - timedelta(minutes=minutes_ago), "processed_at": NOW - timedelta(minutes=minutes_ago),
        "sender_name": "Ravi", "sender_role": "SITE_ENGINEER", **extra,
    }


def call(tool: str, **result: Any) -> dict[str, Any]:
    return {"tool": tool, "args": {}, "result": result}


def filed(message: dict[str, Any], turn: dict[str, Any] | None) -> tuple[str, str, str | None]:
    out = classify(message, turn, now=NOW)
    assert out is not None
    return out["state"], out["outcome"], out["tool"]


# ── what counts as working ──────────────────────────────────────────────────


def test_a_prepared_card_a_read_and_a_send_all_work():
    assert filed(msg(1), {"calls": [call("record_receipt", status="ready, NOT saved")]}) == (WORKS, "ready", "record_receipt")
    assert filed(msg(2), {"calls": [call("stock_levels", status=200)]}) == (WORKS, "answered", "stock_levels")
    assert filed(msg(3), {"calls": [call("send_report", status="sent to their WhatsApp")]}) == (WORKS, "sent", "send_report")


def test_plumbing_calls_are_never_what_a_message_was_about():
    turn = {"calls": [call("open_tools", status="opened"), call("purchase_orders", status=200)]}
    assert filed(msg(1), turn) == (WORKS, "answered", "purchase_orders")


def test_a_refusal_the_model_recovered_from_is_filed_under_what_worked():
    turn = {"calls": [call("record_receipt", error="'Tata steel' is not in the company's material list."),
                      call("add_material", status="ready, NOT saved")]}
    assert filed(msg(1), turn) == (WORKS, "ready", "add_material")


def test_a_question_for_the_person_is_not_a_failure():
    held = {"calls": [call("record_receipt", status="held: the code asks which site")], "asked": "Which site?"}
    assert filed(msg(1), held) == (WORKS, "asked", "record_receipt")
    refused_with_a_question = {"calls": [call("record_usage", error="Which site is this for? Nothing is prepared.")]}
    assert filed(msg(2), refused_with_a_question) == (WORKS, "asked", "record_usage")


def test_a_duplicate_the_code_blocked_is_working_as_meant():
    turn = {"calls": [call("record_usage", error="Already saved at 13:25: 50 bags Cement used.")]}
    assert filed(msg(1), turn) == (WORKS, "duplicate", "record_usage")


def test_a_save_tap_is_filed_under_the_tool_it_saved():
    turn = {"calls": [], "save_results": [{"tool": "record_attendance", "status": 201, "summary": "5 masons"}]}
    assert filed(msg(1, "Save", kind="interactive"), turn) == (WORKS, "saved", "record_attendance")


def test_a_tap_the_code_answers_with_no_turn_works():
    assert filed(msg(1, "7 pm", kind="interactive"), None) == (WORKS, "tapped", None)


# ── what counts as broken ───────────────────────────────────────────────────


def test_a_failed_message_and_an_outage_are_broken_whatever_else_the_turn_holds():
    assert filed(msg(1, status="failed", reply=None, error_code="AI_UNAVAILABLE"), None) == (BROKEN, "failed", None)
    out = classify(msg(2), {"outage": True, "calls": [call("stock_levels", status=200)]}, now=NOW)
    assert (out["state"], out["section"], out["reason"]) == (BROKEN, "failed", "AI outage")


def test_a_message_nobody_answered_is_broken_once_it_is_old_enough():
    assert filed(msg(1, status="pending", reply=None, minutes_ago=30), None) == (BROKEN, "no_reply", None)
    assert classify(msg(2, status="pending", reply=None, minutes_ago=1), None, now=NOW) is None  # still answering


def test_a_refusal_with_nothing_else_is_broken_and_keeps_its_reason():
    turn = {"calls": [call("record_receipt", error="'TMT bars' is not in the company's material list. Nothing is prepared.")]}
    out = classify(msg(1), turn, now=NOW)
    assert (out["state"], out["outcome"]) == (BROKEN, "refused")
    assert out["reason"] == "… is not in the company's material list."
    assert filed(msg(2), {"calls": [call("list_issues", status=422)]})[:2] == (BROKEN, "refused")
    assert filed(msg(3), {"calls": [call("period_report", status="unavailable")]})[:2] == (BROKEN, "refused")


def test_a_save_that_did_not_save_is_broken_even_when_another_line_saved():
    turn = {"save_results": [{"tool": "record_receipt", "status": 201},
                             {"tool": "send_report_to", "status": 422, "reason": "Input should be a valid UUID"}]}
    assert filed(msg(1, "Save", kind="interactive"), turn) == (BROKEN, "save_failed", "send_report_to")


def test_what_mesiri_cannot_do_yet_is_broken_even_when_the_rest_of_the_message_worked():
    tell = {"tool": "tell_the_team", "args": {"kind": "missing_feature", "about": "add a member from WhatsApp"},
            "result": {"status": "Passed to the team."}}
    out = classify(msg(1), {"calls": [call("record_attendance", status="ready, NOT saved"), tell]}, now=NOW)
    assert (out["state"], out["outcome"], out["section"]) == (BROKEN, "cannot_yet", "feedback")
    assert out["note"] == "add a member from WhatsApp"


def test_an_idea_next_to_real_work_is_filed_under_the_work():
    tell = {"tool": "tell_the_team", "args": {"kind": "idea", "about": "a darker card"}, "result": {}}
    assert filed(msg(1), {"calls": [tell]}) == (UNSURE, "idea", "tell_the_team")
    assert filed(msg(2), {"calls": [tell, call("stock_levels", status=200)]}) == (WORKS, "answered", "stock_levels")


def test_a_reply_the_code_had_to_correct_with_nothing_done_is_broken():
    assert filed(msg(1), {"calls": [], "reply_fixed": True, "stop_reason": "answered"})[:2] == (BROKEN, "corrected")


# ── what is left as "not sure" ──────────────────────────────────────────────


def test_talk_a_cancel_and_a_message_with_no_record_are_not_judged():
    assert filed(msg(1, "hi"), {"calls": [], "stop_reason": "answered"})[:2] == (UNSURE, "replied")
    assert filed(msg(2, "Cancel", kind="interactive"), {"calls": [], "cancelled": True})[:2] == (UNSURE, "cancelled")
    assert filed(msg(3), None)[:2] == (UNSURE, "unknown")


def test_a_message_while_a_card_waits_is_filed_under_the_card():
    out = classify(msg(1, "ok"), {"calls": [], "pending": [{"tool": "record_receipt"}]}, now=NOW)
    assert (out["state"], out["outcome"], out["section"]) == (WORKS, "ready", "card")


# ── sections, reasons, grouping ─────────────────────────────────────────────


def test_a_tool_is_placed_by_its_api_route_and_code_tools_by_the_table():
    assert section_of("record_receipt") == "materials"
    assert section_of("record_attendance") == "labour"
    assert section_of("send_dpr") == section_of("period_report") == section_of("send_report") == "reports"
    assert section_of("tell_the_team") == "feedback"
    assert section_of("a_tool_that_does_not_exist") == section_of(None) == "other"


def test_every_tool_of_the_assistant_has_a_named_section():
    """A route added to ALLOWED under a new first path part must get a name here, not fall into "other"."""
    from admin.message_map import SECTIONS
    from agent_api.tools import ALLOWED

    missing = sorted({a.path.strip("/").split("/")[0] for a in ALLOWED} - set(SECTIONS))
    assert missing == []


def test_reason_kind_drops_the_particulars_but_not_an_apostrophe_word():
    assert reason_kind("'എം സാൻഡ്' is not in the company's material list. Nothing is prepared.") == (
        "… is not in the company's material list.")
    assert reason_kind("the API answered 422") == "the API answered 422"
    assert reason_kind("Already saved at 13:25: 50 bags") == "Already saved at N: N bags"


def test_build_map_groups_the_same_kind_and_counts_a_repeated_message_once():
    ready = {"calls": [call("record_receipt", status="ready, NOT saved")]}
    messages = [
        msg(1, "20 bag cement vannu", minutes_ago=50),
        msg(2, "20 Bag  cement vannu", minutes_ago=40, kind="voice", sender="919000005678"),
        msg(3, "steel 2 ton vannu", minutes_ago=30),
        msg(4, status="failed", reply=None, error_code="AI_UNAVAILABLE", minutes_ago=20),
        msg(5, status="pending", reply=None, minutes_ago=0),  # still answering: not counted
    ]
    out = build_map(messages, {"cor_1": ready, "cor_2": ready, "cor_3": ready}, now=NOW)

    assert out["totals"] == {"messages": 4, WORKS: 3, BROKEN: 1, UNSURE: 0, "people": 2}
    materials = next(s for s in out["sections"] if s["key"] == "materials")
    assert (materials["label"], materials[WORKS], materials[BROKEN]) == ("Materials and stock", 3, 0)
    (group,) = materials["groups"]
    assert (group["title"], group["outcome"], group["count"], group["people"]) == ("Record receipt", "ready", 3, 2)
    assert group["how"] == {"text": 2, "voice": 1}
    assert group["companies"] == ["Acme Builders"]
    assert [(e["text"], e["times"]) for e in group["examples"]] == [("steel 2 ton vannu", 1), ("20 Bag  cement vannu", 2)]
    newest = group["examples"][1]
    assert (newest["sender"], newest["role"], newest["phone_tail"], newest["type"]) == ("Ravi", "SITE_ENGINEER", "5678", "voice")
    failed = next(s for s in out["sections"] if s["key"] == "failed")
    assert failed["groups"][0]["reason"] == "AI_UNAVAILABLE"


def test_every_tap_is_its_own_example():
    saved = {"save_results": [{"tool": "record_receipt", "status": 201, "summary": "20 bags Cement"}]}
    messages = [msg(n, "Save", kind="interactive", minutes_ago=n) for n in (1, 2, 3)]
    out = build_map(messages, {f"cor_{n}": saved for n in (1, 2, 3)}, now=NOW)
    assert len(out["sections"][0]["groups"][0]["examples"]) == 3


def test_build_thread_is_the_conversation_around_the_message_and_says_what_was_done():
    messages = [
        msg(1, "old talk", minutes_ago=300),  # more than 30 minutes before the next: another conversation
        msg(2, "20 bag cement vannu", minutes_ago=60),
        msg(3, "Save", kind="interactive", minutes_ago=59),
        msg(4, "next day", minutes_ago=5),
    ]
    turns = {
        "cor_2": {"calls": [call("record_receipt", status="ready, NOT saved")]},
        "cor_3": {"save_results": [{"tool": "record_receipt", "status": 201, "summary": "20 bags Cement"}]},
    }
    thread = build_thread(messages, turns, message_id=messages[1]["id"], now=NOW)
    assert [(t["text"], t["selected"]) for t in thread] == [("20 bag cement vannu", True), ("Save", False)]
    assert thread[0]["did"] == ["Record receipt: ready, NOT saved"]
    assert thread[1]["did"] == ["Saved: 20 bags Cement"]
    assert build_thread(messages, turns, message_id="missing", now=NOW) == []


def test_two_lines_of_the_same_kind_in_one_turn_are_said_once_with_the_count():
    ready = call("record_receipt", status="ready, NOT saved")
    thread = build_thread([msg(1)], {"cor_1": {"calls": [ready, ready]}}, message_id=msg(1)["id"], now=NOW)
    assert thread[0]["did"] == ["Record receipt: ready, NOT saved (×2)"]


# ── the routes ──────────────────────────────────────────────────────────────


@dataclass
class FakeMessageLogger:
    rows: list[dict[str, Any]] = field(default_factory=list)
    asked: dict[str, Any] = field(default_factory=dict)

    async def list_for_map(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.asked = kwargs
        return self.rows

    async def list_around(self, message_id: Any, **_: Any) -> list[dict[str, Any]]:
        return [r for r in self.rows if any(str(x["id"]) == str(message_id) for x in self.rows)]


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


async def test_the_page_is_for_platform_admins_only():
    client, _ = _client([], {})
    async with client:
        assert (await client.get("/admin/message-map")).status_code == 401
        tenant_admin = {"Authorization": f"Bearer {_token(role='ADMIN', org='org_1')}"}
        assert (await client.get("/admin/message-map", headers=tenant_admin)).status_code == 403
        some_id = "00000000-0000-4000-8000-000000000001"
        assert (await client.get(f"/admin/message-map/thread/{some_id}", headers=tenant_admin)).status_code == 403


async def test_the_map_and_the_thread_are_served_to_a_platform_admin():
    now = datetime.now(UTC)
    rows = [{**msg(1), "received_at": now - timedelta(minutes=20), "processed_at": now - timedelta(minutes=20)}]
    client, logger = _client(rows, {"cor_1": {"calls": [call("record_receipt", status="ready, NOT saved")]}})
    admin = {"Authorization": f"Bearer {_token(role='ADMIN', org=None)}"}
    async with client:
        resp = await client.get("/admin/message-map?days=7", headers=admin)
        assert resp.status_code == 200
        body = resp.json()
        assert body["window"]["days"] == 7 and body["truncated"] is False
        assert body["totals"]["works"] == 1
        assert body["sections"][0]["groups"][0]["examples"][0]["text"] == "20 bag cement vannu"
        assert logger.asked["organization_id"] is None and logger.asked["limit"] == 5001

        thread = await client.get(f"/admin/message-map/thread/{rows[0]['id']}", headers=admin)
        assert thread.status_code == 200
        assert thread.json()["messages"][0]["selected"] is True
        assert thread.json()["company"] == "Acme Builders"

        missing = await client.get("/admin/message-map/thread/00000000-0000-4000-8000-000000000099", headers=admin)
        assert missing.status_code == 404
        assert (await client.get("/admin/message-map?days=90", headers=admin)).status_code == 422
