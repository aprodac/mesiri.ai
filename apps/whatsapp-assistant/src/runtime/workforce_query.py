"""Workforce register lookups for the Labour attendance workflow.

The matching node needs candidates from the register to decide whether a
reported "Ravi" is someone already known (Labour plan principle P4 — never
identified by name alone). A node must never query a repository itself (see
workflows/runtime.py), so the read happens here and is seeded into the event's
fields by runtime/inbound_journey.py's `_seed_worker_candidates`, exactly as
money accounts are for expense.

**2026-07-27: this is now backed by the real database.** It shipped as a stub
while Labour was built conversation-first, and the stub is kept below only for
local/test use where no database exists. The register (``workforce_workers``)
is real, has dashboard CRUD (domains/workforce/router.py), and attendance
history (``labour_attendance_lines``) is real too — so "has this worker been
seen on this site before", the single strongest corroborating signal matching
has, is now a genuine answer rather than a configured guess.

Why that signal matters enough to compute here rather than defer: P4 caps a
name-only match below auto-accept by construction, so without corroboration
*every* named worker asks a question. `seen_on_site` / `seen_on_project` are
what let a returning worker match silently, which is what keeps a ten-worker
report to zero questions instead of ten (P9).

Two properties this deliberately preserves from the stub era:

- **Read-only.** There is no write path here at all. Attendance never writes
  the register (principle P1); promotion is a separate, explicitly confirmed
  act performed from the dashboard.
- **Never invents a worker.** An organization with an empty register gets an
  empty list, every named worker becomes a temporary worker, and nothing is
  asked (principle P3). That is correct behaviour, not a degraded mode.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from mesiri.infrastructure.postgres.database import PostgresDatabase

logger = logging.getLogger(__name__)

STUB_WORKERS_ENV = "MESIRI_LABOUR__STUB_WORKERS"

#: Only active workers are offered as candidates. A retired worker must never
#: be silently matched onto a new report -- if they genuinely returned, that
#: is a deliberate reactivation on the dashboard, not something attendance
#: capture should infer.
_ACTIVE = "active"

#: Upper bound on candidates handed to matching. Matching is O(candidates x
#: reported names) pure scoring, and a prompt can only show 10 options anyway
#: (channel/replies.py's list limit), so reading an entire 2000-worker register
#: into memory for one report would be waste, not thoroughness.
_MAX_CANDIDATES = 200


class WorkforceQueryService(Protocol):
    """Read-only access to the workforce register."""

    async def list_worker_candidates(
        self,
        *,
        organization_id: str,
        project_id: str | None = None,
        site_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Registered workers plausibly on this project/site.

        Each entry matches `domains/workforce/matching.WorkerCandidate`'s
        shape: worker_id, name, and optionally trade, contractor,
        seen_on_site, seen_on_project.
        """
        ...

    async def create_worker(
        self,
        *,
        organization_id: str,
        name: str,
        trade: str | None = None,
        daily_wage: object | None = None,
        created_by: str | None = None,
    ) -> str:
        """Insert a new active permanent worker and return its UUID string."""
        ...

    async def attach_team_photo(
        self,
        *,
        organization_id: str,
        report_id: str,
        media_object_key: str,
        created_by: str | None = None,
    ) -> str | None:
        """Attach a team photo to a recorded attendance report."""
        ...

    async def find_existing_report_for_day(
        self,
        *,
        organization_id: str,
        project_id: str,
        site_id: str | None,
        occurred_date: str,
    ) -> dict[str, Any] | None:
        """The live report already recorded for this site and day, if any.

        Returns report_id, total_headcount, total_cost and line_count so the
        supervisor can be told what is already on record before deciding
        whether this new report replaces it, plus `counted_lines` (BE-10: the
        lines the day counts right now, across every live report). None --
        the ordinary case -- means the day is clear.
        """
        ...


