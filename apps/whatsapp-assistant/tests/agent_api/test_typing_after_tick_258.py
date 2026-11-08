"""WA-258 (Ilan, 8 Nov): a voice note showed "typing...", then the ✅ reaction, then NO typing until the reply.

WA-210 showed "typing..." again after the ✅ by repeating the read + typing call on a message already marked read; on
the phone it did not come back. Now a voice note / photo / document gets its ✅ the moment the webhook is claimed,
BEFORE the read + typing call, so "typing..." is the last thing shown; the journey never reacts a second time.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import runtime.message_journey as mj
from mesiri_contracts.assistant.enums import InputModality

VOICE = {"from": "919876543210", "id": "wamid.in.1", "type": "audio", "audio": {"id": "m1"}}


def _claim_handler(monkeypatch):  # noqa: ANN001, ANN202
    from tests.unit.test_reply_composer import _build

    _on, deps, choices, setup = _build(monkeypatch)
    _, mark = mj.build_message_handlers(**deps, offered_choices_store=choices, setup_questions=setup,
                                        user_language_store=None)
    return mark, deps["sender"]


async def test_the_reported_voice_note_gets_its_tick_before_typing(monkeypatch) -> None:  # noqa: ANN001
    mark, sender = _claim_handler(monkeypatch)
    await mark("wamid.in.1", VOICE)
    sender.send_reaction.assert_awaited_once_with("919876543210", "wamid.in.1", "✅")
    names = [c[0] for c in sender.mock_calls]
    assert names.index("send_reaction") < names.index("mark_as_read")  # typing is the last thing shown


async def test_siblings_photo_and_document_too_text_never(monkeypatch) -> None:  # noqa: ANN001
    assert mj.early_ack(dict(VOICE, type="image")) and mj.early_ack(dict(VOICE, type="document"))
    assert not mj.early_ack(dict(VOICE, type="text")) and not mj.early_ack(dict(VOICE, type="interactive"))
    mark, sender = _claim_handler(monkeypatch)
    await mark("wamid.t", {"from": "919876543210", "id": "wamid.t", "type": "text"})
    sender.send_reaction.assert_not_awaited()
    sender.mark_as_read.assert_awaited_once_with("wamid.t")


async def test_guard_a_forwarded_voice_note_gets_no_tick_at_the_webhook(monkeypatch) -> None:  # noqa: ANN001
    """WA-02: a forwarded batch gets one summary, no acks."""
    mark, sender = _claim_handler(monkeypatch)
    await mark("wamid.f", dict(VOICE, context={"forwarded": True}))
    sender.send_reaction.assert_not_awaited()


async def test_guard_a_failed_reaction_still_marks_read(monkeypatch) -> None:  # noqa: ANN001
    mark, sender = _claim_handler(monkeypatch)
    sender.send_reaction.side_effect = RuntimeError("meta down")
    await mark("wamid.in.1", VOICE)
    sender.mark_as_read.assert_awaited_once_with("wamid.in.1")


async def test_the_journey_does_not_react_again_to_a_voice_note(monkeypatch) -> None:  # noqa: ANN001
    from tests.unit.test_reply_composer import _build, _saved_attendance
    from tests.unit.test_reply_composer import _message as _journey_message

    on_normalized, deps, _choices, _setup = _build(monkeypatch)
    deps["interaction_handler"].handle_fast_path.return_value = _saved_attendance()
    deps["sender"].keep_typing = AsyncMock(return_value=False)
    await on_normalized(_journey_message(modality=InputModality.VOICE), {})
    deps["sender"].send_reaction.assert_not_awaited()  # its ✅ went at the webhook
    deps["sender"].keep_typing.assert_awaited()  # "typing..." is still kept up while the reply is worked on
