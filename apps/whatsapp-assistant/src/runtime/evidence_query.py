"""Evidence-attach service (#2 Batch Media, wiring layer only).

Same shape and justification as runtime/activity_query.py and
runtime/money_account_query.py: adapts the backend's
PostgresProgressExecutionRepository.persist_attach_evidence into a plain
async method the assistant can call directly.

Unlike every other confirmed-action dispatch (Material, Expense, Labour,
Progress's own CreateActivity/AddProgressUpdate), attaching evidence photos
is never behind a YES/NO confirmation -- a photo is unambiguous evidence,
not a business fact someone could have misheard (see
AttachEvidenceCommand's docstring in shared/contracts). So this is called
directly from the WhatsApp image-purpose tap handler (runtime/dependencies.py),
not through interactions/ExecutionDispatcher/WorkflowRuntime -- there is no
draft, no workflow_instance, nothing to confirm.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mesiri.infrastructure.postgres.database import PostgresDatabase


class EvidenceAttachService:
    def __init__(self, db: PostgresDatabase) -> None:
        self._db = db

    async def attach_photos(
        self,
        *,
        organization_id: str,
        activity_id: str,
        media_object_keys: list[str],
        uploaded_by: str,
        correlation_id: str,
        mime_type: str | None = None,
        caption: str | None = None,
        captions: list[str | None] | None = None,
    ) -> list[str]:
        """Attach every photo in ``media_object_keys`` to ``activity_id`` in
        one transaction. Returns the created progress_attachments ids -- an
        empty list is a legitimate outcome (an empty batch), never an
        error.

        ``captions`` (PHO-01): one per photo, the sender's own words, kept
        with their photo; ``caption`` is the one for all of them."""
        if not media_object_keys:
            return []

        from mesiri.application.progress.repository import ProgressExecutionRepository
        from mesiri.infrastructure.postgres.repositories.progress_execution import (
            PostgresProgressExecutionRepository,
        )
        from mesiri_contracts.application.commands.progress import AttachEvidenceCommand
        from mesiri_contracts.common.ids import new_id

        per_photo = list(captions) if captions is not None else [caption] * len(media_object_keys)
        per_photo += [caption] * (len(media_object_keys) - len(per_photo))
        # One command per run of photos with the same caption, in the order they came.
        groups: list[tuple[str | None, list[str]]] = []
        for key, text in zip(media_object_keys, per_photo, strict=False):
            said = (text or "").strip() or None
            if groups and groups[-1][0] == said:
                groups[-1][1].append(key)
            else:
                groups.append((said, [key]))
        repo: ProgressExecutionRepository = PostgresProgressExecutionRepository()
        created: list[str] = []
        async with self._db.transaction() as conn:
            for text, keys in groups:
                cmd = AttachEvidenceCommand(
                    command_id=new_id("cmd"),
                    correlation_id=correlation_id,
                    organization_id=organization_id,
                    activity_id=activity_id,
                    media_object_keys=keys,
                    mime_type=mime_type,
                    caption=text,
                    uploaded_by=uploaded_by,
                )
                created += await repo.persist_attach_evidence(conn, cmd)
        return created
