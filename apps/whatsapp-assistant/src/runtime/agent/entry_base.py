"""What every direct entry shares (ARCH-01, ARCH-02; ADR section 10b).

A tool's arguments become a workflow's event without the classic pipeline.
Each entry (materials in ``material_entry.py``; work done, site issues and
expenses in ``site_entry.py``) runs the same steps first, here:

- who the sender is, their company, and which project/site they may use:
  ``ContextResolver.resolve``, unchanged (no new permission logic);
- the company's module switch for the workflow;
- the project and site: picked, resolved, or remembered from the last save,
  always from the sender's own list; asked with buttons when unclear;
- the event and the planner decision ``WorkflowRuntime.start`` takes, exactly
  as the planner builds them.

The save itself is unchanged: ``WorkflowRuntime.start`` + save-first.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from mesiri_contracts.assistant.canonical_event import CanonicalEventType, IntentCompleteness
from mesiri_contracts.assistant.enums import InputModality
from mesiri_contracts.assistant.planner_decision import (
    PlannerDecisionType,
    PlannerPriority,
    WorkflowKey,
)
from mesiri_contracts.assistant.v2.canonical_event import CanonicalEventV2
from mesiri_contracts.assistant.v2.planner_decision import PlannerDecisionV2
from mesiri_contracts.common.ids import new_id

_log = logging.getLogger("mesiri.agent")

SCOPE_KEYS = ("project_id", "site_id", "project_name", "site_name")


def tool_understanding(candidate: Any, message: Any, *, language: str | None = None) -> Any:
    """What the context layer reads to place an entry (``ContextResolver.resolve``
    takes an understanding): the tool's candidate, as the model understood it."""
    from mesiri_contracts.assistant.confidence import ConfidenceLevel
    from mesiri_contracts.assistant.understanding_result import UnderstandingResult

    return UnderstandingResult(
        source_message_id=message.message_id,
        correlation_id=message.correlation_id,
        input_modality=InputModality.TEXT,
        detected_language=language,
        semantic_type=candidate.semantic_type,
        candidates=[candidate],
        intents=[candidate],
        overall_confidence=ConfidenceLevel.HIGH,
    )


@dataclass(slots=True)
class Ready:
    """Start this workflow: the event is complete."""

    decision: PlannerDecisionV2
    event: CanonicalEventV2
    #: (organization, user, project, site) in the context layer's ids: what
    #: to remember as the sender's active project/site once it is saved.
    scope: tuple[str, str, str | None, str | None] | None = None


@dataclass(slots=True)
class Say:
    """Nothing started; tell the model this (status as ``StepResult``)."""

    status: str
    text: str
    #: "choose" only: the question and its options, shown as buttons by the
    #: code whatever the model writes (round 3c, 21 Oct: it asked in plain
    #: text and the options never appeared).
    question: str | None = None
    options: tuple[str, ...] = ()


@dataclass(slots=True)
class Scoped:
    """The sender's context and the entry's project/site, settled."""

    ctx: Any
    organization_id: str
    project_id: Any
    site_id: Any
    #: The same project/site in the context layer's ids (for ``remember``).
    context_project: str | None
    context_site: str | None


