"""ARCH-02: work done, site issues and expenses from the agent without the classic pipeline.

The fixes canonicalization made and the seeds the pipeline ran come from the
same functions; what changed is that a work entry's date is now resolved
("yesterday" was saved as today on the classic route).
"""

from __future__ import annotations

import datetime
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

from tests.unit.test_material_entry import (
    MESSAGE,
    ORG,
    PRJ,
    SITE,
    _actor,
    _Context,
    _Modules,
    _Understanding,
)

from mesiri_contracts.assistant.candidates import Candidate
from mesiri_contracts.assistant.canonical_event import CanonicalEventType
from mesiri_contracts.assistant.enums import SemanticType
from mesiri_contracts.assistant.planner_decision import WorkflowKey
from runtime.agent.entry_base import Ready, Say
from runtime.agent.site_entry import SiteEntry


class _Accounts:
    async def list_accounts(self, **kwargs: Any) -> list[Any]:
        return [SimpleNamespace(id="acc-1", name="Site cash"), SimpleNamespace(id="acc-2", name="HDFC")]


def _site_actor() -> Any:
    actor = _actor(SITE)
    actor.organization_id = ORG
    return actor


def _entry(*, modules=None, context=None, **services: Any) -> SiteEntry:
    return SiteEntry(
        context_resolver=context or _Context(),
        org_settings_query=modules,
        actor=_site_actor(),
        **services,
    )


async def _prepare(entry: SiteEntry, semantic_type: SemanticType, message: Any = MESSAGE, **fields: Any):
    candidate = Candidate(semantic_type=semantic_type, fields=fields)
    return await entry.prepare(message, _Understanding(candidate), candidate)


def _yesterday() -> str:
    return (datetime.datetime.now(ZoneInfo("Asia/Kolkata")).date() - datetime.timedelta(days=1)).isoformat()


async def test_work_done_is_ready_with_its_percentage_and_its_stated_date():
    ready = await _prepare(
        _entry(),
        SemanticType.GENERAL_SITE_UPDATE,
        narrative="slab concreting",
        work_type="concreting",
        progress_percent=40,
        occurred_on="yesterday",
        project_id=PRJ,
    )
    assert isinstance(ready, Ready)
    assert ready.decision.workflow_key is WorkflowKey.SITE_UPDATE
    assert ready.event.event_type is CanonicalEventType.GENERAL_SITE_UPDATE_REQUESTED
    fields = ready.event.fields
    assert fields["progress_percent"] == 40
    assert "40%" in fields["narrative"]
    assert (fields["occurred_date"], fields["occurred_date_source"]) == (_yesterday(), "stated_by_user")
    assert "project_id" not in fields and "occurred_on" not in fields
    assert (str(ready.event.project_id), str(ready.event.site_id)) == (PRJ, SITE)


async def test_an_issue_keeps_its_fields_and_the_engineer_question_prefix():
    ready = await _prepare(
        _entry(),
        SemanticType.SITE_ISSUE,
        issue_type="OTHER",
        severity="LOW",
        narrative="Question for your engineer: can we cast the slab tomorrow?",
    )
    assert isinstance(ready, Ready)
    assert ready.decision.workflow_key is WorkflowKey.SITE_ISSUE_REPORT
    assert ready.event.fields["narrative"].startswith("Question for your engineer: ")
    assert ready.event.fields["occurred_date_source"] == "inferred_at_confirmation"


async def test_an_issue_without_its_kind_and_an_expense_without_an_amount_are_refused():
    assert isinstance(await _prepare(_entry(), SemanticType.SITE_ISSUE, narrative="leak"), Say)
    said = await _prepare(_entry(), SemanticType.EXPENSE, amount=0, description="tea")
    assert isinstance(said, Say) and "amount above zero" in said.text


