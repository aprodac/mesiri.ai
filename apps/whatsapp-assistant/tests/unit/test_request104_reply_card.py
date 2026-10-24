"""Request 104: the real reply path puts the Send / Save card under a reply
whose only item is a pending action (nothing was saved as a draft)."""

from __future__ import annotations

import functools

import pytest
from tests.unit.request104_fakes import ENGINEER, FakeActions
from tests.unit.test_agent_routing import _build, _message

import runtime.message_journey as mj
from mesiri_ai.fakes import FakeToolCallingProvider
from runtime.agent import save_button as sb
from runtime.agent.action_entry import ActionEntry
from runtime.agent.actions import ENGINEER_QUESTION, new_action


@pytest.fixture
def actions(monkeypatch):  # noqa: ANN001, ANN201
    service = FakeActions(people=[ENGINEER])
    built = mj.build_message_handlers

    @functools.wraps(built)
    def with_actions(**kw):  # noqa: ANN003, ANN202
        return built(**kw, actions=service)

    async def prepare(self, message, understanding, candidate):  # noqa: ANN001, ANN202
        return new_action(ENGINEER_QUESTION, {"question": "When will the drawings come?", "recipients": [dict(ENGINEER)], "asker": "Ravi"}, "Send to engineer: When will the drawings come?")

    monkeypatch.setattr(mj, "build_message_handlers", with_actions)
    monkeypatch.setattr(ActionEntry, "prepare", prepare)
    return service


async def test_an_engineer_question_goes_out_as_a_send_card(monkeypatch, actions):
    provider = FakeToolCallingProvider(
        [
            [("note_for_engineer", {"question": "When will the drawings come?"})],
            "I can send your question about the drawings. Check it and tap Send.",
        ]
    )
    on_normalized, deps, _ = _build(monkeypatch, mode="agent", provider=provider)
    await on_normalized(_message("ask the engineer when the drawings will come"), {})

    sent = deps["sender"].send_button.await_args
    assert "📝 Send to engineer: When will the drawings come?" in sent.kwargs["body"]
    assert [b.title for b in sent.kwargs["buttons"]] == [sb.SEND_TITLE, sb.CANCEL_TITLE]
    assert sent.kwargs["buttons"][0].id.startswith("agt:save:x")
    assert actions.delivered == []  # nothing is sent before the tap


async def test_the_send_tap_messages_the_engineer_and_says_who(monkeypatch, actions):
    from types import SimpleNamespace

    from mesiri_contracts.assistant.enums import InputModality

    provider = FakeToolCallingProvider(
        [[("note_for_engineer", {"question": "When will the drawings come?"})], "Check it and tap Send."]
    )
    on_normalized, deps, _ = _build(monkeypatch, mode="agent", provider=provider)
    same_sender = SimpleNamespace(
        organization_id="00000000-0000-4000-8000-0000000000aa",
        org_active=True,
        user_id="00000000-0000-4000-8000-0000000000bb",
        full_name="Ravi",
        role="SUPERVISOR",
        org_name="Acme",
        projects=[],
        sites=[],
    )

    async def resolve(_reader, _wa_id):  # noqa: ANN001, ANN202
        return same_sender

    monkeypatch.setattr(mj, "resolve_sender", resolve)
    await on_normalized(_message("ask the engineer when the drawings will come"), {})
    save_id = deps["sender"].send_button.await_args.kwargs["buttons"][0].id

    tap = _message(sb.SEND_TITLE, modality=InputModality.INTERACTIVE).model_copy(
        update={"metadata": {"interactive_reply_id": save_id, "interactive_reply_type": "button_reply"}}
    )
    await on_normalized(tap, {})

    assert [p["name"] for p in actions.delivered] == ["Ravi"]
    texts = [c.args[1] for c in deps["sender"].send_text.await_args_list]
    assert any(t.startswith("✅ Sent to Ravi (site engineer)") for t in texts), texts
