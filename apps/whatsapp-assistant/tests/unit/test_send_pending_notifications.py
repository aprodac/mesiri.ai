"""runtime/send_pending_notifications.py -- the pure row -> message mapping
(#9 Notifications). Everything else in that module needs a live DB and
real WhatsApp credentials, so it is not covered here."""

from __future__ import annotations

from runtime.send_pending_notifications import _render


def _row(rule_key: str, payload: dict | None = None) -> dict:
    return {"rule_key": rule_key, "payload": payload or {}}


def test_stuck_confirmation_has_a_specific_message():
    text = _render(_row("stuck_confirmation"))
    assert "waiting" in text.lower() or "yes" in text.lower()


def test_unknown_rule_key_falls_back_to_a_generic_message():
    text = _render(_row("some_future_rule_key"))
    assert "pending item" in text.lower()


def test_automation_rule_key_renders_from_its_own_payload_message():
    text = _render(_row("automation:11111111-1111-4111-8111-111111111111", {"message": "Reminder: submit today's report."}))
    assert text == "Reminder: submit today's report."


def test_project_dpr_send_rows_use_their_own_message():
    # Before WA-12 these fell through to the generic line (BE-16 bug).
    text = _render(_row("project_dpr_send:p1", {"message": "Today's DPR (DPR-P-1) is attached."}))
    assert text == "Today's DPR (DPR-P-1) is attached."


def test_automation_rule_key_with_no_message_falls_back_to_generic():
    text = _render(_row("automation:11111111-1111-4111-8111-111111111111", {}))
    assert "pending item" in text.lower()
