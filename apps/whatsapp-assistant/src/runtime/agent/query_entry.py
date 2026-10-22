"""ARCH-06 step 2: lookups, transfers, site/project creation and money undo from
the agent, without the classic pipeline (Ilan, 22 Oct).

These tools used to run through ``process_inbound_message``. Here, as for the
entries (``site_entry.py``, ``labour_entry.py``, ``material_entry.py``), the
tool's arguments become the workflow's event:

- context, module switch, project/site: ``entry_base.EntryScope.settle``. A
  lookup never answers for the whole company by accident: the ones whose
  services read "no project" as "everything" require a project; with several
  sites, a lookup covers the whole project instead of asking which site.
- who may create a project or site: the pipeline's own rule and words
  (admin or project manager), checked before the workflow starts;
- the data each workflow answers from, by the pipeline's own seed functions
  (``runtime/inbound_journey/seeding.py``), so the read rules in them
  (SEC-01: expenses for admin/owner/finance/PM, own projects only) hold.

The workflows, their answers and confirmations are unchanged. The DPR PDF is
sent after the run, as the pipeline did (``deliver``).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from channel.receipt.data import company_zone
from mesiri_contracts.assistant.canonical_event import CanonicalEventType as E
from mesiri_contracts.assistant.enums import SemanticType as T
from mesiri_contracts.assistant.planner_decision import WorkflowKey as K
from workflows.registry import module_for_event

from .entry_base import SCOPE_KEYS, EntryScope, Ready, Say, number

_log = logging.getLogger("mesiri.agent")

#: semantic type -> (event type, workflow, settle options)
_LOOKUP = {"project": "required", "ask_site": False, "lookup": True}
_ROUTES: dict[Any, tuple[E, K, dict[str, Any]]] = {
    T.LABOUR_QUERY: (E.LABOUR_QUERY_ASKED, K.LABOUR_QUERY, _LOOKUP),
    T.INVENTORY_QUERY: (E.INVENTORY_QUERY_ASKED, K.MATERIAL_INVENTORY_QUERY, _LOOKUP),
    T.ACTIVITY_QUERY: (E.ACTIVITY_QUERY_ASKED, K.ACTIVITY_QUERY, _LOOKUP),
    T.PROJECT_DETAIL_QUERY: (E.PROJECT_DETAIL_QUERY_ASKED, K.PROJECT_DETAIL_QUERY, _LOOKUP),
    T.DPR_REQUEST: (E.DPR_REQUESTED, K.DPR_REQUEST, _LOOKUP),
    T.TRANSFER: (E.TRANSFER_REQUESTED, K.TRANSFER, {"project": "none"}),
    T.SITE_CREATE: (E.SITE_CREATE_REQUESTED, K.SITE_CREATE, {"project": "required", "ask_site": False}),
    T.PROJECT_CREATE: (E.PROJECT_CREATE_REQUESTED, K.PROJECT_CREATE, {"project": "none"}),
}
_FINANCE = {
    "balance": (E.ACCOUNT_BALANCE_QUERY_ASKED, K.ACCOUNT_BALANCE_QUERY, {"project": "none", "lookup": True}),
    "expenses": (
        E.EXPENSE_QUERY_ASKED,
        K.EXPENSE_QUERY,
        {"project": "optional", "ask_site": False, "lookup": True},
    ),
}
_REVERSAL = {
    "expense": (E.EXPENSE_REVERSAL_REQUESTED, K.REVERSE, {"project": "optional", "ask_site": False}),
    "transfer": (E.TRANSFER_REVERSAL_REQUESTED, K.REVERSE, {"project": "none"}),
    "petty_cash": (E.PETTY_CASH_REVERSAL_REQUESTED, K.REVERSE, {"project": "none"}),
}

#: The semantic types this entry takes.
QUERY_ENTRY_TYPES = frozenset({*_ROUTES, T.FINANCE_QUERY, T.REVERSAL})


def _route(semantic_type: Any, fields: dict[str, Any]) -> tuple[E, K, dict[str, Any]] | None:
    if semantic_type is T.FINANCE_QUERY:
        return _FINANCE.get(str(fields.get("query_kind") or ""))
    if semantic_type is T.REVERSAL:
        return _REVERSAL.get(str(fields.get("target_kind") or ""))
    return _ROUTES.get(semantic_type)


@dataclass(slots=True)
class QueryEntry(EntryScope):
    context_resolver: Any
    org_settings_query: Any | None
    actor: Any
    active_context: Any | None = None
    inventory_query: Any | None = None
    labour_query_service: Any | None = None
    activity_search_service: Any | None = None
    dpr_request_query: Any | None = None
    project_detail_query: Any | None = None
    expense_query_service: Any | None = None
    money_account_query: Any | None = None
    reversal_query: Any | None = None
    object_storage: Any | None = None
    #: ``(wa_id, data, *, filename, caption) -> bool``: the DPR PDF.
    send_document: Callable[..., Awaitable[Any]] | None = None

    async def prepare(self, message: Any, understanding: Any, candidate: Any) -> Ready | Say | None:
        """The workflow to start, a line to say, or None (not one of these)."""
        semantic_type = getattr(candidate, "semantic_type", None)
        if semantic_type not in QUERY_ENTRY_TYPES:
            return None
        fields = {**candidate.fields, **candidate.unknown_fields}
        route = _route(semantic_type, fields)
        if route is None:
            return Say("error", "Couldn't do that: it was not clear what to look up or undo.")
        event_type, workflow_key, options = route

        if workflow_key is K.TRANSFER:
            amount = number(fields.get("amount"))
            if amount is None or amount <= 0:
                return Say("error", "Not saved: an amount above zero is needed.")
        if workflow_key in (K.SITE_CREATE, K.PROJECT_CREATE):
            from runtime.inbound_journey.process import (
                _PROJECT_CREATE_DENIED_REPLY,
                _PROJECT_CREATE_ROLES,
                _SITE_CREATE_DENIED_REPLY,
            )

            if str(getattr(self.actor, "role", "") or "").strip().upper() not in _PROJECT_CREATE_ROLES:
                denied = _SITE_CREATE_DENIED_REPLY if workflow_key is K.SITE_CREATE else _PROJECT_CREATE_DENIED_REPLY
                return Say("info", denied)
            if not str(fields.get("name") or "").strip():
                return Say("error", "Not saved: the name is needed.")

        scoped = await self.settle(
            message, understanding, candidate, module=module_for_event(workflow_key, fields), **options
        )
        if isinstance(scoped, Say):
            return scoped
        for key in SCOPE_KEYS:
            fields.pop(key, None)
        ready = self.ready(scoped, message, event_type, workflow_key, fields)
        await self._seed(ready, message, timezone=str(company_zone(scoped.ctx.timezone)))
        return ready

    async def _seed(self, ready: Ready, message: Any, *, timezone: str) -> None:
        """The data the workflow answers from, by the pipeline's own seeds.
        Never raises: a failed seed answers from what it has, as before."""
        from runtime.inbound_journey import seeding as s

        event, decision, actor, key = ready.event, ready.decision, self.actor, ready.decision.workflow_key
        if key is K.MATERIAL_INVENTORY_QUERY:
            seeds = [s._inject_inventory_context(event, self.inventory_query)]
        elif key is K.LABOUR_QUERY:
            seeds = [s._seed_labour_query(event, decision, self.labour_query_service, actor, timezone)]
        elif key is K.ACTIVITY_QUERY:
            seeds = [s._seed_activity_search(event, decision, self.activity_search_service, actor, timezone)]
        elif key is K.DPR_REQUEST:
            seeds = [
                s._seed_dpr_request(
                    event, decision, self.dpr_request_query, actor, timezone, object_storage=self.object_storage
                )
            ]
        elif key is K.PROJECT_DETAIL_QUERY:
            seeds = [
                s._seed_project_detail_query(
                    event,
                    decision,
                    self.activity_search_service,
                    self.labour_query_service,
                    self.expense_query_service,
                    self.inventory_query,
                    self.project_detail_query,
                    actor,
                    timezone,
                )
            ]
        elif key in (K.ACCOUNT_BALANCE_QUERY, K.EXPENSE_QUERY):
            seeds = [s._seed_finance_query_context(event, decision, self.money_account_query, self.expense_query_service, actor)]
        elif key is K.TRANSFER:
            seeds = [s._seed_account_candidates(event, decision, self.money_account_query, actor)]
        elif key is K.REVERSE:
            seeds = [s._seed_reversal_target(event, decision, self.reversal_query, actor)]
        else:
            seeds = []
        if key in (K.SITE_CREATE, K.PROJECT_CREATE):
            s._seed_project_create_role(event, decision, actor)
        for seed in seeds:
            try:
                await seed
            except Exception:  # noqa: BLE001 -- the workflow answers from what it has
                _log.warning("query_entry.seed_failed correlation_id=%s key=%s", message.correlation_id, key.value, exc_info=True)

    async def deliver(self, ready: Ready, message: Any) -> str | None:
        """After the run: the DPR PDF the answer says is attached, as the
        pipeline sent it (one retry). A line to add when it did not go."""
        fields = ready.event.fields
        if ready.decision.workflow_key is not K.DPR_REQUEST or not fields.get("dpr_object_key"):
            return None
        if self.send_document is None or self.object_storage is None:
            return None
        from runtime.inbound_journey.process import _send_with_one_retry

        code = fields.get("dpr_code") or "DPR"

        async def _send() -> None:
            stored = await self.object_storage.get_object(fields["dpr_object_key"])
            sent = await self.send_document(message.sender.wa_id, stored.data, filename=f"{code}.pdf", caption=None)
            if sent is False:
                raise RuntimeError("send_document returned False")

        if await _send_with_one_retry(_send, what="dpr_request.document", correlation_id=message.correlation_id):
            return None
        return f"Sorry, the PDF didn't go through. The report ({code}) is ready, please ask again in a minute."
