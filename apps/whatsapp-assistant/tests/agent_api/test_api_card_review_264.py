"""WA-264 (Ilan, 8 Nov: "does the ai actually check and see what we are telling to save?"): every line was checked by
code when prepared, but not its MEANING. In his chat "6 rods used" and "one rod is 5 kg" became "5 kg Steel used",
and every check passed.

Now a second AI step reads the conversation, the message and the card's structured lines and says whether each line
records what they meant. Shadow mode: it runs after the reply has gone, adds no time and changes nothing; the verdict
goes to the trace (stage card_review). The code checks the checker: a problem must point at a line on the card and
quote the person's own words.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

from tests.agent_api.standin import two_receipts_model
from tests.agent_api.test_api_preview_card_210 import UPDATE, _stand_in_tools  # noqa: F401
from tests.agent_api.test_api_receipts_132 import CTX, Cards, _message, _service

from agent_api import whatsapp as wa
from agent_api.card_review import checked, conversation, review_card
from mesiri_ai.models import ChatMessage

STEEL_CARD = ["1. 🏗️ Used: *Steel TMT 12mm* · Main block · 5 kg"]
SAID = "Yes, the steel I said was used, is it from Saver? Six steel"
EARLIER = "30 bags of cement arrived, 6 steel rods we used. 5 kg anu"
WRONG = {"verdict": "wrong", "problems": [{"line": 1, "problem": "5 kg is the weight of one rod, not what was used",
                                           "said": "6 steel rods we used", "should_be": "6 nos Steel used"}],
         "question": "6 rod aano use cheythathu?"}


def test_the_reported_size_taken_as_the_quantity_is_found() -> None:
    verdict = checked(json.dumps(WRONG), STEEL_CARD, f"{SAID} {EARLIER}")
    assert verdict.verdict == "wrong" and verdict.problems[0]["line"] == 1 and verdict.question


def test_guard_a_problem_quoting_words_never_said_is_dropped() -> None:
    made_up = dict(WRONG, problems=[dict(WRONG["problems"][0], said="7 rods were used")])
    verdict = checked(json.dumps(made_up), STEEL_CARD, f"{SAID} {EARLIER}")
    assert verdict.verdict == "unsure" and verdict.problems == [] and verdict.dropped == 1


def test_guard_a_problem_on_a_line_not_on_the_card_is_dropped_and_missing_is_line_0() -> None:
    bad = dict(WRONG, problems=[dict(WRONG["problems"][0], line=4),
                                dict(WRONG["problems"][0], line=0, problem="the cement delivery is missing",
                                     said="30 bags of cement arrived")])
    verdict = checked(json.dumps(bad), STEEL_CARD, f"{SAID} {EARLIER}")
    assert [p["line"] for p in verdict.problems] == [0] and verdict.dropped == 1


def test_guard_not_json_or_an_unknown_verdict_is_unsure() -> None:
    assert checked("sorry, I can't", STEEL_CARD, SAID).verdict == "unsure"
    assert checked(json.dumps({"verdict": "maybe"}), STEEL_CARD, SAID).verdict == "unsure"
    assert checked(json.dumps({"verdict": "ok", "problems": WRONG["problems"]}), STEEL_CARD, SAID).problems == []


def test_the_conversation_is_the_latest_turns_without_code_notes() -> None:
    history = [ChatMessage(role="user", text=EARLIER), ChatMessage(role="model", text="(looked it up)"),
               ChatMessage(role="model", text="6 nos Steel Main block-il upayogichu.")]
    assert conversation(history) == [f"Person: {EARLIER}", "Mesiri: 6 nos Steel Main block-il upayogichu."]


class _Checker:
    def __init__(self, answer: str = json.dumps({"verdict": "ok", "problems": [], "question": ""})) -> None:
        self.prompts: list[str] = []
        self.answer = answer

    async def generate_json(self, system_prompt: str, user_prompt: str, *, correlation_id: str | None = None) -> str:
        self.prompts.append(user_prompt)
        return self.answer


async def test_review_card_reads_the_card_the_person_saw_and_their_words() -> None:
    checker = _Checker(json.dumps(WRONG))
    verdict = await review_card(checker, said=SAID, lines=STEEL_CARD,
                                history=[ChatMessage(role="user", text=EARLIER)], organization_id="org")
    sent = json.loads(checker.prompts[0])
    assert sent["CARD"] == STEEL_CARD and sent["THIS_MESSAGE"] == SAID and sent["CONVERSATION"] == [f"Person: {EARLIER}"]
    assert verdict is not None and verdict.verdict == "wrong"


async def test_guard_no_json_call_no_check() -> None:
    assert await review_card(object(), said=SAID, lines=STEEL_CARD, history=[], organization_id="org") is None


class _ModelWithChecker:
    """The tool-calling model of the turn, plus the JSON call the check uses."""

    def __init__(self) -> None:
        self._turns = two_receipts_model()
        self.checker = _Checker()

    async def run_tools(self, *a, **k):  # noqa: ANN002, ANN003, ANN201
        return await self._turns.run_tools(*a, **k)

    async def generate_json(self, *a, **k):  # noqa: ANN002, ANN003, ANN201
        return await self.checker.generate_json(*a, **k)


async def _turn(model: _ModelWithChecker, mode: str = "shadow"):  # noqa: ANN202
    cards, order = Cards(preview=True), []
    service, sent = _service(model, cards, order)
    service._trace = AsyncMock()
    service.__dict__["_card_review_cache"] = {str(CTX.organization_id): (mode, 9e18)}
    await service.handle(_message(UPDATE), CTX)
    await asyncio.gather(*list(wa._BACKGROUND))
    return service, sent


async def test_a_shown_card_is_checked_after_the_reply_and_only_logged() -> None:
    model = _ModelWithChecker()
    service, sent = await _turn(model)
    assert sent[-1].header_image == b"PREVIEW"  # the reply went out as before
    (prompt,) = model.checker.prompts
    assert json.loads(prompt)["CARD"][0].startswith("1. 📥 Delivery: *Cement*")
    stages = [c.kwargs for c in service._trace.log_stage.await_args_list if c.kwargs.get("stage") == "card_review"]
    assert len(stages) == 1 and stages[0]["stage_payload"]["verdict"] == "ok"


async def test_guard_off_means_no_check() -> None:
    model = _ModelWithChecker()
    await _turn(model, mode="off")
    assert model.checker.prompts == []
