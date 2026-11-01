"""Request 197: v2 creates a project (and a site) from chat through the existing project_create /
site_create workflows. Role and organisation are checked by code (the query entry), a name that
already exists is pointed to, and the confirmation shows the size."""

from __future__ import annotations

from types import SimpleNamespace

from agent_v2.agents.main import MainAgent, V2Run, all_specs
from runtime.agent import tools as t
from runtime.agent.entry_base import Say
from runtime.agent.query_entry import QueryEntry
from runtime.agent.tools import ScopeLookup, to_candidate
from workflows.project_create.nodes import request_confirmation


def test_v2_offers_create_project_and_create_site():
    assert {t.CREATE_PROJECT, t.CREATE_SITE} <= {s.name for s in all_specs()}


def test_size_and_type_ride_in_the_projects_description():
    c = to_candidate(t.CREATE_PROJECT, {"name": "Ilan Testing", "size_sqft": 5000, "project_type": "G+1 supermarket"}, ScopeLookup())
    assert c.fields == {"name": "Ilan Testing", "description": "5,000 sq ft · G+1 supermarket"}
    plain = to_candidate(t.CREATE_PROJECT, {"name": "Ilan Testing"}, ScopeLookup())
    assert plain.fields == {"name": "Ilan Testing"}


def test_the_confirmation_line_shows_name_and_size():
    draft = SimpleNamespace(fields={"name": "Fsuz Garden", "description": "5,000 sq ft"})
    prompt = request_confirmation({"draft_action": draft})["pending_prompt"]
    assert "*Fsuz Garden*" in prompt and "5,000 sq ft" in prompt


async def test_a_worker_cannot_create_a_project_the_code_refuses():
    for role in ("WORKER", "SUPERVISOR", "ENGINEER"):
        entry = QueryEntry(None, None, SimpleNamespace(role=role))
        candidate = to_candidate(t.CREATE_PROJECT, {"name": "X"}, ScopeLookup())
        said = await entry.prepare(SimpleNamespace(correlation_id="c"), None, candidate)
        assert isinstance(said, Say) and "admin or project manager" in said.text, role


async def test_a_name_that_exists_is_pointed_to_and_nothing_is_created():
    toolbox = SimpleNamespace(scope=ScopeLookup(projects=(("p1", "Green Villa"),)), answers=[], user_text="")
    state = V2Run(toolbox=toolbox)
    handle = MainAgent.handler(SimpleNamespace(), state, "org")
    outcome = await handle(t.CREATE_PROJECT, {"name": " green  villa "})
    assert outcome.content["status"] == "already_exists" and outcome.content["project"] == "Green Villa"
