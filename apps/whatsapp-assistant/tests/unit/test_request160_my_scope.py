"""Request [160]: "which projects am I on?" is answered from the actor, not asked back."""

from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

from runtime.agent import toolbox as tb
from runtime.agent.scope_answer import asks_own_scope, scope_facts
from runtime.agent.tool_choice import tools_for
from runtime.agent.tools import MY_SCOPE, QUERY_TOOLS, ScopeLookup, tool_specs

HOSPITAL = NS(id="p1", name="Hospital Project", location="Aluva")
MITHILASH = NS(id="p2", name="Mithilash", location="Kochi")


def _site(sid, name, pid):
    return NS(id=sid, name=name, project_id=pid)


SITES = [_site("s1", "Block A", "p1"), _site("s2", "Block B", "p1"), _site("s3", "Main", "p2")]


def _actor(projects, sites=(), role="PROJECT_MANAGER"):
    return NS(role=role, org_name="Paraclette", projects=list(projects), sites=list(sites))


class Gateway:
    def __init__(self, actor):
        self.actor = actor
        self.runs = []

    async def run(self, candidate, *, text):  # a project lookup would land here
        self.runs.append(candidate)
        raise AssertionError("my_scope must not run a project query")

    async def finish(self):
        return None


def _box(actor, text):
    gateway = Gateway(actor)
    return tb.AgentToolbox(gateway, ScopeLookup(), text), gateway


async def test_replay_1446_two_projects_listed_with_sites_and_buttons_no_question():
    box, gateway = _box(_actor([HOSPITAL, MITHILASH], SITES), "machane, which project am I assigned to?")
    # The model chose query_project with nothing named: the code sends it to my_scope.
    out = await box.handle("query_project", {})
    assert out.content["status"] == "answer"
    text = out.content["text"]
    assert "2 projects" in text and "Hospital Project (Aluva · 2 sites)" in text and "Mithilash (Kochi · 1 site)" in text
    assert "Project Manager" in text
    assert "Which" not in text and "which" not in out.content["instruction"].replace("Do not ask which project", "")
    assert box.parked is not None
    assert [r.title for r in box.parked.list_rows or box.parked.buttons] == ["Hospital Project", "Mithilash"]
    assert gateway.runs == []


@pytest.mark.parametrize("said", ["ente sites ethokke", "where am I assigned", "എന്റെ പ്രോജക്ടുകൾ ഏതൊക്കെ?", "my projects", "which projects am I on?"])
async def test_sibling_wordings_reach_my_scope(said):
    assert asks_own_scope(said)
    box, _ = _box(_actor([HOSPITAL, MITHILASH], SITES), said)
    assert (await box.handle("query_project", {})).content["status"] == "answer"
    box, _ = _box(_actor([HOSPITAL, MITHILASH], SITES), said)
    assert (await box.handle(MY_SCOPE, {})).content["status"] == "answer"


async def test_one_project_is_answered_directly_without_buttons():
    box, _ = _box(_actor([HOSPITAL], SITES[:2]), "my projects")
    out = await box.handle(MY_SCOPE, {})
    assert "1 project" in out.content["text"] and "Sites: Block A, Block B" in out.content["text"]
    assert box.parked is None


async def test_no_project_says_so_and_who_can_assign():
    box, _ = _box(_actor([]), "my projects")
    out = await box.handle(MY_SCOPE, {})
    assert "not on any project" in out.content["text"] and "admin" in out.content["text"]
    assert box.parked is None


async def test_admin_gets_the_company_projects_with_a_count():
    text = scope_facts(_actor([HOSPITAL, MITHILASH], SITES, role="ADMIN"))
    assert "The company has 2 projects" in text and "Role: Admin at Paraclette" in text


async def test_another_companys_project_never_appears():
    """The list is the sender's actor only: a project not on it is not in the answer."""
    other = NS(id="p9", name="Rival Towers", location="Delhi")
    text = scope_facts(_actor([HOSPITAL], SITES))
    assert "Rival Towers" not in text
    box, _ = _box(_actor([HOSPITAL, MITHILASH], SITES), "my projects")
    out = await box.handle(MY_SCOPE, {})
    assert other.name not in out.content["text"]


async def test_guards_named_project_and_vague_status_still_go_to_the_project_query():
    for said, args in [("Hospital project status", {"project": "Hospital Project"}), ("how is the project going", {})]:
        assert not asks_own_scope(said)
        box, gateway = _box(_actor([HOSPITAL, MITHILASH], SITES), said)
        await box.handle("query_project", args)  # the fake gateway refuses; the toolbox logs it
        assert len(gateway.runs) == 1  # it reached the project query path
        assert box.parked is None  # and no project list was offered
    assert not asks_own_scope("who is on Hospital project")
    assert not asks_own_scope("Hospital Project")


async def test_my_scope_saves_nothing_and_is_always_offered():
    assert MY_SCOPE in QUERY_TOOLS
    assert any(spec.name == MY_SCOPE for spec in tool_specs())
    assert any(spec.name == MY_SCOPE for spec in tools_for("50 masons"))
    box, _ = _box(_actor([HOSPITAL], SITES), "my projects")
    await box.handle(MY_SCOPE, {})
    assert box.attempted_writes == 0 and box.saved == []
