"""ARCH-03: labour attendance from the agent, without the classic pipeline.

Approved by Alan (Module Isolation: Labour/Attendance), relayed by Ilan on
22 Oct. The save_labour tool used to run through ``process_inbound_message``;
here, as for materials and site entries, its arguments become the workflow's
event:

- context, module switch ("labour"), project/site: ``entry_base.EntryScope``;
  a site is not required (the save needs only the project, as before);
- the lines, by the pipeline's own normaliser (``_normalize_labour_fields``)
  and the date (``resolve_occurred_date``, the company's day);
- the two lookups the pipeline ran before the graph, the same functions: the
  company's workers a named line may be (``_seed_worker_candidates``) and the
  day's attendance already recorded (``_seed_existing_attendance``: the BE-10
  snapshot or the "replace or add?" question).

The labour graph, save-first and everything after the save (worker
promotion, team photo) are unchanged.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from canonicalization.occurred_date import resolve_occurred_date
from channel.receipt.data import company_zone
from mesiri_contracts.assistant.canonical_event import CanonicalEventType
from mesiri_contracts.assistant.enums import InputModality, SemanticType
from mesiri_contracts.assistant.planner_decision import WorkflowKey
from workflows.registry import module_for_workflow

from .entry_base import SCOPE_KEYS, EntryScope, Ready, Say

_log = logging.getLogger("mesiri.agent")


@dataclass(slots=True)
class LabourEntry(EntryScope):
    context_resolver: Any
    org_settings_query: Any | None
    actor: Any
    active_context: Any | None = None
    workforce_query: Any | None = None

    async def prepare(self, message: Any, understanding: Any, candidate: Any) -> Ready | Say | None:
        """The workflow to start, or a line to say."""
        if getattr(candidate, "semantic_type", None) is not SemanticType.LABOUR_UPDATE:
            return None
        from canonicalization.builder import _normalize_labour_fields

        fields = {**candidate.fields, **candidate.unknown_fields}
        scoped = await self.settle(
            message, understanding, candidate, module=module_for_workflow(WorkflowKey.LABOUR_ATTENDANCE)
        )
        if isinstance(scoped, Say):
            return scoped

        for key in SCOPE_KEYS:
            fields.pop(key, None)
        metadata = getattr(message, "metadata", None) or {}
        if metadata.get("forwarded"):
            fields["is_forwarded"] = True
            if metadata.get("frequently_forwarded"):
                fields["is_frequently_forwarded"] = True
        fields = _normalize_labour_fields(
            fields, input_modality=getattr(message, "modality", None) or InputModality.TEXT
        )
        if not fields.get("lines"):
            return Say("error", "Not saved: who worked is needed (a name, or a trade and how many).")
        # The company's day: a blank or default "UTC" zone is India (22 Oct).
        fields = resolve_occurred_date(fields, timezone_name=str(company_zone(scoped.ctx.timezone)))

        ready = self.ready(
            scoped, message, CanonicalEventType.LABOUR_ATTENDANCE_REQUESTED, WorkflowKey.LABOUR_ATTENDANCE, fields
        )
        await self._seed(ready, message)
        return ready

    async def _seed(self, ready: Ready, message: Any) -> None:
        """What the pipeline looked up before the graph ran; each skips itself
        when its service is not wired. Never raises."""
        from runtime.inbound_journey.seeding import (
            _seed_existing_attendance,
            _seed_worker_candidates,
        )

        event, decision = ready.event, ready.decision
        for seed in (
            _seed_worker_candidates(event, decision, self.workforce_query, self.actor),
            _seed_existing_attendance(
                event, decision, self.workforce_query, self.actor, org_settings_query=self.org_settings_query
            ),
        ):
            try:
                await seed
            except Exception:  # noqa: BLE001 -- the graph goes on without it, as the pipeline would have failed
                _log.warning("labour_entry.seed_failed correlation_id=%s", message.correlation_id, exc_info=True)
