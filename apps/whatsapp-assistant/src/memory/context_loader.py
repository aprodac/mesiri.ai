"""Loads a ContextPack for a user by reading the existing scattered stores.

This is the ONE place that composes context/active_context.py,
interactions/pending_report.py, interactions/pending_media.py, this
package's own recent_turns.py/conversation_scope.py, and the workflow
runtime's pending-confirmation check into a single snapshot. It does not
reimplement or replace any of those stores -- see memory/requirements.py's
docstring for why duplicating them would be wrong.

Every read here is independent of every other, so they run concurrently via
asyncio.gather -- the same pattern context/resolver.py already uses for its
own five-source precedence gather.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol

from context.active_context import RedisActiveContextStore
from interactions.pending_media import PendingMediaStore

from .context_pack import ContextPack
from .conversation_scope import CurrentActivityStore, CurrentDateStore
from .recent_turns import RecentTurnsStore

logger = logging.getLogger(__name__)


class _PendingConfirmationCheck(Protocol):
    """The one capability this loader needs from WorkflowRuntime: whether the
    user has an open confirmation or slot question. A narrow Protocol rather
    than importing WorkflowRuntime directly -- memory/ has no other reason to
    depend on workflows/, and this keeps the dependency one-directional
    (workflows/ may one day want to read memory/, never the reverse)."""

    async def get_awaiting_confirmation(self, user_id: str) -> object | None: ...
    async def get_awaiting_input(self, user_id: str) -> object | None: ...


class ConversationMemoryLoader:
    """Builds one ContextPack per inbound message.

    A Redis outage on any single scope must not break the journey -- every
    read below degrades to that scope's "unknown" value (None / False / ())
    rather than raising, since a ContextPack is a hint the caller can always
    fall back from. Errors are logged once per scope, not per field, since a
    Redis outage affects every scope on the same read at once and one line is
    enough to say so.
    """

    def __init__(
        self,
        *,
        active_context: RedisActiveContextStore,
        current_activity: CurrentActivityStore,
        current_date: CurrentDateStore,
        recent_turns: RecentTurnsStore,
        pending_media: PendingMediaStore,
        workflow_runtime: _PendingConfirmationCheck,
    ) -> None:
        self._active_context = active_context
        self._current_activity = current_activity
        self._current_date = current_date
        self._recent_turns = recent_turns
        self._pending_media = pending_media
        self._workflow_runtime = workflow_runtime

    async def current_activity_id(self, *, user_id: str) -> str | None:
        """The activity this conversation last touched (a hint; never raises)."""
        return await self._safe(self._current_activity.get_current(user_id=user_id), scope="current_activity")

    async def load(self, *, organization_id: str, user_id: str) -> ContextPack:
        (
            active,
            activity_id,
            current_date,
            turns,
            pending_media_present,
            awaiting_confirmation,
            awaiting_input,
        ) = await asyncio.gather(
            self._safe(
                self._active_context.get_active_context(
                    organization_id=organization_id, user_id=user_id
                ),
                scope="active_context",
            ),
            self._safe(self._current_activity.get_current(user_id=user_id), scope="current_activity"),
            self._safe(self._current_date.get_current(user_id=user_id), scope="current_date"),
            self._safe(self._recent_turns.recent(user_id=user_id), scope="recent_turns", default=()),
            self._safe(
                self._pending_media.has_pending(user_id=user_id),
                scope="pending_media",
                default=False,
            ),
            self._safe(
                self._workflow_runtime.get_awaiting_confirmation(user_id),
                scope="awaiting_confirmation",
            ),
            self._safe(
                self._workflow_runtime.get_awaiting_input(user_id), scope="awaiting_input"
            ),
        )

        return ContextPack(
            user_id=user_id,
            current_project_id=active.project_id if active else None,
            current_site_id=active.site_id if active else None,
            current_activity_id=activity_id,
            current_date=current_date,
            has_pending_confirmation=awaiting_confirmation is not None
            or awaiting_input is not None,
            has_pending_media=bool(pending_media_present),
            recent_turns=turns or (),
        )

    @staticmethod
    async def _safe(coro, *, scope: str, default=None):
        try:
            return await coro
        except Exception:  # noqa: BLE001 -- a memory read must never break the journey
            logger.warning("memory.load_failed scope=%s", scope, exc_info=True)
            return default
