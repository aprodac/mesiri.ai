"""ARCH-06 step 2: lookups, transfers, site/project create and money undo from
the agent without the classic pipeline (Ilan, 22 Oct)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from tests.unit.test_material_entry import (
    MESSAGE,
    ORG,
    PRJ,
    SITE,
    _actor,
    _Context,
    _Understanding,
)

from mesiri_contracts.assistant.candidates import Candidate
from mesiri_contracts.assistant.canonical_event import CanonicalEventType
from mesiri_contracts.assistant.enums import SemanticType
from mesiri_contracts.assistant.planner_decision import WorkflowKey
from runtime.agent.entry_base import Ready, Say
from runtime.agent.query_entry import QueryEntry

SITE2 = "55555555-0000-4000-8000-000000000002"


def _entry(*, role: str = "PROJECT_MANAGER", context=None, sites=(SITE,), **services: Any) -> QueryEntry:
    actor = _actor(*sites, role=role)
    actor.organization_id = ORG
    actor.projects = [SimpleNamespace(id=PRJ, name="Villa")]
    return QueryEntry(context_resolver=context or _Context(), org_settings_query=None, actor=actor, **services)


async def _prepare(entry: QueryEntry, semantic_type: SemanticType, **fields: Any):
    candidate = Candidate(semantic_type=semantic_type, fields=fields)
    return await entry.prepare(MESSAGE, _Understanding(candidate), candidate)


async def test_a_lookup_over_several_sites_covers_the_project_without_asking():
    entry = _entry(context=_Context(site_id=None), sites=(SITE, SITE2))
    ready = await _prepare(entry, SemanticType.LABOUR_QUERY, date_range="today")
    assert isinstance(ready, Ready)
    assert ready.decision.workflow_key is WorkflowKey.LABOUR_QUERY
    assert str(ready.event.project_id) == PRJ and ready.event.site_id is None


async def test_a_lookup_never_answers_for_the_whole_company():
    """The query services read "no project" as "everything"."""
    said = await _prepare(_entry(context=_Context(project_id=None, site_id=None)), SemanticType.INVENTORY_QUERY)
    assert isinstance(said, Say) and said.status == "choose"


async def test_the_finance_lookup_and_undo_go_by_their_kind():
    balance = await _prepare(_entry(), SemanticType.FINANCE_QUERY, query_kind="balance")
    assert balance.event.event_type is CanonicalEventType.ACCOUNT_BALANCE_QUERY_ASKED
    assert balance.event.project_id is None  # accounts are company-wide
    expenses = await _prepare(_entry(), SemanticType.FINANCE_QUERY, query_kind="expenses")
    assert expenses.decision.workflow_key is WorkflowKey.EXPENSE_QUERY
    undo = await _prepare(_entry(), SemanticType.REVERSAL, target_kind="transfer")
    assert undo.event.event_type is CanonicalEventType.TRANSFER_REVERSAL_REQUESTED
    assert isinstance(await _prepare(_entry(), SemanticType.FINANCE_QUERY), Say)


async def test_only_an_admin_or_project_manager_creates_a_site_or_project():
    said = await _prepare(_entry(role="SITE_ENGINEER"), SemanticType.SITE_CREATE, name="Block C")
    assert isinstance(said, Say) and "Only an admin or project manager" in said.text
    ready = await _prepare(_entry(), SemanticType.SITE_CREATE, name="Block C")
    assert ready.event.fields["created_by_role"] == "PROJECT_MANAGER"
    assert str(ready.event.project_id) == PRJ
    project = await _prepare(_entry(role="ADMIN"), SemanticType.PROJECT_CREATE, name="Hospital")
    assert project.decision.workflow_key is WorkflowKey.PROJECT_CREATE and project.event.project_id is None


async def test_a_transfer_needs_an_amount():
    said = await _prepare(_entry(), SemanticType.TRANSFER, amount=0)
    assert isinstance(said, Say) and "amount above zero" in said.text


async def test_the_dpr_pdf_goes_after_the_answer_and_a_failure_is_said():
    class _Store:
        async def get_object(self, key: str) -> Any:
            return SimpleNamespace(data=b"%PDF")

    sent: list[str] = []

    async def send_document(wa_id: str, data: bytes, *, filename: str, caption: Any) -> bool:
        sent.append(filename)
        return len(sent) > 5  # fails both tries

    entry = _entry(object_storage=_Store(), send_document=send_document)
    ready = await _prepare(entry, SemanticType.DPR_REQUEST)
    ready.event.fields.update({"dpr_object_key": "k", "dpr_code": "DPR-1"})
    message = SimpleNamespace(correlation_id="c", sender=SimpleNamespace(wa_id="91"))
    line = await entry.deliver(ready, message)
    assert sent == ["DPR-1.pdf", "DPR-1.pdf"]
    assert line.startswith("Sorry, the PDF didn't go through")
