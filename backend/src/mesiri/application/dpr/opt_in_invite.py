"""Inviting an outside DPR contact to opt in on WhatsApp (WA-09).

BE-15: an outside contact (client, architect...) on a project's DPR list
gets nothing until an opt-in is recorded. When one is added without it, the
company sends one invite -- "Suresh Builders would like to send you the
daily progress report for Green Towers on WhatsApp. Reply YES to receive
it, or STOP to never be messaged." -- and the reply records the answer
(whatsapp_opt_ins, method `whatsapp_reply`) with no admin involved.

- One invite per company and number, ever: not repeated if one was already
  queued, or if any answer is on record (an opt-out is never asked again).
- A YES or STOP from the number answers every company that invited it
  (decided 16 Oct).
- Only for numbers that aren't company users: the WhatsApp side checks the
  reply before its "not registered" path, so a user typing "stop" mid-chat
  is never opted out.
"""

from __future__ import annotations

import datetime
import re
import uuid
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.application.dpr.recipients import OPTED_IN, OPTED_OUT, WHATSAPP_REPLY

RULE_KEY_PREFIX = "dpr_optin:"
TEMPLATE_NAME = "mesiri_dpr_optin"

YES = "yes"
STOP = "stop"
#: Button ids, in the message and as the template's quick-reply payloads.
YES_ID = "optin:yes"
STOP_ID = "optin:stop"

INVITE_TEXT = (
    "{company} would like to send you the daily progress report for {project} on "
    "WhatsApp. Reply YES to receive it, or STOP to never be messaged."
)
THANKS_TEXT = "Thanks. You'll get the daily progress report from {companies} here."
STOPPED_TEXT = "Done. {companies} won't message you here again. Reply YES if you change your mind."

_YES_WORDS = frozenset({"YES", "Y", "YES PLEASE", "OK", "OKAY", "START", "SUBSCRIBE"})
_STOP_WORDS = frozenset({"STOP", "NO", "UNSUBSCRIBE", "STOP ALL", "OPT OUT", "OPTOUT"})


def rule_key(phone: str) -> str:
    return f"{RULE_KEY_PREFIX}{phone}"


def invite_payload(*, phone: str, company: str, project: str) -> dict[str, Any]:
    """The notification payload: in the 24-hour window a message with YES /
    STOP buttons; outside it (always, for a new contact) the template."""
    return {
        "to_wa_id": phone,
        "requires_opt_in": False,  # this is the request for it
        "message": INVITE_TEXT.format(company=company, project=project),
        "buttons": [{"id": YES_ID, "title": "YES"}, {"id": STOP_ID, "title": "STOP"}],
        "template": {
            "name": TEMPLATE_NAME,
            "body_params": [company, project],
            "button_payloads": [YES_ID, STOP_ID],
        },
    }


def parse_reply(text: str | None, interactive_id: str | None = None) -> str | None:
    """YES / STOP from a button tap or a typed reply, else None."""
    if interactive_id == YES_ID:
        return YES
    if interactive_id == STOP_ID:
        return STOP
    words = " ".join(re.sub(r"[^A-Za-z ]", " ", text or "").upper().split())
    if words in _YES_WORDS:
        return YES
    if words in _STOP_WORDS:
        return STOP
    return None


async def queue_invite(
    conn: AsyncConnection,
    *,
    organization_id: uuid.UUID,
    project_id: uuid.UUID,
    phone: str,
    today: datetime.date,
) -> bool:
    """Queue the one invite for this company and number. False when one was
    already queued or an answer is on record."""
    params = {"org": organization_id, "phone": phone, "key": rule_key(phone)}
    already = (
        await conn.execute(
            sa.text(
                "SELECT 1 FROM notifications WHERE organization_id = :org AND rule_key = :key "
                "UNION ALL "
                "SELECT 1 FROM whatsapp_opt_ins WHERE organization_id = :org AND phone = :phone "
                "LIMIT 1"
            ),
            params,
        )
    ).first()
    if already is not None:
        return False
    names = (
        await conn.execute(
            sa.text(
                "SELECT o.name AS company, p.name AS project FROM projects p "
                "JOIN organizations o ON o.id = p.organization_id "
                "WHERE p.id = :project AND p.organization_id = :org"
            ),
            {"org": organization_id, "project": project_id},
        )
    ).mappings().first()
    if names is None:
        return False
    from mesiri.infrastructure.postgres.repositories.notifications import (
        PostgresNotificationRepository,
    )

    claimed = await PostgresNotificationRepository(conn).claim(
        organization_id=organization_id,
        rule_key=rule_key(phone),
        subject_id=phone,
        occurred_on=today,
        recipient_user_id=None,
        project_id=project_id,
        payload=invite_payload(phone=phone, company=names["company"], project=names["project"]),
    )
    return claimed is not None


@dataclass(frozen=True)
class Answered:
    state: str
    companies: list[str]

    def reply(self) -> str:
        names = " and ".join(self.companies)
        return (THANKS_TEXT if self.state == OPTED_IN else STOPPED_TEXT).format(companies=names)


async def record_answer(conn: AsyncConnection, *, phone: str, answer: str) -> Answered | None:
    """Record YES / STOP for every company that invited this number. None
    when no company did (the reply isn't an answer to an invite)."""
    rows = (
        await conn.execute(
            sa.text(
                "SELECT DISTINCT o.id, o.name FROM notifications n "
                "JOIN organizations o ON o.id = n.organization_id "
                "WHERE n.rule_key = :key ORDER BY o.name"
            ),
            {"key": rule_key(phone)},
        )
    ).mappings().all()
    if not rows:
        return None
    from mesiri.infrastructure.postgres.repositories.report_recipients import (
        PostgresReportRecipientRepository,
    )

    state = OPTED_IN if answer == YES else OPTED_OUT
    repo = PostgresReportRecipientRepository(conn)
    for row in rows:
        await repo.record_consent(
            organization_id=row["id"],
            phone=phone,
            state=state,
            method=WHATSAPP_REPLY,
            note="Replied on WhatsApp to the opt-in invite",
        )
    return Answered(state=state, companies=[row["name"] for row in rows])
