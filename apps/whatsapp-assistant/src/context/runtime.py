"""Context resolver production wiring and development diagnostics.

Constructs the authoritative M4 ContextResolver with:
- Adapters reading the main (control-plane) tables for identity, membership,
  roles, projects, sites, and preferences (lazily initialized — no sqlalchemy
  import at module load).
- A caller-supplied Redis client for the active-context store: a real
  ``RedisClient`` in production (connected by the lifespan handler) or
  ``FakeRedis`` for the unit-test / no-Redis lane.
"""

from __future__ import annotations

import logging
import os

from context.active_context import RedisActiveContextStore
from context.main_table_repositories import (
    MainContextPreferenceRepository,
    MainExternalIdentityRepository,
    MainIdentityBridgeRepository,
    MainMembershipRepository,
    MainProjectRepository,
    MainReplyContextProvider,
    MainRolePermissionRepository,
    MainSiteRepository,
    MainWorkflowContextProvider,
)
from context.resolver import ContextDependencies, ContextResolver
from mesiri_contracts.assistant.v2.resolved_context import ResolvedContextV2

logger = logging.getLogger(__name__)


class _LazyAsyncEngine:
    """Defers SQLAlchemy engine creation to the first database query.

    Allows ``build_context_resolver()`` to run without sqlalchemy installed
    (sqlalchemy is an optional infra dependency absent in the fast unit-test
    lane). Only the ``connect()`` method is proxied because that is the only
    method used by the context repository mixins.
    """

    def __init__(self) -> None:
        self._engine = None

    def connect(self):  # returns the same async context manager as a real engine
        return self._get_engine().connect()

    def _get_engine(self):
        if self._engine is None:
            from sqlalchemy.ext.asyncio import create_async_engine

            host = os.environ.get("MESIRI_POSTGRES__HOST", "localhost")
            port = os.environ.get("MESIRI_POSTGRES__PORT", "5432")
            user_ = os.environ.get("MESIRI_POSTGRES__USER", "mesiri")
            password = os.environ.get("MESIRI_POSTGRES__PASSWORD", "mesiri_local_dev")
            database = os.environ.get("MESIRI_POSTGRES__DATABASE", "mesiri")
            dsn = f"postgresql+asyncpg://{user_}:{password}@{host}:{port}/{database}"
            self._engine = create_async_engine(dsn, echo=False, pool_pre_ping=True)
        return self._engine


def _identity_ports(engine) -> dict:
    """The identity/scope ports, read straight from the main tables (BE-01)."""
    return {
        "identities": MainExternalIdentityRepository(engine),
        "memberships": MainMembershipRepository(engine),
        "roles": MainRolePermissionRepository(),
        "projects": MainProjectRepository(engine),
        "sites": MainSiteRepository(engine),
        "preferences": MainContextPreferenceRepository(),
        "reply_context": MainReplyContextProvider(engine),
        "workflow_context": MainWorkflowContextProvider(engine),
        "bridge": MainIdentityBridgeRepository(engine),
    }


def build_context_resolver(redis=None) -> ContextResolver:
    """Construct the production M4 ContextResolver.

    Args:
        redis: A connected redis-like client satisfying the ``_RedisLike``
            protocol (``namespaced``, ``set_json``, ``get_json``). When
            ``None`` the in-process ``FakeRedis`` is used — correct for the
            unit-test lane and for local development without a Redis instance.
            Pass a connected ``RedisClient`` from ``build_container()`` for
            production deployments.

    The SQLAlchemy engine is built lazily on the first database query so the
    resolver can be constructed in the fast unit-test lane (no sqlalchemy
    required at import time).
    """
    if redis is None:
        from mesiri.infrastructure.redis.client import FakeRedis

        redis = FakeRedis()

    engine = _LazyAsyncEngine()
    ports = _identity_ports(engine)

    deps = ContextDependencies(
        identities=ports["identities"],
        memberships=ports["memberships"],
        roles=ports["roles"],
        projects=ports["projects"],
        sites=ports["sites"],
        preferences=ports["preferences"],
        active_context=RedisActiveContextStore(redis),
        # Real adapters as of the reply/workflow-context wiring: these were
        # Null providers, which silently disabled two of the five precedence
        # levels in context_policy. Both fail soft (None = "no opinion"), so
        # the chain simply falls through to ACTIVE_CONTEXT / USER_DEFAULT as
        # before if either lookup finds nothing.
        reply_context=ports["reply_context"],
        workflow_context=ports["workflow_context"],
        bridge=ports["bridge"],
        redis=redis,  # identity cache TTL=60s
    )
    return ContextResolver(deps)


def log_resolved_context(context: ResolvedContextV2) -> None:
    """Log the M4 ResolvedContext v2 for development visibility (not user-facing)."""
    logger.info(
        "ResolvedContext correlation_id=%s context_user=%s context_org=%s "
        "canonical_user=%s canonical_org=%s project=%s site=%s source=%s confidence=%s",
        context.correlation_id,
        context.context_user_id or "unknown",
        context.context_organization_id or "unknown",
        context.user_id or "unknown",
        context.organization_id or "unknown",
        context.project_id or "unknown",
        context.site_id or "unknown",
        context.context_source.value,
        context.context_confidence.value,
    )
    if context.role_ids:
        logger.info("ResolvedContext roles=%s", context.role_ids)
    if context.permissions:
        logger.info("ResolvedContext permissions=%s", context.permissions)
