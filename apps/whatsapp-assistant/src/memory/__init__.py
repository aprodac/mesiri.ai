"""Conversation memory (M19) -- see requirements.py for the scope list.

Public surface: ``ConversationMemoryLoader`` (read), ``ConversationMemoryCoordinator``
(write), and ``build_conversation_memory()`` (wiring). Everything else in this
package is an implementation detail of one scope's storage.
"""

from __future__ import annotations

from context.active_context import RedisActiveContextStore

from .context_loader import ConversationMemoryLoader
from .context_pack import ContextPack
from .conversation_scope import CurrentActivityStore, CurrentDateStore
from .coordinator import ConversationMemoryCoordinator
from .recent_turns import ConversationTurn, RecentTurnsStore

__all__ = [
    "ContextPack",
    "ConversationMemoryLoader",
    "ConversationMemoryCoordinator",
    "ConversationTurn",
    "build_conversation_memory",
]


def build_conversation_memory(
    redis, workflow_runtime
) -> tuple[ConversationMemoryLoader, ConversationMemoryCoordinator]:
    """Construct the loader + coordinator pair from one Redis client.

    ``redis`` is a connected M1 RedisClient (or FakeRedis) satisfying the
    narrow ``_RedisLike`` protocol each scope store declares independently --
    same convention as context.runtime.build_context_resolver(). Reuses
    interactions.pending_report / interactions.pending_media's own stores
    rather than constructing new ones, so both slices share the exact same
    Redis-backed state (there is only one pending report per user, never a
    separate copy for memory's own bookkeeping).

    ``workflow_runtime`` must satisfy memory.context_loader's
    _PendingConfirmationCheck protocol -- pass the same WorkflowRuntime
    instance already built for interactions/dependencies wiring.
    """
    from interactions.pending_media import PendingMediaStore

    active_context = RedisActiveContextStore(redis)
    current_activity = CurrentActivityStore(redis)
    current_date = CurrentDateStore(redis)
    recent_turns = RecentTurnsStore(redis)
    pending_media = PendingMediaStore(redis)

    loader = ConversationMemoryLoader(
        active_context=active_context,
        current_activity=current_activity,
        current_date=current_date,
        recent_turns=recent_turns,
        pending_media=pending_media,
        workflow_runtime=workflow_runtime,
    )
    coordinator = ConversationMemoryCoordinator(
        current_activity=current_activity,
        current_date=current_date,
        recent_turns=recent_turns,
    )
    return loader, coordinator
