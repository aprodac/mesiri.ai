"""What a trial company's people hear on WhatsApp as the trial ends (SS-08).

Rules and wording: mesiri/domains/organizations/trial_notices.py. The
reminders themselves are queued by the scheduler (application/
organizations/trial.py); this module answers messages:

- **Expired trial**, called from the "company not active" branch:
  - the owner hears the trial has ended, that their data is safe for N
    days, with a [Continue with Mesiri] button;
  - anyone else is told to ask the owner.

  A suspended company is not ours: the caller keeps its own reply.
- **"CONTINUE"** from a trial owner (the reminder asks for it), typed or
  tapped, before or after expiry: records a continue request for the
  control panel and tells the Mesiri team's WhatsApp group. Converting to
  paid stays manual (SS-10).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from channel.replies import ListRow, ReplySpec
from mesiri.application.organizations.trial import expiry_details, record_continue_request
from mesiri.domains.organizations import lifecycle
from mesiri.domains.organizations import trial_notices as notices

if TYPE_CHECKING:
    from backend.ports import ActorIdentity
    from mesiri.infrastructure.postgres.database import PostgresDatabase
    from runtime.team_notify import TeamNotifier

_log = logging.getLogger("mesiri.trial")

_OWNER_ROLE = "ADMIN"


def _wants_to_continue(message: Any) -> bool:
    tap = str((message.metadata or {}).get("interactive_reply_id") or "")
    return tap == notices.CONTINUE_TAP or notices.is_continue(message.text)


class TrialJourney:
    def __init__(self, *, db: PostgresDatabase, notifier: TeamNotifier) -> None:
        self._db = db
        self._notifier = notifier

    async def handle_inactive(self, message: Any, actor: ActorIdentity) -> ReplySpec | None:
        """The reply for a company that isn't operational, when that's because
        its trial ended; None otherwise (suspended), for the caller's reply."""
        async with self._db.transaction() as conn:
            details = await expiry_details(conn, actor.organization_id)
        if details is None or details["effective_status"] != lifecycle.EXPIRED:
            return None
        if str(actor.role or "").upper() != _OWNER_ROLE:
            return ReplySpec(
                text=notices.expired_member_message(
                    company=details["company"], owner_name=details["owner_name"]
                )
            )
        if _wants_to_continue(message):
            return await self._continue(actor)
        return ReplySpec(
            text=notices.expired_owner_message(
                end_day=details["end_day"], retention_days=details["retention_days"]
            ),
            buttons=[ListRow(id=notices.CONTINUE_TAP, title="Continue with Mesiri")],
        )

    async def handle_continue(self, message: Any, actor: ActorIdentity) -> ReplySpec | None:
        """A trial company owner's "CONTINUE", while the trial still runs; None for
        anything else, including the same word from a paying company."""
        if not _wants_to_continue(message):
            return None
        if str(actor.role or "").upper() != _OWNER_ROLE:
            return None
        async with self._db.transaction() as conn:
            details = await expiry_details(conn, actor.organization_id)
        if details is None or details["effective_status"] != lifecycle.TRIAL:
            return None
        return await self._continue(actor)

    async def _continue(self, actor: ActorIdentity) -> ReplySpec:
        async with self._db.transaction() as conn:
            added = await record_continue_request(
                conn, actor.organization_id, user_id=str(actor.user_id), via="whatsapp"
            )
        if not added:
            return ReplySpec(text=notices.CONTINUE_ALREADY)
        _log.info("trial.continue_requested org=%s", actor.organization_id)
        await self._notifier.post(
            f"💰 *{actor.org_name or 'A trial company'}* wants to continue with Mesiri "
            f"({actor.full_name}). Please call them and convert in the control panel."
        )
        return ReplySpec(text=notices.CONTINUE_RECEIVED)
