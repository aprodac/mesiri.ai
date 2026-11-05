"""[265] (5 Nov, Sahal, a new company: "the AI understanding me was bad"). Three mechanisms behind it:

1. A corrective retry from the code was written as the person ("My message also said 2026-05-21 ..."), so the model
   apologised to them ("My bad! Sorry, I missed that date.") and that answer to the check replaced the real reply.
   Now every retry says it is the code's, unseen by the person, and asks for the whole reply again; a sentence that
   is only an apology for a slip never goes out.
2. A project made on WhatsApp ("Supermarket Kerala") had no site, so a report for it could only ask "which site?"
   again, and the facts told the model "Only one site: Banglore. Use it; never ask". Now a new project gets its first
   site at Save, and a report to a project with no site goes on it, its site added at Save.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from fastapi import Depends, FastAPI, Header
from pydantic import BaseModel
from tests.agent_api.standin import ACTOR, PROJECT, SITE

from agent_api.agent import (
    SITE_OF,
    ApiAgent,
    PendingWrite,
    Places,
    check_note,
    confirm,
)
from agent_api.client import ApiClient
from agent_api.reply_guard import without_apology
from agent_api.tools import ALLOWED, CONFIRM_ARG, build_tools
from agent_api.whatsapp import ApiWhatsApp
from mesiri.domains.shared.auth import get_current_user
from mesiri_ai.fakes import FakeToolCallingProvider

KERALA = str(uuid.uuid4())  # "Supermarket Kerala": made on WhatsApp, no site
PLACES = Places(projects=((PROJECT, "Banglore"), (KERALA, "Supermarket Kerala")),
                sites=((SITE, "Banglore", PROJECT),))


class Issue(BaseModel):
    project_id: uuid.UUID
    site_id: uuid.UUID
    title: str


class NewSite(BaseModel):
    name: str


class NewProject(BaseModel):
    name: str


def _api(seen: list[tuple[str, str, dict]]) -> FastAPI:
    app = FastAPI()
    sites: dict[str, list[dict]] = {PROJECT: [{"id": SITE, "name": "Banglore"}]}

    @app.get("/projects/{project_id}")
    async def project(project_id: str, jwt: dict = Depends(get_current_user)):
        return {"id": project_id, "name": "Supermarket Kerala" if project_id == KERALA else "Banglore"}

    @app.get("/projects/{project_id}/sites")
    async def list_sites(project_id: str, jwt: dict = Depends(get_current_user)):
        return sites.get(project_id, [])

    @app.post("/projects/{project_id}/sites", status_code=201)
    async def add_site(project_id: str, body: NewSite, jwt: dict = Depends(get_current_user),
                       key: str | None = Header(default=None, alias="Idempotency-Key")):
        made = {"id": str(uuid.uuid4()), "name": body.name}
        sites.setdefault(project_id, []).append(made)
        seen.append(("POST", f"/projects/{project_id}/sites", {"name": body.name}))
        return made

    @app.post("/projects", status_code=201)
    async def new_project(body: NewProject, jwt: dict = Depends(get_current_user),
                          key: str | None = Header(default=None, alias="Idempotency-Key")):
        seen.append(("POST", "/projects", {"name": body.name}))
        return {"id": KERALA, "name": body.name}

    @app.post("/progress/issues", status_code=201)
    async def issue(body: Issue, jwt: dict = Depends(get_current_user),
                    key: str | None = Header(default=None, alias="Idempotency-Key")):
        seen.append(("POST", "/progress/issues", body.model_dump(mode="json")))
        return {"id": str(uuid.uuid4())}

    return app


def _tools(app: FastAPI):  # noqa: ANN202
    names = {"report_issue", "create_project", "add_site", "list_sites"}
    return build_tools(app.openapi(), tuple(a for a in ALLOWED if a.name in names))


_ISSUE = ("report_issue", {"project_id": KERALA, "title": "Drawings not received",
                           CONFIRM_ARG: "Drawings not received, Supermarket Kerala"})


async def test_a_report_to_a_project_with_no_site_goes_on_it_and_save_adds_its_site() -> None:
    seen: list[tuple[str, str, dict]] = []
    app = _api(seen)
    client = ApiClient(ACTOR, app=app)
    try:
        turn = await ApiAgent(FakeToolCallingProvider([[_ISSUE], "Ready."]), _tools(app)).run(
            client, "Supermarket Kerala: drawings not received", places=PLACES)
        [entry] = turn.pending  # held, not "which site?" again
        assert entry.body["site_id"] == f"{SITE_OF}{KERALA}"
        assert entry.summary.endswith("📍 *Supermarket Kerala* (new site)")
        [result] = await confirm(client, turn.pending)
    finally:
        await client.close()
    assert result.ok
    assert ("POST", f"/projects/{KERALA}/sites", {"name": "Supermarket Kerala"}) in seen
    [issue] = [b for m, p, b in seen if p == "/progress/issues"]
    assert issue["site_id"] != f"{SITE_OF}{KERALA}" and uuid.UUID(issue["site_id"])


async def test_guard_a_project_with_a_site_is_unchanged() -> None:
    seen: list[tuple[str, str, dict]] = []
    app = _api(seen)
    client = ApiClient(ACTOR, app=app)
    call = ("report_issue", {"project_id": PROJECT, "site_id": SITE, "title": "Rain", CONFIRM_ARG: "Rain, Banglore"})
    try:
        turn = await ApiAgent(FakeToolCallingProvider([[call], "Ready."]), _tools(app)).run(
            client, "Banglore: rain stopped work", places=PLACES)
        await confirm(client, turn.pending)
    finally:
        await client.close()
    assert turn.pending[0].body["site_id"] == SITE and "📍" not in turn.pending[0].summary
    assert not [p for m, p, b in seen if p.endswith("/sites")]  # no site added


async def test_sibling_a_project_made_on_whatsapp_gets_its_first_site_at_save() -> None:
    seen: list[tuple[str, str, dict]] = []
    app = _api(seen)
    client = ApiClient(ACTOR, app=app)
    made = PendingWrite("create_project", "POST", "/projects", {}, {"name": "Supermarket Kerala"}, "New project", "k")
    try:
        [result] = await confirm(client, [made])
    finally:
        await client.close()
    assert result.ok
    assert seen == [("POST", "/projects", {"name": "Supermarket Kerala"}),
                    ("POST", f"/projects/{KERALA}/sites", {"name": "Supermarket Kerala"})]


async def test_the_facts_never_say_only_one_site_while_a_project_has_none() -> None:
    project = lambda pid, name: SimpleNamespace(id=pid, name=name)  # noqa: E731
    site = SimpleNamespace(id=SITE, name="Banglore", project_id=PROJECT)
    ctx = SimpleNamespace(projects=[project(PROJECT, "Banglore"), project(KERALA, "Supermarket Kerala")],
                          sites=[site], organization_id=ACTOR.organization_id, timezone="Asia/Kolkata")
    agent = ApiWhatsApp.__new__(ApiWhatsApp)
    agent._catalog = {ACTOR.organization_id: (float("inf"), "")}

    async def nothing(*_a, **_k):  # noqa: ANN002, ANN003, ANN202
        return ""
    agent._today = nothing  # type: ignore[method-assign]
    agent._catalog_for = nothing  # type: ignore[method-assign]
    facts = await agent._facts(ctx, None)  # type: ignore[arg-type]
    assert "Only one site" not in facts
    assert "Supermarket Kerala has no site yet" in facts
    ctx.projects = ctx.projects[:1]  # guard: one project, one site -> unchanged
    assert "Only one site: Banglore. Use it; never ask which site." in await agent._facts(ctx, None)  # type: ignore[arg-type]


async def test_a_retry_from_the_code_is_never_the_persons_words_and_the_reply_has_no_apology() -> None:
    # The model says "saved" with nothing prepared: the code asks once more. The second answer apologises.
    class TwoAnswers:  # one scripted answer per model call
        provider = "fake"

        def __init__(self) -> None:
            self.answers = ["Saved ✅", "My bad! Sorry, I missed that. Which site was the rain at?"]
            self.last_messages: list = []

        async def run_tools(self, system_prompt, messages, tools, handler, **_kw):  # noqa: ANN001, ANN003, ANN202
            from mesiri_ai.models import ToolRunResult

            self.last_messages = list(messages)
            return ToolRunResult(text=self.answers.pop(0), calls=[], steps=0, stop_reason="answered", model="fake")

    provider = TwoAnswers()
    app = _api([])
    client = ApiClient(ACTOR, app=app)
    try:
        turn = await ApiAgent(provider, _tools(app)).run(client, "rain today", places=PLACES)
    finally:
        await client.close()
    note = provider.last_messages[-1].text
    assert note.startswith("(A check by Mesiri's code, not a message from the person; they never see it:")
    assert "WHOLE reply" in note and "no apology" in note
    assert turn.reply == "Which site was the rain at?"


def test_check_note_wraps_any_retry_text() -> None:
    note = check_note("(My message also said 2026-05-21, and nothing you prepared has it.)").text
    assert note.count("(") == 1 and "My message also said 2026-05-21, and nothing you prepared has it. Then" in note


def test_only_bare_apologies_for_a_slip_are_dropped() -> None:
    assert without_apology("My bad! Sorry, I missed that date.\n\nThe contract was signed on 21 May 2026.") == (
        "The contract was signed on 21 May 2026.")
    assert without_apology("Apologies for the confusion. Ready: client Day 2 Day.") == "Ready: client Day 2 Day."
    # guards: an apology that carries an action or a real limit stays
    for kept in ("Sorry, I couldn't hear the voice note. Please say it again.",
                 "Sorry, I missed the 6 masons. Added them.",
                 "Sorry, I got the quantity wrong: changed to 6 masons."):
        assert without_apology(kept) == kept
