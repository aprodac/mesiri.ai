"""SA-37: an announcement's delivery through the shared notification sender.

Inside the 24-hour window it goes at once, pictures first and the words last. Outside it, with no approved
template, it is not skipped: it waits for the person's next message (status waiting_window, out of the pending
queue) and goes on the first drain after it, or is skipped once older than its hold. With the template approved,
the template goes once and the full message still waits for their reply. Guard: any other notification outside
the window without a template is still skipped, as before.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from mesiri.application.notifications import checks
from runtime import notification_query
from runtime.send_pending_notifications import drain_and_send

NOW = datetime(2026, 11, 7, 6, 0, tzinfo=UTC)  # 11:30 in India: not quiet hours anyway
PAYLOAD = {"message": "*New in Mesiri: Material Requests*", "images": ["announcements/a/1.png", "announcements/a/2.png"],
           "hold_until_window": True, "hold_days": 7,
           "template": {"name": "mesiri_product_update", "body_params": ["Material Requests"]}}


class _Sender:
    def __init__(self) -> None:
        self.sent: list[tuple] = []

    async def send_text(self, wa_id, text, **_):
        self.sent.append(("text", text))
        return True

    async def send_image(self, wa_id, data, *, caption=None, filename="x.png", shows=None):
        self.sent.append(("image", data))
        return True

    async def send_template(self, wa_id, **kwargs):
        self.sent.append(("template", kwargs["name"], tuple(kwargs["body_params"])))
        return True


class _Storage:
    async def get_object(self, key):
        return SimpleNamespace(data=key.encode())


@pytest.fixture
def queue(monkeypatch):
    state = {"rows": {}, "last_inbound": None}

    def rows(status):
        return [r for r in state["rows"].values() if r["status"] == status]

    class _Queue:
        def __init__(self, db, actor_reader):
            pass

        async def list_pending(self):
            return rows("pending")

        async def list_waiting_window(self):
            return rows("waiting_window")

        async def set_waiting(self, *, notification_id, waiting, payload=None):
            row = state["rows"][notification_id]
            row["status"] = "waiting_window" if waiting else "pending"
            if payload is not None:
                row["payload"] = payload

        async def resolve_recipient_wa_id(self, user_id):
            return "919999999999"

        async def consent_state(self, *, organization_id, wa_id):
            return None

        async def timezone_for(self, *, organization_id, project_id):
            return "Asia/Kolkata"

        async def last_inbound_at(self, wa_id):
            return state["last_inbound"]

        async def is_test_company(self, organization_id):
            return False

        async def mark_sent(self, *, notification_id):
            state["rows"][notification_id]["status"] = "sent"

        async def mark_skipped(self, *, notification_id, reason):
            state["rows"][notification_id].update(status="skipped", skip_reason=reason)

    monkeypatch.setattr(notification_query, "NotificationSendQueueService", _Queue)
    monkeypatch.setattr(checks, "is_quiet_hours", lambda *, local_now: False)
    return state


def _add(state, *, rule_key="announcement", payload=PAYLOAD, created=NOW - timedelta(hours=1), status="pending"):
    nid = f"n{len(state['rows']) + 1}"
    state["rows"][nid] = {"id": nid, "organization_id": "org1", "project_id": None, "rule_key": rule_key,
                          "subject_id": f"a:{nid}", "recipient_user_id": "u1", "payload": dict(payload),
                          "created_at": created, "status": status}
    return nid


async def _drain(sender, approved=frozenset(), now=NOW):
    return await drain_and_send(db=None, actor_reader=None, sender=sender, object_storage=_Storage(),
                                approved_templates=approved, now_utc=now)


async def test_inside_the_window_pictures_go_first_then_the_words(queue):
    nid = _add(queue)
    queue["last_inbound"] = NOW - timedelta(hours=2)
    sender = _Sender()
    assert await _drain(sender) == {"sent": 1, "skipped": 0}
    assert [s[0] for s in sender.sent] == ["image", "image", "text"]
    assert sender.sent[-1][1] == "*New in Mesiri: Material Requests*"
    assert queue["rows"][nid]["status"] == "sent"


async def test_outside_the_window_it_waits_for_their_next_message_then_goes(queue):
    nid = _add(queue)
    queue["last_inbound"] = NOW - timedelta(days=3)
    sender = _Sender()
    assert await _drain(sender) == {"sent": 0, "skipped": 0}
    assert sender.sent == [] and queue["rows"][nid]["status"] == "waiting_window"
    # Still quiet: nothing on the next tick either.
    await _drain(sender)
    assert sender.sent == []
    # They message Mesiri: the next drain releases it and sends it in the same tick.
    queue["last_inbound"] = NOW - timedelta(minutes=1)
    assert await _drain(sender) == {"sent": 1, "skipped": 0}
    assert [s[0] for s in sender.sent] == ["image", "image", "text"]
    assert queue["rows"][nid]["status"] == "sent"


async def test_a_held_message_older_than_its_hold_is_skipped_with_the_reason(queue):
    nid = _add(queue, created=NOW - timedelta(days=8), status="waiting_window")
    queue["last_inbound"] = NOW - timedelta(minutes=1)
    sender = _Sender()
    await _drain(sender)
    assert sender.sent == []
    assert (queue["rows"][nid]["status"], queue["rows"][nid]["skip_reason"]) == ("skipped", "expired_waiting_for_window")


async def test_with_the_template_approved_it_goes_once_and_the_message_follows_their_reply(queue):
    nid = _add(queue)
    queue["last_inbound"] = NOW - timedelta(days=3)
    sender = _Sender()
    approved = frozenset({"mesiri_product_update"})
    assert await _drain(sender, approved) == {"sent": 1, "skipped": 0}
    assert sender.sent == [("template", "mesiri_product_update", ("Material Requests",))]
    assert queue["rows"][nid]["status"] == "waiting_window"
    await _drain(sender, approved)  # no second template
    assert len(sender.sent) == 1
    queue["last_inbound"] = NOW - timedelta(minutes=1)
    await _drain(sender, approved)
    assert [s[0] for s in sender.sent] == ["template", "image", "image", "text"]


async def test_guard_other_notifications_outside_the_window_are_still_skipped(queue):
    nid = _add(queue, rule_key="stuck_confirmation", payload={"message": "Waiting for your Save"})
    queue["last_inbound"] = NOW - timedelta(days=3)
    sender = _Sender()
    assert await _drain(sender) == {"sent": 0, "skipped": 1}
    assert queue["rows"][nid]["status"] == "skipped"
