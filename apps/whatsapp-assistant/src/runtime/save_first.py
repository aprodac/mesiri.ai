"""Save first, confirm later on WhatsApp (WA-01).

Decided 13 Oct 2026: what a site sends -- work done, labour, materials in
and used, site issues -- is saved straight away as a DRAFT, and the site
engineer confirms the day's drafts with the evening DPR. The old
"Confirm? YES/NO" step is skipped for these flows; questions the record
genuinely needs (which worker? which site? replace today's list?) are still
asked before saving.

Quiet daytime (WA-03): during the day ask only what is needed to file the
update correctly -- which project, site, material or unit; arrived or used;
a missing quantity; which worker; replace or add to today's list. Anything
else is saved and shown on the evening report instead. So far that is:

- usage beyond known stock: saved, flagged on the DPR (BE-12's
  ``beyond_stock``), and the saved reply says so (``over_stock_note``);
- "is this the open work or new work?": saved as new work.

A company switched back to confirm-first keeps every question.

Saving goes through the exact path a "YES" takes (InteractionHandler.
save_now -> runtime.resume(CONFIRM) -> the module's own dispatcher), so the
duplicate guard, gates, events and multi-part plans behave exactly as for a
confirmed reply. This module only decides WHICH flows save first, records
the draft (backend fact_reviews, BE-09) with what the AI read
(extractions), and undoes the sender's latest draft on "UNDO".

`capture_mode` (company setting, default save_first) switches a company
back to confirm-first without a deploy.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from mesiri_contracts.assistant.draft_action import DraftActionType
from mesiri_contracts.assistant.planner_decision import WorkflowKey
from trade_label import trade_label

if TYPE_CHECKING:
    from mesiri.infrastructure.postgres.database import PostgresDatabase

    from .org_settings_query import OrganizationSettingsQueryService

_log = logging.getLogger("mesiri.save_first")

#: The capture flows that save first. Everything else (corrections, undo,
#: admin, queries) still asks before writing.
SAVE_FIRST_KEYS: frozenset[WorkflowKey] = frozenset(
    {
        WorkflowKey.SITE_UPDATE,
        WorkflowKey.ACTIVITY_CONTINUATION,
        WorkflowKey.LABOUR_ATTENDANCE,
        WorkflowKey.MATERIAL_RECEIPT,
        WorkflowKey.MATERIAL_USAGE,
        WorkflowKey.MATERIAL_TRANSFER,
        WorkflowKey.SITE_ISSUE_REPORT,
    }
)

#: Which review log entry each saved action becomes. A progress update is
#: saved first too but belongs to its activity, which is what gets reviewed.
FACT_TYPE_BY_ACTION: dict[DraftActionType, str] = {
    DraftActionType.CREATE_ACTIVITY: "activity",
    DraftActionType.RECORD_LABOUR_ATTENDANCE: "labour_report",
    DraftActionType.RECORD_MATERIAL_RECEIPT: "material_receipt",
    DraftActionType.RECORD_MATERIAL_USAGE: "material_usage",
    # The outflow is the reviewable fact: rejecting it takes back both halves.
    DraftActionType.TRANSFER_MATERIAL: "material_usage",
    DraftActionType.RECORD_SITE_ISSUE: "site_issue",
}

#: Appended to the saved reply (wording approved 13 Oct).
DRAFT_NOTE = "Saved as a draft. You'll confirm it with tonight's report. Reply UNDO if it's wrong."

#: WA-03: above the draft note when a saved usage is more than the known stock.
OVER_STOCK_NOTE = "That's more than the {available} in stock, so it's flagged on tonight's report."

#: BE-13: the note instead, when the entry's day was already confirmed.
LATE_REOPEN_NOTE = (
    "Saved. {site}'s report for {day} was already confirmed but hasn't gone out yet, "
    "so I've reopened it. Please confirm the day again. Reply UNDO if it's wrong."
)
LATE_REVISED_NOTE = (
    "Saved as a late entry. {site}'s report for {day} was already confirmed and sent, "
    "so this shows in your next report and in a revised copy of {day}'s. "
    "Reply UNDO if it's wrong."
)

#: What a reply to "UNDO" says, per fact type.
_UNDONE_LABEL: dict[str, str] = {
    "activity": "the work update",
    "labour_report": "the attendance",
    "material_receipt": "the material received",
    "material_usage": "the material used",
    "site_issue": "the issue",
}

#: How far back "UNDO" reaches: the sender's own latest draft from the last
#: few hours, never something older they may have forgotten about.
UNDO_WINDOW_HOURS = 6

_USER_PREFIX = "ctx_user_"


def canonical_uuid(value: Any) -> uuid.UUID | None:
    """A WhatsApp-side id as a database UUID (`ctx_user_<uuid>` or a bare
    UUID string). None when it is neither -- the review log then simply
    records no actor rather than failing the save."""
    text = str(value or "")
    if text.startswith(_USER_PREFIX):
        text = text[len(_USER_PREFIX) :]
    try:
        return uuid.UUID(text)
    except ValueError:
        return None


async def company_saves_first(
    org_settings_query: OrganizationSettingsQueryService | None, organization_id: str | None
) -> bool:
    """Whether this company saves capture drafts without asking (the default,
    also when its setting can't be read)."""
    if org_settings_query is None or not organization_id:
        return True
    from mesiri.domains.organizations import settings as settings_spec

    stored = await org_settings_query.get(
        organization_id=str(organization_id), key=settings_spec.CAPTURE_MODE
    )
    return settings_spec.saves_first(stored)


#: [103]: under the over-stock line when no opening stock was ever entered.
OPENING_STOCK_HINT = 'If there was stock before Mesiri, send "opening stock {material} 500 {unit}".'


def over_stock_note(
    action_type: DraftActionType,
    quantity: Any,
    unit: Any,
    available_stock: Any,
    *,
    no_opening_stock: bool = False,
    material: Any = None,
) -> str | None:
    """WA-03: the line saying a saved usage is more than the known stock, or
    None when it is not (or the figures can't be read)."""
    if action_type is not DraftActionType.RECORD_MATERIAL_USAGE or available_stock is None:
        return None
    try:
        used, available = float(quantity), float(available_stock)
    except (TypeError, ValueError):
        return None
    if used <= available:
        return None
    unit_text = f" {unit}" if unit else ""
    note = OVER_STOCK_NOTE.format(available=f"{available:g}{unit_text}")
    if no_opening_stock:
        name = " ".join(str(material or "").casefold().split()) or "cement"
        note += "\n" + OPENING_STOCK_HINT.format(material=name, unit=unit or "bags")
    return note


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def _replaces(new: dict[str, Any], old: dict[str, Any]) -> bool:
    """Whether `new`, sent later the same site-day, replaces `old` -- the
    backend's COUNTED_LINE_SQL rule (repositories/workforce.py), in Python."""
    if old.get("worker_id") and str(new.get("worker_id") or "") == str(old["worker_id"]):
        return True
    if _norm(old.get("worker_name")):
        return _norm(new.get("worker_name")) == _norm(old.get("worker_name"))
    if old.get("worker_id"):
        return False
    return (
        not new.get("worker_id")
        and not _norm(new.get("worker_name"))
        and _norm(new.get("contractor")) == _norm(old.get("contractor"))
        and _norm(new.get("trade")) == _norm(old.get("trade"))
    )


def _headcount(line: dict[str, Any]) -> int:
    try:
        return int(line.get("headcount") or 1)
    except (TypeError, ValueError):
        return 1


def snapshot_note(
    action_type: DraftActionType, new_lines: Any, day_lines: Any
) -> str | None:
    """BE-10: the line saying which of today's figures a re-send replaced
    ("Ravi mason 10 → 12"), or None when it replaced nothing. Labour is the
    latest figure per contractor + trade (or per named worker) for the day,
    so the supervisor is told instead of asked."""
    if action_type is not DraftActionType.RECORD_LABOUR_ATTENDANCE:
        return None
    if not isinstance(new_lines, list) or not isinstance(day_lines, list):
        return None
    new = [line for line in new_lines if isinstance(line, dict)]
    old = [line for line in day_lines if isinstance(line, dict)]

    # One entry per thing a person would name: a worker, or contractor + trade.
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for line in new:
        if line.get("worker_id") or _norm(line.get("worker_name")):
            key = ("worker", str(line.get("worker_id") or _norm(line.get("worker_name"))))
        else:
            key = ("crew", _norm(line.get("contractor")), _norm(line.get("trade")))
        groups.setdefault(key, []).append(line)

    changed: list[str] = []
    repeated: list[str] = []
    for key, lines in groups.items():
        replaced = [o for o in old if any(_replaces(n, o) for n in lines)]
        if not replaced:
            continue
        first = lines[0]
        if key[0] == "worker":
            repeated.append(str(first.get("worker_name") or "a worker").strip())
            continue
        label = " ".join(
            part
            for part in (
                str(first.get("contractor") or "").strip(),
                trade_label(first.get("trade")),
            )
            if part
        ) or "workers"
        before = sum(_headcount(o) for o in replaced)
        after = sum(_headcount(n) for n in lines)
        if before == after:
            repeated.append(f"{label} {after}")
        else:
            changed.append(f"{label} {before} → {after}")

    parts: list[str] = []
    if changed:
        parts.append("Updated today's figures: " + ", ".join(changed) + ".")
    if repeated:
        parts.append("Already recorded today, counted once: " + ", ".join(repeated) + ".")
    return " ".join(parts) or None


class SaveFirstService:
    """Never raises into the journey: a failure to record the draft is
    logged and the save itself (already done) stands."""

    def __init__(
        self,
        db: PostgresDatabase,
        org_settings_query: OrganizationSettingsQueryService | None = None,
    ) -> None:
        self._db = db
        self._settings = org_settings_query

    async def applies(self, *, workflow_key: WorkflowKey | None, organization_id: str | None) -> bool:
        """Whether this flow, for this company, saves without asking."""
        if workflow_key not in SAVE_FIRST_KEYS:
            return False
        return await company_saves_first(self._settings, organization_id)

    async def record_draft(
        self,
        *,
        organization_id: str,
        actor_user_id: str | None,
        action_type: DraftActionType,
        fact_id: str,
        fields: dict[str, Any],
        correlation_id: str | None,
    ) -> bool:
        """Mark the just-saved item as a draft and keep what the AI read.
        False when this action is not reviewed (a progress update) or the
        write failed."""
        fact_type = FACT_TYPE_BY_ACTION.get(action_type)
        org_uuid = canonical_uuid(organization_id)
        fact_uuid = canonical_uuid(fact_id)
        if fact_type is None or org_uuid is None or fact_uuid is None:
            return False
        from mesiri.infrastructure.postgres.repositories.fact_reviews import (
            PostgresFactReviewRepository,
        )

        try:
            async with self._db.transaction() as conn:
                model_row = None
                if correlation_id:
                    from sqlalchemy import text

                    model_row = (
                        await conn.execute(
                            text(
                                "SELECT id, provider, model FROM provider_executions "
                                "WHERE correlation_id = :cid AND model IS NOT NULL "
                                "AND succeeded = true LIMIT 1"
                            ),
                            {"cid": correlation_id},
                        )
                    ).mappings().first()
                reviews = PostgresFactReviewRepository(conn)
                extraction_id = await reviews.record_extraction(
                    organization_id=org_uuid,
                    extracted={"action_type": action_type.value, "fields": fields},
                    correlation_id=correlation_id,
                    provider_execution_id=model_row["id"] if model_row else None,
                    provider=model_row["provider"] if model_row else None,
                    model=model_row["model"] if model_row else None,
                    confidence=_confidence(fields),
                )
                await reviews.mark_draft(
                    organization_id=org_uuid,
                    fact_type=fact_type,
                    fact_id=fact_uuid,
                    extraction_id=extraction_id,
                    actor_user_id=canonical_uuid(actor_user_id),
                )
            return True
        except Exception:  # noqa: BLE001 -- the item is saved; only its draft mark failed
            _log.exception(
                "save_first.record_draft_failed fact_type=%s fact_id=%s", fact_type, fact_id
            )
            return False

    async def note_for(
        self, *, organization_id: str, action_type: DraftActionType, fact_id: str
    ) -> str:
        """The line under the saved reply: the usual draft note, or -- when
        the entry's site day was already confirmed -- what happens to it
        (BE-13). Falls back to the usual note on any doubt."""
        fact_type = FACT_TYPE_BY_ACTION.get(action_type)
        org_uuid = canonical_uuid(organization_id)
        fact_uuid = canonical_uuid(fact_id)
        if fact_type is None or org_uuid is None or fact_uuid is None:
            return DRAFT_NOTE
        try:
            from sqlalchemy import text

            from mesiri.application.dpr.late_entries import REOPENED, day_status_for_fact
            from mesiri.infrastructure.postgres.repositories.fact_reviews import _FACT_SOURCES

            table, date_expr = _FACT_SOURCES[fact_type]
            async with self._db.transaction() as conn:
                located = (
                    await conn.execute(
                        text(
                            f"SELECT t.site_id, {date_expr} AS fact_date, s.name AS site_name "
                            f"FROM {table} t LEFT JOIN sites s ON s.id = t.site_id "
                            "WHERE t.organization_id = :org AND t.id = :id"
                        ),
                        {"org": org_uuid, "id": fact_uuid},
                    )
                ).mappings().first()
                if located is None or located["site_id"] is None:
                    return DRAFT_NOTE
                outcome = await day_status_for_fact(
                    conn,
                    organization_id=org_uuid,
                    site_id=located["site_id"],
                    fact_date=located["fact_date"],
                )
        except Exception:  # noqa: BLE001 -- the usual note is never wrong to show
            _log.exception("save_first.note_failed fact_type=%s fact_id=%s", fact_type, fact_id)
            return DRAFT_NOTE
        if outcome is None:
            return DRAFT_NOTE
        day = f"{located['fact_date'].day} {located['fact_date']:%b}"
        site = located["site_name"] or "This site"
        template = LATE_REOPEN_NOTE if outcome == REOPENED else LATE_REVISED_NOTE
        return template.format(site=site, day=day)

    async def undo_latest_draft(
        self, *, organization_id: str | None, actor_user_id: str | None
    ) -> str | None:
        """Reject the sender's latest still-draft item from the last few
        hours, through its module's own undo. Returns the reply to send, or
        None when there is no such draft (the normal "undo" handling then
        runs, as before)."""
        org_uuid = canonical_uuid(organization_id)
        actor_uuid = canonical_uuid(actor_user_id)
        if org_uuid is None or actor_uuid is None:
            return None
        from sqlalchemy import text

        from mesiri.application.dpr.fact_review import FactReviewError
        from mesiri.infrastructure.postgres.repositories.fact_reviews import (
            PostgresFactReviewRepository,
        )

        try:
            async with self._db.transaction() as conn:
                row = (
                    await conn.execute(
                        text(
                            """
                            SELECT fact_type, fact_id FROM (
                                SELECT DISTINCT ON (fact_type, fact_id)
                                       fact_type, fact_id, state, actor_user_id, created_at
                                FROM fact_reviews
                                WHERE organization_id = :org_id
                                  AND created_at > now() - make_interval(hours => :hours)
                                ORDER BY fact_type, fact_id, created_at DESC
                            ) latest
                            WHERE state = 'draft' AND actor_user_id = :actor
                            ORDER BY created_at DESC
                            LIMIT 1
                            """
                        ),
                        {"org_id": org_uuid, "actor": actor_uuid, "hours": UNDO_WINDOW_HOURS},
                    )
                ).mappings().first()
                if row is None:
                    return None
                try:
                    await PostgresFactReviewRepository(conn).reject(
                        organization_id=org_uuid,
                        fact_type=row["fact_type"],
                        fact_id=row["fact_id"],
                        actor_user_id=actor_uuid,
                        reason="Undone on WhatsApp by the sender",
                    )
                except FactReviewError as exc:
                    return f"Couldn't undo that: {exc}."
            return f"Done. I've removed {_UNDONE_LABEL.get(row['fact_type'], 'that update')}."
        except Exception:  # noqa: BLE001 -- fall back to the normal undo handling
            _log.exception("save_first.undo_failed actor=%s", actor_user_id)
            return None

    async def undo_facts(
        self,
        *,
        organization_id: str | None,
        actor_user_id: str | None,
        facts: list[tuple[str, uuid.UUID]],
    ) -> FactsUndone:
        """Request 88: withdraw exactly these entries (the ones the sender's
        last card held), saved or still drafts, each through its module's own
        undo. Only the sender's own, in their own company, and not already
        withdrawn; each in its own transaction, so one refusal (its day was
        already confirmed) leaves the rest done. Unlike ``undo_latest_draft``
        it never picks a record itself."""
        undone = FactsUndone()
        org_uuid = canonical_uuid(organization_id)
        actor_uuid = canonical_uuid(actor_user_id)
        if org_uuid is None or actor_uuid is None:
            undone.refused.append("not your entry")
            return undone
        from sqlalchemy import text

        from mesiri.application.dpr import fact_review
        from mesiri.application.dpr.fact_review import FactReviewError
        from mesiri.infrastructure.postgres.repositories.fact_reviews import (
            PostgresFactReviewRepository,
        )

        reason = "Undone on WhatsApp by the sender"
        from runtime.day_facts import PROGRESS_UPDATE

        for fact_type, fact_id in facts:
            if fact_type == PROGRESS_UPDATE:
                await self._void_update(org_uuid, actor_uuid, fact_id, reason, undone)
                continue
            try:
                async with self._db.transaction() as conn:
                    latest = (
                        await conn.execute(
                            text(
                                """
                                SELECT state, actor_user_id FROM fact_reviews
                                WHERE organization_id = :org_id
                                  AND fact_type = :fact_type AND fact_id = :fact_id
                                ORDER BY created_at DESC
                                LIMIT 1
                                """
                            ),
                            {"org_id": org_uuid, "fact_type": fact_type, "fact_id": fact_id},
                        )
                    ).mappings().first()
                    # An entry with no review row cannot be tied to the sender.
                    if latest is None or canonical_uuid(latest["actor_user_id"]) != actor_uuid:
                        undone.refused.append("not your entry")
                        continue
                    state = latest["state"]
                    if state == fact_review.REJECTED:
                        undone.already += 1
                        continue
                    reviews = PostgresFactReviewRepository(conn)
                    if state == fact_review.DRAFT:
                        await reviews.reject(
                            organization_id=org_uuid,
                            fact_type=fact_type,
                            fact_id=fact_id,
                            actor_user_id=actor_uuid,
                            reason=reason,
                        )
                    else:
                        # Saved (confirmed): reject() only takes drafts, so the
                        # same steps it runs, minus that one check.
                        located = await reviews.locate(org_uuid, fact_type, fact_id)
                        await reviews._refuse_if_day_frozen(org_uuid, located)  # noqa: SLF001
                        await reviews._undo(org_uuid, fact_type, fact_id, actor_uuid, reason)  # noqa: SLF001
                        await reviews._append(  # noqa: SLF001
                            organization_id=org_uuid,
                            fact_type=fact_type,
                            fact_id=fact_id,
                            located=located,
                            state=fact_review.REJECTED,
                            extraction_id=None,
                            actor_user_id=actor_uuid,
                            note=reason,
                        )
                    undone.done.append((fact_type, fact_id))
            except FactReviewError as exc:
                undone.refused.append(str(exc))
            except Exception:  # noqa: BLE001 -- the sender is told; the log keeps the cause
                _log.exception("save_first.undo_facts_failed fact_type=%s fact_id=%s", fact_type, fact_id)
                undone.refused.append("something went wrong")
        return undone

    async def _void_update(
        self, org_uuid: uuid.UUID, actor_uuid: uuid.UUID, update_id: uuid.UUID, reason: str, undone: FactsUndone
    ) -> None:
        """Request 137: one progress update (continued work) taken back through the
        progress module's own void -- the sender's own, refused once its day is in
        an approved report. The activity and its earlier updates stay."""
        from sqlalchemy import text

        from mesiri.infrastructure.postgres.repositories.progress import (
            PostgresProgressReadRepository,
        )
        from runtime.day_facts import PROGRESS_UPDATE

        try:
            async with self._db.transaction() as conn:
                row = (
                    await conn.execute(
                        text(
                            "SELECT pu.reported_by_user_id, pu.deleted_at FROM progress_updates pu"
                            " JOIN activities a ON a.id = pu.activity_id"
                            " WHERE pu.id = :id AND a.organization_id = :org"
                        ),
                        {"id": update_id, "org": org_uuid},
                    )
                ).mappings().first()
                if row is None or canonical_uuid(row["reported_by_user_id"]) != actor_uuid:
                    undone.refused.append("not your entry")
                    return
                if row["deleted_at"] is not None:
                    undone.already += 1
                    return
                refused = await PostgresProgressReadRepository(conn).void_progress_update(
                    organization_id=org_uuid, update_id=update_id, reason=reason, corrected_by_user_id=actor_uuid
                )
                if refused:
                    undone.refused.append(refused)
                    return
                undone.done.append((PROGRESS_UPDATE, update_id))
        except Exception:  # noqa: BLE001 -- the sender is told; the log keeps the cause
            _log.exception("save_first.void_update_failed update_id=%s", update_id)
            undone.refused.append("something went wrong")

    async def settle_drafts(
        self,
        *,
        organization_id: str | None,
        actor_user_id: str | None,
        facts: list[tuple[str, uuid.UUID]],
        keep: bool,
    ) -> DraftsSettled:
        """The agent's Save / Cancel tap (WA-35): confirm (``keep``) or reject
        the drafts one reply showed. Only the sender's own drafts in their own
        company, and only those still drafts; each in its own transaction, so
        one refused item (its day already confirmed) leaves the rest done."""
        settled = DraftsSettled()
        org_uuid = canonical_uuid(organization_id)
        actor_uuid = canonical_uuid(actor_user_id)
        if org_uuid is None or actor_uuid is None:
            settled.refused.append("not your entry")
            return settled
        from sqlalchemy import text

        from mesiri.application.dpr.fact_review import FactReviewError
        from mesiri.infrastructure.postgres.repositories.fact_reviews import (
            PostgresFactReviewRepository,
        )

        for fact_type, fact_id in facts:
            try:
                async with self._db.transaction() as conn:
                    latest = (
                        await conn.execute(
                            text(
                                """
                                SELECT state, actor_user_id FROM fact_reviews
                                WHERE organization_id = :org_id
                                  AND fact_type = :fact_type AND fact_id = :fact_id
                                ORDER BY created_at DESC
                                LIMIT 1
                                """
                            ),
                            {"org_id": org_uuid, "fact_type": fact_type, "fact_id": fact_id},
                        )
                    ).mappings().first()
                    # No review row means the item was never a draft: it counts
                    # as kept (fact_review.states_for).
                    state = latest["state"] if latest is not None else "confirmed"
                    if state != "draft":
                        if (state == "confirmed") == keep:
                            settled.already += 1
                        else:
                            settled.refused.append(
                                "it was already saved; fix it on the dashboard"
                                if keep is False
                                else "it was already cancelled; send it again"
                            )
                        continue
                    if canonical_uuid(latest["actor_user_id"]) != actor_uuid:
                        settled.refused.append("not your entry")
                        continue
                    reviews = PostgresFactReviewRepository(conn)
                    if keep:
                        await reviews.confirm(
                            organization_id=org_uuid,
                            fact_type=fact_type,
                            fact_id=fact_id,
                            actor_user_id=actor_uuid,
                        )
                    else:
                        await reviews.reject(
                            organization_id=org_uuid,
                            fact_type=fact_type,
                            fact_id=fact_id,
                            actor_user_id=actor_uuid,
                            reason="Cancelled on WhatsApp by the sender",
                        )
                    settled.done += 1
            except FactReviewError as exc:
                settled.refused.append(str(exc))
            except Exception:  # noqa: BLE001 -- the tap is told; the log keeps the cause
                _log.exception(
                    "save_first.settle_failed keep=%s fact_type=%s fact_id=%s", keep, fact_type, fact_id
                )
                settled.refused.append("something went wrong")
        return settled


@dataclass(slots=True)
class FactsUndone:
    """What ``undo_facts`` did: the entries withdrawn, how many were already
    withdrawn, and why any were refused."""

    done: list[tuple[str, uuid.UUID]] = field(default_factory=list)
    already: int = 0
    refused: list[str] = field(default_factory=list)


@dataclass(slots=True)
class DraftsSettled:
    """What a Save / Cancel tap did: how many drafts it settled, how many were
    no longer drafts, and why any were refused."""

    done: int = 0
    already: int = 0
    refused: list[str] = field(default_factory=list)


def _confidence(fields: dict[str, Any]) -> str | None:
    """The extraction's ContextConfidence, when the draft carries one."""
    for key in ("confidence", "context_confidence", "extraction_confidence"):
        value = fields.get(key)
        if isinstance(value, str) and value:
            return value
    return None
