"""WA-277 step F (reliability plan step 3, WA-267): what is saved is said by the code, and the card check may ask
before a card goes out.

1. A save made by words ("save cheythoo") was announced in the model's own sentence; only when a line was refused did
   the code's ✅ / ❌ lines go out (WA-260). The same decision had two wordings: the Save button's lines, and whatever
   the model wrote. Now every save by words gets the code's lines, the ones the button gives; the model's words follow
   only when they say something else, with any "saved" taken out.
2. The card check (WA-264) ran only after the reply and only logged. Where the company's ``card_review`` is "ask", it
   runs before the card: a finding the code itself checked (a line on the card, the person's own words quoted) puts
   its ONE question above the card, and that question is the open one for their next message.

Guards: the card and its Save still go out with the question (the check can be wrong); "ok", "unsure", a slow or
failing check leave the reply exactly as it was; "shadow" and "off" are unchanged; a save by the button is unchanged.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

from tests.agent_api.standin import two_receipts_model
from tests.agent_api.test_api_card_review_264 import _ModelWithChecker
from tests.agent_api.test_api_preview_card_210 import UPDATE
from tests.agent_api.test_api_preview_card_210 import _stand_in_tools as _preview_tools  # noqa: F401
from tests.agent_api.test_api_receipts_132 import CTX as CARD_CTX
from tests.agent_api.test_api_receipts_132 import Cards, _service
from tests.agent_api.test_api_receipts_132 import _message as _card_message
from tests.agent_api.test_api_whatsapp_119 import CTX, Harness, _message

from agent_api import whatsapp as wa
from agent_api.agent import SAVE_READY
from mesiri_ai.fakes import FakeToolCallingProvider

LINE_1, LINE_2 = "50 bags cement, Green Villa", "50 TMT bars, Green Villa"
QUESTION = "50 TMT bar aano, 50 kg aano vannathu?"
FINDING = {"verdict": "wrong", "question": QUESTION, "problems": [
    {"line": 2, "problem": "the unit is not what they said", "said": "50 TMT vannu", "should_be": "50 nos TMT"}]}


# 1. The code says what was saved ----------------------------------------------------------------------------------

async def _saved_by_words(model_words: str) -> Harness:
    h = Harness(two_receipts_model())
    await h.service.handle(_message(), CTX)
    h.service._agent._provider = FakeToolCallingProvider([[(SAVE_READY, {})], model_words])
    await h.service.handle(_message("save cheythoo"), CTX)
    return h


async def test_a_save_by_words_is_said_in_the_codes_lines() -> None:
    h = await _saved_by_words("Ellam save cheythu, 50 bags cement um 50 TMT um.")
    text = h.sent[-1].text
    assert h.posts() == 2
    assert f"✅ {LINE_1}" in text and f"✅ {LINE_2}" in text  # the lines the Save button gives
    assert "Ellam save cheythu" not in text  # the model's own "saved" is not a second wording of it


async def test_sibling_whatever_language_the_model_claims_it_in() -> None:
    for words in ("Saved both entries.", "दोनों दर्ज कर दिया।", "രണ്ടും സേവ് ചെയ്തു."):
        h = await _saved_by_words(words)
        assert f"✅ {LINE_1}" in h.sent[-1].text and words not in h.sent[-1].text


async def test_guard_words_about_something_else_follow_the_saved_lines() -> None:
    h = await _saved_by_words("Naale report 9 pm-inu pokum.")
    text = h.sent[-1].text
    assert text.index(f"✅ {LINE_1}") < text.index("Naale report 9 pm-inu pokum.")


async def test_guard_a_save_by_the_button_is_unchanged() -> None:
    h = Harness(two_receipts_model())
    await h.service.handle(_message(), CTX)
    await h.service.handle(_message(None, tap=h.buttons()[0]), CTX)
    assert h.posts() == 2 and f"✅ {LINE_1}" in h.sent[-1].text


# 2. The card check asks before the card ---------------------------------------------------------------------------

async def _card_turn(answer: dict | str, mode: str = "ask", delay: float = 0.0):  # noqa: ANN202
    model = _ModelWithChecker()
    model.checker.answer = answer if isinstance(answer, str) else json.dumps(answer)
    if delay:
        slow = model.checker.generate_json

        async def late(*a, **k):  # noqa: ANN002, ANN003, ANN202
            await asyncio.sleep(delay)
            return await slow(*a, **k)

        model.checker.generate_json = late  # type: ignore[method-assign]
    cards, order = Cards(preview=True), []
    service, sent = _service(model, cards, order)
    service._trace = AsyncMock()
    service.__dict__["_card_review_cache"] = {str(CARD_CTX.organization_id): (mode, 9e18)}
    await service.handle(_card_message(UPDATE), CARD_CTX)
    await asyncio.gather(*list(wa._BACKGROUND))
    return service, sent, model


async def test_a_finding_puts_its_one_question_above_the_card() -> None:
    service, sent, model = await _card_turn(FINDING)
    reply = sent[-1]
    assert reply.text.startswith(f"❓ {QUESTION}")
    assert reply.header_image == b"PREVIEW" and reply.buttons[0].id.startswith(wa.SAVE_PREFIX)  # the card and Save stay
    assert len(model.checker.prompts) == 1  # checked once, before the reply; no second run after it
    state = await service._state(CARD_CTX)
    assert state["asked"] == {"question": QUESTION, "options": []}  # their next message answers THIS question
    stages = [c.kwargs for c in service._trace.log_stage.await_args_list if c.kwargs.get("stage") == "card_review"]
    assert len(stages) == 1 and stages[0]["stage_payload"]["mode"] == "ask"


async def test_guard_ok_and_unsure_leave_the_reply_as_it_was() -> None:
    _, plain, _ = await _card_turn({"verdict": "ok", "problems": [], "question": ""}, mode="off")
    for answer in ({"verdict": "ok", "problems": [], "question": ""}, {"verdict": "unsure", "problems": []},
                   "not json at all"):
        _, sent, _ = await _card_turn(answer)
        assert sent[-1].text == plain[-1].text and "❓" not in sent[-1].text


async def test_guard_a_finding_that_quotes_words_never_said_asks_nothing() -> None:
    made_up = dict(FINDING, problems=[dict(FINDING["problems"][0], said="70 kg steel came")])
    _, sent, _ = await _card_turn(made_up)
    assert "❓" not in sent[-1].text  # the code checks the checker (WA-264)


async def test_guard_a_slow_check_never_holds_the_card(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(wa, "CARD_ASK_SECONDS", 0.05)
    _, sent, _ = await _card_turn(FINDING, delay=0.5)
    assert "❓" not in sent[-1].text and sent[-1].header_image == b"PREVIEW"


async def test_guard_shadow_still_only_logs_after_the_reply() -> None:
    service, sent, model = await _card_turn(FINDING, mode="shadow")
    assert "❓" not in sent[-1].text and len(model.checker.prompts) == 1
    stages = [c.kwargs for c in service._trace.log_stage.await_args_list if c.kwargs.get("stage") == "card_review"]
    assert stages[0]["stage_payload"]["mode"] == "shadow" and stages[0]["stage_payload"]["verdict"] == "wrong"


def test_the_setting_takes_ask() -> None:
    from mesiri.domains.organizations import settings

    assert settings.validate(settings.CARD_REVIEW, "ask") == "ask"
    assert settings.CARD_REVIEW_DEFAULT == "shadow"  # nobody gets it until the team switches it on
