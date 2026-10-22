"""Back from the classic pipeline (22 Oct): adding a team member, correcting a
work quantity and closing a site issue, as agent tools on a direct entry."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from tests.unit.test_material_entry import MESSAGE, ORG, PRJ, SITE, _actor, _Context, _Understanding

from channel.replies import ReplySpec
from mesiri_contracts.assistant.canonical_event import CanonicalEventType
from mesiri_contracts.assistant.enums import SemanticType
from mesiri_contracts.assistant.planner_decision import WorkflowKey
from runtime.agent.change_entry import ChangeEntry
from runtime.agent.entry_base import Ready, Say
from runtime.agent.tools import (
    ADD_MEMBER,
    CORRECT_WORK_QUANTITY,
    UPDATE_ISSUE,
    ScopeLookup,
    to_candidate,
)
from workflows.entities import Ambiguous, Candidate, Missing, Resolved


class _Members:
    def __init__(self, outcome: Any) -> None:
        self.outcome = outcome

    async def resolve(self, *, organization_id: str, name_hint: str) -> Any:
        return self.outcome


def _entry(role: str = "PROJECT_MANAGER", **services: Any) -> ChangeEntry:
    actor = _actor(SITE, role=role)
    actor.organization_id = ORG
    actor.projects = [SimpleNamespace(id=PRJ, name="Villa")]
    return ChangeEntry(context_resolver=_Context(), org_settings_query=None, actor=actor, **services)


async def _prepare(entry: ChangeEntry, tool: str, **args: Any):
    candidate = to_candidate(tool, args, ScopeLookup())
    return await entry.prepare(MESSAGE, _Understanding(candidate), candidate)


# -- add a team member ------------------------------------------------------------


async def test_a_known_person_is_added_under_their_stored_name():
    entry = _entry(member_resolver=_Members(Resolved(entity_id="u1", display_name="Ravi Kumar")))
    ready = await _prepare(entry, ADD_MEMBER, name="ravi kumar", role="supervisor")
    assert isinstance(ready, Ready)
    assert ready.decision.workflow_key is WorkflowKey.ADD_PROJECT_MEMBER
    assert ready.event.event_type is CanonicalEventType.ADD_PROJECT_MEMBER_REQUESTED
    fields = ready.event.fields
    assert (fields["member_name"], fields["role"], fields["created_by_role"]) == ("Ravi Kumar", "supervisor", "PROJECT_MANAGER")
    assert str(ready.event.project_id) == PRJ


async def test_only_an_admin_or_project_manager_adds_someone():
    said = await _prepare(_entry(role="SITE_ENGINEER"), ADD_MEMBER, name="Ravi")
    assert isinstance(said, Say) and said.status == "info"


async def test_near_matches_are_a_question_with_their_names():
    near = Ambiguous(candidates=(Candidate("u1", "Hisham"), Candidate("u2", "Hisham K")))
    said = await _prepare(_entry(member_resolver=_Members(near)), ADD_MEMBER, name="Hysam")
    assert said.status == "choose" and said.options == ("Hisham", "Hisham K")


async def test_a_new_person_is_offered_then_created_through_the_plan():
    created: list[tuple] = []

    async def create(name: str, event: Any, phone: str | None) -> ReplySpec:
        created.append((name, phone, event.fields["created_by_role"]))
        return ReplySpec(text="What is Ravi's WhatsApp number?")

    entry = _entry(member_resolver=_Members(Missing(name_hint="Ravi")), create_member=create)
    said = await _prepare(entry, ADD_MEMBER, name="Ravi")
    assert said.status == "choose" and said.options == ("Yes, add them", "No")
    assert created == []  # never without a yes
    said = await _prepare(entry, ADD_MEMBER, name="Ravi", new_person=True, phone="9876543210")
    assert said.status == "needs_answer" and "WhatsApp number" in said.text
    assert created == [("Ravi", "9876543210", "PROJECT_MANAGER")]


# -- correct the last quantity logged ---------------------------------------------


class _Activities:
    async def get_latest_quantity_update(self, *, organization_id: str, activity_id: str) -> dict | None:
        if activity_id != "a1":
            return None
        return {"progress_update_id": "p9", "quantity": 180, "unit": "sqm", "unit_id": "u-sqm", "work_type": "plastering", "narrative": "2nd floor"}


async def test_a_correction_targets_the_last_quantity_this_chat_logged():
    async def remembered() -> str:
        return "a1"

    entry = _entry(activity_query=_Activities(), remembered_activity=remembered)
    ready = await _prepare(entry, CORRECT_WORK_QUANTITY, new_quantity=150)
    assert ready.decision.workflow_key is WorkflowKey.ACTIVITY_CORRECTION
    f = ready.event.fields
    assert (f["progress_update_id"], f["old_quantity"], f["old_unit"], f["new_quantity"]) == ("p9", "180", "sqm", 150)
    assert f["correction_activity_summary"] == "plastering — 2nd floor"


async def test_with_nothing_logged_in_this_chat_the_workflow_says_so():
    entry = _entry(activity_query=_Activities(), remembered_activity=None)
    ready = await _prepare(entry, CORRECT_WORK_QUANTITY, new_quantity=150)
    assert "progress_update_id" not in ready.event.fields  # the workflow answers "nothing to correct"


# -- close, reopen or withdraw a site issue -----------------------------------------


class _Issues:
    def __init__(self) -> None:
        self.asked: dict = {}

    async def find_latest(self, **kwargs: Any) -> dict:
        self.asked = kwargs
        return {"site_issue_id": "i7", "issue_type": "EQUIPMENT_BREAKDOWN", "severity": "HIGH", "narrative": "JCB breakdown"}


async def test_fixed_resolves_the_latest_open_issue():
    issues = _Issues()
    ready = await _prepare(_entry(site_issue_query=issues), UPDATE_ISSUE, action="resolve", notes="mechanic came")
    assert ready.event.event_type is CanonicalEventType.SITE_ISSUE_RESOLVE_REQUESTED
    assert ready.decision.workflow_key is WorkflowKey.SITE_ISSUE_CLOSE
    assert ready.event.fields["site_issue_id"] == "i7" and ready.event.fields["resolution_notes"] == "mechanic came"
    assert issues.asked["statuses"] == ("OPEN", "ACKNOWLEDGED") and issues.asked["by_transition_time"] is False


async def test_reopen_looks_at_the_issue_closed_last():
    issues = _Issues()
    await _prepare(_entry(site_issue_query=issues), UPDATE_ISSUE, action="reopen")
    assert issues.asked["by_transition_time"] is True and "RESOLVED" in issues.asked["statuses"]


async def test_an_unknown_action_is_said_not_guessed():
    said = await _prepare(_entry(site_issue_query=_Issues()), UPDATE_ISSUE, action="delete")
    assert isinstance(said, Say) and said.status == "error"


def test_the_tools_map_to_their_semantic_types():
    assert to_candidate(ADD_MEMBER, {"name": "Ravi"}, ScopeLookup()).semantic_type is SemanticType.ADD_PROJECT_MEMBER
    assert to_candidate(CORRECT_WORK_QUANTITY, {"new_quantity": 3}, ScopeLookup()).semantic_type is SemanticType.ACTIVITY_CORRECTION
    assert to_candidate(UPDATE_ISSUE, {"action": "resolve"}, ScopeLookup()).semantic_type is SemanticType.SITE_ISSUE_UPDATE
