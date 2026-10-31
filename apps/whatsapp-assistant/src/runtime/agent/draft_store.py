"""Where the open drafts live (request 124, P1): the ``message_drafts`` table.

One open draft per sender (the table's partial unique index is the guarantee).
Save claims it inside the same transaction that writes the items, so a double
tap writes once and a failed save leaves it open; Cancel discards it. Postgres,
not Redis: it survives a restart and the control panel can read it
(ADR-draft-per-message section 3).

``MemoryDraftStore`` is the same behaviour for tests and for a deployment with
no database.
"""

from __future__ import annotations

import contextlib
import json
import logging
import time
import uuid
from typing import Any, Protocol

from runtime.save_first import canonical_uuid

from .draft import DISCARDED, DRAFT_TTL_SECONDS, OPEN, SAVED, DraftItem, MessageDraft

_log = logging.getLogger("mesiri.agent")


class DraftStore(Protocol):
    async def open_for(self, organization_id: Any, user_id: Any) -> MessageDraft | None:
        """The sender's open draft, or None (an expired one is discarded)."""
        ...

    async def get(self, draft_id: str, organization_id: Any, user_id: Any) -> MessageDraft | None:
        """The sender's own draft by id, whatever its state."""
        ...

    async def put(self, draft: MessageDraft) -> None:
        """Create or update an open draft."""
        ...

    async def claim(self, draft_id: str) -> bool:
        """open -> saved, once: False when it was already taken (a second tap)."""
        ...

    async def discard(self, draft_id: str) -> bool:
        """open -> discarded: False when it was not open."""
        ...

    async def latest_closed(
        self, organization_id: Any, user_id: Any, within_seconds: float
    ) -> MessageDraft | None:
        """Request 162: the sender's most recent draft that was cancelled or saved
        within ``within_seconds`` (None when it is older, or one is open): what a
        late word like "I didn't say workers" or a tap on its old button is about."""
        ...


def _items(raw: Any) -> list[DraftItem]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return []
    return [item for item in (DraftItem.from_json(r) for r in raw or []) if item is not None]


class MemoryDraftStore:
    def __init__(self) -> None:
        self.rows: dict[str, MessageDraft] = {}

    @staticmethod
    def _mine(draft: MessageDraft, organization_id: Any, user_id: Any) -> bool:
        return draft.organization_id == str(organization_id) and draft.user_id == str(user_id)

    async def open_for(self, organization_id: Any, user_id: Any) -> MessageDraft | None:
        for draft in self.rows.values():
            if draft.status == OPEN and self._mine(draft, organization_id, user_id):
                if draft.expired():
                    draft.status = DISCARDED
                    continue
                return _copy(draft)
        return None

    async def get(self, draft_id: str, organization_id: Any, user_id: Any) -> MessageDraft | None:
        draft = self.rows.get(draft_id)
        return _copy(draft) if draft is not None and self._mine(draft, organization_id, user_id) else None

    async def put(self, draft: MessageDraft) -> None:
        draft.updated = time.time()
        draft.persisted = True
        self.rows[draft.id] = _copy(draft)

    async def claim(self, draft_id: str) -> bool:
        draft = self.rows.get(draft_id)
        if draft is None or draft.status != OPEN:
            return False
        draft.status = SAVED
        draft.updated = time.time()
        return True

    async def latest_closed(
        self, organization_id: Any, user_id: Any, within_seconds: float
    ) -> MessageDraft | None:
        mine = [d for d in self.rows.values() if self._mine(d, organization_id, user_id)]
        if any(d.status == OPEN and not d.expired() for d in mine):
            return None
        closed = [d for d in mine if d.status in (SAVED, DISCARDED) and time.time() - d.updated <= within_seconds]
        return _copy(max(closed, key=lambda d: d.updated)) if closed else None

    @contextlib.asynccontextmanager
    async def transaction(self):
        """All-or-nothing like ``PostgresDatabase.shared_transaction()``: what
        the block did to the rows is undone when it raises."""
        before = {k: _copy(v) for k, v in self.rows.items()}
        try:
            yield
        except BaseException:
            self.rows = before
            raise

    async def discard(self, draft_id: str) -> bool:
        draft = self.rows.get(draft_id)
        if draft is None or draft.status != OPEN:
            return False
        draft.status = DISCARDED
        draft.updated = time.time()
        return True


def _copy(draft: MessageDraft) -> MessageDraft:
    clone = MessageDraft(
        id=draft.id,
        organization_id=draft.organization_id,
        user_id=draft.user_id,
        items=_items([i.to_json() for i in draft.items]),
        project_id=draft.project_id,
        site_id=draft.site_id,
        source_message_id=draft.source_message_id,
        status=draft.status,
        created=draft.created,
        updated=draft.updated,
        persisted=draft.persisted,
    )
    return clone


