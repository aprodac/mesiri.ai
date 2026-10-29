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


async def test_the_dpr_is_not_a_query_entry_type():
    """Request 143: the DPR is report_entry's (a PDF from Day Facts), not a lookup's."""
    from runtime.agent.query_entry import QUERY_ENTRY_TYPES

    assert SemanticType.DPR_REQUEST not in QUERY_ENTRY_TYPES


async def test_a_lookup_asked_for_as_a_pdf_is_sent_as_one():
    """The classic "send it as a PDF" of a lookup, from the agent's as_pdf."""
    from runtime.agent.tools import QUERY_MATERIALS, ScopeLookup, to_candidate

    sent: list[tuple[str, bytes]] = []

    async def send_document(wa_id: str, data: bytes, *, filename: str, caption: Any, shows=None) -> bool:
        sent.append((filename, data[:4]))
        return True

    candidate = to_candidate(QUERY_MATERIALS, {"material": "cement", "as_pdf": True}, ScopeLookup())
    assert candidate.fields["output_format"] == "pdf"
    entry = _entry(send_document=send_document)
    ready = await entry.prepare(MESSAGE, _Understanding(candidate), candidate)
    ready.event.fields["inventory_levels"] = [{"material_name": "Cement", "on_hand": 40, "unit": "bags"}]
    message = SimpleNamespace(correlation_id="c", sender=SimpleNamespace(wa_id="91"))
    assert await entry.deliver(ready, message) is None
    assert len(sent) == 1 and sent[0][0].endswith(".pdf") and sent[0][1] == b"%PDF"
    without = to_candidate(QUERY_MATERIALS, {"material": "cement"}, ScopeLookup())
    assert "output_format" not in without.fields


class _WorkLog:
    """Records the dates the work-log lookup was asked for."""

    def __init__(self) -> None:
        self.asked: list[tuple[Any, Any]] = []

    async def search(self, *, start_date: Any, end_date: Any, **kwargs: Any) -> dict[str, Any]:
        self.asked.append((start_date, end_date))
        return {"activities": [], "open_issues": []}


async def test_wrk03_what_was_done_yesterday_is_asked_for_yesterday_in_the_project_zone():
    """The audit's "answers today": the lookup is for the project's yesterday,
    whatever day it is on the host (two zones 25 hours apart, so one of them
    is never the host's date)."""
    from runtime.agent.project_day import project_yesterday

    for zone in ("Pacific/Kiritimati", "Pacific/Pago_Pago"):
        log = _WorkLog()
        context = _Context()
        context.ctx.timezone = zone
        entry = _entry(activity_search_service=log, context=context)
        ready = await _prepare(entry, SemanticType.ACTIVITY_QUERY, date_range="yesterday")
        assert isinstance(ready, Ready)
        yesterday = project_yesterday(zone)
        assert log.asked == [(yesterday, yesterday)], zone
        assert ready.event.fields["activity_search_results"]["date_range_label"].lower().startswith("yesterday")