class PostgresWorkforceQueryService:
    """Reads the real register, annotated with where each worker has worked."""

    def __init__(self, db: PostgresDatabase) -> None:
        self._db = db

    async def list_worker_candidates(
        self,
        *,
        organization_id: str,
        project_id: str | None = None,
        site_id: str | None = None,
    ) -> list[dict[str, Any]]:
        import sqlalchemy as sa

        try:
            org_id = uuid.UUID(organization_id)
        except (TypeError, ValueError):
            return []

        # seen_on_site / seen_on_project are computed in SQL rather than by
        # reading attendance history into Python: the register is the small
        # table and its history is the large one, so the join belongs in the
        # database. EXISTS (not a count) because matching only asks whether
        # the worker has been here before, never how often.
        lines = sa.table(
            "labour_attendance_lines",
            sa.column("worker_id"),
            sa.column("report_id"),
        )
        reports = sa.table(
            "labour_attendance_reports",
            sa.column("id"),
            sa.column("project_id"),
            sa.column("site_id"),
            sa.column("organization_id"),
        )
        workers = sa.table(
            "workforce_workers",
            sa.column("id"),
            sa.column("organization_id"),
            sa.column("name"),
            sa.column("trade"),
            sa.column("contractor"),
            sa.column("status"),
        )

        def _worked_in(scope_column, scope_value: uuid.UUID):
            return (
                sa.select(sa.literal(1))
                .select_from(lines.join(reports, lines.c.report_id == reports.c.id))
                .where(
                    lines.c.worker_id == workers.c.id,
                    reports.c.organization_id == org_id,
                    scope_column == scope_value,
                )
                .exists()
            )

        seen_on_site: Any = sa.literal(False)
        seen_on_project: Any = sa.literal(False)
        if site_id:
            try:
                seen_on_site = _worked_in(reports.c.site_id, uuid.UUID(site_id))
            except (TypeError, ValueError):
                pass
        if project_id:
            try:
                seen_on_project = _worked_in(reports.c.project_id, uuid.UUID(project_id))
            except (TypeError, ValueError):
                pass

        query = (
            sa.select(
                workers.c.id,
                workers.c.name,
                workers.c.trade,
                workers.c.contractor,
                seen_on_site.label("seen_on_site"),
                seen_on_project.label("seen_on_project"),
            )
            .where(
                workers.c.organization_id == org_id,
                workers.c.status == _ACTIVE,
            )
            .order_by(workers.c.name)
            .limit(_MAX_CANDIDATES)
        )

        async with self._db.transaction() as conn:
            rows = (await conn.execute(query)).mappings().all()

        return [
            {
                "worker_id": str(row["id"]),
                "name": row["name"],
                "trade": row["trade"],
                "contractor": row["contractor"],
                "seen_on_site": bool(row["seen_on_site"]),
                "seen_on_project": bool(row["seen_on_project"]),
            }
            for row in rows
        ]

    async def create_worker(
        self,
        *,
        organization_id: str,
        name: str,
        trade: str | None = None,
        daily_wage: object | None = None,
        created_by: str | None = None,
    ) -> str:
        """Promote a named temporary worker into the Worker Register.

        Promotion is now an **update, not an insert**. Recording the
        attendance already gave this person a durable id and marked them
        ``temporary`` (see labour_execution.py's `_ensure_worker_identities`),
        so inserting a second row here would fork them in two: the days they
        already worked would stay attached to the old id while everything
        afterwards accrued to the new one. That fork is exactly what this
        phase exists to remove.

        So: find the existing row by normalized name + trade, flip it to
        ``permanent``, and return the id it already had. Every day of
        attendance recorded before the promotion stays attached, because the
        row never moved. Only when no such row exists -- a worker added from a
        path that never went through attendance -- does this still insert.

        Defaults on insert: PERMANENT type, ACTIVE status. The daily wage from
        the attendance line is carried as the default, the strongest signal
        available at promotion time. On update the wage is only filled in when
        the row does not already have one, so promoting somebody never
        overwrites a rate an admin set deliberately.

        Returns the worker's UUID string, existing or new.
        """
        import decimal

        import sqlalchemy as sa

        from mesiri.domains.workforce.workers import normalize_name, normalize_trade

        try:
            org_id = uuid.UUID(organization_id)
        except (TypeError, ValueError):
            raise ValueError(f"invalid organization_id: {organization_id!r}") from None

        normalized_trade = normalize_trade(trade)
        normalized_name = normalize_name(name)

        wage_decimal: decimal.Decimal | None = None
        if daily_wage is not None:
            try:
                wage_decimal = decimal.Decimal(str(daily_wage))
            except (decimal.InvalidOperation, TypeError, ValueError):
                wage_decimal = None

        async with self._db.transaction() as conn:
            candidates = (
                await conn.execute(
                    sa.text(
                        "SELECT id, name, trade, default_daily_wage FROM workforce_workers "
                        "WHERE organization_id = :org_id"
                    ),
                    {"org_id": org_id},
                )
            ).mappings().all()

            existing_id = None
            existing_wage = None
            for row in candidates:
                if (
                    normalize_name(row["name"]) == normalized_name
                    and normalize_trade(row["trade"]) == normalized_trade
                ):
                    existing_id = row["id"]
                    existing_wage = row["default_daily_wage"]
                    break

            if existing_id is not None:
                await conn.execute(
                    sa.text(
                        "UPDATE workforce_workers "
                        "SET worker_type = 'permanent', status = 'active', "
                        "    default_daily_wage = COALESCE(default_daily_wage, :wage), "
                        "    updated_at = now() "
                        "WHERE id = :id"
                    ),
                    {
                        "id": existing_id,
                        "wage": wage_decimal if existing_wage is None else None,
                    },
                )
                return str(existing_id)

            worker_id = uuid.uuid4()
            await conn.execute(
                sa.text(
                    "INSERT INTO workforce_workers "
                    "(id, organization_id, name, trade, worker_type, status, "
                    " default_daily_wage, created_at, created_by, updated_at) "
                    "VALUES (:id, :org_id, :name, :trade, 'permanent', 'active', "
                    "        :wage, now(), :created_by, now())"
                ),
                {
                    "id": worker_id,
                    "org_id": org_id,
                    "name": name.strip(),
                    "trade": normalized_trade,
                    "wage": wage_decimal,
                    "created_by": uuid.UUID(created_by) if created_by else None,
                },
            )

        return str(worker_id)

    async def find_existing_report_for_day(
        self,
        *,
        organization_id: str,
        project_id: str,
        site_id: str | None,
        occurred_date: str,
    ) -> dict[str, Any] | None:
        """What is already on record for this site and day.

        Mirrors the backend repository method of the same name (which the
        dashboard read path uses) rather than sharing it: the assistant talks
        to Postgres through its own PostgresDatabase port and never imports
        backend repositories.

        Superseded reports are excluded, so re-sending a day twice compares
        against the *live* report both times rather than against a correction
        that no longer counts.

        A NULL site_id is matched with IS NULL, not `= NULL` (always false),
        or a project with no named site could never detect its own duplicate.
        """
        import datetime as _datetime

        import sqlalchemy as sa

        try:
            org_id = uuid.UUID(organization_id)
            project_uuid = uuid.UUID(project_id)
            site_uuid = uuid.UUID(site_id) if site_id else None
        except (TypeError, ValueError):
            return None
        # asyncpg is strictly typed: it will not coerce the ISO string that
        # travels through the canonical event into a DATE, and raises DataError
        # rather than casting. Shipping this untyped meant every attendance
        # message failed with "something went wrong -- nothing was recorded",
        # because the seeding gather does not isolate one seed's failure.
        try:
            occurred = _datetime.date.fromisoformat(str(occurred_date or "").strip())
        except (TypeError, ValueError):
            return None

        site_clause = "site_id IS NULL" if site_uuid is None else "site_id = :site_id"
        params: dict[str, Any] = {
            "org_id": org_id,
            "project_id": project_uuid,
            "occurred_date": occurred,
        }
        if site_uuid is not None:
            params["site_id"] = site_uuid

        async with self._db.transaction() as conn:
            report = (
                await conn.execute(
                    sa.text(
                        "SELECT id FROM labour_attendance_reports "
                        "WHERE organization_id = :org_id "
                        "  AND project_id = :project_id "
                        f"  AND {site_clause} "
                        "  AND occurred_date = :occurred_date "
                        "  AND id NOT IN ("
                        "        SELECT corrects_report_id FROM labour_attendance_reports "
                        "        WHERE corrects_report_id IS NOT NULL) "
                        "ORDER BY created_at DESC LIMIT 1"
                    ),
                    params,
                )
            ).first()
            if report is None:
                return None

            report_uuid = report[0]
            totals = (
                await conn.execute(
                    sa.text(
                        "SELECT COUNT(*) AS line_count, "
                        "       COALESCE(SUM(COALESCE(headcount, 1)), 0) AS total_headcount, "
                        "       COALESCE(SUM(CASE WHEN daily_wage IS NOT NULL "
                        "                    THEN COALESCE(headcount, 1) * daily_wage "
                        "                    ELSE 0 END), 0) AS total_cost "
                        "FROM labour_attendance_lines WHERE report_id = :report_id"
                    ),
                    {"report_id": report_uuid},
                )
            ).first()

            # BE-10: what the day counts right now, across every live report,
            # so a save-first reply can say which figures a re-send replaced.
            # Uses the backend's own rule so this cannot drift from the totals.
            from mesiri.infrastructure.postgres.repositories.workforce import (
                counted_line_sql,
                live_report_sql,
            )

            counted = (
                await conn.execute(
                    sa.text(
                        "SELECT lal.worker_id, lal.worker_name, lal.contractor, lal.trade, "
                        "       lal.headcount "
                        "FROM labour_attendance_lines lal "
                        "JOIN labour_attendance_reports lar ON lar.id = lal.report_id "
                        "WHERE lar.organization_id = :org_id "
                        "  AND lar.project_id = :project_id "
                        f"  AND lar.{site_clause} "
                        "  AND lar.occurred_date = :occurred_date "
                        f"  AND {live_report_sql('lar')} "
                        f"  AND {counted_line_sql('lal', 'lar')}"
                    ),
                    params,
                )
            ).mappings().all()

        return {
            "report_id": str(report_uuid),
            "line_count": int(totals[0] or 0) if totals else 0,
            "total_headcount": int(totals[1] or 0) if totals else 0,
            "total_cost": str(totals[2] or "0") if totals else "0",
            "counted_lines": [
                {
                    "worker_id": str(row["worker_id"]) if row["worker_id"] else None,
                    "worker_name": row["worker_name"],
                    "contractor": row["contractor"],
                    "trade": row["trade"],
                    "headcount": row["headcount"],
                }
                for row in counted
            ],
        }

    async def attach_team_photo(
        self,
        *,
        organization_id: str,
        report_id: str,
        media_object_key: str,
        created_by: str | None = None,
    ) -> str | None:
        """Link a photo of the crew to an already-recorded attendance report.

        Written under its own attachment_type ('attendance_team_photo') rather
        than alongside the photographed sheet: the sheet is the *source* a
        report was read from, this is *corroboration* taken afterwards. A
        gallery, a daily report or a future verification step can then ask for
        one without getting the other.

        Attendance itself is append-only (P5) and is not touched here -- an
        attachment is a separate row pointing at the report, so adding one
        later neither rewrites nor supersedes what was recorded.

        The organization is checked against the report rather than trusted
        from the caller, so a photo can never be pinned to another tenant's
        record. Returns the new attachment id, or None when the report does
        not exist or belongs to somebody else.
        """
        import sqlalchemy as sa

        try:
            org_id = uuid.UUID(organization_id)
            report_uuid = uuid.UUID(report_id)
        except (TypeError, ValueError):
            return None
        if not str(media_object_key or "").strip():
            return None

        attachment_id = uuid.uuid4()
        async with self._db.transaction() as conn:
            owner = (
                await conn.execute(
                    sa.text(
                        "SELECT 1 FROM labour_attendance_reports "
                        "WHERE id = :report_id AND organization_id = :org_id"
                    ),
                    {"report_id": report_uuid, "org_id": org_id},
                )
            ).first()
            if owner is None:
                return None

            await conn.execute(
                sa.text(
                    "INSERT INTO labour_attendance_attachments "
                    "(id, report_id, media_object_key, attachment_type, created_at, created_by) "
                    "VALUES (:id, :report_id, :key, 'attendance_team_photo', now(), :created_by)"
                ),
                {
                    "id": attachment_id,
                    "report_id": report_uuid,
                    "key": media_object_key,
                    "created_by": uuid.UUID(created_by) if created_by else None,
                },
            )
        return str(attachment_id)


