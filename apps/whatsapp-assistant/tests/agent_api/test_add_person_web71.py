"""WEB-71 (Ilan, 6 Nov: "users will join by me sending their contact number to Mesiri and telling it to add; when it
asks what role to give I select it, and the project, or I tell it directly in a voice message"): someone NEW is added
by name and WhatsApp number with `add_person` (POST /projects/{project_id}/members/by-number, the same add-by-number
step an approved join request uses). The role words are the code's (classic's role words), the write waits for Save
like every write, and after the Save the owner gets the invite to forward (Mesiri can't message a new number first).
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from tests.agent_api.standin import ACTOR, PROJECT

from agent_api.agent import ApiAgent, PendingWrite, WriteResult
from agent_api.client import Actor, ApiClient
from agent_api.tools import ALLOWED, CONFIRM_ARG, build_tools
from agent_api.whatsapp import person_invites
from mesiri.domains.shared.auth import get_current_user
from mesiri_ai.fakes import FakeToolCallingProvider

ADMIN = Actor(user_id=ACTOR.user_id, organization_id=ACTOR.organization_id, role="ADMIN", name="Ilan")
WORKER = Actor(user_id=ACTOR.user_id, organization_id=ACTOR.organization_id, role="SITE_ENGINEER", name="Ravi")


class Person(BaseModel):
    fullName: str
    whatsappNumber: str
    role: str = "SITE_ENGINEER"


def _api(added: list[dict]) -> FastAPI:
    app = FastAPI()

    @app.post("/projects/{project_id}/members/by-number", status_code=201)
    async def add(project_id: str, body: Person, jwt: dict = Depends(get_current_user)):
        if str(jwt.get("role", "")).upper() not in ("ADMIN", "PROJECT_MANAGER"):
            raise HTTPException(status_code=403, detail="Only an admin or this project's manager can add people to it")
        added.append(body.model_dump())
        return {"userId": str(uuid.uuid4()), "email": "", "fullName": body.fullName, "role": body.role,
                "status": "active"}

    return app


def _call(role: str = "site engineer") -> tuple[str, dict]:
    return ("add_person", {"project_id": PROJECT, "fullName": "Ravi Kumar", "whatsappNumber": "98765 43210",
                           "role": role, CONFIRM_ARG: f"Add Ravi Kumar (98765 43210) as {role}"})


async def _run(actor: Actor, script: list, text: str):  # noqa: ANN202
    added: list[dict] = []
    app = _api(added)
    tools = build_tools(app.openapi(), tuple(a for a in ALLOWED if a.name == "add_person"))
    client = ApiClient(actor, app=app)
    try:
        return await ApiAgent(FakeToolCallingProvider(script), tools).run(client, text), added
    finally:
        await client.close()


async def test_the_asked_message_prepares_the_new_person_for_save() -> None:
    turn, added = await _run(ADMIN, [[_call("supervisor")], "Ready: add Ravi Kumar. Tap Save."],
                             "add Ravi Kumar 98765 43210 as supervisor")
    assert [e.tool for e in turn.pending] == ["add_person"]
    assert turn.pending[0].body == {"fullName": "Ravi Kumar", "whatsappNumber": "98765 43210",
                                    "role": "SITE_ENGINEER"}
    assert added == []  # held for Save, like every write


async def test_sibling_a_voice_note_naming_a_project_manager() -> None:
    turn, _ = await _run(ADMIN, [[_call("PM")], "Ready."], "ee number add cheyyu, Ravi Kumar, PM aayi")
    assert turn.pending[0].body["role"] == "PROJECT_MANAGER"


async def test_guard_a_worker_cannot_add_people() -> None:
    turn, added = await _run(WORKER, [[_call()], "Only an admin or the project manager can add people."], "add Ravi")
    assert turn.pending == [] and added == []
    assert "Only an admin or this project's manager" in turn.calls[0]["result"]["error"]


def test_after_save_the_owner_gets_the_invite_to_forward() -> None:
    pending = PendingWrite(tool="add_person", method="POST", path=f"/projects/{PROJECT}/members/by-number",
                           params={}, body={"fullName": "Ravi Kumar"}, summary="Add Ravi", idempotency_key="k")
    ctx = SimpleNamespace(org_name="Acme Builders", projects=[SimpleNamespace(id=PROJECT, name="Skyline")])
    message = SimpleNamespace(metadata={"display_phone_number": "+1 555 000 1111"})
    texts = person_invites([WriteResult(pending, 201, {"fullName": "Ravi Kumar"})], ctx, message)
    assert texts[0] == "✅ *Ravi Kumar* is on *Skyline*. Forward the next message to them so they can start:"
    assert texts[1].startswith("Hi Ravi, Acme Builders uses Mesiri") and "https://wa.me/15550001111?text=Hi" in texts[1]
    # A refused add gets no invite.
    assert person_invites([WriteResult(pending, 409, {"detail": "taken"})], ctx, message) == []
