"""What conversation memory covers, per scope, and how it may be used.

Nothing here does I/O. This module is the one place that declares the
contract every scope must honor -- TTL, and whether a scope may be treated as
authoritative -- so a new memory scope can't accidentally skip the "Redis is
a hint, not authorization" rule that context/active_context.py and
interactions/pending_media.py both already document independently.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class MemoryAuthority(str, Enum):
    """How much weight a caller may put on a scope's value.

    HINT: informs a default or a bias; must be revalidated against Postgres
    (or simply re-derived) before being used for authorization, billing, or
    anything a wrong guess would make expensive. Every scope below is HINT --
    there is no AUTHORITATIVE level in this module on purpose. If a future
    scope genuinely needs to be trusted outright, that is a deliberate
    architectural decision belonging in context/, not a default here.
    """

    HINT = "hint"


@dataclass(frozen=True, slots=True)
class MemoryScopeSpec:
    """One scope's storage contract: TTL and authority level.

    ``ttl_seconds`` is intentionally short across the board -- conversation
    memory answers "what were we just talking about", not "what happened last
    month". A scope that needs longer-lived recall belongs in Postgres
    (the domain tables already are that memory), not here.
    """

    name: str
    ttl_seconds: int
    authority: MemoryAuthority
    description: str


# Existing scopes, already implemented elsewhere -- listed here so the full
# picture of "what conversation memory covers" lives in one place, even
# though context_loader.py reads them via their own stores rather than
# duplicating storage. Do not add a second store for any of these.
CURRENT_PROJECT_SITE = MemoryScopeSpec(
    name="current_project_site",
    ttl_seconds=30 * 60,
    authority=MemoryAuthority.HINT,
    description=(
        "Last project/site the user was scoped to. Backed by "
        "context.active_context.RedisActiveContextStore. Revalidated against "
        "Postgres authorization on every read by ContextResolver -- never "
        "trusted outright."
    ),
)
PENDING_CONFIRMATION = MemoryScopeSpec(
    name="pending_confirmation",
    ttl_seconds=0,  # no TTL -- lives in Postgres (workflow_instances), not Redis
    authority=MemoryAuthority.HINT,
    description=(
        "The draft awaiting the user's YES/NO. Backed by the "
        "workflow_instances table (workflows/ports.py's "
        "WorkflowInstanceRepository), phases awaiting_confirmation / "
        "collecting_fields. Postgres-authoritative for workflow state, but "
        "still a HINT for scope inheritance -- see WORKFLOW_CONTEXT below."
    ),
)
PENDING_MEDIA = MemoryScopeSpec(
    name="pending_media",
    ttl_seconds=600,
    authority=MemoryAuthority.HINT,
    description=(
        "A newly-arrived image awaiting a 'what is this for?' answer. "
        "Backed by interactions.pending_media.PendingMediaStore."
    ),
)
NEXT_MESSAGE_INTENT_HINT = MemoryScopeSpec(
    name="next_message_intent_hint",
    ttl_seconds=300,
    authority=MemoryAuthority.HINT,
    description=(
        "A category-menu tap's bias for the very next message. Backed by "
        "interactions.category_hint.CategoryHintStore."
    ),
)

# New scopes, added by this module.
CURRENT_ACTIVITY = MemoryScopeSpec(
    name="current_activity",
    ttl_seconds=2 * 60 * 60,
    authority=MemoryAuthority.HINT,
    description=(
        "The Activity the user most recently created or continued in this "
        "conversation. Strictly better evidence for 'continue'/'finished it' "
        "than runtime.activity_query's ORDER BY updated_at DESC fallback, "
        "which has no notion of *this specific conversation*. Still only a "
        "hint: the seeding step must confirm the activity is still OPEN in "
        "Postgres before using it (an activity this memory points at may "
        "since have been completed or reassigned)."
    ),
)
CURRENT_DATE = MemoryScopeSpec(
    name="current_date",
    ttl_seconds=6 * 60 * 60,
    authority=MemoryAuthority.HINT,
    description=(
        "A date the user explicitly stated in this conversation ('for "
        "yesterday's pour'), remembered so a follow-up in the same "
        "conversation without its own date inherits it instead of silently "
        "defaulting to today. Never longer-lived than half a work day -- a "
        "stale remembered date defaulting a genuinely-new report to the "
        "wrong day is a worse failure mode than asking again."
    ),
)
RECENT_TURNS = MemoryScopeSpec(
    name="recent_turns",
    ttl_seconds=30 * 60,
    authority=MemoryAuthority.HINT,
    description=(
        "The last few (user text, assistant reply) pairs in this "
        "conversation. Hard-capped and TTL'd -- this is prompt-context "
        "fodder for later NLU, not an audit log (inbound_messages already is "
        "that, in Postgres, unbounded). Must never grow without bound."
    ),
)

# Cap enforced by RecentTurnsStore regardless of what a caller passes in --
# unbounded growth of a per-user Redis list is the one failure mode every
# other scope above structurally avoids by being single-slot.
# WA-58: 10, not 6 -- a clarification of a few turns (which project, how many,
# which unit) pushed the message it was about out of the window (live 23 Oct).
RECENT_TURNS_MAX_ENTRIES = 10
