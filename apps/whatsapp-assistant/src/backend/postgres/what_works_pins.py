"""What works pins (SA-39 phase 5): the conversation a platform admin chose as the model example of one journey.

All SQL for ``what_works_pins`` (migration 0552) is here. A pin is keyed by (capability, journey) and points at
the first inbound message of the pinned request. Pin and unpin write their ``admin_audit_log`` entry in the same
transaction (``record_admin_action``): saved together or not at all. Platform-admin only at the caller.
"""

from __future__ import annotations

import uuid
from typing import Any

from mesiri.domains.audit.actions import WHAT_WORKS_PINNED, WHAT_WORKS_UNPINNED, AuditActor


class PostgresWhatWorksPins:
    def __init__(self, engine: Any) -> None:
        self._engine = engine

    async def list(self) -> dict[tuple[str, str], dict[str, Any]]:
        """Every pin by (capability, journey)."""
        from sqlalchemy import text

        async with self._engine.connect() as conn:
            rows = (await conn.execute(text(
                "SELECT capability, journey, message_id, note, pinned_by_label, pinned_at FROM what_works_pins"
            ))).mappings().all()
        return {(r["capability"], r["journey"]): {
            "message_id": str(r["message_id"]), "note": r["note"], "by": r["pinned_by_label"],
            "at": r["pinned_at"].isoformat() if r["pinned_at"] else None,
        } for r in rows}

    async def pin(self, *, capability: str, journey: str, message_id: uuid.UUID, note: str | None,
                  actor: AuditActor) -> None:
        """Pin (or replace the pin of) one journey, and record it."""
        from sqlalchemy import text

        from mesiri.application.audit.record import record_admin_action

        async with self._engine.begin() as conn:
            before = (await conn.execute(text(
                "SELECT message_id FROM what_works_pins WHERE capability = :c AND journey = :j"
            ), {"c": capability, "j": journey})).scalar()
            await conn.execute(text(
                "INSERT INTO what_works_pins (capability, journey, message_id, note, pinned_by, pinned_by_label, "
                "pinned_at) VALUES (:c, :j, :m, :n, :by, :label, now()) "
                "ON CONFLICT (capability, journey) DO UPDATE SET message_id = EXCLUDED.message_id, "
                "note = EXCLUDED.note, pinned_by = EXCLUDED.pinned_by, pinned_by_label = EXCLUDED.pinned_by_label, "
                "pinned_at = now()"
            ), {"c": capability, "j": journey, "m": message_id, "n": note, "by": actor.user_id, "label": actor.label})
            await record_admin_action(
                conn, actor=actor, action=WHAT_WORKS_PINNED, target_type="what_works_journey",
                target_id=f"{capability}/{journey}", summary=f"Pinned the example of {journey} for {capability}",
                details={"capability": capability, "journey": journey, "message_id": str(message_id),
                         "before": str(before) if before else None, "note": note},
            )

    async def unpin(self, *, capability: str, journey: str, actor: AuditActor) -> bool:
        """Remove the pin of one journey (the scored pick shows again); False when there was none."""
        from sqlalchemy import text

        from mesiri.application.audit.record import record_admin_action

        async with self._engine.begin() as conn:
            removed = (await conn.execute(text(
                "DELETE FROM what_works_pins WHERE capability = :c AND journey = :j RETURNING message_id"
            ), {"c": capability, "j": journey})).scalar()
            if removed is None:
                return False
            await record_admin_action(
                conn, actor=actor, action=WHAT_WORKS_UNPINNED, target_type="what_works_journey",
                target_id=f"{capability}/{journey}", summary=f"Unpinned the example of {journey} for {capability}",
                details={"capability": capability, "journey": journey, "message_id": str(removed)},
            )
        return True
