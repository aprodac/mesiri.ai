"""[282] (7 Nov 2026, live test): "bathroom leak plumber vannu fix cheythu" answered
"The tool failed. I can't find an open issue...", in English, though the leak was saved a
minute earlier. `list_issues` was called with `status=open`; the column is an enum (`OPEN`), the
API raised, and the exception reached the model as {"error": "the tool failed"}.

1. The reported message: a bad value is a 422 that names the meant value, so the model's next
   call (`OPEN`) finds the leak.
2. Sibling: any other crash of a read comes back as a code-written note, never an exception
   and never the words "tool failed".
3. Guard: a read that works is passed on unchanged.
"""

from __future__ import annotations

import uuid

from fastapi import Depends, FastAPI
from sqlalchemy.exc import DataError
from tests.agent_api.standin import ACTOR, SITE

from agent_api.agent import UNAVAILABLE_NOTE, ApiAgent
from agent_api.client import ApiClient
from agent_api.tools import ALLOWED, build_tools
from mesiri.domains.shared.auth import get_current_user
from mesiri.http import db_errors
from mesiri_ai.fakes import FakeToolCallingProvider

MESSAGE = "bathroom leak plumber vannu fix cheythu"
LEAK = {"id": str(uuid.uuid4()), "narrative": "Water leak in ground floor bathroom", "status": "OPEN"}


class _Enum(Exception):
    def __str__(self) -> str:
        return 'invalid input value for enum site_issue_status: "open"'


def _issues_api(*, crash: bool = False) -> FastAPI:
    app = FastAPI()
    db_errors.install(app)

    @app.get("/progress/issues")
    async def list_issues(site_id: str | None = None, status: str | None = None,
                          jwt: dict = Depends(get_current_user)):
        if crash:
            raise RuntimeError("database went away")
        if status is not None and status != status.upper():
            # What asyncpg raises through SQLAlchemy for a lower-case enum value.
            raise DataError("SELECT ... FROM site_issues", {}, _Enum())
        return {"items": [LEAK] if status in (None, "OPEN") else [], "total": 1}

    return app


def _tools(app: FastAPI):  # noqa: ANN202
    return build_tools(app.openapi(), tuple(a for a in ALLOWED if a.name == "list_issues"))


async def _turn(app: FastAPI, model: FakeToolCallingProvider):  # noqa: ANN202
    client = ApiClient(ACTOR, app=app)
    try:
        return await ApiAgent(model, _tools(app)).run(client, MESSAGE)
    finally:
        await client.close()


async def test_a_lower_case_status_is_explained_and_the_retry_finds_the_leak() -> None:
    model = FakeToolCallingProvider([
        [("list_issues", {"site_id": SITE, "status": "open"})],
        [("list_issues", {"site_id": SITE, "status": "OPEN"})],
        "Bathroom leak close cheyyatte?",
    ])
    turn = await _turn(_issues_api(), model)
    first, second = turn.calls
    assert first["result"]["status"] == 422
    assert "Did you mean 'OPEN'?" in first["result"]["result"]
    assert second["result"]["status"] == 200 and LEAK["id"] in second["result"]["result"]


async def test_a_crashed_read_is_a_code_written_note_never_tool_failed() -> None:
    model = FakeToolCallingProvider([
        [("list_issues", {"site_id": SITE, "status": "OPEN"})],
        "Ippo check cheyyan pattiyilla, oru minute kazhinju ayakkamo?",
    ])
    turn = await _turn(_issues_api(crash=True), model)
    (call,) = turn.calls
    assert call["result"] == {"status": "unavailable", "note": UNAVAILABLE_NOTE}
    assert "tool failed" not in str(turn.calls).lower()


async def test_a_working_read_is_passed_on_unchanged() -> None:
    model = FakeToolCallingProvider([[("list_issues", {"site_id": SITE, "status": "OPEN"})], "1 open issue."])
    turn = await _turn(_issues_api(), model)
    assert turn.calls[0]["result"]["status"] == 200


def test_the_reply_never_says_the_tool_failed() -> None:
    """Live re-test, 7 Nov 19:01: the model wrote "The tool failed." again, copying its earlier reply, although the
    code's note said never to. The code cuts it; the rest of the answer stays."""
    from agent_api.reply_guard import without_internals

    live = ("The tool failed. I could not check for open issues right now, so please try again in a minute if you "
            "want to record the fix for the leak, and tell me which issue it is.")
    clean = without_internals(live)
    assert "tool" not in clean.lower()
    assert clean.startswith("I could not check for open issues right now")
    for leak in ("The tool returned an error.", "Tool call failed.", "The tool is not available now."):
        assert without_internals(f"{leak} Leak closed.") == "Leak closed."


def test_site_tools_in_a_message_are_not_cut() -> None:
    """Guard: tools on a construction site are real ("the tools were stolen", "cutting tool broke")."""
    from agent_api.reply_guard import without_internals

    for said in ("The tools were stolen from the store room.", "Cutting tool broke, new one needed."):
        assert without_internals(said) == said


def test_every_app_that_serves_the_api_turns_a_bad_value_into_a_422() -> None:
    """Guard (the second live re-test failed because v3's own API app lacked the handler): all three apps install it."""
    from sqlalchemy.exc import DBAPIError

    from agent_api.app import build_api_app
    from mesiri_contracts.common.errors import MesiriError

    def has_handler(app: FastAPI) -> bool:
        return DBAPIError in app.exception_handlers and MesiriError in app.exception_handlers

    from mesiri.http.app import create_app as backend_app
    from runtime.dependencies import Settings
    from runtime.lifecycle import create_app as assistant_app

    assert has_handler(build_api_app(None))  # what v3 calls
    assert has_handler(backend_app())
    assert has_handler(assistant_app(Settings(verify_token="x", app_secret="x", access_token="x")))  # production
