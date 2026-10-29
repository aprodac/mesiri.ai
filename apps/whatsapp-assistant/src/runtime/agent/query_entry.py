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

The workflows, their answers and confirmations are unchanged. A lookup asked for
as a PDF (``as_pdf``) is sent after the run, as the pipeline did (``deliver``).
The DPR is not a lookup here: ``report_entry.py`` makes and sends it from Day
Facts (request 143).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from mesiri_contracts.assistant.canonical_event import CanonicalEventType as E
from mesiri_contracts.assistant.enums import SemanticType as T
from mesiri_contracts.assistant.planner_decision import WorkflowKey as K
from workflows.registry import module_for_event

from .entry_base import ALL_SITES, SCOPE_KEYS, EntryScope, Ready, Say, number
from .project_day import project_zone_name

_log = logging.getLogger("mesiri.agent")

#: semantic type -> (event type, workflow, settle options)
_LOOKUP = {"project": "required", "ask_site": False, "lookup": True}
_ROUTES: dict[Any, tuple[E, K, dict[str, Any]]] = {
    T.LABOUR_QUERY: (E.LABOUR_QUERY_ASKED, K.LABOUR_QUERY, _LOOKUP),
    T.INVENTORY_QUERY: (E.INVENTORY_QUERY_ASKED, K.MATERIAL_INVENTORY_QUERY, _LOOKUP),
    T.ACTIVITY_QUERY: (E.ACTIVITY_QUERY_ASKED, K.ACTIVITY_QUERY, _LOOKUP),
    T.PROJECT_DETAIL_QUERY: (E.PROJECT_DETAIL_QUERY_ASKED, K.PROJECT_DETAIL_QUERY, _LOOKUP),
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


def _one_name_per_trade(results: Any) -> None:
    """Request 88: the trades a labour answer lists, each once. Stored trade
    codes differ in spelling ("mason" and "masons", "bar_bending" and
    "bar_bender"); the workforce module's own trade mapping says which are the
    same, so the answer names each trade once. Request 94: and with its
    headcount (``trade_counts``, from the saved lines), so "trade wise" is
    always answered with numbers. Only what is shown changes."""
    if not isinstance(results, dict) or not results.get("trades"):
        return
    from mesiri.domains.workforce.workers import normalize_trade

    def name(trade: Any) -> str:
        return normalize_trade(trade) or str(trade)

    seen: dict[str, str] = {}
    for trade in results["trades"]:
        seen.setdefault(name(trade), name(trade))
    results["trades"] = list(seen.values())
    counts: dict[str, int] = dict.fromkeys(seen, 0)
    for row in results.get("rows") or []:
        trade = str(row.get("trade") or "").strip()
        if trade:
            counts[name(trade)] = counts.get(name(trade), 0) + int(row.get("headcount") or 1)
    if any(counts.values()):
        results["trade_counts"] = [[trade, count] for trade, count in counts.items()]


@dataclass(slots=True)
class QueryEntry(EntryScope):
    context_resolver: Any
    org_settings_query: Any | None
    actor: Any
    active_context: Any | None = None
    inventory_query: Any | None = None
    labour_query_service: Any | None = None
    activity_search_service: Any | None = None
    project_detail_query: Any | None = None
    expense_query_service: Any | None = None
    money_account_query: Any | None = None
    reversal_query: Any | None = None
    object_storage: Any | None = None
    #: ``(wa_id, data, *, filename, caption) -> bool``: a lookup asked for as a PDF.
    send_document: Callable[..., Awaitable[Any]] | None = None
    #: Request 91: the receipt's renderer, for the Stock card; None draws none.
    card_renderer: Any | None = None
    #: The Stock card PNG for this turn's all-materials answer (set by
    #: ``deliver``, read by the journey when it sends the reply), else None.
    stock_card: bytes | None = None

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
            from runtime.inbound_journey._shared import (
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
        for key in (*SCOPE_KEYS, ALL_SITES):
            fields.pop(key, None)
        ready = self.ready(scoped, message, event_type, workflow_key, fields)
        timezone = project_zone_name(scoped.ctx.timezone)
        await self._seed(ready, message, timezone=timezone)
        return ready

    async def _seed(self, ready: Ready, message: Any, *, timezone: str) -> None:
        """The data the workflow answers from, by the pipeline's own seeds.
        Never raises: a failed seed answers from what it has, as before."""
        from runtime.inbound_journey import seeding as s

        event, decision, actor, key = ready.event, ready.decision, self.actor, ready.decision.workflow_key
        if key is K.MATERIAL_INVENTORY_QUERY:
            seeds = [s._inject_inventory_context(event, self.inventory_query, timezone)]
        elif key is K.LABOUR_QUERY:
            seeds = [s._seed_labour_query(event, decision, self.labour_query_service, actor, timezone)]
        elif key is K.ACTIVITY_QUERY:
            seeds = [
                s._seed_activity_search(
                    event, decision, self.activity_search_service, actor, timezone,
                    labour_query_service=self.labour_query_service,
                    inventory_query=self.inventory_query,
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
        if key is K.LABOUR_QUERY:
            _one_name_per_trade(event.fields.get("labour_results"))
        elif key is K.ACTIVITY_QUERY:
            _one_name_per_trade((event.fields.get("activity_search_results") or {}).get("labour"))

    async def _stock_card(self, ready: Ready) -> None:
        """Request 91: for an all-materials question (no one material named,
        2+ rows) draw the Stock card; the journey sends it with the reply as
        its caption. Any failure leaves ``stock_card`` None: the reply is
        the text, as before."""
        self.stock_card = None
        fields, event = ready.event.fields, ready.event
        levels = fields.get("inventory_levels") or []
        if self.card_renderer is None or fields.get("material_name") or len(levels) < 2:
            return
        try:
            from channel.cards import build_stock_card, render_png, stock_html

            usage: dict[tuple[str, str], float] = {}
            if self.inventory_query is not None:
                try:
                    usage = await self.inventory_query.usage_last_days(
                        organization_id=event.organization_id,
                        project_id=event.project_id,
                        site_id=event.site_id,
                    )
                except Exception:  # noqa: BLE001 -- no usage figures, no "days left"
                    _log.warning("query_entry.stock_usage_failed", exc_info=True)
            site = next(
                (s.name for s in getattr(self.actor, "sites", None) or () if str(s.id) == str(event.site_id)),
                None,
            )
            card = build_stock_card(levels, usage, where=site or getattr(self.actor, "org_name", None) or "Site")
            self.stock_card = await render_png(self.card_renderer, stock_html(card), card="stock")
        except Exception:  # noqa: BLE001 -- the card is an extra
            _log.warning("query_entry.stock_card_failed", exc_info=True)

    async def deliver(self, ready: Ready, message: Any) -> str | None:
        """After the run: a lookup asked for as a PDF, sent as the pipeline
        sent it (one retry). A line to add when it did not go. (The DPR is
        ``report_entry``'s.)"""
        fields = ready.event.fields
        key = ready.decision.workflow_key
        if key is K.MATERIAL_INVENTORY_QUERY and fields.get("output_format") != "pdf":
            await self._stock_card(ready)
        if self.send_document is None:
            return None
        from runtime.inbound_journey._shared import _send_with_one_retry

        if fields.get("output_format") == "pdf":
            from runtime.inbound_journey.seeding import _build_query_pdf

            built = _build_query_pdf(key, fields)
            if built is None:
                return None
            data, filename = built

            async def _send_pdf() -> None:
                sent = await self.send_document(message.sender.wa_id, data, filename=filename, caption=None)
                if sent is False:
                    raise RuntimeError("send_document returned False")

            if await _send_with_one_retry(_send_pdf, what="query_pdf", correlation_id=message.correlation_id):
                return None
            return "Sorry, the PDF didn't go through. Please ask again in a minute."
        return None
