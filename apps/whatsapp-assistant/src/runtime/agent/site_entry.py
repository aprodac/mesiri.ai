"""ARCH-02: work done, site issues and expenses from the agent, without the classic pipeline.

The agent's save_work_done, report_issue, note_for_engineer and save_expense
used to run through ``process_inbound_message`` (canonicalize -> gates ->
planner -> graph) with its replies captured. Here, as for materials
(``material_entry.py``), the tool's arguments become the workflow's event:

- context, module switch, project/site: ``entry_base.EntryScope.settle``;
- the field fixes canonicalization made, by the same functions: the work
  narrative (``_ensure_site_update_narrative``), the percentage
  (``apply_progress``) and the date (``resolve_occurred_date``, now for work
  done too: "yesterday" was saved as today on the classic route);
- the seeds the pipeline ran before the graph, the same functions: the open
  activity a progress update may be about (``_seed_open_activity``); the
  expense's accounts, duplicate check and vendor (``_seed_account_candidates``,
  ``_seed_duplicate_check``, ``_seed_vendor_check``).

The save is unchanged: ``WorkflowRuntime.start`` + save-first (expenses stay
confirm-first, their graph's own questions included).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from canonicalization.occurred_date import resolve_occurred_date
from channel.receipt.data import company_zone
from mesiri_contracts.assistant.canonical_event import CanonicalEventType
from mesiri_contracts.assistant.enums import SemanticType
from mesiri_contracts.assistant.planner_decision import WorkflowKey
from workflows.registry import module_for_workflow

from .entry_base import SCOPE_KEYS, EntryScope, Ready, Say, number

_log = logging.getLogger("mesiri.agent")

_ROUTES = {
    SemanticType.GENERAL_SITE_UPDATE: (CanonicalEventType.GENERAL_SITE_UPDATE_REQUESTED, WorkflowKey.SITE_UPDATE),
    SemanticType.SITE_ISSUE: (CanonicalEventType.SITE_ISSUE_REPORTED, WorkflowKey.SITE_ISSUE_REPORT),
    SemanticType.EXPENSE: (CanonicalEventType.EXPENSE_REQUESTED, WorkflowKey.EXPENSE_SUBMIT),
}

#: The semantic types this entry takes.
SITE_ENTRY_TYPES = frozenset(_ROUTES)


@dataclass(slots=True)
class SiteEntry(EntryScope):
    context_resolver: Any
    org_settings_query: Any | None
    actor: Any
    active_context: Any | None = None
    activity_query: Any | None = None
    money_account_query: Any | None = None
    duplicate_expense_query: Any | None = None
    vendor_query: Any | None = None
    #: ``() -> activity id | None``: the activity this conversation last
    #: touched (memory's CurrentActivityStore), the classic route's first pick.
    remembered_activity: Callable[[], Awaitable[str | None]] | None = None

    async def prepare(self, message: Any, understanding: Any, candidate: Any) -> Ready | Say | None:
        """The workflow to start, a line to say, or None (use the classic route)."""
        route = _ROUTES.get(getattr(candidate, "semantic_type", None))
        if route is None:
            return None
        event_type, workflow_key = route
        fields = {**candidate.fields, **candidate.unknown_fields}

        if workflow_key is WorkflowKey.SITE_ISSUE_REPORT and not fields.get("issue_type"):
            return Say("error", "Not saved: the kind of issue is needed.")
        if workflow_key is WorkflowKey.EXPENSE_SUBMIT:
            amount = number(fields.get("amount"))
            if amount is None or amount <= 0:
                return Say("error", "Not saved: an amount above zero is needed.")

        scoped = await self.settle(
            message,
            understanding,
            candidate,
            module=module_for_workflow(workflow_key),
            # Work done is always at a site (the save refuses it without one).
            site_required=workflow_key is WorkflowKey.SITE_UPDATE,
            # So is an issue (request 104, D): asked which site, never "didn't go through".
            site_prompt=workflow_key is WorkflowKey.SITE_ISSUE_REPORT,
        )
        if isinstance(scoped, Say):
            return scoped

        for key in SCOPE_KEYS:
            fields.pop(key, None)
        continues = str(fields.pop("continues", "") or "").strip()
        metadata = getattr(message, "metadata", None) or {}
        if metadata.get("forwarded"):
            fields["is_forwarded"] = True
            if metadata.get("frequently_forwarded"):
                fields["is_frequently_forwarded"] = True
        if workflow_key is WorkflowKey.SITE_UPDATE:
            from canonicalization.builder import _ensure_site_update_narrative
            from canonicalization.progress import apply_progress, settle_place_and_status

            # The floor is settled before the percentage rebuilds the note from
            # the fields, and the status after it (it needs the percentage).
            fields = settle_place_and_status(_ensure_site_update_narrative(fields, understanding))
            fields = apply_progress(fields, None)
            if not fields.get("work_type"):
                # The model often names the work only inside its quantities
                # ("50 meter wiring": live golden set, 22 Oct).
                named = [q.get("work_type") for q in fields.get("quantities") or [] if isinstance(q, dict)]
                if named and named[0]:
                    fields["work_type"] = named[0]
            # Request 83: the floor and "finished" reach the card and the note
            # even when the model left them out of their fields.
            fields = settle_place_and_status(fields)
        # The card's rule: a blank or default "UTC" zone is India, so a 2:45 AM
        # entry lands on today, not yesterday (22 Oct).
        fields = resolve_occurred_date(fields, timezone_name=str(company_zone(scoped.ctx.timezone)))

        ready = self.ready(scoped, message, event_type, workflow_key, fields)
        await self._seed(ready, message)
        if continues and workflow_key is WorkflowKey.SITE_UPDATE:
            _continue(ready.event.fields, continues, message, remembered=await self._last_activity(message))
        return ready

    async def _last_activity(self, message: Any) -> str | None:
        if self.remembered_activity is None:
            return None
        try:
            return await self.remembered_activity()
        except Exception:  # noqa: BLE001 -- a hint only
            _log.warning("site_entry.remembered_failed correlation_id=%s", message.correlation_id, exc_info=True)
            return None

    async def _seed(self, ready: Ready, message: Any) -> None:
        """What the pipeline looked up before the graph ran; each seed skips
        itself when its service is not wired. Never raises."""
        from runtime.inbound_journey.seeding import (
            _seed_account_candidates,
            _seed_duplicate_check,
            _seed_open_activity,
            _seed_vendor_check,
        )

        event, decision, actor = ready.event, ready.decision, self.actor
        if decision.workflow_key is WorkflowKey.SITE_UPDATE:
            seeds = [_seed_open_activity(event, decision, self.activity_query, actor, org_settings_query=self.org_settings_query)]
        elif decision.workflow_key is WorkflowKey.EXPENSE_SUBMIT:
            seeds = [
                _seed_account_candidates(event, decision, self.money_account_query, actor),
                _seed_duplicate_check(event, decision, self.duplicate_expense_query, actor),
                _seed_vendor_check(event, decision, self.vendor_query, actor),
            ]
        else:
            seeds = []
        for seed in seeds:
            try:
                await seed
            except Exception:  # noqa: BLE001 -- the graph asks without it, as the pipeline did on a failure
                _log.warning("site_entry.seed_failed correlation_id=%s", message.correlation_id, exc_info=True)


def _continue(fields: dict[str, Any], continues: str, message: Any, *, remembered: str | None = None) -> None:
    """The model said which open activity this continues (it sees them in its
    context, and the conversation): when that is one of the seeded open
    activities, the update goes to it -- not a second activity for the same
    work, which the classic guess made whenever it was unsure (save-first
    treats an unclear match as new). Anything that matches none of them is
    left to that guess, as before -- unless the activity this conversation
    last touched is one of the open ones: the classic route's first pick, used
    here only when the model says this continues work."""
    from runtime.today_context import open_work_label
    from workflows.site_update.nodes import _apply_match

    candidates = fields.get("_open_activity_candidates") or []
    said = " ".join(continues.casefold().split())
    hits = [c for c in candidates if " ".join(open_work_label(c).casefold().split()) == said]
    if not hits:
        # A name given loosely ("plastering"): its work type, when only one
        # open activity has it.
        hits = [c for c in candidates if said and said == " ".join(str(c.get("work_type") or "").replace("_", " ").casefold().split())]
    if len(hits) != 1 and remembered:
        hits = [c for c in candidates if str(c.get("activity_id")) == str(remembered)]
    if len(hits) != 1:
        _log.info(
            "site_entry.continues_unmatched correlation_id=%s candidates=%s",
            message.correlation_id,
            len(candidates),
        )
        return
    hit = hits[0]
    fields.update(
        _apply_match(fields, activity_id=hit["activity_id"], work_type=hit.get("work_type"), narrative=hit.get("narrative"))
    )
    fields.pop("_open_activity_candidates", None)
