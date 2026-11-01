"""Request 200: a new project / site is a card line with Save / Cancel (like every write), never the
old Yes / No; details already given are reused; the created line names the project; no ** in replies."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from runtime.agent import tools as t
from runtime.agent.action_entry import ActionEntry
from runtime.agent.actions import CREATE_PROJECT, ActionService, ActionStore, PendingAction
from runtime.agent.entry_base import Say, Scoped
from runtime.agent.reply_clean import clean_model_text, whatsapp_bold
from runtime.agent.tools import ScopeLookup, to_candidate
from runtime.agent.wording import LANGUAGES, say


class _Redis:
    def __init__(self) -> None:
        self.data: dict[str, object] = {}

    def namespaced(self, key: str) -> str:
        return key

    async def set_json(self, key, value, *, ttl_seconds=None):  # noqa: ANN001
        self.data[key] = value

    async def get_json(self, key):  # noqa: ANN001
        return self.data.get(key)

    async def delete(self, key):  # noqa: ANN001
        self.data.pop(key, None)


def _actor(role="ADMIN", projects=()):
    return SimpleNamespace(
        role=role, organization_id=uuid.uuid4(), user_id=uuid.uuid4(),
        projects=[SimpleNamespace(id=pid, name=name) for pid, name in projects], sites=[],
    )


class _Entry(ActionEntry):
    async def settle(self, message, understanding, candidate, **kw):  # noqa: ANN001, ANN003
        pid = next((str(p.id) for p in self.actor.projects), None) if kw.get("project") == "required" else None
        return Scoped(SimpleNamespace(timezone=None), str(self.actor.organization_id), pid, None, None, None)


def _entry(actor):
    return _Entry(None, None, actor, SimpleNamespace(store=ActionStore(_Redis())))


def _candidate(tool, args, language="english"):
    c = to_candidate(tool, args, ScopeLookup())
    return c.model_copy(update={"fields": {**c.fields, "language": language}})


async def test_create_project_is_a_card_line_with_size_and_place():
    entry = _entry(_actor())
    got = await entry.prepare(SimpleNamespace(correlation_id="c"), None, _candidate(
        t.CREATE_PROJECT, {"name": "Sahal A", "size_sqft": 7000, "project_type": "G+1 supermarket", "location": "Kerala"}))
    assert isinstance(got, PendingAction) and got.kind == CREATE_PROJECT
    assert got.summary == "🏗️ New project: Sahal A · 7,000 sq ft · G+1 supermarket · Kerala"


async def test_details_given_before_the_name_are_kept_and_never_asked_again():
    entry = _entry(_actor())
    first = await entry.prepare(SimpleNamespace(correlation_id="c"), None, _candidate(
        t.CREATE_PROJECT, {"size_sqft": 7000, "location": "Kerala"}))
    assert isinstance(first, Say) and "name" in first.text
    second = await entry.prepare(SimpleNamespace(correlation_id="c"), None, _candidate(t.CREATE_PROJECT, {"name": "Sahal A"}))
    assert isinstance(second, PendingAction)
    assert "7,000 sq ft" in second.summary and "Kerala" in second.summary
    assert second.payload["size_text"] == "7,000 sq ft"
    # used once: a later, different project starts clean
    third = await entry.prepare(SimpleNamespace(correlation_id="c"), None, _candidate(t.CREATE_PROJECT, {"name": "Other"}))
    assert third.summary == "🏗️ New project: Other"


@pytest.mark.parametrize("role", ["WORKER", "SUPERVISOR", "SITE_ENGINEER"])
async def test_guard_a_worker_is_told_to_ask_the_admin(role):
    said = await _entry(_actor(role)).prepare(SimpleNamespace(correlation_id="c"), None, _candidate(t.CREATE_PROJECT, {"name": "X"}))
    assert isinstance(said, Say) and "admin or project manager" in said.text


async def test_a_name_that_exists_is_not_created_twice():
    entry = _entry(_actor(projects=[("p1", "Sahal A")]))
    said = await entry.prepare(SimpleNamespace(correlation_id="c"), None, _candidate(t.CREATE_PROJECT, {"name": " sahal  a "}))
    assert isinstance(said, Say) and "already exists" in said.text


async def test_create_site_is_a_card_line_under_the_project():
    entry = _entry(_actor(projects=[("p1", "Green Villa")]))
    got = await entry.prepare(SimpleNamespace(correlation_id="c"), None, _candidate(
        t.CREATE_SITE, {"name": "Block B", "project": "Green Villa"}))
    assert got.summary == "📍 New site: Block B · Green Villa"
    assert got.payload["project_id"] == "p1"


class _Dispatcher:
    def __init__(self, status):  # noqa: ANN001
        self.status, self.seen = status, []

    async def dispatch(self, confirmed):  # noqa: ANN001
        self.seen.append(confirmed)
        return SimpleNamespace(status=self.status, rejection_reasons=["name is too long"])


async def test_after_save_the_project_is_made_and_named_in_the_senders_language():
    from mesiri_contracts.application.results.execution_result import ExecutionStatus
    from mesiri_contracts.assistant.draft_action import DraftActionType

    dispatcher = _Dispatcher(ExecutionStatus.SUCCEEDED)
    service = ActionService(store=ActionStore(_Redis()), db=None, actor_reader=None, dispatcher=dispatcher)
    actor = _actor()
    action = PendingAction("a" * 32, CREATE_PROJECT, {"name": "Sahal A", "location": "Kerala", "description": "7,000 sq ft",
                                                       "size_text": "7,000 sq ft", "language": "english"}, "x")
    line = await service.run(action, actor, None)
    assert line == "Project Sahal A created ✅ (7,000 sq ft). Send its updates now, or tell me what's next."
    draft = dispatcher.seen[0].draft_action
    assert draft.action_type is DraftActionType.CREATE_PROJECT and draft.fields["created_by_role"] == "ADMIN"
    action.payload["language"] = "manglish"
    assert "Sahal A undaakki" in await service.run(action, actor, None)


async def test_a_refusal_is_said_not_claimed_as_created():
    from mesiri_contracts.application.results.execution_result import ExecutionStatus

    service = ActionService(store=ActionStore(_Redis()), db=None, actor_reader=None, dispatcher=_Dispatcher(ExecutionStatus.REJECTED))
    line = await service.run(PendingAction("b" * 32, CREATE_PROJECT, {"name": "X"}, "x"), _actor(), None)
    assert line.startswith("❌ Not created") and "created ✅" not in line


def test_the_created_lines_exist_in_every_language():
    for key in ("project.created", "site.created"):
        for language in LANGUAGES:
            assert say(key, language, name="N", size="", project="P")


def test_replies_never_carry_double_stars():
    assert whatsapp_bold("Please tap **Yes** below") == "Please tap *Yes* below"
    assert "**" not in clean_model_text("Tap **Yes** to confirm, or **No**.")
