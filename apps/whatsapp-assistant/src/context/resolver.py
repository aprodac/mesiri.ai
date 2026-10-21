"""M4 Context Resolver — the orchestration entry point.

Consumes a ``NormalizedMessage`` + ``UnderstandingResult`` and produces a
``ResolvedContext`` (or a typed ``MesiriError`` as ``Result.err``). It wires the
authoritative identity stage to candidate collection, deterministic precedence,
authorization validation, ambiguity detection, and confidence — emitting a
structured observability event at every stage.

Boundaries: SQL lives in the Postgres repositories, Redis lives in the active
context store; this orchestrator only talks to ports. It never selects a
workflow, persists a business record, or converses with the user (all M5+).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from mesiri.observability import tracing
from mesiri.observability.logging import get_logger
from mesiri_contracts.assistant.context_enums import ContextConfidence, ContextSource
from mesiri_contracts.assistant.normalized_message import NormalizedMessage
from mesiri_contracts.assistant.understanding_result import UnderstandingResult
from mesiri_contracts.assistant.v2.resolved_context import ResolvedContextV2
from mesiri_contracts.common.errors import ErrorCode, MesiriError
from mesiri_contracts.common.result import Result

from . import context_policy, errors
from .explicit import ProjectRef, SiteRef, extract_references
from .identity import Principal, resolve_principal
from .models import ContextCandidate
from .ports import (
    ActiveContextStore,
    ContextPreferenceRepository,
    ExternalIdentityRepository,
    IdentityBridgeRepository,
    OrganizationMembershipRepository,
    ProjectRepository,
    ReplyContextProvider,
    RolePermissionRepository,
    SiteRepository,
    WorkflowContextProvider,
)

_log = get_logger("mesiri.context")

WHATSAPP_PROVIDER = "whatsapp"


@dataclass(slots=True)
class ContextDependencies:
    """The full set of ports the resolver needs."""

    identities: ExternalIdentityRepository
    memberships: OrganizationMembershipRepository
    roles: RolePermissionRepository
    projects: ProjectRepository
    sites: SiteRepository
    preferences: ContextPreferenceRepository
    active_context: ActiveContextStore
    reply_context: ReplyContextProvider
    workflow_context: WorkflowContextProvider
    bridge: IdentityBridgeRepository
    # Optional Redis client for identity caching (TTL=60s). When None, identity
    # resolution always hits Postgres (safe default for tests / no-Redis envs).
    redis: object | None = None


class ContextResolver:
    def __init__(self, deps: ContextDependencies) -> None:
        self._d = deps

    @property
    def active_context(self) -> ActiveContextStore:
        """The sender's active project/site slot this resolver reads (the
        agent writes it after a save, so the next message is not asked)."""
        return self._d.active_context

    async def resolve(
        self, message: NormalizedMessage, understanding: UnderstandingResult
    ) -> Result[ResolvedContextV2]:
        # Propagate the journey's correlation id (never mint a new one here).
        with tracing.correlation_scope(
            correlation_id=message.correlation_id, message_id=message.message_id
        ):
            _log.info("context.resolution_started", channel=message.channel)
            try:
                ctx = await self._resolve(message, understanding)
            except MesiriError as err:
                err.with_correlation(message.correlation_id)
                _log.error("context.resolution_failed", error=err, message_id=message.message_id)
                return Result.err(err)
            _log.info(
                "context.resolution_completed",
                organization_id=ctx.organization_id,
                user_id=ctx.user_id,
                project_id=ctx.project_id,
                site_id=ctx.site_id,
                context_source=ctx.context_source.value,
                result_status="resolved",
            )
            return Result.ok(ctx)

    async def _resolve(
        self, message: NormalizedMessage, understanding: UnderstandingResult
    ) -> ResolvedContextV2:
        principal = await resolve_principal(
            provider=WHATSAPP_PROVIDER,
            external_subject=message.sender.wa_id,
            identities=self._d.identities,
            memberships=self._d.memberships,
            roles=self._d.roles,
            redis=self._d.redis,
        )
        _log.info("context.identity_resolved", user_id=principal.user_id)
        _log.info("context.organization_resolved", organization_id=principal.organization_id)
        _log.info(
            "context.membership_validated",
            organization_id=principal.organization_id,
            membership_id=principal.membership_id,
        )
        _log.info(
            "context.permissions_resolved",
            user_id=principal.user_id,
            role_count=len(principal.role_ids),
            permission_count=len(principal.permissions),
        )

        candidates = await self._collect_candidates(message, understanding, principal)
        _log.info(
            "context.candidates_collected",
            candidate_count=len(candidates),
            organization_id=principal.organization_id,
        )

        winner = context_policy.select(candidates)
        _log.info(
            "context.authorization_validated",
            organization_id=principal.organization_id,
            authorized_count=sum(1 for c in candidates if c.authorized),
        )

        if winner is None:
            return await self._build(principal, None, message)
        return await self._build(principal, winner, message)

    async def _canonical_scope(
        self,
        *,
        context_organization_id: str,
        context_user_id: str,
        context_project_id: str | None,
        context_site_id: str | None,
    ) -> tuple[str, str, str | None, str | None]:
        # org and user are always required and fully independent reads.
        org, user = await asyncio.gather(
            self._d.bridge.canonical_organization_id(context_organization_id),
            self._d.bridge.canonical_user_id(context_user_id),
        )
        if org is None:
            raise errors.canonical_identity_not_mapped("organization", context_organization_id)
        if user is None:
            raise errors.canonical_identity_not_mapped("user", context_user_id)

        project: str | None = None
        site: str | None = None
        if context_project_id is not None and context_site_id is not None:
            # Both present: fetch in parallel.
            project, site = await asyncio.gather(
                self._d.bridge.canonical_project_id(context_project_id),
                self._d.bridge.canonical_site_id(context_site_id),
            )
            if project is None:
                raise errors.canonical_identity_not_mapped("project", context_project_id)
            if site is None:
                raise errors.canonical_identity_not_mapped("site", context_site_id)
        elif context_project_id is not None:
            project = await self._d.bridge.canonical_project_id(context_project_id)
            if project is None:
                raise errors.canonical_identity_not_mapped("project", context_project_id)
        elif context_site_id is not None:
            site = await self._d.bridge.canonical_site_id(context_site_id)
            if site is None:
                raise errors.canonical_identity_not_mapped("site", context_site_id)
        return org, user, project, site

    # -- Candidate collection -------------------------------------------------

    async def _collect_candidates(
        self,
        message: NormalizedMessage,
        understanding: UnderstandingResult,
        principal: Principal,
    ) -> list[ContextCandidate]:
        candidates: list[ContextCandidate] = []
        org, user = principal.organization_id, principal.user_id

        # 1. Explicit references (highest precedence — must resolve first before
        # the parallel gather below, so short-circuit can still save the 4 other
        # reads if an explicit tap already gave us a definitive answer).
        project_ref, site_ref = extract_references(understanding)
        explicit = await self._explicit_candidate(org, user, project_ref, site_ref)
        if explicit is not None:
            candidates.append(explicit)
            _log.info("context.explicit_context_evaluated", resolved=True)
        else:
            _log.info("context.explicit_context_evaluated", resolved=False)

        # 2+3+4+5: The remaining four context sources are fully independent
        # reads — none depends on another's result. Run them concurrently.
        # _get_active_candidate returns (was_present, candidate) to preserve
        # the "present but stale/unauthorized" distinction in logging.
        reply_cand, workflow_cand, active_result, default_cand = await asyncio.gather(
            self._get_reply_candidate(
                org, user, message.reply_context.replied_to_message_id
            )
            if message.reply_context
            else self._skip_none(),
            self._get_workflow_candidate(org, user),
            self._get_active_candidate(org, user),
            self._default_candidate(org, user),
        )
        active_present, active_cand = active_result

        if message.reply_context:
            if reply_cand is not None:
                candidates.append(reply_cand)
            _log.info("context.reply_context_evaluated", resolved=reply_cand is not None)

        if workflow_cand is not None:
            candidates.append(workflow_cand)
        _log.info("context.workflow_context_evaluated", resolved=workflow_cand is not None)

        if active_cand is not None:
            candidates.append(active_cand)
        _log.info(
            "context.active_context_evaluated",
            present=active_present,
            resolved=active_cand is not None,
        )

        if default_cand is not None:
            candidates.append(default_cand)
        _log.info("context.default_context_evaluated", resolved=default_cand is not None)

        return candidates

    # -- Private coroutine helpers for the parallel gather above ---------------

    @staticmethod
    async def _skip_none() -> None:
        """No-op placeholder used in asyncio.gather() when an optional
        context source (reply) does not apply to the current message."""
        return None

    async def _get_reply_candidate(
        self, org: str, user: str, replied_to_message_id: str
    ) -> ContextCandidate | None:
        pair = await self._d.reply_context.context_for_reply(
            organization_id=org,
            replied_to_message_id=replied_to_message_id,
        )
        return await self._validated_candidate(org, user, ContextSource.REPLY_CONTEXT, pair)

    async def _get_workflow_candidate(
        self, org: str, user: str
    ) -> ContextCandidate | None:
        pair = await self._d.workflow_context.active_workflow_context(
            organization_id=org, user_id=user
        )
        return await self._validated_candidate(org, user, ContextSource.WORKFLOW_CONTEXT, pair)

    async def _get_active_candidate(
        self, org: str, user: str
    ) -> tuple[bool, ContextCandidate | None]:
        """Returns (was_present, candidate) so the caller can log `present`
        accurately even when the active-context entry is stale/unauthorized."""
        active = await self._d.active_context.get_active_context(
            organization_id=org, user_id=user
        )
        if active is None:
            return False, None
        cand = await self._validated_candidate(
            org, user, ContextSource.ACTIVE_CONTEXT, (active.project_id, active.site_id)
        )
        return True, cand

    # Name-reference resolution failures that must degrade gracefully rather
    # than kill context resolution outright -- see _explicit_candidate.
    _UNRESOLVED_NAME_REF_CODES = frozenset(
        {
            ErrorCode.PROJECT_NOT_FOUND.value,
            ErrorCode.AMBIGUOUS_PROJECT.value,
            ErrorCode.SITE_NOT_FOUND.value,
            ErrorCode.AMBIGUOUS_SITE.value,
        }
    )

    async def _explicit_candidate(
        self,
        org: str,
        user: str,
        project_ref: ProjectRef | None,
        site_ref: SiteRef | None,
    ) -> ContextCandidate | None:
        if project_ref is None and site_ref is None:
            return None

        project_id: str | None = None
        site_id: str | None = None
        by_id = False
        evidence_parts: list[str] = []

        if project_ref is not None:
            try:
                project, pid_by_id = await self._resolve_project_ref(org, user, project_ref)
            except MesiriError as err:
                if not project_ref.by_id and err.error_code in self._UNRESOLVED_NAME_REF_CODES:
                    # A NAME reference (never an explicit id tap) that
                    # doesn't resolve to exactly one authorized project must
                    # not kill the whole message -- fall through to the
                    # normal "no project resolved" flow, same as if no name
                    # had been mentioned at all, so the existing project-
                    # selection gate (which lists every project the sender
                    # can otherwise reach) gets a chance to ask instead.
                    # Real bug this fixes: naming a project by name failed
                    # every time with "I couldn't understand you" whenever
                    # that name wasn't yet reflected in the newer per-
                    # project membership table -- even for a project the
                    # sender demonstrably already has access to via every
                    # other path (the project picker, single-project
                    # convenience, etc).
                    _log.info(
                        "context.explicit_project_ref_unresolved",
                        error_code=err.error_code,
                        reference=project_ref.value,
                    )
                    return None
                raise
            project_id = project.project_id
            by_id = by_id or pid_by_id
            evidence_parts.append(f"project={project_ref.value!r}")

        if site_ref is not None:
            try:
                site, sid_by_id = await self._resolve_site_ref(org, user, site_ref, project_id)
            except MesiriError as err:
                if not site_ref.by_id and err.error_code in self._UNRESOLVED_NAME_REF_CODES:
                    _log.info(
                        "context.explicit_site_ref_unresolved",
                        error_code=err.error_code,
                        reference=site_ref.value,
                    )
                    return None
                raise
            # Site must belong to the resolved project (if any).
            if project_id is not None and site.project_id != project_id:
                raise errors.project_site_mismatch(project_id, site.site_id)
            site_id = site.site_id
            if project_id is None:
                project_id = site.project_id  # infer project from an explicit site
            by_id = by_id or sid_by_id
            evidence_parts.append(f"site={site_ref.value!r}")

        return ContextCandidate(
            source=ContextSource.MESSAGE_EXPLICIT,
            organization_id=org,
            project_id=project_id,
            site_id=site_id,
            confidence=context_policy.confidence_for_explicit(by_id=by_id),
            authorized=True,
            evidence="; ".join(evidence_parts),
            reference=project_ref.value if project_ref else (site_ref.value if site_ref else None),
        )

    async def _resolve_project_ref(self, org: str, user: str, ref: ProjectRef):
        if ref.by_id:
            proj = await self._d.projects.get_authorized_project(
                organization_id=org, user_id=user, project_id=ref.value
            )
            if proj is not None:
                return proj, True
            in_org = await self._d.projects.get_project_in_org(
                organization_id=org, project_id=ref.value
            )
            if in_org is not None:
                raise errors.project_access_denied(org, user, ref.value)
            raise errors.project_not_found(ref.value)
        # Name reference.
        matches = await self._d.projects.find_authorized_projects_by_name(
            organization_id=org, user_id=user, name=ref.value
        )
        if len(matches) == 1:
            return matches[0], False
        if len(matches) > 1:
            raise errors.ambiguous_project(ref.value, [p.project_id for p in matches])
        raise errors.project_not_found(ref.value)

    async def _resolve_site_ref(self, org: str, user: str, ref: SiteRef, project_id: str | None):
        if ref.by_id:
            site = await self._d.sites.get_authorized_site(
                organization_id=org, user_id=user, site_id=ref.value
            )
            if site is not None:
                return site, True
            in_org = await self._d.sites.get_site_in_org(organization_id=org, site_id=ref.value)
            if in_org is not None:
                raise errors.site_access_denied(org, user, ref.value)
            raise errors.site_not_found(ref.value)
        matches = await self._d.sites.find_authorized_sites_by_name(
            organization_id=org, user_id=user, name=ref.value, project_id=project_id
        )
        if len(matches) == 1:
            return matches[0], False
        if len(matches) > 1:
            raise errors.ambiguous_site(ref.value, [s.site_id for s in matches])
        raise errors.site_not_found(ref.value)

    async def _validated_candidate(
        self,
        org: str,
        user: str,
        source: ContextSource,
        pair: tuple[str | None, str | None] | None,
    ) -> ContextCandidate | None:
        """Validate a (project_id, site_id) pair from a non-explicit source.

        Returns an authorized candidate, or None if the pair is missing / stale /
        no longer authorized (lower-precedence sources then apply).
        """
        if pair is None:
            return None
        project_id, site_id = pair
        if project_id is None and site_id is None:
            return None

        v_project_id: str | None = None
        v_site_id: str | None = None

        if project_id is not None:
            proj = await self._d.projects.get_authorized_project(
                organization_id=org, user_id=user, project_id=project_id
            )
            if proj is None:
                return None  # stale / unauthorized -> drop candidate
            v_project_id = proj.project_id

        if site_id is not None:
            site = await self._d.sites.get_authorized_site(
                organization_id=org, user_id=user, site_id=site_id
            )
            if site is None:
                # Keep an authorized project even if the site went stale.
                if v_project_id is None:
                    return None
            elif v_project_id is not None and site.project_id != v_project_id:
                pass  # inconsistent pair: keep project, drop site
            else:
                v_site_id = site.site_id
                if v_project_id is None:
                    v_project_id = site.project_id

        if v_project_id is None and v_site_id is None:
            return None

        return ContextCandidate(
            source=source,
            organization_id=org,
            project_id=v_project_id,
            site_id=v_site_id,
            confidence=context_policy.confidence_for_source(source),
            authorized=True,
            evidence=f"{source.value} validated",
        )

    async def _default_candidate(self, org: str, user: str) -> ContextCandidate | None:
        prefs = await self._d.preferences.get_preferences(organization_id=org, user_id=user)
        if prefs is not None and prefs.default_project_id is not None:
            cand = await self._validated_candidate(
                org,
                user,
                ContextSource.USER_DEFAULT,
                (prefs.default_project_id, prefs.default_site_id),
            )
            if cand is not None:
                return cand
        # Single-project convenience: exactly one authorized project.
        authorized = await self._d.projects.list_authorized_projects(
            organization_id=org, user_id=user
        )
        if len(authorized) == 1:
            return ContextCandidate(
                source=ContextSource.USER_DEFAULT,
                organization_id=org,
                project_id=authorized[0].project_id,
                site_id=None,
                confidence=context_policy.confidence_for_source(ContextSource.USER_DEFAULT),
                authorized=True,
                evidence="single authorized project",
            )
        return None

    # -- Build ----------------------------------------------------------------

    async def _build(
        self,
        principal: Principal,
        winner: ContextCandidate | None,
        message: NormalizedMessage,
    ) -> ResolvedContextV2:
        if winner is None:
            source = ContextSource.UNRESOLVED
            confidence = ContextConfidence.UNRESOLVED
            project_id = site_id = None
        else:
            source = winner.source
            confidence = winner.confidence
            project_id = winner.project_id
            site_id = winner.site_id

        (
            canonical_org,
            canonical_user,
            canonical_project,
            canonical_site,
        ) = await self._canonical_scope(
            context_organization_id=principal.organization_id,
            context_user_id=principal.user_id,
            context_project_id=project_id,
            context_site_id=site_id,
        )

        return ResolvedContextV2(
            correlation_id=message.correlation_id,
            source_message_id=message.message_id,
            causation_id=message.message_id,
            conversation_id=message.sender.wa_id,
            context_organization_id=principal.organization_id,
            context_user_id=principal.user_id,
            context_project_id=project_id,
            context_site_id=site_id,
            organization_id=canonical_org,
            user_id=canonical_user,
            project_id=canonical_project,
            site_id=canonical_site,
            membership_id=principal.membership_id,
            role_ids=principal.role_ids,
            permissions=principal.permissions,
            context_source=source,
            context_confidence=confidence,
            locale=principal.locale,
            timezone=principal.timezone,
        )
