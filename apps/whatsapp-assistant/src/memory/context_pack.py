"""ContextPack -- the resolved conversation-memory snapshot for one message.

An immutable value object, not a store: context_loader.py builds one of these
per inbound message by reading the existing scattered stores concurrently.
Nothing in this module does I/O.
"""

from __future__ import annotations

from dataclasses import dataclass

from memory.recent_turns import ConversationTurn


@dataclass(frozen=True, slots=True)
class ContextPack:
    """Everything conversation memory knows about this user, at this moment.

    Every field is a HINT (see memory/requirements.py) -- callers must not
    treat a populated field as authorization or as ground truth. ``None``
    means "no opinion", not "confirmed absent"; a caller falling back to its
    own resolution logic on None is always correct.
    """

    user_id: str
    current_project_id: str | None
    current_site_id: str | None
    current_activity_id: str | None
    current_date: str | None
    has_pending_confirmation: bool
    has_pending_media: bool
    recent_turns: tuple[ConversationTurn, ...]

    @property
    def is_mid_interaction(self) -> bool:
        """True when the user has ANY open loop -- a pending confirmation,
        a held report gate, or a held image. Callers that need to decide
        "is this a fresh request or a continuation of something open" should
        read this rather than checking the three flags individually, so a
        future fourth open-loop kind is covered automatically."""
        return (
            self.has_pending_confirmation
            or self.has_pending_media
        )