class PostgresDraftStore:
    """``message_drafts`` through ``PostgresDatabase.transaction()``: inside a
    ``shared_transaction()`` (the Save tap) every call joins it."""

    def __init__(self, db: Any) -> None:
        self._db = db

    @staticmethod
    def _draft(row: Any) -> MessageDraft:
        return MessageDraft(
            id=uuid.UUID(str(row["id"])).hex,
            organization_id=str(row["organization_id"]),
            user_id=str(row["user_id"]),
            items=_items(row["items"]),
            project_id=str(row["project_id"]) if row["project_id"] else None,
            site_id=str(row["site_id"]) if row["site_id"] else None,
            source_message_id=row["source_message_id"],
            status=row["status"],
            created=float(row["created_epoch"]),
            updated=float(row["updated_epoch"]),
            persisted=True,
        )

    _COLUMNS = (
        "id, organization_id, user_id, project_id, site_id, source_message_id, status, items, "
        "EXTRACT(EPOCH FROM created_at) AS created_epoch, EXTRACT(EPOCH FROM updated_at) AS updated_epoch"
    )

    async def open_for(self, organization_id: Any, user_id: Any) -> MessageDraft | None:
        from sqlalchemy import text

        org, user = canonical_uuid(organization_id), canonical_uuid(user_id)
        if org is None or user is None:
            return None
        async with self._db.transaction() as conn:
            row = (
                await conn.execute(
                    text(
                        f"SELECT {self._COLUMNS} FROM message_drafts "
                        "WHERE organization_id = :org AND user_id = :user AND status = 'open'"
                    ),
                    {"org": org, "user": user},
                )
            ).mappings().first()
            if row is None:
                return None
            draft = self._draft(row)
            if draft.expired():
                await conn.execute(
                    text("UPDATE message_drafts SET status = 'discarded', updated_at = now() WHERE id = :id AND status = 'open'"),
                    {"id": uuid.UUID(draft.id)},
                )
                return None
            return draft

    async def get(self, draft_id: str, organization_id: Any, user_id: Any) -> MessageDraft | None:
        from sqlalchemy import text

        org, user = canonical_uuid(organization_id), canonical_uuid(user_id)
        if org is None or user is None:
            return None
        try:
            ident = uuid.UUID(hex=draft_id)
        except ValueError:
            return None
        async with self._db.transaction() as conn:
            row = (
                await conn.execute(
                    text(
                        f"SELECT {self._COLUMNS} FROM message_drafts "
                        "WHERE id = :id AND organization_id = :org AND user_id = :user"
                    ),
                    {"id": ident, "org": org, "user": user},
                )
            ).mappings().first()
        return self._draft(row) if row is not None else None

    async def put(self, draft: MessageDraft) -> None:
        from sqlalchemy import text

        items = json.dumps([i.to_json() for i in draft.items], default=str)
        params = {
            "id": uuid.UUID(hex=draft.id),
            "org": canonical_uuid(draft.organization_id),
            "user": canonical_uuid(draft.user_id),
            "project": canonical_uuid(draft.project_id),
            "site": canonical_uuid(draft.site_id),
            "source": draft.source_message_id,
            "items": items,
        }
        async with self._db.transaction() as conn:
            await conn.execute(
                text(
                    "INSERT INTO message_drafts (id, organization_id, user_id, project_id, site_id, "
                    "source_message_id, status, items) "
                    "VALUES (:id, :org, :user, :project, :site, :source, 'open', CAST(:items AS jsonb)) "
                    "ON CONFLICT (id) DO UPDATE SET items = EXCLUDED.items, project_id = EXCLUDED.project_id, "
                    "site_id = EXCLUDED.site_id, updated_at = now() WHERE message_drafts.status = 'open'"
                ),
                params,
            )
        draft.persisted = True
        draft.updated = time.time()

    async def claim(self, draft_id: str) -> bool:
        from sqlalchemy import text

        async with self._db.transaction() as conn:
            row = (
                await conn.execute(
                    text(
                        "UPDATE message_drafts SET status = 'saved', saved_at = now(), updated_at = now() "
                        "WHERE id = :id AND status = 'open' RETURNING id"
                    ),
                    {"id": uuid.UUID(hex=draft_id)},
                )
            ).first()
        return row is not None

    async def latest_closed(
        self, organization_id: Any, user_id: Any, within_seconds: float
    ) -> MessageDraft | None:
        from sqlalchemy import text

        org, user = canonical_uuid(organization_id), canonical_uuid(user_id)
        if org is None or user is None:
            return None
        async with self._db.transaction() as conn:
            row = (
                await conn.execute(
                    text(
                        f"SELECT {self._COLUMNS} FROM message_drafts "
                        "WHERE organization_id = :org AND user_id = :user "
                        "AND status IN ('saved', 'discarded') "
                        "AND updated_at > now() - make_interval(secs => :secs) "
                        "AND NOT EXISTS (SELECT 1 FROM message_drafts o WHERE o.organization_id = :org "
                        "AND o.user_id = :user AND o.status = 'open') "
                        "ORDER BY updated_at DESC LIMIT 1"
                    ),
                    {"org": org, "user": user, "secs": float(within_seconds)},
                )
            ).mappings().first()
        return self._draft(row) if row is not None else None

    async def discard(self, draft_id: str) -> bool:
        from sqlalchemy import text

        async with self._db.transaction() as conn:
            row = (
                await conn.execute(
                    text(
                        "UPDATE message_drafts SET status = 'discarded', updated_at = now() "
                        "WHERE id = :id AND status = 'open' RETURNING id"
                    ),
                    {"id": uuid.UUID(hex=draft_id)},
                )
            ).first()
        return row is not None


__all__ = ["DISCARDED", "DRAFT_TTL_SECONDS", "OPEN", "SAVED", "DraftStore", "MemoryDraftStore", "PostgresDraftStore"]