class EntryScope:
    """The shared steps; the entry classes carry ``context_resolver``,
    ``org_settings_query``, ``actor`` and ``active_context``."""

    __slots__ = ()

    async def settle(
        self,
        message: Any,
        understanding: Any,
        candidate: Any,
        *,
        module: str | None,
        site_required: bool = False,
        project: str = "required",
        ask_site: bool = True,
        lookup: bool = False,
        site_prompt: bool = False,
    ) -> Scoped | Say:
        """The sender's context and the project/site for this entry, or what
        to say (a question with buttons, a module that is off, a failure).

        ``project``: "required" (asked when unclear), "optional" (none is
        fine: the whole company where the answer allows it) or "none" (not
        used: a new project, a transfer). ``ask_site`` False: with several
        sites, none is picked (a lookup covers the whole project).
        ``lookup``: the wording is "couldn't look this up", not "not saved".
        ``site_prompt``: the entry needs a site (an issue, the day's conditions):
        a sender with none in this project is asked which of their sites."""
        no = "Couldn't look this up:" if lookup else "Not saved:"
        picked_project = candidate.fields.get("project_id")
        picked_site = candidate.fields.get("site_id")
        result = await self.context_resolver.resolve(message, understanding)
        retried = False
        if not result.is_ok and (picked_project or picked_site):
            retried = True
            # The context layer authorises a named project by a narrower rule
            # than the sender's own list (only "on_track" projects, members
            # only), so a project picked from that list could fail and loop
            # (live 22 Oct 00:50). Resolve who/which company without it; the
            # pick is applied below from their own list, as the classic
            # project picker always did.
            bare = candidate.model_copy(
                update={"fields": {k: v for k, v in candidate.fields.items() if k not in SCOPE_KEYS}}
            )
            result = await self.context_resolver.resolve(
                message, understanding.model_copy(update={"candidates": [bare], "intents": [bare]})
            )
        if not result.is_ok:
            error = getattr(result, "error", None)
            _log.warning(
                "entry.context_failed correlation_id=%s code=%s retried=%s",
                message.correlation_id,
                getattr(error, "code", error),
                retried,
            )
            if retried:
                # They already picked; asking again would loop (review, 22 Oct).
                return Say("error", f"{no} the system could not place this.")
            names = [p.name for p in getattr(self.actor, "projects", None) or []]
            if not names:
                return Say("error", f"{no} I couldn't tell which project this is for.")
            return choose("Which project is this for?", names, "project")
        ctx = result.unwrap()
        organization_id = str(ctx.organization_id)

        if module is not None and not await self._module_on(organization_id, module):
            from channel.replies import render_module_disabled_reply

            return Say("info", render_module_disabled_reply(module, getattr(self.actor, "role", None)))

        # Only when the context layer refused the pick does their own list
        # decide it; otherwise its resolved ids stand, as before.
        named = any(candidate.fields.get(k) for k in SCOPE_KEYS)
        project_id, site_id = await self._scope(
            ctx, picked_project if retried else None, picked_site if retried else None, named=named
        )
        if project == "none":
            return Scoped(ctx, organization_id, None, None, None, None)
        if project_id is None and project == "optional":
            return Scoped(ctx, organization_id, None, None, None, None)
        if project_id is None:
            names = [p.name for p in getattr(self.actor, "projects", None) or []]
            if not names:
                return Say("info", f"{no} you are not on any project yet. Your admin can add you.")
            return choose("Which project is this for?", names, "project")
        unmatched = self._unmatched_site(candidate, project_id, site_id)
        if unmatched is not None:
            return unmatched
        if site_id is None:
            sites = [s for s in getattr(self.actor, "sites", None) or [] if str(s.project_id) == str(project_id)]
            said = " ".join(str(candidate.fields.get("site_name") or "").casefold().split())
            hit = [s for s in sites if said and " ".join(str(s.name).casefold().split()) == said]
            if len(hit) == 1:
                # A name two projects share comes as a name, not an id; within
                # this project it is one site ("Block A" tapped looped, 22 Oct).
                sites = hit
            if len(sites) > 1 and not ask_site:
                sites = []  # the whole project
            if len(sites) > 1:
                return choose("Which site is this for?", [s.name for s in sites], "site")
            site_id = sites[0].id if sites else None
            if site_id is None and (site_required or site_prompt) and not self._has_site_in(ctx, project_id):
                # Without a site the save refuses it, and the model asked
                # "which site?" with nothing to pick (live 22 Oct): say why.
                # Request 104, D: an issue or the day's conditions are the same
                # (they used to go on and "didn't go through" at save).
                what = "work done" if site_required else "this"
                return Say(
                    "info",
                    f"Not saved: you are not on any site of this project yet, so {what} "
                    "can't be recorded. Your admin can add you to its site on the dashboard.",
                )
            # Otherwise let it through site-less, as the classic site gate did.
        if project_id == ctx.project_id and ctx.context_project_id is not None:
            # The context layer's own ids for what it resolved (they can
            # differ from the canonical ones); a pick or a remembered slot is
            # already in the sender's own (context-layer) ids.
            context_project = ctx.context_project_id
            if site_id is not None and str(site_id) != str(ctx.site_id):
                context_site = str(site_id)  # a pick or today's site, not the resolver's
            else:
                context_site = ctx.context_site_id or (str(site_id) if site_id is not None else None)
        else:
            context_project = str(project_id)
            context_site = str(site_id) if site_id is not None else None
        return Scoped(ctx, organization_id, project_id, site_id, context_project, context_site)

    def ready(
        self,
        scoped: Scoped,
        message: Any,
        event_type: CanonicalEventType,
        workflow_key: WorkflowKey,
        fields: dict[str, Any],
    ) -> Ready:
        """The event and decision the planner would build for it."""
        ctx = scoped.ctx
        media = getattr(message, "media", None)
        if media is not None and getattr(message, "modality", None) in (InputModality.IMAGE, InputModality.DOCUMENT):
            # The photo or bill the entry was read from: saved as its evidence
            # (an expense attachment, ...), as the pipeline carried it.
            fields = {**fields, "media_object_key": media.object_key}
        event = CanonicalEventV2(
            event_id=new_id("evt"),
            correlation_id=message.correlation_id,
            source_message_id=message.message_id,
            conversation_id=ctx.conversation_id,
            event_type=event_type,
            completeness=IntentCompleteness.ACTIONABLE,
            organization_id=ctx.organization_id,
            user_id=ctx.user_id,
            project_id=scoped.project_id,
            site_id=scoped.site_id,
            permissions=ctx.permissions,
            fields=fields,
        )
        decision = PlannerDecisionV2(
            correlation_id=event.correlation_id,
            source_message_id=event.source_message_id,
            causation_event_id=event.event_id,
            decision_type=PlannerDecisionType.START_WORKFLOW,
            workflow_key=workflow_key,
            reason=event.event_type,
            priority=PlannerPriority.NORMAL,
            organization_id=event.organization_id,
            user_id=event.user_id,
            project_id=event.project_id,
            site_id=event.site_id,
        )
        return Ready(
            decision=decision,
            event=event,
            scope=(ctx.context_organization_id, ctx.context_user_id, scoped.context_project, scoped.context_site),
        )

    def _unmatched_site(self, candidate: Any, project_id: Any, site_id: Any) -> Say | None:
        """V1 audit SIT-01: a site the message names ("5 masons at Site Z",
        "Sight B") that is none of the sender's sites is asked about, never
        filed under today's site. None when no name was said, or the site
        the entry goes to is the one named."""
        said = " ".join(str(candidate.fields.get("site_name") or "").casefold().split())
        if not said or candidate.fields.get("site_id"):
            return None
        own = list(getattr(self.actor, "sites", None) or [])
        named = [s for s in own if " ".join(str(s.name).casefold().split()) == said]
        if site_id is not None and any(str(s.id) == str(site_id) for s in named):
            return None
        if site_id is None and any(str(s.project_id) == str(project_id) for s in named):
            return None  # one of this project's sites by name: settled below
        in_project = [s.name for s in own if str(s.project_id) == str(project_id)]
        options = in_project or [s.name for s in own]
        if not options:
            return None
        said_as = " ".join(str(candidate.fields.get("site_name")).split())
        return choose(f'I don\'t have a site called "{said_as}". Which site is this for?', options, "site")

    def _has_site_in(self, ctx: Any, project_id: Any) -> bool:
        """Whether the sender may report on any site of the project, in either
        of its ids (the context layer's or the canonical one; the same in
        production)."""
        ids = {str(project_id)}
        if project_id == ctx.project_id and ctx.context_project_id is not None:
            ids.add(str(ctx.context_project_id))
        return any(str(s.project_id) in ids for s in getattr(self.actor, "sites", None) or [])

    async def _scope(
        self, ctx: Any, picked_project: Any, picked_site: Any, *, named: bool = False
    ) -> tuple[Any, Any]:
        """(project, site) for the entry. What they picked or named, when it
        is in their own list; else, when the message names none, today's site
        (or the last one saved to); else what the context layer resolved. Every id
        comes from the sender's own projects/sites (ActorIdentity), the same
        list the classic pickers offered and applied."""
        own_projects = {str(p.id) for p in getattr(self.actor, "projects", None) or [] if getattr(p, "id", None)}
        own_sites = {
            str(s.id): str(s.project_id) for s in getattr(self.actor, "sites", None) or [] if getattr(s, "id", None)
        }
        if picked_site is not None and str(picked_site) in own_sites:
            return own_sites[str(picked_site)], picked_site
        if picked_project is not None and str(picked_project) in own_projects:
            site = ctx.site_id if ctx.site_id is not None and own_sites.get(str(ctx.site_id)) == str(picked_project) else None
            return picked_project, site
        remembered = await self._remembered(ctx)
        source = str(getattr(getattr(ctx, "context_source", None), "value", getattr(ctx, "context_source", "")) or "")
        weak = source in ("", "active_context", "user_default", "unresolved")
        if (
            not named
            and weak
            and remembered is not None
            and own_sites.get(str(remembered.site_id)) == str(remembered.project_id)
        ):
            # Today's site (WA-45) when the message names none, before the
            # context layer's pick: that layer authorises projects by a
            # narrower rule (members only) and fell back to another project
            # with no site of theirs (live 22 Oct, an admin at Tower A). Never
            # over a reply to a record or an open workflow, which say more.
            if ctx.site_id is not None and str(ctx.context_site_id) == str(remembered.site_id):
                return ctx.project_id, ctx.site_id  # the same site, in canonical ids
            return remembered.project_id, remembered.site_id
        if ctx.project_id is not None:
            return ctx.project_id, ctx.site_id
        if remembered is not None and str(remembered.project_id) in own_projects:
            site = remembered.site_id if own_sites.get(str(remembered.site_id)) == str(remembered.project_id) else None
            return remembered.project_id, site
        return None, None

    async def _remembered(self, ctx: Any) -> Any:
        if self.active_context is None:
            return None
        try:
            return await self.active_context.get_active_context(
                organization_id=ctx.context_organization_id, user_id=ctx.context_user_id
            )
        except Exception:  # noqa: BLE001 -- a missed hint only costs one question
            _log.warning("entry.remembered_failed", exc_info=True)
            return None

    async def remember(self, ready: Ready, *, correlation_id: str | None = None) -> None:
        """After a save: this project/site is where the sender is working, so
        the next message is not asked again (Ilan, 21 Oct). The slot is
        re-checked against their access whenever it is read. Never raises."""
        if self.active_context is None or ready.scope is None or ready.scope[3] is None:
            # Without a site it would wipe today's site (review, 22 Oct).
            return
        organization_id, user_id, project_id, site_id = ready.scope
        try:
            await self.active_context.set_active_context(
                organization_id=organization_id,
                user_id=user_id,
                project_id=project_id,
                site_id=site_id,
                ttl_seconds=_until_midnight(getattr(self.actor, "timezone", None)),
            )
        except Exception:  # noqa: BLE001 -- a missed hint only costs one question
            _log.warning("entry.remember_failed correlation_id=%s", correlation_id, exc_info=True)

    async def _module_on(self, organization_id: str, module: str) -> bool:
        if self.org_settings_query is None:
            return True
        try:
            return module in await self.org_settings_query.enabled_modules(organization_id=organization_id)
        except Exception:  # noqa: BLE001 -- the save path's own MODULE_DISABLED check is the backstop
            _log.warning("entry.modules_failed", exc_info=True)
            return True


def _until_midnight(timezone: str | None) -> int:
    """Today's site lasts the company's day (WA-45), not 12 hours past it."""
    from datetime import UTC, datetime

    from channel.receipt.data import company_zone

    from .work_site import seconds_until_midnight

    return seconds_until_midnight(datetime.now(UTC), str(company_zone(timezone)))


def choose(question: str, options: list[str], arg: str, *, note: str = "") -> Say:
    """The sender must choose (ARCH-04): the model is told, and the options
    go out as buttons under its question."""
    shown = list(options)[:10]
    # A name can hold a comma ("Green Villa, Kakkanad"): quoted and separated
    # by " | " so the model never reads one name as two options.
    listed = " | ".join(f'"{name}"' for name in shown)
    return Say(
        "choose",
        f"Not saved yet. {question} Options: {listed} (names may contain commas). The options are shown as buttons; "
        f"when they answer, call this tool again with that exact {arg}.{note}",
        question=question,
        options=tuple(shown),
    )


def number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
