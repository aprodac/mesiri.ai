"""[219] (3 Nov 17:07, test company): "Rana Mart ennoru puthiya project undaakku" was answered in English with an
apology and an offer to make a second Rana Mart; the next message, "Add Mohanlal to Live Mart B as site engineer", got
"I have two projects named 'Rana Mart'. Which one…?". The question only lived in the chat history, so the model read
any next message as its answer. Now the code keeps the open question and decides: a tap or a reply naming one of its
options (or a short reply: "the second one", "yes") answers it; anything else is a new request and the question is
dropped. A project that already exists is said by the code, in their language, and never offered again."""

from __future__ import annotations

import uuid

from fastapi import FastAPI
from pydantic import BaseModel
from tests.agent_api.standin import ACTOR, PROJECT, SITE, stand_in_api

from agent_api.agent import ApiAgent, Places, answers_question, question_left_open
from agent_api.client import ApiClient
from agent_api.tools import ALLOWED, CONFIRM_ARG, build_tools
from mesiri_ai.fakes import FakeToolCallingProvider

RANA_1, RANA_2 = str(uuid.uuid4()), str(uuid.uuid4())
PLACES = Places(projects=((RANA_1, "Rana Mart"), (RANA_2, "Rana Mart"), (PROJECT, "Live Mart B")),
                sites=((SITE, "Live Mart B main", PROJECT),))
WHICH = {"question": "I have two projects named 'Rana Mart'. Which one?", "options": ["Rana Mart", "Rana Mart (2)"]}
MOHANLAL = "Add Mohanlal to Live Mart B as site engineer"


# -- the code decides whether a message answers the open question ---------------------------------


def test_an_unrelated_request_does_not_answer_the_open_question() -> None:
    assert not answers_question(MOHANLAL, WHICH)
    assert not answers_question("No. " + MOHANLAL, WHICH)
    # siblings: which material / which site / a duplicate's "another one?", then something else (typed or voice)
    assert not answers_question("Add Rajesh to Live Mart B as site engineer",
                                {"question": "Which cement?", "options": ["OPC cement", "PPC cement"]})
    assert not answers_question("innu Live Mart B-il 6 mason undaayirunnu",
                                {"question": "Which site?", "options": ["Green Villa", "Zeta Plaza"]})
    assert not answers_question(MOHANLAL, {"question": "Already saved at 17:07. Another one?", "options": []})


def test_guard_a_tap_an_option_or_a_short_reply_answers_it() -> None:
    assert answers_question("Rana Mart (2)", WHICH)  # a tap comes as the option's title
    assert answers_question("the second one", WHICH)
    assert answers_question("Green Villa", {"question": "Which site?", "options": ["Green Villa", "Zeta Plaza"]})
    assert answers_question("athe", {"question": "Another one?", "options": []})
    assert answers_question("anything at all", None)  # nothing open: nothing to drop


# -- the model is told the question is dropped --------------------------------------------------------


async def _run(model, text: str, open_question):  # noqa: ANN001, ANN202
    app = stand_in_api([])
    client = ApiClient(ACTOR, app=app)
    try:
        return await ApiAgent(model, build_tools(app.openapi(), ())).run(
            client, text, open_question=open_question, places=PLACES)
    finally:
        await client.close()


async def test_a_new_request_drops_the_open_question() -> None:
    model = FakeToolCallingProvider(["Mohanlal isn't in your team yet."])
    turn = await _run(model, MOHANLAL, WHICH)
    assert turn.dropped_question == WHICH["question"]
    assert "NOT an answer to your last question" in model.last_system_prompt
    assert WHICH["question"] in model.last_system_prompt


async def test_guard_an_answer_keeps_the_question() -> None:
    model = FakeToolCallingProvider(["OK."])
    turn = await _run(model, "the second one", WHICH)
    assert turn.dropped_question == ""
    assert "NOT an answer" not in model.last_system_prompt


# -- a project that already exists: the code says so, in their language -------------------------------


class _ProjectIn(BaseModel):
    name: str


def _projects_api(seen: list) -> FastAPI:
    app = FastAPI()

    @app.post("/projects", status_code=201)
    async def create(body: _ProjectIn):  # noqa: ANN202
        seen.append(body.name)
        return {"id": str(uuid.uuid4()), "name": body.name}

    return app


async def _create(name: str, text: str, language: str | None, places: Places = PLACES):  # noqa: ANN202
    app = _projects_api([])
    client = ApiClient(ACTOR, app=app)
    tools = build_tools(app.openapi(), tuple(a for a in ALLOWED if a.name == "create_project"))
    model = FakeToolCallingProvider([[("create_project", {"name": name, CONFIRM_ARG: f"New project {name}"})],
                                     "I'm sorry, I seem to have made a mistake. Create another with the same name?"])
    try:
        return await ApiAgent(model, tools).run(client, text, places=places, language=language)
    finally:
        await client.close()


async def test_an_existing_project_is_said_by_the_code_and_not_offered_again() -> None:
    turn = await _create("rana  mart", "Rana Mart project create", None)
    assert turn.pending == [] and turn.options == [] and turn.question == ""
    # [221]: the copies are listed here (records unreadable in this stand-in: never archived on a guess), not sent to
    # the dashboard.
    assert turn.reply.startswith("Rana Mart already exists ✅ You have 2 projects with this name:")
    assert "dashboard" not in turn.reply


async def test_sibling_in_manglish_and_a_single_existing_project() -> None:
    turn = await _create("Live Mart B", "Live Mart B ennoru puthiya project undaakku", "manglish")
    assert turn.pending == []
    assert turn.reply == "Live Mart B ippo thanne undu ✅"


def test_the_question_left_open_is_the_asked_one_or_a_reply_ending_in_a_question() -> None:
    assert question_left_open("Which one?", ["A", "B"], "Which one?") == {"question": "Which one?", "options": ["A", "B"]}
    assert question_left_open("", [], "Already saved at 17:07.\n*Another one?*") == {"question": "*Another one?*",
                                                                                     "options": []}
    assert question_left_open("", [], "Ready. Tap Save.") is None


async def test_guard_a_new_name_is_prepared_as_today() -> None:
    turn = await _create("Zeta Plaza", "Zeta Plaza project undaakku", None)
    assert [e.body["name"] for e in turn.pending] == ["Zeta Plaza"]
