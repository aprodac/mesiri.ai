"""SS-34 (guided onboarding): "no more tips" / "explain step by step" said in chat sets the person's start mode
through the dashboard's own route (``PUT /me/start-mode``), at once, the way a reply-language choice is set ([243]):
never a Ready-to-save line. Guard: a record said in the same message still waits for Save."""

from __future__ import annotations

from fastapi import Depends, FastAPI
from pydantic import BaseModel
from tests.agent_api.standin import ACTOR

from agent_api.agent import SET_AT_ONCE, ApiAgent
from agent_api.client import ApiClient
from agent_api.tools import ALLOWED, CONFIRM_ARG, build_tools
from mesiri.domains.identity import preferences_router
from mesiri.domains.shared.auth import get_current_user
from mesiri_ai.fakes import FakeToolCallingProvider


class _Mode(BaseModel):
    start_mode: str


class _Category(BaseModel):
    name: str


def _api(saved: list) -> FastAPI:
    app = FastAPI()

    @app.put("/me/start-mode")
    async def mode(body: _Mode, jwt: dict = Depends(get_current_user)):
        saved.append(("start_mode", body.start_mode, jwt["sub"]))
        return {"start_mode": body.start_mode}

    @app.post("/expenses/categories")
    async def category(body: _Category, jwt: dict = Depends(get_current_user)):
        saved.append(("category", body.name))
        return {"id": "c1", "name": body.name}

    return app


async def _run(script: list, text: str) -> tuple:
    saved: list = []
    app = _api(saved)
    tools = build_tools(app.openapi(), tuple(a for a in ALLOWED if a.name in ("set_start_mode", "add_expense_category")))
    client = ApiClient(ACTOR, app=app)
    try:
        turn = await ApiAgent(FakeToolCallingProvider(script), tools).run(client, text, language="english")
        return turn, saved
    finally:
        await client.close()


async def test_no_more_tips_is_set_at_once_and_never_on_the_card() -> None:
    call = ("set_start_mode", {"start_mode": "free", CONFIRM_ARG: "No more tips"})
    turn, saved = await _run([[call], "Done, no more tips."], "no more tips please")
    assert [s[:2] for s in saved] == [("start_mode", "free")]
    assert turn.pending == []
    assert turn.calls[0]["result"]["status"].startswith("set now")


async def test_guard_a_record_in_the_same_message_still_waits_for_save() -> None:
    call = ("set_start_mode", {"start_mode": "guided", CONFIRM_ARG: "Step by step"})
    add = ("add_expense_category", {"name": "Diesel", CONFIRM_ARG: "New expense category: Diesel"})
    turn, saved = await _run([[call, add], "Ok."], "explain step by step, and add a Diesel category")
    assert [s[:2] for s in saved] == [("start_mode", "guided")]  # the category is not saved before Save
    assert [e.tool for e in turn.pending] == ["add_expense_category"]


def test_the_tool_is_the_real_route() -> None:
    app = FastAPI()
    app.include_router(preferences_router.router)
    tool = build_tools(app.openapi(), tuple(a for a in ALLOWED if a.name == "set_start_mode"))["set_start_mode"]
    assert tool.method == "PUT" and tool.path == "/me/start-mode"
    assert set(tool.spec.parameters["properties"]["start_mode"]["enum"]) == set(preferences_router.START_MODES)
    assert "set_start_mode" in SET_AT_ONCE
