"""Tell the person who hit a dead end that it works now (TM-16, Ilan 29 Oct 2026).

The production watch reports a dead end ("Photo ayakkan Mesiri-kku kazhiyilla") in the team group; an owner
approves the plan; the change is built and deployed. The same push adds a note to ``release_notes.json`` next to
this app, naming the production messages (their correlation ids) of the people who tried it, and the words to send
them. After the deploy, the scheduler's tick (automation_runner.py) queues one ``notifications`` row per person per
note, and the shared send step delivers it like any reminder: inside the 24-hour window, opt-outs and quiet hours
respected.

Only what is in the repository, so only approved and pushed work, can message anyone, and only the people whose own
messages the note names. Each person gets a note once (the notifications table's UNIQUE key on rule, person, day:
the note's own date). Notes older than ``MAX_AGE_DAYS`` are ignored, so a fresh database is never sent old news.
"""

from __future__ import annotations

import datetime
import json
import logging
import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: The notes file, shipped with the app (apps/whatsapp-assistant/release_notes.json).
NOTES_PATH = Path(__file__).resolve().parents[2] / "release_notes.json"
RULE_PREFIX = "release:"
MAX_AGE_DAYS = 7
MAX_CHARS = 700
_ID = re.compile(r"^[a-z0-9][a-z0-9-]{2,60}$")


@dataclass(frozen=True)
class ReleaseNote:
    id: str
    date: datetime.date
    correlation_ids: tuple[str, ...]
    message: str


def parse_notes(raw: Any) -> list[ReleaseNote]:
    """The valid notes of ``{"notes": [{id, date, for: [correlation ids], message}]}``; a bad one is skipped
    and logged, never raised (a typo in one note must not stop the tick)."""
    out: list[ReleaseNote] = []
    for entry in (raw or {}).get("notes") or []:
        try:
            note_id = str(entry["id"]).strip()
            message = " ".join(str(entry["message"]).split(" ")).strip()
            ids = tuple(str(c).strip() for c in entry.get("for") or [] if str(c).strip())
            if not _ID.match(note_id) or not message or len(message) > MAX_CHARS or not ids:
                raise ValueError("id, message (at most 700 characters) and for are required")
            out.append(ReleaseNote(note_id, datetime.date.fromisoformat(str(entry["date"])), ids, message))
        except Exception as exc:  # noqa: BLE001
            logger.warning("release_notes.bad_note entry=%r error=%s", str(entry)[:120], exc)
    return out


def load_notes(path: Path = NOTES_PATH) -> list[ReleaseNote]:
    try:
        return parse_notes(json.loads(path.read_text(encoding="utf-8")))
    except FileNotFoundError:
        return []
    except Exception:  # noqa: BLE001
        logger.exception("release_notes.unreadable path=%s", path)
        return []


def due_notes(notes: list[ReleaseNote], today: datetime.date) -> list[ReleaseNote]:
    return [n for n in notes if 0 <= (today - n.date).days <= MAX_AGE_DAYS]


@dataclass(frozen=True)
class Requester:
    organization_id: uuid.UUID
    user_id: uuid.UUID


async def _requester_sql(conn: Any, correlation_id: str) -> Requester | None:
    """The registered user who sent the production message ``correlation_id``, or None."""
    import sqlalchemy as sa

    row = (
        (
            await conn.execute(
                sa.text(
                    "SELECT im.organization_id, u.id AS user_id FROM inbound_messages im "
                    "JOIN users u ON u.organization_id = im.organization_id "
                    " AND regexp_replace(u.whatsapp_number, '\\D', '', 'g') "
                    "   = regexp_replace(im.sender_wa_id, '\\D', '', 'g') "
                    "WHERE im.correlation_id = :cid LIMIT 1"
                ),
                {"cid": correlation_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None or row["organization_id"] is None:
        return None
    return Requester(uuid.UUID(str(row["organization_id"])), uuid.UUID(str(row["user_id"])))


async def queue_release_notes(
    conn: Any,
    *,
    today: datetime.date | None = None,
    notes: list[ReleaseNote] | None = None,
    requester: Callable[[Any, str], Awaitable[Requester | None]] = _requester_sql,
    claim: Callable[..., Awaitable[Any]] | None = None,
) -> int:
    """Queue each due note once for each person it names. Returns how many were queued now."""
    today = today or datetime.datetime.now(datetime.UTC).date()
    due = due_notes(load_notes() if notes is None else notes, today)
    if not due:
        return 0
    if claim is None:
        from mesiri.infrastructure.postgres.repositories.notifications import (
            PostgresNotificationRepository,
        )

        claim = PostgresNotificationRepository(conn).claim
    queued = 0
    for note in due:
        seen: set[uuid.UUID] = set()
        for cid in note.correlation_ids:
            try:
                who = await requester(conn, cid)
                if who is None or who.user_id in seen:
                    continue
                seen.add(who.user_id)
                claimed = await claim(
                    organization_id=who.organization_id,
                    rule_key=f"{RULE_PREFIX}{note.id}",
                    subject_id=str(who.user_id),
                    occurred_on=note.date,
                    recipient_user_id=who.user_id,
                    payload={"message": note.message},
                )
                if claimed is not None:
                    queued += 1
                    logger.info("release_notes.queued note=%s user=%s", note.id, who.user_id)
            except Exception:  # noqa: BLE001 -- one person's lookup must not stop the others
                logger.exception("release_notes.failed note=%s correlation_id=%s", note.id, cid)
    return queued