class StubWorkforceQueryService:
    """Empty register unless a roster is configured — local/test use only.

    Superseded in production by PostgresWorkforceQueryService above. Kept
    because it is genuinely useful for exercising matching without a database,
    and because its default (empty) is the honest answer rather than a
    fabrication.

    ``worker_id`` must be a real UUID, not a short label like ``"w-ravi"`` --
    once a line matches, its worker_id flows into
    ``LabourAttendanceLine.worker_id`` (application/labour/mapper.py), a
    ``CanonicalUuid`` field, and a non-UUID value fails command validation::

        MESIRI_LABOUR__STUB_WORKERS='[
          {"worker_id": "11111111-1111-4111-8111-111111111111", "name": "Ravi Kumar",
           "trade": "mason", "contractor": "Kumar Team", "seen_on_site": true}
        ]'
    """

    def __init__(
        self,
        roster: list[dict[str, Any]] | None = None,
        existing_reports: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self._roster = roster if roster is not None else _roster_from_env()
        self.created_workers: list[dict[str, Any]] = []
        self.team_photos: list[dict[str, Any]] = []
        #: Keyed "project_id|site_id|occurred_date" so a test can stage a day
        #: that already has attendance. Empty by default -- a clear day is the
        #: ordinary case, and inventing a prior report would make every test
        #: answer a duplicate question it never asked for.
        self._existing_reports = dict(existing_reports or {})

    async def list_worker_candidates(
        self,
        *,
        organization_id: str,
        project_id: str | None = None,
        site_id: str | None = None,
    ) -> list[dict[str, Any]]:
        # Not scoped by org/project/site: a configured test roster is for one
        # tenant on one machine by construction. The Postgres reader above
        # scopes on organization and computes the site/project signals for
        # real -- a worker from another organization never appears there.
        return list(self._roster)

    async def create_worker(
        self,
        *,
        organization_id: str,
        name: str,
        trade: str | None = None,
        daily_wage: object | None = None,
        created_by: str | None = None,
    ) -> str:
        """Stub: records the call in self.created_workers for test assertions."""
        import uuid as _uuid
        worker_id = str(_uuid.uuid4())
        self.created_workers.append(
            {
                "worker_id": worker_id,
                "organization_id": organization_id,
                "name": name,
                "trade": trade,
                "daily_wage": daily_wage,
                "created_by": created_by,
            }
        )
        return worker_id


    async def find_existing_report_for_day(
        self,
        *,
        organization_id: str,
        project_id: str,
        site_id: str | None,
        occurred_date: str,
    ) -> dict[str, Any] | None:
        """Stub: returns a report only if one was staged for this site-day."""
        return self._existing_reports.get(f"{project_id}|{site_id or ''}|{occurred_date}")

    async def attach_team_photo(
        self,
        *,
        organization_id: str,
        report_id: str,
        media_object_key: str,
        created_by: str | None = None,
    ) -> str | None:
        """Stub: records the call in self.team_photos for test assertions."""
        import uuid as _uuid

        attachment_id = str(_uuid.uuid4())
        self.team_photos.append(
            {
                "attachment_id": attachment_id,
                "organization_id": organization_id,
                "report_id": report_id,
                "media_object_key": media_object_key,
                "created_by": created_by,
            }
        )
        return attachment_id


def _roster_from_env() -> list[dict[str, Any]]:
    """Parse the opt-in stub roster, or return empty.

    Never raises: a malformed roster degrades to an empty register (every
    worker temporary, nothing asked) rather than taking down attendance
    capture entirely. A bad env var is a config mistake, not a reason a site
    cannot report who turned up.
    """
    raw = os.environ.get(STUB_WORKERS_ENV, "").strip()
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except ValueError:
        logger.warning("labour.stub_roster_invalid_json env=%s", STUB_WORKERS_ENV)
        return []
    if not isinstance(parsed, list):
        logger.warning("labour.stub_roster_not_a_list env=%s", STUB_WORKERS_ENV)
        return []

    roster: list[dict[str, Any]] = []
    for entry in parsed:
        if not isinstance(entry, dict):
            continue
        worker_id = entry.get("worker_id") or entry.get("id")
        name = entry.get("name")
        if not worker_id or not name:
            continue
        roster.append(
            {
                "worker_id": str(worker_id),
                "name": str(name),
                "trade": entry.get("trade"),
                "contractor": entry.get("contractor"),
                "seen_on_site": bool(entry.get("seen_on_site")),
                "seen_on_project": bool(entry.get("seen_on_project")),
            }
        )
    if roster:
        logger.warning(
            "labour.stub_roster_active count=%d -- workforce register is STUBBED, "
            "not from the database",
            len(roster),
        )
    return roster
