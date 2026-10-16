"""YES / STOP from an outside DPR contact answering the opt-in invite (WA-09).

Checked only for numbers that aren't company users (message_journey's
unregistered branch, before self-serve signup), so a user typing "stop"
mid-conversation is never opted out. The rules -- which companies invited
the number, what gets recorded -- are in mesiri/application/dpr/opt_in_invite.py.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mesiri.infrastructure.postgres.database import PostgresDatabase

_log = logging.getLogger("mesiri.opt_in")


class OptInJourney:
    def __init__(self, *, db: PostgresDatabase) -> None:
        self._db = db

    async def handle(self, message: Any) -> str | None:
        """The reply to send, or None when this isn't an answer to an invite
        (the unregistered path then carries on as before)."""
        from mesiri.application.dpr.opt_in_invite import parse_reply, record_answer

        metadata = message.metadata or {}
        answer = parse_reply(message.text, str(metadata.get("interactive_reply_id") or ""))
        if answer is None:
            return None
        phone = re.sub(r"\D", "", str(message.sender.wa_id or ""))
        if not phone:
            return None
        try:
            async with self._db.transaction() as conn:
                answered = await record_answer(conn, phone=phone, answer=answer)
        except Exception:  # noqa: BLE001 -- fall back to the usual unregistered reply
            _log.exception("opt_in.record_failed")
            return None
        if answered is None:
            return None
        _log.info("opt_in.answered state=%s companies=%d", answered.state, len(answered.companies))
        return answered.reply()