async def test_an_expense_is_seeded_with_the_accounts_to_choose_from():
    ready = await _prepare(_entry(money_account_query=_Accounts()), SemanticType.EXPENSE, amount=500, description="tea")
    assert isinstance(ready, Ready)
    assert ready.decision.workflow_key is WorkflowKey.EXPENSE_SUBMIT
    assert [a["id"] for a in ready.event.fields["account_candidates"]] == ["acc-1", "acc-2"]


async def test_a_switched_off_module_is_said_not_saved():
    said = await _prepare(_entry(modules=_Modules(["dpr"])), SemanticType.EXPENSE, amount=500)
    assert isinstance(said, Say) and said.status == "info"
    ready = await _prepare(_entry(modules=_Modules(["dpr"])), SemanticType.SITE_ISSUE, issue_type="WEATHER")
    assert isinstance(ready, Ready)  # issues and work done need "dpr", expenses "finance"


async def test_a_forwarded_message_is_marked_as_the_pipeline_marked_it():
    message = SimpleNamespace(correlation_id="cor_2", message_id="wamid.2", metadata={"forwarded": True})
    ready = await _prepare(_entry(), SemanticType.SITE_ISSUE, message, issue_type="WEATHER")
    assert ready.event.fields["is_forwarded"] is True


async def test_no_project_asks_which_one_and_other_kinds_go_classic():
    said = await _prepare(_entry(context=_Context(project_id=None, site_id=None)), SemanticType.SITE_ISSUE, issue_type="WEATHER")
    assert isinstance(said, Say) and said.status in ("choose", "info")
    assert await _prepare(_entry(), SemanticType.LABOUR_UPDATE, workers=[]) is None


async def test_work_named_only_in_its_quantities_gets_its_work_type():
    """Live golden set, 22 Oct: '50 meter wiring ho gaya' came with the work
    named only inside quantities."""
    ready = await _prepare(
        _entry(),
        SemanticType.GENERAL_SITE_UPDATE,
        narrative="aaj 50 meter wiring ho gaya",
        quantities=[{"work_type": "wiring", "quantity": 50, "unit": "m"}],
    )
    assert ready.event.fields["work_type"] == "wiring"


async def test_work_with_no_site_of_the_senders_says_so_instead_of_failing_at_save():
    """Live 22 Oct (Hospital Project): a PM with custom site access and no site
    got "which site?" with nothing to pick; the save refuses work without one."""
    entry = _entry(context=_Context(site_id=None))
    entry.actor.sites = []
    said = await _prepare(entry, SemanticType.GENERAL_SITE_UPDATE, narrative="slab concreting")
    assert isinstance(said, Say) and said.status == "info"
    assert "not on any site of this project" in said.text
    # An issue or an expense still goes through without a site, as before.
    ready = await _prepare(entry, SemanticType.SITE_ISSUE, issue_type="WEATHER")
    assert isinstance(ready, Ready) and ready.event.site_id is None


class _Today:
    """The active context: today's site (WA-45) or the last one saved to."""

    def __init__(self, project_id: str, site_id: str) -> None:
        self.slot = SimpleNamespace(project_id=project_id, site_id=site_id)

    async def get_active_context(self, **kwargs: Any) -> Any:
        return self.slot


async def test_todays_site_wins_over_the_context_layers_other_project():
    """Live 22 Oct: an admin set Tower A as today's site; the context layer
    (members-only rule) resolved another project with no site of theirs, and
    the work was refused. Unnamed, today's site from their own list is used."""
    other = "99999999-9999-4999-8999-999999999999"
    entry = _entry(context=_Context(project_id=other, site_id=None))
    entry.active_context = _Today(PRJ, SITE)
    ready = await _prepare(entry, SemanticType.GENERAL_SITE_UPDATE, narrative="slab concreting")
    assert isinstance(ready, Ready)
    assert (str(ready.event.project_id), str(ready.event.site_id)) == (PRJ, SITE)
    # A message that names a project still goes by what it names.
    named = await _prepare(entry, SemanticType.SITE_ISSUE, issue_type="WEATHER", project_name="Other")
    assert isinstance(named, Ready) and str(named.event.project_id) == other
