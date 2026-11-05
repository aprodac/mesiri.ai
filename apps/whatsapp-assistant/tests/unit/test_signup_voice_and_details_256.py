"""[256] (5 Nov, a new prospect, 12:46-12:56): sign-up refused voice notes ("Please type the answer"), refused a full
project description ("keep it under 120 characters") and saved "We are rolla builders" as the company name. Four
dead ends in ten minutes, and the project's details were thrown away.

Now a voice answer is heard (the assistant's own transcription), a long answer is read once for the name in it and
the rest kept as the project's details (shown on the confirm card and saved on the project), and a short answer
loses its lead-in ("We are ..."). Guards: a short typed name is saved as typed with no model call; nothing is
created before "Looks good"; without a transcriber or a model, sign-up works as before.
"""

from __future__ import annotations

import json

import pytest
from tests.unit.test_signup_journey import _tap, _text, _voice
from tests.unit.test_signup_journey import journey as _journey  # noqa: F401 -- the fixture

from runtime import signup_journey as sj

DESCRIPTION = ("we are building a new commercial building in Kerala, a supermarket, ground plus first floor, about "
               "7,000 sqft, complete turnkey contract, construction not started yet")


class _AI:
    def __init__(self, answer: dict | None = None, *, error: bool = False) -> None:
        self.answer = answer or {}
        self.error = error
        self.calls: list[str] = []

    async def generate_json(self, system_prompt: str, user_prompt: str, *, correlation_id=None) -> str:
        self.calls.append(user_prompt)
        if self.error:
            raise RuntimeError("model down")
        return json.dumps(self.answer)


@pytest.fixture
def journey(_journey):  # noqa: F811
    return _journey


def _with(journey, *, heard: str | None = None, ai: _AI | None = None):
    async def transcribe(message):
        if heard is None:
            raise RuntimeError("no audio")
        return heard, heard, "English"

    journey.j._transcribe = transcribe
    journey.j._ai = ai
    return journey


async def _start(journey) -> None:
    await journey.j.handle(_tap(sj.START_TRIAL_ID))


async def test_a_voice_answer_is_heard_like_a_typed_one(journey) -> None:
    _with(journey, heard="Rolla Builders")
    await _start(journey)
    assert await journey.j.handle(_voice()) == sj.ASK_SITE
    await journey.j.handle(_text("Supermarket, Kochi"))
    await journey.j.handle(_tap(sj.CONFIRM_ID))
    assert journey.created_with[0].name == "Rolla Builders"


async def test_a_voice_answer_that_cannot_be_heard_says_so(journey) -> None:
    _with(journey, heard=None)
    await _start(journey)
    reply = await journey.j.handle(_voice())
    assert reply.startswith("Sorry, I couldn't hear that") and sj.ASK_COMPANY in reply
    assert "type the answer" not in reply.lower()


async def test_a_long_description_keeps_the_details_and_asks_only_for_the_name(journey) -> None:
    ai = _AI({"company_name": None, "site_name": None,
              "description": "New commercial building (supermarket) in Kerala, G+1, about 7,000 sqft; turnkey."})
    _with(journey, ai=ai)
    await _start(journey)
    reply = await journey.j.handle(_text(DESCRIPTION))
    assert reply == sj.DETAILS_KEPT_MESSAGE.format(question=sj.ASK_COMPANY)
    assert await journey.j.handle(_text("We are rolla builders")) == sj.ASK_SITE
    confirm = await journey.j.handle(_text("Supermarket, Kerala"))
    assert "*Company:* Rolla Builders" in confirm and "*Project details:* New commercial building" in confirm
    await journey.j.handle(_tap(sj.CONFIRM_ID))
    new = journey.created_with[0]
    assert new.name == "Rolla Builders" and new.project_description.startswith("New commercial building")
    assert len(ai.calls) == 1  # the short answers needed no model call


async def test_a_long_answer_with_the_name_and_the_site_skips_the_site_question(journey) -> None:
    ai = _AI({"company_name": "Rolla Builders", "site_name": "Supermarket, Kerala", "description": "G+1 supermarket"})
    _with(journey, ai=ai)
    await _start(journey)
    confirm = await journey.j.handle(_text("we are rolla builders, building a G+1 supermarket in Kerala now"))
    assert "*Company:* Rolla Builders" in confirm and "*Site:* Supermarket, Kerala" in confirm
    assert journey.created_with == []  # nothing is created before "Looks good"


async def test_a_long_voice_answer_is_read_too(journey) -> None:
    ai = _AI({"company_name": "Rolla Builders", "site_name": None, "description": "Supermarket, G+1"})
    _with(journey, heard="our company is rolla builders and we are doing a supermarket ground plus one", ai=ai)
    await _start(journey)
    assert await journey.j.handle(_voice()) == sj.ASK_SITE


@pytest.mark.parametrize(("said", "name"), [
    ("We are rolla builders", "Rolla Builders"),
    ("Company name is Suresh Builders", "Suresh Builders"),
    ("our company is ABC infra", "ABC infra"),
    ("Suresh Builders", "Suresh Builders"),
    ("KMR Constructions Pvt Ltd", "KMR Constructions Pvt Ltd"),
])
def test_a_short_answer_loses_its_lead_in(said: str, name: str) -> None:
    assert sj._name_only(said, "company") == name


def test_site_and_owner_lead_ins() -> None:
    assert sj._name_only("site is Green Villa, Kakkanad", "site") == "Green Villa, Kakkanad"
    assert sj._name_only("my name is asha", "owner_name") == "Asha"


# -- guards -------------------------------------------------------------------------------------------------------


async def test_guard_a_short_typed_name_makes_no_model_call(journey) -> None:
    ai = _AI({"company_name": "Wrong"})
    _with(journey, ai=ai)
    await _start(journey)
    assert await journey.j.handle(_text("Suresh Builders")) == sj.ASK_SITE
    assert ai.calls == []


async def test_guard_a_model_that_fails_leaves_the_old_check(journey) -> None:
    _with(journey, ai=_AI(error=True))
    await _start(journey)
    reply = await journey.j.handle(_text(DESCRIPTION))
    assert "doesn't look like a company name" in reply or "a bit long" in reply


async def test_guard_without_a_transcriber_a_voice_answer_asks_to_type(journey) -> None:
    journey.j._transcribe = None
    await _start(journey)
    reply = await journey.j.handle(_voice())
    assert reply == sj.TYPE_IT_MESSAGE.format(question=sj.ASK_COMPANY)

