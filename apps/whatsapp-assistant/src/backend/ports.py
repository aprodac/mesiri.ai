"""Backend capability boundary — what the assistant is allowed to know.

The assistant (context resolution, live-identity bridge, planner, workflows)
may depend on these types and protocols. They MUST NOT depend on:

  - table names (users, organizations, projects, sites)
  - JOIN conditions
  - SQLAlchemy models or ORM details
  - database migrations
  - raw tenant-filtering SQL

Concrete implementations live in backend/postgres/ and own all persistence
knowledge. If the backend schema changes, only those adapters change — the
assistant logic is untouched.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

# ---------------------------------------------------------------------------
# Domain models (assistant-visible surface)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProjectSummary:
    """A project the actor is authorized to see."""

    id: str
    name: str
    location: str | None = None
    code: str | None = None
    status: str | None = None
    progress: int | None = None
    open_issues: int | None = None


@dataclass(frozen=True, slots=True)
class SiteSummary:
    """A site the actor is authorized to see."""

    id: str
    name: str
    project_id: str | None = None


@dataclass(frozen=True, slots=True)
class ActorIdentity:
    """The authoritative, tenant-scoped identity resolved for a WhatsApp sender.

    This is what the assistant knows about the person who sent a message.
    It carries enough context for identity gates, user-facing replies, and
    project/site selection — nothing more.
    """

    user_id: str
    full_name: str
    role: str
    organization_id: str | None
    org_name: str | None
    org_active: bool
    projects: list[ProjectSummary] = field(default_factory=list)
    sites: list[SiteSummary] = field(default_factory=list)
    #: organizations.timezone (IANA name); None = India.
    timezone: str | None = None


# ---------------------------------------------------------------------------
# Ports — what the assistant depends on
# ---------------------------------------------------------------------------


class ActorReader(Protocol):
    """Resolves a WhatsApp sender to their authoritative ActorIdentity.

    Returns None when the wa_id is unregistered (no matching user record).
    The implementation owns all schema/SQL knowledge; the assistant knows
    only ActorIdentity.
    """

    async def resolve_by_whatsapp_id(self, wa_id: str) -> ActorIdentity | None: ...

    async def resolve_whatsapp_id_by_user_id(self, user_id: str) -> str | None:
        """The reverse lookup -- #9 Notifications needs to turn a
        backend-resolved recipient_user_id back into the wa_id
        WhatsAppSender sends to. None when the user has no whatsapp_number
        on file or is not active."""
        ...
