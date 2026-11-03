"""[207] (Paraclette, 2-3 Nov 23:33-00:58, Ilan by voice): "create project Rana Mart and add Sahal as site engineer"
got "adding Sahal as site engineer isn't available here, use the web dashboard" (cor_9498573a129f4f55b4337a1aa27bc859,
cor_e2f6448919dc4cd7b494a08494a79209, cor_cf124a9ac6d7436bbcc042c8ca713243).

The dashboard's own route (POST /projects/{project_id}/members) is now a v3 tool. The code, not the model, turns the
name they said into a person already in the company (buttons when more than one could be meant; never a new person)
and the role words into a role code. The API decides who may: an admin or this project's manager (a worker is
refused before anything is prepared).
"""

from __future__ import annotations

import uuid

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from tests.agent_api.standin import ACTOR, PROJECT

from agent_api.agent import ApiAgent
from agent_api.client import Actor, ApiClient
from agent_api.tools import ALLOWED, CONFIRM_ARG, build_tools
from mesiri.domains.shared.auth import get_current_user
from mesiri_ai.fakes import FakeToolCallingProvider

SAHAL = str(uuid.uuid4())
SAHAL_K = str(uuid.uuid4())
ANU = str(uuid.uuid4())
ADMIN = Actor(user_id=ACTOR.user_id, organization_id=ACTOR.organization_id, role="ADMIN", name="Ilan")
WORKER = Actor(user_id=ACTOR.user_id, organization_id=ACTOR.organization_id, role="SITE_ENGINEER", name="Ravi")


class Member(BaseModel):
    userId: uuid.UUID
    role: str = "SITE_ENGINEER"


def _api(people: list[tuple[str, str]], added: list[dict]) -> FastAPI:
    app = FastAPI()

    def may(jwt: dict) -> None:
        if str(jwt.get("role", "")).upper() not in ("ADMIN", "PROJECT_MANAGER"):
            raise HTTPException(status_code=403, detail="Only an admin or this project's manager can add people to it")

    @app.get("/projects/{project_id}/member-candidates")
    async def candidates(project_id: str, jwt: dict = Depends(get_current_user)):
        may(jwt)
        return [{"userId": i, "fullName": n, "role": "SITE_ENGINEER"} for i, n in people]

    @app.post("/projects/{project_id}/members", status_code=201)
    async def add(project_id: str, body: Member, jwt: dict = Depends(get_current_user)):
        may(jwt)
        added.append({"project": project_id, "user": str(body.userId), "role": body.role})
        return {"userId": str(body.userId), "email": "", "fullName": "", "role": body.role, "status": "active"}

    return app


def _call(user: str, role: str = "site engineer") -> tuple[str, dict]:
    return ("add_project_member", {"project_id": PROJECT, "userId": user, "role": role,
                                   CONFIRM_ARG: f"Add {user} to Rana Mart as {role}"})


async def _run(actor: Actor, people: list[tuple[str, str]], script: list, text: str):  # noqa: ANN202
    added: list[dict] = []
    app = _api(people, added)
    tools = build_tools(app.openapi(), tuple(a for a in ALLOWED if a.name == "add_project_member"))
    client = ApiClient(actor, app=app)
    try:
        return await ApiAgent(FakeToolCallingProvider(script), tools).run(client, text), added
    finally:
        await client.close()


async def test_the_reported_message_prepares_sahal_as_site_engineer() -> None:
    turn, added = await _run(ADMIN, [(SAHAL, "Sahal"), (ANU, "Anu")],
                             [[_call("Sahal")], "Ready: add Sahal to Rana Mart as site engineer. Tap Save."],
                             "Sahal-ine Rana Mart-il site engineer aayi add cheyyu")
    assert [e.tool for e in turn.pending] == ["add_project_member"]
    assert turn.pending[0].body == {"userId": SAHAL, "role": "SITE_ENGINEER"}
    assert added == []  # held for Save, like every write


async def test_sibling_a_project_manager_is_added_by_their_first_name() -> None:
    turn, _ = await _run(ADMIN, [(SAHAL_K, "Sahal Kareem"), (ANU, "Anu")],
                         [[_call("Anu", "PM")], "Ready."], "Anu-ine PM aakku")
    assert turn.pending[0].body == {"userId": ANU, "role": "PROJECT_MANAGER"}


async def test_sibling_a_worker_asking_is_refused_before_anything_is_prepared() -> None:
    turn, added = await _run(WORKER, [(SAHAL, "Sahal")],
                             [[_call("Sahal")], "Only an admin or the project manager can add people."], "add Sahal")
    assert turn.pending == [] and added == []
    assert "Only an admin or this project's manager" in turn.calls[0]["result"]["error"]


async def test_sibling_a_name_two_people_share_gets_buttons() -> None:
    turn, _ = await _run(ADMIN, [(SAHAL, "Sahal P"), (SAHAL_K, "Sahal K")],
                         [[_call("Sahal")], "Which Sahal?"], "add Sahal")
    assert turn.pending == []
    assert sorted(turn.options) == ["Sahal K", "Sahal P"]


async def test_guard_someone_not_in_the_company_is_never_created() -> None:
    turn, added = await _run(ADMIN, [(ANU, "Anu")], [[_call("Rahul")], "Rahul isn't in the company yet."], "add Rahul")
    assert turn.pending == [] and added == []
    assert "dashboard" in turn.calls[0]["result"]["error"]
