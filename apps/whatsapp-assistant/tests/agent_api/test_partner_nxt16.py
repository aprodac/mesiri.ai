"""NXT-16 (option B, approved by Alan 8 Nov 2026): a subcontractor's contact on WhatsApp gets only the /partner routes.

Guards: the partner tool list never holds a staff route, the staff list never holds a /partner route; what they send
is said as waiting for the company, never as approved or paid; a staff member's number never reaches the partner path
(it is asked only in the unregistered branch)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from agent_api.partner import PARTNER_ALLOWED, PARTNER_SOP, _with_results
from agent_api.tools import ALLOWED

JOURNEY = (Path(__file__).resolve().parents[2] / "src/runtime/message_journey.py").read_text(encoding="utf-8")


def test_partner_tools_are_only_partner_routes_and_staff_tools_never_are() -> None:
    assert PARTNER_ALLOWED and all(a.path.startswith("/partner/") for a in PARTNER_ALLOWED)
    assert not any(a.path.startswith("/partner") for a in ALLOWED)


def test_the_sop_never_promises_approval_or_payment() -> None:
    assert "never that it is approved or paid" in PARTNER_SOP
    assert "Never promise a payment date" in PARTNER_SOP


def test_sent_lines_come_from_the_api_and_save_talk_is_dropped() -> None:
    ok = SimpleNamespace(ok=True, body={"ref": "RA-3", "work_order": "WO-0003", "amount": "15200.00",
                                        "check": ["billed 6 cum more than measured on Concreting M20"]})
    out = _with_results("Your bill is ready. Tap Save to send it.", [ok])
    assert "Tap Save" not in out and "RA-3" in out and "waits for the company's check" in out and "6 cum" in out
    refused = SimpleNamespace(ok=False, body={"detail": "Work order not found"})
    assert "Not sent: Work order not found" in _with_results("", [refused])


def test_guard_partner_path_only_for_numbers_that_are_not_staff() -> None:
    unregistered = JOURNEY.index("_partner_for()")
    assert JOURNEY.index("reply = unregistered_message(wa_id)") > unregistered
    assert "partner.reply_failed" in JOURNEY  # a failure falls back to the usual path, never a dead end


def test_the_partner_tools_resolve_against_the_agent_api() -> None:
    from agent_api.app import build_api_app
    from agent_api.tools import build_tools

    tools = build_tools(build_api_app(None).openapi(), PARTNER_ALLOWED)
    assert set(tools) == {a.name for a in PARTNER_ALLOWED}
