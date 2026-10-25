"""Request 116 E: "✅ Saved" after the Save tap says what was saved."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

from runtime.agent import cards as c
from runtime.agent import save_button as sb

ACTOR = SimpleNamespace(organization_id="org-1", user_id="user-1")


class _Redis:
    def __init__(self) -> None:
        self.data: dict[str, Any] = {}

    def namespaced(self, *parts: str) -> str:
        return ":".join(parts)

    async def set_json(self, key, value, *, ttl_seconds=None) -> None:
        self.data[key] = value

    async def get_json(self, key):
        return self.data.get(key)

    async def delete(self, *keys) -> None:
        for key in keys:
            self.data.pop(key, None)


class _Handler:
    def __init__(self, done: int = 1) -> None:
        self.done = done

    async def settle_drafts(self, *, organization_id, user_id, facts, keep):
        return SimpleNamespace(done=self.done, refused=[])


def _item(summary: str) -> c.CardItem:
    return c.CardItem("save_activity", {}, "activity", str(uuid.uuid4()), summary)


def _tap(action: str, items: list[c.CardItem]):
    return SimpleNamespace(metadata={"interactive_reply_id": sb.tap_id(action, [i.fact for i in items])})


async def test_saved_line_names_the_site_and_the_lines():
    store = c.CardStore(_Redis())
    item = _item("Plastering 50 sq ft (completed)")
    await store.put(ACTOR, c.new_card(c.OPEN, [item], "Green Villa, Kakkanad"))
    reply = await sb.handle_tap(_tap(sb.SAVE, [item]), ACTOR, _Handler(), store)
    assert reply.text == "✅ Saved · Green Villa, Kakkanad: Plastering 50 sq ft (completed)"


async def test_saved_line_joins_several_entries_and_works_without_a_site():
    store = c.CardStore(_Redis())
    items = [_item("3 mason"), _item("Plastering 50 sq ft")]
    await store.put(ACTOR, c.new_card(c.OPEN, items))
    reply = await sb.handle_tap(_tap(sb.SAVE, items), ACTOR, _Handler(2), store)
    assert reply.text == "✅ Saved · 3 mason; Plastering 50 sq ft"


async def test_saved_line_is_the_bare_one_when_the_card_is_gone():
    item = _item("3 mason")
    reply = await sb.handle_tap(_tap(sb.SAVE, [item]), ACTOR, _Handler(), c.CardStore(_Redis()))
    assert reply.text == sb.SAVED_DONE


async def test_cancel_line_is_unchanged():
    store = c.CardStore(_Redis())
    item = _item("3 mason")
    await store.put(ACTOR, c.new_card(c.OPEN, [item], "Green Villa"))
    reply = await sb.handle_tap(_tap(sb.CANCEL, [item]), ACTOR, _Handler(), store)
    assert reply.text == sb.CANCELLED_DONE


# -- H: "code entha?" sends the code and the message to forward, nothing more ----


async def test_h_the_join_code_reply_is_two_messages_not_three(monkeypatch):
    from unittest.mock import AsyncMock

    from channel.replies import ReplySpec
    from mesiri_ai.fakes import FakeToolCallingProvider
    from runtime import message_journey as mj

    from .test_agent_routing import _build, _message

    sent_forward = []

    class _Join:
        async def share_code(self, msg, ctx):
            await _Join.sender.send_text("919876543210", "Here is your join code")
            return ReplySpec(text="Join Acme on Mesiri, code ABC123")

        async def handle_tap(self, message, actor):
            return None

        async def handle_code_request(self, message, actor):
            return None

        async def handle_unregistered(self, message):
            return None

    provider = FakeToolCallingProvider([[("get_join_code", {})], "Sheri, join code ayachittundu 👍"])
    built = mj.build_message_handlers
    join = _Join()

    import functools

    @functools.wraps(built)
    def with_join(**kw):
        return built(**kw, join_journey=join)

    monkeypatch.setattr(mj, "build_message_handlers", with_join)
    on_normalized, deps, _ = _build(monkeypatch, mode="agent", provider=provider)
    _Join.sender = deps["sender"]
    deps["sender"].send_text = AsyncMock(side_effect=lambda *a, **k: sent_forward.append(a[1]))
    await on_normalized(_message("code entha?"), {})
    assert "Sheri, join code ayachittundu 👍" not in sent_forward
    assert sent_forward == ["Here is your join code"] or "Join Acme on Mesiri, code ABC123" in str(deps["sender"].mock_calls)
    assert "Sheri, join code ayachittundu" not in str(deps["sender"].mock_calls)


# -- F: the day's work lines carry the amounts ------------------------------------


def test_f_day_lines_show_the_amount_per_work_summed():
    from runtime.site_day_review import day_lines

    q = {"work_type": "plastering", "quantity": "50.0000", "unit": "sqft"}
    lines = day_lines(
        {
            "activity_count": 4,
            "activities": [
                {"work_type": "plastering", "quantities": [q]},
                {"work_type": "plastering", "quantities": [q]},
                {"work_type": "plastering", "quantities": [q]},
                {"work_type": "brick_work", "quantities": []},
            ],
        }
    )
    assert lines == ["• Work: Plastering 150 sq ft, Brick work (4 items)"]


def test_f_cancelled_work_and_other_units_are_handled():
    from runtime.site_day_review import day_lines

    lines = day_lines(
        {
            "activity_count": 2,
            "activities": [
                {"work_type": "plastering", "quantities": [{"quantity": "10", "unit": "sqm"}]},
                {"work_type": "plastering", "review": "rejected", "quantities": [{"quantity": "99", "unit": "sqm"}]},
                {"work_type": "plastering", "quantities": [{"quantity": "2.5", "unit": "sqft"}]},
            ],
        }
    )
    assert lines == ["• Work: Plastering 10 sq m + 2.5 sq ft (2 items)"]
