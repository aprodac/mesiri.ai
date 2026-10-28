"""Adding a team member, correcting a work quantity and closing a site issue,
from the agent (22 Oct, Ilan: the three things the classic pipeline did that
the agent had no tool for).

As for the other entries, the tool's arguments become the workflow's event:
context and scope by ``entry_base.EntryScope.settle``, and what the pipeline
looked up before the graph by the same rules, now here:

- add_member: the name is matched against the company's active users before a
  draft (ENTITY_RESOLUTION_PLAN.md ADR-E1): one match is used, near matches
  are a question, and a new person is offered -- to a role that may create
  users -- through the existing CREATE_USER -> ADD_PROJECT_MEMBER plan
  (``runtime/member_create_plan.py``). Only an admin or project manager adds.
- correct_work_quantity: the newest amount on the activity this conversation
  last touched, else the sender's own newest amount of the last two days, read
  from the Day Facts (runtime/day_facts.py, request 137 -- the one reader of
  saved work); nothing to correct is said plainly by the workflow. draft_v2
  senders never reach this: their correction is resolved in the toolbox.
- update_issue: the latest site issue in a status the action may change
  (the executor re-checks it at Yes).

The workflows, their confirmations and the backend's own checks are unchanged.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from mesiri_contracts.assistant.canonical_event import CanonicalEventType as E
from mesiri_contracts.assistant.enums import SemanticType as T
from mesiri_contracts.assistant.planner_decision import WorkflowKey as K
from workflows.registry import module_for_workflow

from .entry_base import SCOPE_KEYS, EntryScope, Ready, Say, choose

_log = logging.getLogger("mesiri.agent")

_ISSUE_EVENTS = {
    "acknowledge": E.SITE_ISSUE_ACKNOWLEDGE_REQUESTED,
    "resolve": E.SITE_ISSUE_RESOLVE_REQUESTED,
    "wont_fix": E.SITE_ISSUE_WONT_FIX_REQUESTED,
    "cancel": E.SITE_ISSUE_CANCEL_REQUESTED,
    "reopen": E.SITE_ISSUE_REOPEN_REQUESTED,
}
_LIVE = ("OPEN", "ACKNOWLEDGED")
#: Which statuses each action may target (progress_execution.py re-checks the
#: same rule against the row at Yes).
_ISSUE_TARGETS = {
    "acknowledge": ("OPEN",),
    "resolve": _LIVE,
    "wont_fix": _LIVE,
    "cancel": _LIVE,
    "reopen": ("ACKNOWLEDGED", "RESOLVED", "WONT_FIX"),
}
_ADD_MEMBER_DENIED = "Only an admin or project manager can add someone to a project."

#: The semantic types this entry takes.
CHANGE_ENTRY_TYPES = frozenset({T.ADD_PROJECT_MEMBER, T.ACTIVITY_CORRECTION, T.SITE_ISSUE_UPDATE})


@dataclass(slots=True)
class ChangeEntry(EntryScope):
    context_resolver: Any
    org_settings_query: Any | None
    actor: Any
    active_context: Any | None = None
    member_resolver: Any | None = None
    activity_query: Any | None = None
    site_issue_query: Any | None = None
    #: Request 137: the day's work facts (runtime/day_facts.DayFactsReader).
    day_facts: Any | None = None
    #: ``() -> activity id | None``: the activity this conversation last touched.
    remembered_activity: Callable[[], Awaitable[str | None]] | None = None
    #: ``(name, event, phone) -> ReplySpec | None``: starts CREATE_USER and holds
    #: the add (runtime/member_create_plan.start_member_create_plan).
    create_member: Callable[..., Awaitable[Any]] | None = None

    async def prepare(self, message: Any, understanding: Any, candidate: Any) -> Ready | Say | None:
        semantic_type = getattr(candidate, "semantic_type", None)
        if semantic_type not in CHANGE_ENTRY_TYPES:
            return None
        fields = {**candidate.fields, **candidate.unknown_fields}
        if semantic_type is T.ADD_PROJECT_MEMBER:
            return await self._add_member(message, understanding, candidate, fields)
        if semantic_type is T.ACTIVITY_CORRECTION:
            return await self._correct(message, understanding, candidate, fields)
        return await self._issue(message, understanding, candidate, fields)

    # -- add a team member -----------------------------------------------------

    async def _add_member(self, message: Any, understanding: Any, candidate: Any, fields: dict) -> Ready | Say:
        from runtime.inbound_journey._shared import _PROJECT_CREATE_ROLES

        role = str(getattr(self.actor, "role", "") or "").strip().upper()
        if role not in _PROJECT_CREATE_ROLES:
            return Say("info", _ADD_MEMBER_DENIED)
        name = str(fields.get("member_name") or "").strip()
        if not name:
            return Say("error", "Not added: the person's name is needed.")
        scoped = await self.settle(
            message, understanding, candidate, module=module_for_workflow(K.ADD_PROJECT_MEMBER), ask_site=False
        )
        if isinstance(scoped, Say):
            return scoped
        new_person = bool(fields.pop("new_person", False))
        phone = str(fields.pop("whatsapp_number", "") or "").strip() or None
        # WA-84: shown on the card only (the workflow's draft keeps name, role and who
        # asked): which project, the role word they used, the site they named.
        site_said = str(fields.get("site_name") or "").strip()
        for key in SCOPE_KEYS:
            fields.pop(key, None)
        fields["created_by_role"] = role
        fields["project_label"] = next(
            (
                str(p.name)
                for p in getattr(self.actor, "projects", None) or []
                if str(p.id) in (str(scoped.project_id), str(scoped.context_project or ""))
            ),
            "",
        )
        fields["role_said"] = str(fields.get("role") or "")
        if site_said:
            fields["site_said"] = site_said
        ready = self.ready(scoped, message, E.ADD_PROJECT_MEMBER_REQUESTED, K.ADD_PROJECT_MEMBER, fields)

        from workflows.entities import Ambiguous, Resolved

        outcome = None
        if self.member_resolver is not None:
            try:
                outcome = await self.member_resolver.resolve(
                    organization_id=str(scoped.ctx.organization_id), name_hint=name
                )
            except Exception:  # noqa: BLE001 -- the backend's own check still runs at Yes
                _log.warning("change_entry.member_lookup_failed correlation_id=%s", message.correlation_id, exc_info=True)
                return ready
        if outcome is None or isinstance(outcome, Resolved):
            if isinstance(outcome, Resolved):
                ready.event.fields["member_name"] = outcome.display_name
            return ready
        if isinstance(outcome, Ambiguous):
            names = [c.display_name for c in outcome.candidates]
            return choose(f'Which person is "{name}"?', names, "name")
        # Nobody by that name in the company. Admins and project managers may
        # create the person (the same roles CREATE_USER allows).
        if self.create_member is None:
            return Say("info", f'Not added: there is nobody called "{name}" in the company yet. An admin adds people on the dashboard.')
        if not new_person:
            return Say(
                "choose",
                f'Not added yet: "{name}" is not in the company. Ask whether to add them as a new person. '
                "If yes, call this tool again with new_person true (and their WhatsApp number if they gave it).",
                question=f'{name} isn\'t in the company yet. Add them as a new person?',
                options=("Yes, add them", "No"),
            )
        spec = await self.create_member(name, ready.event, phone)
        if spec is None:
            return Say("error", f'Not added: "{name}" could not be set up just now. Please try again.')
        options = tuple(b.title for b in (spec.buttons or ()))
        return Say("needs_answer", spec.text, question=spec.text, options=options)

    # -- correct the last quantity logged ----------------------------------------

    async def _correct(self, message: Any, understanding: Any, candidate: Any, fields: dict) -> Ready | Say:
        if fields.get("new_quantity") in (None, ""):
            return Say("error", "Not changed: the right quantity is needed.")
        scoped = await self.settle(
            message, understanding, candidate, module=module_for_workflow(K.ACTIVITY_CORRECTION), ask_site=False
        )
        if isinstance(scoped, Say):
            return scoped
        for key in SCOPE_KEYS:
            fields.pop(key, None)
        ready = self.ready(scoped, message, E.ACTIVITY_CORRECTION_REQUESTED, K.ACTIVITY_CORRECTION, fields)
        remembered = None
        if self.remembered_activity is not None:
            try:
                remembered = await self.remembered_activity()
            except Exception:  # noqa: BLE001 -- the workflow says there is nothing to correct
                _log.warning("change_entry.remembered_failed correlation_id=%s", message.correlation_id, exc_info=True)
        if self.day_facts is not None:
            try:
                # The activity this conversation touched, else (after a gap, a new
                # session) the sender's own newest amount (WRK-06): saved or still a
                # draft, as the old lookup did.
                import datetime as dt

                from runtime import day_facts as df

                today = df.project_today_for(self.actor)
                facts = await self.day_facts.work(
                    organization_id=str(self.actor.organization_id),
                    start=today - dt.timedelta(days=2),
                    end=today,
                    reported_by_user_id=str(getattr(self.actor, "user_id", "") or "") or None,
                    include_pending=True,
                )
                target = df.correction_target(facts, remembered)
            except Exception:  # noqa: BLE001
                _log.warning("change_entry.correction_lookup_failed correlation_id=%s", message.correlation_id, exc_info=True)
                target = None
            if target is not None:
                f = ready.event.fields
                for key in ("progress_update_id", "activity_quantity_id"):
                    if target.get(key):
                        f[key] = target[key]
                old = target["quantity"]
                f["old_quantity"] = f"{old:g}" if isinstance(old, float) else str(old)
                f["old_unit_id"] = target.get("unit_id")
                f["old_unit"] = target.get("unit")
                summary = [b for b in (target.get("work_type"), target.get("narrative")) if b]
                if summary:
                    f["correction_activity_summary"] = " — ".join(summary)
        return ready

    # -- close, reopen or withdraw a site issue -----------------------------------

    async def _issue(self, message: Any, understanding: Any, candidate: Any, fields: dict) -> Ready | Say:
        action = str(fields.get("action") or "").strip().lower()
        event_type = _ISSUE_EVENTS.get(action)
        if event_type is None:
            return Say("error", "Not changed: it was not clear what to do with the issue.")
        scoped = await self.settle(
            message, understanding, candidate, module=module_for_workflow(K.SITE_ISSUE_CLOSE), ask_site=False
        )
        if isinstance(scoped, Say):
            return scoped
        for key in SCOPE_KEYS:
            fields.pop(key, None)
        ready = self.ready(scoped, message, event_type, K.SITE_ISSUE_CLOSE, fields)
        if self.site_issue_query is not None:
            try:
                target = await self.site_issue_query.find_latest(
                    organization_id=str(self.actor.organization_id),
                    project_id=ready.event.project_id,
                    site_id=ready.event.site_id,
                    statuses=_ISSUE_TARGETS[action],
                    by_transition_time=action == "reopen",
                )
            except Exception:  # noqa: BLE001 -- the workflow says there is nothing to close
                _log.warning("change_entry.issue_lookup_failed correlation_id=%s", message.correlation_id, exc_info=True)
                target = None
            if target is not None:
                f = ready.event.fields
                f["site_issue_id"] = target["site_issue_id"]
                f["site_issue_type"] = target["issue_type"]
                f["site_issue_severity"] = target["severity"]
                f["site_issue_narrative"] = target["narrative"]
        return ready
