"""[257] (5 Nov, a new customer): a voice note gave the client, a contract of about 2.5 crore, the signing date
and stage-wise payments. The update carried only the client, yet the card line said "Client name, contract value,
and payment terms" and the reply said Saved: the details were lost under a line that claimed them.

Project lines are now drawn by the code from the fields that will be saved; details with no field of their own go
into the description (SOP), which an update adds to and never replaces.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel
from tests.agent_api.standin import ACTOR

from agent_api.agent import ApiAgent, Places, project_line
from agent_api.client import ApiClient
from agent_api.tools import ALLOWED, CONFIRM_ARG, build_tools
from mesiri_ai.fakes import FakeToolCallingProvider

PROJECT = str(uuid.uuid4())
PLACES = Places(projects=((PROJECT, "Supermarket Kerala"),), sites=())
CLAIM = "Client name, contract value, and payment terms for Supermarket Kerala project"


class _ProjectEdit(BaseModel):
    name: str | None = None
    client: str | None = None
    location: str | None = None
    description: str | None = None


def _api(saved: dict[str, Any]) -> FastAPI:
    app = FastAPI()

    @app.get("/projects/{project_id}")
    async def read(project_id: str):  # noqa: ANN202
        return {"id": project_id, "name": "Supermarket Kerala", **saved}

    @app.put("/projects/{project_id}")
    async def edit(project_id: str, body: _ProjectEdit):  # noqa: ANN202
        return {"id": project_id, **body.model_dump(exclude_none=True)}

    @app.post("/projects", status_code=201)
    async def create(body: _ProjectEdit):  # noqa: ANN202
        return {"id": str(uuid.uuid4()), **body.model_dump(exclude_none=True)}

    return app


async def _turn(calls: list, saved: dict[str, Any] | None = None) -> Any:  # noqa: ANN401
    app = _api(saved or {})
    client = ApiClient(ACTOR, app=app)
    tools = build_tools(app.openapi(), tuple(a for a in ALLOWED if a.name in ("update_project", "create_project")))
    try:
        return await ApiAgent(FakeToolCallingProvider([calls, "Ready."]), tools).run(client, "voice", places=PLACES)
    finally:
        await client.close()


async def test_the_card_line_names_only_what_will_be_saved() -> None:
    turn = await _turn([("update_project", {"project_id": PROJECT, "client": "Day to Day Supermarket",
                                            CONFIRM_ARG: CLAIM})])
    (entry,) = turn.pending
    assert entry.summary == "*Supermarket Kerala*: client Day to Day Supermarket"
    assert "contract" not in entry.summary and "payment" not in entry.summary


async def test_contract_details_in_the_description_are_on_the_line_and_added_to_what_was_there() -> None:
    details = "Turnkey contract, about 2.5 crore, signed 21 May 2026; paid in stages over 2 years"
    turn = await _turn([("update_project", {"project_id": PROJECT, "client": "Day to Day Supermarket",
                                            "description": details, CONFIRM_ARG: CLAIM})],
                       saved={"description": "Ground + first floor supermarket, about 7,000 sqft."})
    (entry,) = turn.pending
    assert entry.body["description"] == f"Ground + first floor supermarket, about 7,000 sqft. {details}"
    assert entry.summary.startswith("*Supermarket Kerala*: client Day to Day Supermarket; details Ground")


async def test_guard_a_description_that_already_holds_the_old_one_is_kept_as_is() -> None:
    old = "Ground + first floor supermarket."
    turn = await _turn([("update_project", {"project_id": PROJECT, "description": f"{old} Turnkey, 2.5 crore.",
                                            CONFIRM_ARG: "x"})], saved={"description": old})
    assert turn.pending[0].body["description"] == f"{old} Turnkey, 2.5 crore."


async def test_a_new_project_line_comes_from_its_body() -> None:
    turn = await _turn([("create_project", {"name": "Day 2 Day Mart", "client": "Supermarket",
                                            "location": "Kerala", CONFIRM_ARG: "Ok, a new project is ready"})])
    assert turn.pending[0].summary == "New project *Day 2 Day Mart*: client Supermarket; location Kerala"


def test_rename_and_empty_lines() -> None:
    path = f"/projects/{PROJECT}"
    assert project_line("update_project", {"name": "D2D Supermarket"}, PLACES, path) == (
        "*Supermarket Kerala*: name D2D Supermarket")
    assert project_line("update_project", {}, PLACES, path) == ""  # nothing to show: the model's line stays
    long = "x" * 120
    assert project_line("update_project", {"description": long}, PLACES, path).endswith("x…")
