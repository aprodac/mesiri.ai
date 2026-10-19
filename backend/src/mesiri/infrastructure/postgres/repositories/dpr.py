"""PostgreSQL repository for Daily Progress Reports (DPR).

Handles read/write operations for daily_reports, daily_report_versions, and
daily_report_sources (docs/execution/DAILY_REPORTING_PLAN.md ADR-D6/D9).

`assemble_site_report_payload` + `create_version` are the real generation
path (#16 Daily Report Generation): they compose a version's `payload`
JSONB from the activities/site_issues/progress_attachments actually
recorded for one site+date, rather than trusting a caller-supplied payload.
The older `create_report`/`get_report`/`list_reports` methods remain for the
existing dashboard's manual-entry form (POST /dpr/daily-reports with a
hand-typed payload) -- a different, still-valid path for a report with no
WhatsApp activity behind it, not something this generation path replaces.

Scope, stated plainly (matches this session's other narrowing decisions):
`assemble_site_report_payload` composes activities + site_issues +
evidence *counts* + labour attendance + material movements for one
SITE-level report -- a cross-module read, deliberately: a report without
manpower and material isn't one a client accepts, and both exist today
(unlike finance, which genuinely can't participate yet -- expenses never
emit to `outbox_events`, so there is no event trail this read could join
against; equipment has no backend at all, no table, no read/write path).
PROJECT-level composition from approved SITE versions (ADR-D9/P8,
`daily_report_sources`) is not built here either -- a natural next step,
not silently done halfway.
"""

from __future__ import annotations

import datetime
import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.application.dpr import site_day


class PostgresDprRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    # ------------------------------------------------------------------
    # Manual-entry path (existing dashboard form) -- unchanged in shape,
    # only the enum bug below is fixed.
    # ------------------------------------------------------------------

    async def list_reports(
        self,
        *,
        organization_id: uuid.UUID,
        project_ids: set[uuid.UUID] | None,
        site_id: uuid.UUID | None,
        status: str | None,
        date_from: datetime.date | None,
        date_to: datetime.date | None,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, Any]], int]:
        where = ["dr.organization_id = :organization_id"]
        params: dict[str, Any] = {"organization_id": organization_id, "limit": limit, "offset": offset}

        if project_ids is not None:
            where.append("dr.project_id = ANY(:project_ids)")
            params["project_ids"] = list(project_ids)
        if site_id is not None:
            where.append("dr.site_id = :site_id")
            params["site_id"] = site_id
        if date_from is not None:
            where.append("dr.report_date >= :date_from")
            params["date_from"] = date_from
        if date_to is not None:
            where.append("dr.report_date <= :date_to")
            params["date_to"] = date_to
        if status is not None:
            where.append("dr.status = :status")
            params["status"] = status.upper()

        where_clause = " AND ".join(where)

        total_row = (
            await self._conn.execute(
                text(f"SELECT COUNT(*) AS total FROM daily_reports dr WHERE {where_clause}"), params
            )
        ).mappings().first()
        total = total_row["total"] if total_row else 0

        query = f"""
            SELECT
                dr.id,
                COALESCE(dr.code, concat('DPR-', to_char(dr.report_date, 'YYYYMMDD'), '-', SUBSTRING(dr.id::text, 1, 4))) AS dpr_number,
                dr.report_date::text AS report_date,
                p.name AS project_name,
                COALESCE(s.name, 'Project-wide') AS site_name,
                COALESCE(u.name, 'Site Lead') AS prepared_by_name,
                'Site Engineer' AS prepared_by_role,
                LOWER(dr.status::text) AS workflow_status,
                COALESCE(dr.weather, 'not_set') AS weather,
                NULL::int AS temperature_celsius,
                'day' AS shift,
                0 AS activities_count,
                0 AS labour_count,
                0 AS issues_count,
                '' AS narrative_summary,
                dr.created_at::text AS created_at
            FROM daily_reports dr
            JOIN projects p ON dr.project_id = p.id
            LEFT JOIN sites s ON dr.site_id = s.id
            LEFT JOIN users u ON p.organization_id = u.organization_id
            WHERE {where_clause}
            ORDER BY dr.report_date DESC, dr.created_at DESC
            LIMIT :limit OFFSET :offset
        """

        rows = (await self._conn.execute(text(query), params)).mappings().all()
        return [dict(r) for r in rows], total

    async def get_report(
        self, organization_id: uuid.UUID, report_id: uuid.UUID
    ) -> dict[str, Any] | None:
        query = """
            SELECT
                dr.id,
                COALESCE(dr.code, concat('DPR-', to_char(dr.report_date, 'YYYYMMDD'), '-', SUBSTRING(dr.id::text, 1, 4))) AS dpr_number,
                dr.report_date::text AS report_date,
                p.name AS project_name,
                COALESCE(s.name, 'Project-wide') AS site_name,
                'Site Engineer' AS prepared_by_name,
                'Site Lead' AS prepared_by_role,
                LOWER(dr.status::text) AS workflow_status,
                COALESCE(dr.weather, 'not_set') AS weather,
                NULL::int AS temperature_celsius,
                'day' AS shift,
                0 AS activities_count,
                0 AS labour_count,
                0 AS issues_count,
                '' AS narrative_summary,
                dr.created_at::text AS created_at,
                '[]'::json AS work_items,
                '[]'::json AS labour_items,
                '[]'::json AS equipment_items,
                '[]'::json AS issues,
                '[]'::json AS attachments
            FROM daily_reports dr
            JOIN projects p ON dr.project_id = p.id
            LEFT JOIN sites s ON dr.site_id = s.id
            WHERE dr.organization_id = :org_id AND dr.id = :id
        """
        row = (await self._conn.execute(text(query), {"org_id": organization_id, "id": report_id})).mappings().first()
        return dict(row) if row else None

    async def create_report(
        self, organization_id: uuid.UUID, user_id: uuid.UUID, payload: dict[str, Any]
    ) -> dict[str, Any]:
        report_id = uuid.uuid4()
        report_date = payload["report_date"]
        project_id = payload.get("project_id")
        site_id = payload.get("site_id")

        if not project_id:
            # Fallback to first project in organization
            first_p = (await self._conn.execute(
                text("SELECT id FROM projects WHERE organization_id = :org_id LIMIT 1"),
                {"org_id": organization_id}
            )).mappings().first()
            project_id = first_p["id"] if first_p else uuid.uuid4()

        code = f"DPR-{report_date.replace('-', '')}-{str(report_id)[:4].upper()}"

        query = """
            INSERT INTO daily_reports (
                id, organization_id, project_id, site_id, level, report_date, code, status
            ) VALUES (
                :id, :organization_id, :project_id, :site_id, :level, :report_date, :code, 'DRAFT'
            ) RETURNING id, code, report_date::text AS report_date, status::text AS workflow_status
        """
        # Status is 'DRAFT' -- daily_report_status's actual enum values are
        # DRAFT/IN_REVIEW/APPROVED/PUBLISHED/NOT_REPORTED (migration 0440).
        # This previously inserted 'UNDER_REVIEW', which isn't a member of
        # that enum -- a live INSERT would have raised
        # InvalidTextRepresentation the first time this code path actually
        # ran against Postgres. Caught while building the real generation
        # path below, before this manual-entry path had ever been exercised
        # against a live database (0440's own docstring: "No application
        # code writes to these tables yet").
        params = {
            "id": report_id,
            "organization_id": organization_id,
            "project_id": project_id,
            "site_id": site_id,
            "level": "SITE" if site_id else "PROJECT",
            "report_date": report_date,
            "code": code,
        }
        res = (await self._conn.execute(text(query), params)).mappings().first()
        res_dict = dict(res)
        res_dict["dpr_number"] = res_dict["code"]
        res_dict["workflow_status"] = res_dict["workflow_status"].lower()
        res_dict["project_name"] = "Active Project"
        res_dict["site_name"] = "Active Site"
        res_dict["prepared_by_name"] = "Current Engineer"
        res_dict["weather"] = payload.get("weather", "sunny")
        res_dict["temperature_celsius"] = payload.get("temperature_celsius", 32)
        res_dict["shift"] = payload.get("shift", "day")
        res_dict["activities_count"] = len(payload.get("work_items", []))
        res_dict["labour_count"] = sum(item.get("headcount", 0) for item in payload.get("labour_items", []))
        res_dict["issues_count"] = len(payload.get("issues", []))

        return res_dict

    async def submit_for_review(
        self, organization_id: uuid.UUID, report_id: uuid.UUID
    ) -> bool:
        """Collecting / needs details / ready -> IN_REVIEW ("with engineer",
        BE-08). The allowed starting statuses come from site_day's
        transition table, so this and the WhatsApp flow cannot disagree."""
        query = """
            UPDATE daily_reports
            SET status = 'IN_REVIEW', updated_at = now()
            WHERE organization_id = :org_id AND id = :id AND status::text = ANY(:from_statuses)
        """
        res = await self._conn.execute(
            text(query),
            {"org_id": organization_id, "id": report_id, "from_statuses": site_day.sources_for(site_day.IN_REVIEW)},
        )
        return res.rowcount > 0

    async def approve_report(
        self, organization_id: uuid.UUID, user_id: uuid.UUID, report_id: uuid.UUID, notes: str | None
    ) -> bool:
        """The engineer's confirmation (decided 13 Oct: the engineer is the
        only approver) -> APPROVED, frozen (P7). Any pre-confirmation status
        is accepted, not only IN_REVIEW: the bulk-approve action never calls
        submit_for_review first, and an engineer may confirm a day that is
        still missing parts ("site closed, no labour today").

        Also records who confirmed and when on the current version, which
        the version table always had columns for but nothing ever set. The
        user is looked up rather than trusted, so an id with no users row
        leaves the field empty instead of failing the confirmation.

        A site day's drafts are confirmed with it (BE-09, approved 13 Oct:
        the engineer has just looked at them; anything wrong is rejected
        first), and the version is rebuilt so the frozen DPR shows them as
        confirmed."""
        await self._confirm_drafts_before_approval(
            organization_id=organization_id, user_id=user_id, report_id=report_id
        )
        query = """
            UPDATE daily_reports
            SET status = 'APPROVED', updated_at = now()
            WHERE organization_id = :org_id AND id = :id AND status::text = ANY(:from_statuses)
        """
        res = await self._conn.execute(
            text(query),
            {"org_id": organization_id, "id": report_id, "from_statuses": site_day.sources_for(site_day.APPROVED)},
        )
        if res.rowcount == 0:
            return False
        await self._conn.execute(
            text(
                """
                UPDATE daily_report_versions v
                SET approved_by_user_id = (SELECT id FROM users WHERE id = :user_id),
                    approved_at = now()
                FROM daily_reports dr
                WHERE dr.id = :id AND v.id = dr.current_version_id
                """
            ),
            {"id": report_id, "user_id": user_id},
        )
        return True

    async def _confirm_drafts_before_approval(
        self, *, organization_id: uuid.UUID, user_id: uuid.UUID, report_id: uuid.UUID
    ) -> None:
        scope = (
            await self._conn.execute(
                text(
                    "SELECT project_id, site_id, report_date, level::text AS level, "
                    "status::text AS status FROM daily_reports "
                    "WHERE organization_id = :org_id AND id = :id"
                ),
                {"org_id": organization_id, "id": report_id},
            )
        ).mappings().first()
        if (
            scope is None
            or scope["level"] != "SITE"
            or scope["status"] not in site_day.sources_for(site_day.APPROVED)
        ):
            return

        from mesiri.infrastructure.postgres.repositories.fact_reviews import (
            PostgresFactReviewRepository,
        )

        confirmed = await PostgresFactReviewRepository(self._conn).confirm_drafts_for_day(
            organization_id=organization_id,
            site_id=scope["site_id"],
            report_date=scope["report_date"],
            actor_user_id=user_id,
        )
        # BE-13: earlier days' late entries listed in this report are now
        # shown here (once) and confirmed with it.
        from mesiri.application.dpr.late_entries import claim_for_report

        confirmed += await claim_for_report(
            self._conn,
            organization_id=organization_id,
            site_id=scope["site_id"],
            report_date=scope["report_date"],
            report_id=report_id,
            actor_user_id=user_id,
        )
        if confirmed:
            payload = await self.assemble_site_report_payload(
                organization_id=organization_id,
                project_id=scope["project_id"],
                site_id=scope["site_id"],
                report_date=scope["report_date"],
            )
            await self.create_version(daily_report_id=report_id, payload=payload)

    async def publish_report(
        self, organization_id: uuid.UUID, report_id: uuid.UUID
    ) -> bool:
        """APPROVED -> PUBLISHED ("sent"). Terminal per P7 (create_version
        already refuses to regenerate a payload once status is APPROVED/
        PUBLISHED)."""
        query = """
            UPDATE daily_reports
            SET status = 'PUBLISHED', updated_at = now()
            WHERE organization_id = :org_id AND id = :id AND status::text = ANY(:from_statuses)
        """
        res = await self._conn.execute(
            text(query),
            {"org_id": organization_id, "id": report_id, "from_statuses": site_day.sources_for(site_day.PUBLISHED)},
        )
        return res.rowcount > 0

    # ------------------------------------------------------------------
    # Real generation path (#16 Daily Report Generation).
    # ------------------------------------------------------------------

    async def assemble_site_report_payload(
        self,
        *,
        organization_id: uuid.UUID,
        project_id: uuid.UUID,
        site_id: uuid.UUID,
        report_date: datetime.date,
    ) -> dict[str, Any]:
        payload, _ = await self.assemble_site_day(
            organization_id=organization_id,
            project_id=project_id,
            site_id=site_id,
            report_date=report_date,
        )
        return payload

    async def assemble_site_day(
        self,
        *,
        organization_id: uuid.UUID,
        project_id: uuid.UUID,
        site_id: uuid.UUID,
        report_date: datetime.date,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """The payload below, plus the day's reviewable items with their ids
        (WEB-04's site DPR page; application/dpr/assembly.build_review_items).

        Compose one SITE-level DPR payload from what was actually
        recorded on `report_date` -- activities (with their quantities),
        open+resolved-today site issues, an evidence count per activity,
        the day's labour attendance, and the day's material movements.
        Returns a plain JSON-safe dict, ready for `create_version`'s
        `payload` column or a PDF renderer.

        Labour and material live in their own modules (labour_attendance_*,
        material_movements) with their own writers -- this method only
        reads them, scoped to the same site+date every other section here
        already uses, the same cross-module read every other section in
        this method already is (see module docstring's scope note on why
        this composition doesn't extend to finance).

        Photo bytes are NOT embedded here -- only counts and captions.
        Inlining actual thumbnails needs the object-storage read wired
        through this call, deferred to keep this pass to counts/text
        (see module docstring's scope note).
        """
        header_query = text(
            """
            SELECT
                (SELECT name FROM projects WHERE id = :project_id) AS project_name,
                (SELECT name FROM sites WHERE id = :site_id) AS site_name
            """
        )
        header = (
            await self._conn.execute(
                header_query, {"project_id": project_id, "site_id": site_id}
            )
        ).mappings().first()

        activities_query = text(
            """
            SELECT a.id, a.work_type, a.narrative, a.status, a.contractor,
                   a.started_at, a.ended_at, a.location_id
            FROM activities a
            WHERE a.organization_id = :org_id
              AND a.project_id = :project_id
              AND a.site_id = :site_id
              AND a.activity_date = :report_date
              AND a.deleted_at IS NULL
            ORDER BY a.created_at
            """
        )
        activity_rows = (
            await self._conn.execute(
                activities_query,
                {
                    "org_id": organization_id,
                    "project_id": project_id,
                    "site_id": site_id,
                    "report_date": report_date,
                },
            )
        ).mappings().all()

        activity_ids = [row["id"] for row in activity_rows]

        quantities_by_activity: dict[Any, list[dict[str, Any]]] = {}
        evidence_count_by_activity: dict[Any, int] = {}
        if activity_ids:
            quantities_query = text(
                """
                SELECT aq.activity_id, aq.work_type, aq.quantity, u.code AS unit_code
                FROM activity_quantities aq
                JOIN units_of_measure u ON u.id = aq.unit_id
                WHERE aq.activity_id = ANY(:activity_ids)
                ORDER BY aq.created_at
                """
            )
            for row in (
                await self._conn.execute(quantities_query, {"activity_ids": activity_ids})
            ).mappings().all():
                quantities_by_activity.setdefault(row["activity_id"], []).append(
                    {
                        "work_type": row["work_type"],
                        "quantity": str(row["quantity"]),
                        "unit": row["unit_code"],
                    }
                )

            evidence_query = text(
                """
                SELECT parent_id AS activity_id, count(*) AS n
                FROM progress_attachments
                WHERE parent_type = 'ACTIVITY' AND parent_id = ANY(:activity_ids)
                GROUP BY parent_id
                """
            )
            for row in (
                await self._conn.execute(evidence_query, {"activity_ids": activity_ids})
            ).mappings().all():
                evidence_count_by_activity[row["activity_id"]] = int(row["n"])

        issues_query = text(
            """
            SELECT id, issue_type, severity, narrative, status, delay_duration_minutes
            FROM site_issues
            WHERE organization_id = :org_id
              AND project_id = :project_id
              AND site_id = :site_id
              AND occurred_at::date = :report_date
              -- Withdrawn as reported in error (0460) -- including a
              -- rejected draft (BE-09) -- is not part of the day.
              AND status != 'CANCELLED'
            ORDER BY
                CASE severity WHEN 'CRITICAL' THEN 0 WHEN 'HIGH' THEN 1
                              WHEN 'MEDIUM' THEN 2 ELSE 3 END,
                occurred_at
            """
        )
        issue_rows = (
            await self._conn.execute(
                issues_query,
                {
                    "org_id": organization_id,
                    "project_id": project_id,
                    "site_id": site_id,
                    "report_date": report_date,
                },
            )
        ).mappings().all()

        # Superseded and voided reports are excluded here, which they were
        # not before: this query counted every row for the day, so a
        # supervisor who re-sent the list and chose "Replace it" put both
        # reports into the DPR -- the same 16 + 18 = 34 man-day double count
        # the dashboard aggregate had already been fixed to avoid. The rule
        # is shared with that aggregate rather than restated (see
        # repositories/workforce.py's LIVE_REPORT_SQL) so the DPR and the
        # dashboard cannot disagree about what a day cost again.
        # BE-10: and a figure re-sent later the same day replaces the earlier
        # one (latest per contractor + trade, or per named worker), so 10 then
        # 12 masons from one contractor is 12, not 22.
        from mesiri.infrastructure.postgres.repositories.workforce import (
            counted_line_sql,
            live_report_sql,
        )

        labour_query = text(
            f"""
            SELECT lar.id AS report_id, lal.worker_name, lal.trade, lal.headcount,
                   lal.daily_wage, lal.contractor
            FROM labour_attendance_lines lal
            JOIN labour_attendance_reports lar ON lar.id = lal.report_id
            WHERE lar.organization_id = :org_id
              AND lar.project_id = :project_id
              AND lar.site_id = :site_id
              AND lar.occurred_date = :report_date
              AND {live_report_sql("lar")}
              AND {counted_line_sql("lal", "lar")}
            """
        )
        labour_rows = (
            await self._conn.execute(
                labour_query,
                {
                    "org_id": organization_id,
                    "project_id": project_id,
                    "site_id": site_id,
                    "report_date": report_date,
                },
            )
        ).mappings().all()

        material_query = text(
            """
            SELECT mm.material_id, mc.name AS material_name, u.code AS unit,
                   mm.movement_type, mm.quantity, mm.source_type, mm.source_id,
                   COALESCE(mr.movement_reason, mu.movement_reason) AS movement_reason
            FROM material_movements mm
            JOIN materials_catalog mc ON mc.id = mm.material_id
            JOIN units_of_measure u ON u.id = mm.unit_id
            LEFT JOIN material_receipts mr
                   ON mm.source_type = 'material_receipt' AND mr.id = mm.source_id
            LEFT JOIN material_usage mu
                   ON mm.source_type = 'material_usage' AND mu.id = mm.source_id
            WHERE mm.organization_id = :org_id
              AND mm.project_id = :project_id
              AND mm.site_id = :site_id
              AND mm.occurred_at::date = :report_date
              -- A corrected movement and its correction cancel out; showing
              -- both would read as 50 received AND 50 used. This also keeps a
              -- rejected draft (BE-09, reversed by Materials) off the DPR.
              AND mm.reversal_of_movement_id IS NULL
              AND NOT EXISTS (
                  SELECT 1 FROM material_movements r WHERE r.reversal_of_movement_id = mm.id
              )
            """
        )
        material_rows = (
            await self._conn.execute(
                material_query,
                {
                    "org_id": organization_id,
                    "project_id": project_id,
                    "site_id": site_id,
                    "report_date": report_date,
                },
            )
        ).mappings().all()

        # BE-12: stock before and after the day, for every material that moved
        # on it. From the whole ledger (corrections included), the same sum
        # get_available_stock uses, so "closing" is what the site really held.
        # Stock is per site, not per project, matching the outflow guard.
        stock_rows = (
            await self._conn.execute(
                text(
                    """
                    SELECT mm.material_id, mc.name AS material_name, u.code AS unit,
                           SUM(CASE WHEN mm.occurred_at::date < :report_date
                                    THEN CASE WHEN mm.movement_type = 'RECEIPT'
                                              THEN mm.quantity ELSE -mm.quantity END
                                    ELSE 0 END) AS opening,
                           SUM(CASE WHEN mm.movement_type = 'RECEIPT'
                                    THEN mm.quantity ELSE -mm.quantity END) AS closing
                    FROM material_movements mm
                    JOIN materials_catalog mc ON mc.id = mm.material_id
                    JOIN units_of_measure u ON u.id = mm.unit_id
                    WHERE mm.organization_id = :org_id
                      AND mm.site_id = :site_id
                      AND mm.occurred_at::date <= :report_date
                    GROUP BY mm.material_id, mc.name, u.code
                    HAVING bool_or(mm.occurred_at::date = :report_date)
                    """
                ),
                {"org_id": organization_id, "site_id": site_id, "report_date": report_date},
            )
        ).mappings().all()

        conditions_row = (
            await self._conn.execute(
                text(
                    """
                    SELECT weather, hours_lost, site_working, tomorrow_plan
                    FROM daily_reports
                    WHERE organization_id = :org_id AND project_id = :project_id
                      AND site_id = :site_id AND report_date = :report_date AND level = 'SITE'
                    """
                ),
                {
                    "org_id": organization_id,
                    "project_id": project_id,
                    "site_id": site_id,
                    "report_date": report_date,
                },
            )
        ).mappings().first()

        # Draft or confirmed, per fact (BE-09). Labour and materials are
        # reviewed per report / per receipt-or-usage record, the unit people
        # actually send.
        from mesiri.application.dpr import fact_review
        from mesiri.infrastructure.postgres.repositories.fact_reviews import (
            PostgresFactReviewRepository,
        )

        reviews = PostgresFactReviewRepository(self._conn)
        review_states = {
            fact_review.ACTIVITY: await reviews.states_for(fact_review.ACTIVITY, activity_ids),
            fact_review.SITE_ISSUE: await reviews.states_for(
                fact_review.SITE_ISSUE, [row["id"] for row in issue_rows]
            ),
            fact_review.LABOUR_REPORT: await reviews.states_for(
                fact_review.LABOUR_REPORT, list({row["report_id"] for row in labour_rows})
            ),
            fact_review.MATERIAL_RECEIPT: await reviews.states_for(
                fact_review.MATERIAL_RECEIPT,
                [r["source_id"] for r in material_rows if r["source_type"] == "material_receipt"],
            ),
            fact_review.MATERIAL_USAGE: await reviews.states_for(
                fact_review.MATERIAL_USAGE,
                [r["source_id"] for r in material_rows if r["source_type"] == "material_usage"],
            ),
        }

        # BE-13: earlier days' late entries this report lists.
        from mesiri.application.dpr.late_entries import late_entries_for_report

        this_report = (
            await self._conn.execute(
                text(
                    "SELECT id FROM daily_reports WHERE organization_id = :org_id "
                    "AND site_id = :site_id AND report_date = :report_date "
                    "AND level::text = 'SITE'"
                ),
                {"org_id": organization_id, "site_id": site_id, "report_date": report_date},
            )
        ).first()
        late_entries = await late_entries_for_report(
            self._conn,
            organization_id=organization_id,
            site_id=site_id,
            report_date=report_date,
            report_id=this_report.id if this_report else None,
        )

        from mesiri.application.dpr.assembly import build_review_items, build_site_report_payload

        payload = build_site_report_payload(
            review_states=review_states,
            late_entries=late_entries,
            conditions=dict(conditions_row) if conditions_row else None,
            project_name=header["project_name"] if header else None,
            site_name=header["site_name"] if header else None,
            report_date=report_date,
            activity_rows=[dict(row) for row in activity_rows],
            quantities_by_activity=quantities_by_activity,
            evidence_count_by_activity=evidence_count_by_activity,
            issue_rows=[dict(row) for row in issue_rows],
            labour_lines=[dict(row) for row in labour_rows],
            material_movement_rows=[dict(row) for row in material_rows],
            material_stock_rows=[dict(row) for row in stock_rows],
        )
        items = build_review_items(
            payload=payload,
            activity_rows=[dict(row) for row in activity_rows],
            issue_rows=[dict(row) for row in issue_rows],
            labour_lines=[dict(row) for row in labour_rows],
            material_movement_rows=[dict(row) for row in material_rows],
            review_states=review_states,
        )
        return payload, items

    async def find_site_report(
        self,
        *,
        organization_id: uuid.UUID,
        project_id: uuid.UUID,
        site_id: uuid.UUID,
        report_date: datetime.date,
    ) -> dict[str, Any] | None:
        """The `daily_reports` row for this SITE+date, or None -- never
        creates one (unlike `get_or_create_daily_report`). Used by
        Activity/Progress Update correction and undo (ADR-D14/D15) to check
        whether a value has already been frozen into an APPROVED/PUBLISHED
        version (P7) before deciding whether to proceed, revise, or refuse."""
        row = (
            await self._conn.execute(
                text(
                    """
                    SELECT id, status::text AS status FROM daily_reports
                    WHERE organization_id = :org_id AND project_id = :project_id
                      AND site_id = :site_id AND report_date = :report_date AND level = 'SITE'
                    """
                ),
                {
                    "org_id": organization_id,
                    "project_id": project_id,
                    "site_id": site_id,
                    "report_date": report_date,
                },
            )
        ).mappings().first()
        return dict(row) if row is not None else None

    async def get_or_create_daily_report(
        self,
        *,
        organization_id: uuid.UUID,
        project_id: uuid.UUID,
        site_id: uuid.UUID,
        report_date: datetime.date,
    ) -> uuid.UUID:
        """The `daily_reports` row for this SITE+date, creating it (status
        DRAFT) if this is the first version ever generated for it. Never
        creates a second row for the same scope+date -- `uq_daily_report_
        scope_date` is the authority, this just upserts against it."""
        existing = (
            await self._conn.execute(
                text(
                    """
                    SELECT id FROM daily_reports
                    WHERE organization_id = :org_id AND project_id = :project_id
                      AND site_id = :site_id AND report_date = :report_date AND level = 'SITE'
                    """
                ),
                {
                    "org_id": organization_id,
                    "project_id": project_id,
                    "site_id": site_id,
                    "report_date": report_date,
                },
            )
        ).mappings().first()
        if existing:
            return existing["id"]

        report_id = uuid.uuid4()
        code = f"DPR-{report_date.strftime('%Y%m%d')}-{str(report_id)[:4].upper()}"
        await self._conn.execute(
            text(
                """
                INSERT INTO daily_reports (
                    id, organization_id, project_id, site_id, level, report_date, code, status
                ) VALUES (
                    :id, :org_id, :project_id, :site_id, 'SITE', :report_date, :code, 'DRAFT'
                )
                """
            ),
            {
                "id": report_id,
                "org_id": organization_id,
                "project_id": project_id,
                "site_id": site_id,
                "report_date": report_date,
                "code": code,
            },
        )
        return report_id

    async def get_or_create_project_daily_report(
        self,
        *,
        organization_id: uuid.UUID,
        project_id: uuid.UUID,
        report_date: datetime.date,
    ) -> uuid.UUID:
        """The PROJECT-level `daily_reports` row for this project+date --
        `site_id` is always NULL at this level (ADR-D9/P8). Mirrors
        `get_or_create_daily_report` exactly, one level up."""
        existing = (
            await self._conn.execute(
                text(
                    """
                    SELECT id FROM daily_reports
                    WHERE organization_id = :org_id AND project_id = :project_id
                      AND site_id IS NULL AND report_date = :report_date AND level = 'PROJECT'
                    """
                ),
                {"org_id": organization_id, "project_id": project_id, "report_date": report_date},
            )
        ).mappings().first()
        if existing:
            return existing["id"]

        report_id = uuid.uuid4()
        code = f"DPR-P-{report_date.strftime('%Y%m%d')}-{str(report_id)[:4].upper()}"
        await self._conn.execute(
            text(
                """
                INSERT INTO daily_reports (
                    id, organization_id, project_id, site_id, level, report_date, code, status
                ) VALUES (
                    :id, :org_id, :project_id, NULL, 'PROJECT', :report_date, :code, 'DRAFT'
                )
                """
            ),
            {
                "id": report_id,
                "org_id": organization_id,
                "project_id": project_id,
                "report_date": report_date,
                "code": code,
            },
        )
        return report_id

    async def assemble_project_report_payload(
        self,
        *,
        organization_id: uuid.UUID,
        project_id: uuid.UUID,
        report_date: datetime.date,
        preview: bool = False,
    ) -> tuple[dict[str, Any], list[tuple[uuid.UUID, uuid.UUID | None]]]:
        """Compose one PROJECT-level DPR payload from each of its active
        sites' own APPROVED/PUBLISHED SITE-level version (ADR-D9/P8) --
        never independently re-derived from raw activities/issues, so a
        project report can never show something its own site reports
        didn't already sign off on. A site with no approved version by the
        time this runs is recorded NOT_REPORTED (via `payload=None` in the
        pair below) -- the project rollup still composes and publishes,
        per P8.

        Also ensures a SITE-level `daily_reports` row exists for every
        active site under the project (creating an empty DRAFT one for a
        site that logged nothing at all) -- `daily_report_sources` needs a
        real `site_daily_report_id` to point at even for a site with
        nothing to report, so the missing report is a visible line rather
        than an absent one.

        Returns `(payload, sources)` -- `sources` is
        `(site_daily_report_id, site_version_id | None)` pairs the caller
        persists via `record_project_sources` once `create_version` (or
        `revise_version`) has minted a real `project_version_id` to attach
        them to.

        `preview=True` (WEB-05, the project DPR page before it is sent) writes
        nothing: a site with no report row yet is simply not reported, and
        `sources` only lists sites that already have a row.
        """
        project_row = (
            await self._conn.execute(
                text("SELECT name FROM projects WHERE id = :id"), {"id": project_id}
            )
        ).mappings().first()

        site_rows = (
            await self._conn.execute(
                text(
                    """
                    SELECT id, name FROM sites
                    WHERE organization_id = :org_id AND project_id = :project_id
                      AND status = 'active'
                    ORDER BY name
                    """
                ),
                {"org_id": organization_id, "project_id": project_id},
            )
        ).mappings().all()

        site_payloads: list[tuple[str | None, dict[str, Any] | None]] = []
        sources: list[tuple[uuid.UUID, uuid.UUID | None]] = []

        for site_row in site_rows:
            if preview:
                found = await self.find_site_report(
                    organization_id=organization_id,
                    project_id=project_id,
                    site_id=site_row["id"],
                    report_date=report_date,
                )
                if found is None:
                    site_payloads.append((site_row["name"], None))
                    continue
                site_daily_report_id = found["id"]
            else:
                site_daily_report_id = await self.get_or_create_daily_report(
                    organization_id=organization_id,
                    project_id=project_id,
                    site_id=site_row["id"],
                    report_date=report_date,
                )
            report_row = (
                await self._conn.execute(
                    text("SELECT status, current_version_id FROM daily_reports WHERE id = :id"),
                    {"id": site_daily_report_id},
                )
            ).mappings().first()

            payload: dict[str, Any] | None = None
            site_version_id: uuid.UUID | None = None
            if (
                report_row is not None
                and report_row["status"] in ("APPROVED", "PUBLISHED")
                and report_row["current_version_id"] is not None
            ):
                version_row = (
                    await self._conn.execute(
                        text("SELECT payload FROM daily_report_versions WHERE id = :id"),
                        {"id": report_row["current_version_id"]},
                    )
                ).mappings().first()
                if version_row is not None:
                    import json

                    raw_payload = version_row["payload"]
                    payload = raw_payload if isinstance(raw_payload, dict) else json.loads(raw_payload)
                    site_version_id = report_row["current_version_id"]

            site_payloads.append((site_row["name"], payload))
            sources.append((site_daily_report_id, site_version_id))

        from mesiri.application.dpr.assembly import build_project_report_payload

        payload = build_project_report_payload(
            project_name=project_row["name"] if project_row else None,
            report_date=report_date,
            site_payloads=site_payloads,
        )
        return payload, sources

    async def record_project_sources(
        self,
        *,
        project_version_id: uuid.UUID,
        sources: list[tuple[uuid.UUID, uuid.UUID | None]],
    ) -> None:
        """Persist P8's composition trail: which SITE version (or none) each
        site under the project contributed to this PROJECT version. Must
        run after `create_version`/`revise_version` has minted
        `project_version_id` -- `daily_report_sources` FKs to it."""
        for site_daily_report_id, site_version_id in sources:
            await self._conn.execute(
                text(
                    """
                    INSERT INTO daily_report_sources (
                        id, project_version_id, site_daily_report_id, site_version_id
                    ) VALUES (
                        :id, :project_version_id, :site_daily_report_id, :site_version_id
                    )
                    ON CONFLICT (project_version_id, site_daily_report_id) DO NOTHING
                    """
                ),
                {
                    "id": uuid.uuid4(),
                    "project_version_id": project_version_id,
                    "site_daily_report_id": site_daily_report_id,
                    "site_version_id": site_version_id,
                },
            )

    async def create_version(
        self,
        *,
        daily_report_id: uuid.UUID,
        payload: dict[str, Any],
        narrative_summary: str | None = None,
        evaluate_readiness: bool = False,
    ) -> dict[str, Any]:
        """Insert a new version (P7: never mutate a prior version's
        payload) and point `daily_reports.current_version_id` at it. A
        report already APPROVED/PUBLISHED is left alone -- regenerating a
        frozen day's DRAFT payload after approval would defeat the freeze
        this table exists to enforce; callers that need to correct an
        approved day must go through `revise_version` with a reason.

        Status after the insert (BE-08): a SITE day takes
        `site_day.status_after_refresh` -- needs details / ready once
        `evaluate_readiness` is set (the project's cutoff has passed), and a
        day with the engineer stays with the engineer. A PROJECT roll-up
        keeps the old behaviour (back to DRAFT, unless it is IN_REVIEW)."""
        report_row = (
            await self._conn.execute(
                text("SELECT status::text AS status, level::text AS level FROM daily_reports WHERE id = :id"),
                {"id": daily_report_id},
            )
        ).mappings().first()
        if report_row and report_row["status"] in site_day.FROZEN:
            raise ValueError(
                f"daily_report {daily_report_id} is already {report_row['status']} -- "
                "cannot silently overwrite an approved version's payload"
            )

        current_status = report_row["status"] if report_row else site_day.DRAFT
        missing: dict[str, list[str]] | None = None
        if report_row and report_row["level"] == "SITE":
            new_status = site_day.status_after_refresh(
                current_status, payload, evaluate_readiness=evaluate_readiness
            )
            if new_status in (site_day.NEEDS_DETAILS, site_day.READY):
                missing = site_day.missing_sections(payload)
        else:
            new_status = current_status if current_status == site_day.IN_REVIEW else site_day.DRAFT

        next_version_row = (
            await self._conn.execute(
                text(
                    "SELECT COALESCE(MAX(version_no), 0) + 1 AS next FROM daily_report_versions "
                    "WHERE daily_report_id = :id"
                ),
                {"id": daily_report_id},
            )
        ).mappings().first()
        version_no = next_version_row["next"]

        version_id = uuid.uuid4()
        import json

        await self._conn.execute(
            text(
                """
                INSERT INTO daily_report_versions (
                    id, daily_report_id, version_no, payload, narrative_summary
                ) VALUES (
                    :id, :daily_report_id, :version_no, CAST(:payload AS JSONB), :narrative_summary
                )
                """
            ),
            {
                "id": version_id,
                "daily_report_id": daily_report_id,
                "version_no": version_no,
                "payload": json.dumps(payload),
                "narrative_summary": narrative_summary,
            },
        )
        await self._conn.execute(
            text(
                "UPDATE daily_reports SET current_version_id = :version_id, "
                "status = CAST(:status AS daily_report_status), "
                "missing_sections = CAST(:missing AS JSONB), updated_at = now() WHERE id = :id"
            ),
            {
                "version_id": version_id,
                "id": daily_report_id,
                "status": new_status,
                "missing": json.dumps(missing) if missing is not None else None,
            },
        )
        return {"id": version_id, "daily_report_id": daily_report_id, "version_no": version_no}

    async def open_site_days(
        self,
        *,
        organization_id: uuid.UUID,
        project_id: uuid.UUID,
        report_date: datetime.date,
    ) -> int:
        """Make sure every active site of the project has its working-day
        record for `report_date` (BE-08), and label the ones nobody drafted
        a version for. Run at the project's cutoff, after the drafts.

        A site that logged nothing used to have no row at all until the
        project roll-up created a bare DRAFT one, so the evening gap-check
        had nothing to ask about. Now such a day is checked against what was
        recorded (labour can exist with no work items) and marked needs
        details or ready. No version is created for it: an empty payload is
        not a report, and would only feed the PDF renderer a blank page.
        Returns how many days were labelled."""
        site_rows = (
            await self._conn.execute(
                text(
                    """
                    SELECT id FROM sites
                    WHERE organization_id = :org_id AND project_id = :project_id
                      AND status = 'active'
                    """
                ),
                {"org_id": organization_id, "project_id": project_id},
            )
        ).mappings().all()

        labelled = 0
        for site_row in site_rows:
            daily_report_id = await self.get_or_create_daily_report(
                organization_id=organization_id,
                project_id=project_id,
                site_id=site_row["id"],
                report_date=report_date,
            )
            report_row = (
                await self._conn.execute(
                    text(
                        "SELECT status::text AS status, current_version_id "
                        "FROM daily_reports WHERE id = :id"
                    ),
                    {"id": daily_report_id},
                )
            ).mappings().first()
            if (
                report_row is None
                or report_row["current_version_id"] is not None
                or report_row["status"] not in site_day.REEVALUATED
            ):
                continue
            payload = await self.assemble_site_report_payload(
                organization_id=organization_id,
                project_id=project_id,
                site_id=site_row["id"],
                report_date=report_date,
            )
            await self.label_site_day(daily_report_id=daily_report_id, payload=payload)
            labelled += 1
        return labelled

    async def label_site_day(self, *, daily_report_id: uuid.UUID, payload: dict[str, Any]) -> str:
        """Label a day that has no version as needs details or ready, from
        what was recorded (no version: an empty payload is not a report).
        Returns the status set."""
        status = site_day.readiness_status(payload)
        await self._conn.execute(
            text(
                "UPDATE daily_reports SET status = CAST(:status AS daily_report_status), "
                "missing_sections = CAST(:missing AS JSONB), updated_at = now() WHERE id = :id"
            ),
            {
                "id": daily_report_id,
                "status": status,
                "missing": json.dumps(site_day.missing_sections(payload)),
            },
        )
        return status

    async def set_site_day_conditions(
        self,
        *,
        organization_id: uuid.UUID,
        project_id: uuid.UUID,
        site_id: uuid.UUID,
        report_date: datetime.date,
        changes: dict[str, Any],
    ) -> dict[str, Any]:
        """Set some of the site day's conditions (BE-14); fields not in
        `changes` are left as they are, a None value clears one. Creates the
        day if nothing was logged yet -- "no work today" is usually said
        about exactly such a day.

        Refuses a confirmed day (ValueError): its conditions are part of the
        frozen version; a correction goes through a revision. After the
        change the day's readiness is re-checked, so marking "no work"
        makes it ready straight away, even before the cutoff."""
        site_day.validate_conditions(changes)
        allowed = {"weather", "hours_lost", "site_working", "tomorrow_plan"}
        changes = {k: v for k, v in changes.items() if k in allowed}

        daily_report_id = await self.get_or_create_daily_report(
            organization_id=organization_id,
            project_id=project_id,
            site_id=site_id,
            report_date=report_date,
        )
        row = (
            await self._conn.execute(
                text("SELECT status::text AS status FROM daily_reports WHERE id = :id"),
                {"id": daily_report_id},
            )
        ).mappings().first()
        status = row["status"] if row else site_day.DRAFT
        if status in site_day.FROZEN:
            raise site_day.InvalidSiteDayTransition(
                f"this day is already {status}; revise it to change its conditions"
            )

        if changes:
            assignments = ", ".join(f"{key} = :{key}" for key in changes)
            await self._conn.execute(
                text(f"UPDATE daily_reports SET {assignments}, updated_at = now() WHERE id = :id"),
                {**changes, "id": daily_report_id},
            )

        payload = await self.assemble_site_report_payload(
            organization_id=organization_id,
            project_id=project_id,
            site_id=site_id,
            report_date=report_date,
        )
        new_status = site_day.status_after_refresh(
            status,
            payload,
            evaluate_readiness=(payload.get("conditions") or {}).get("site_working")
            == site_day.SITE_WORKING_NONE,
        )
        missing = (
            site_day.missing_sections(payload)
            if new_status in (site_day.NEEDS_DETAILS, site_day.READY)
            else None
        )
        if new_status != status or missing is not None:
            await self._conn.execute(
                text(
                    "UPDATE daily_reports SET status = CAST(:status AS daily_report_status), "
                    "missing_sections = CAST(:missing AS JSONB), updated_at = now() WHERE id = :id"
                ),
                {
                    "id": daily_report_id,
                    "status": new_status,
                    "missing": json.dumps(missing) if missing is not None else None,
                },
            )
        return {
            "daily_report_id": daily_report_id,
            "status": new_status.lower(),
            "conditions": payload.get("conditions") or {},
            "missing_sections": missing,
        }

    async def find_site(
        self, *, organization_id: uuid.UUID, site_id: uuid.UUID
    ) -> dict[str, Any] | None:
        row = (
            await self._conn.execute(
                text("SELECT id, project_id FROM sites WHERE organization_id = :org_id AND id = :id"),
                {"org_id": organization_id, "id": site_id},
            )
        ).mappings().first()
        return dict(row) if row else None

    async def list_site_days(
        self,
        *,
        organization_id: uuid.UUID,
        project_ids: set[uuid.UUID] | None,
        report_date: datetime.date,
    ) -> list[dict[str, Any]]:
        """Every active site's working day for `report_date` (BE-08), for
        the Today page (WEB-03). A site with no record yet (before cutoff,
        nothing logged) is listed as collecting with no report id rather
        than left out -- an absent site is exactly what the reader needs.

        Counts are live, not from a version: during the day no version
        exists yet. Workers use the same "live report" rule as the DPR and
        the labour dashboard (workforce.live_report_sql, plus BE-10's
        counted_line_sql), so the three can't disagree; a line with no headcount counts as one person, as the DPR
        does. `open_issues` is everything still open on the site, not only
        today's."""
        from mesiri.infrastructure.postgres.repositories.workforce import (
            counted_line_sql,
            live_report_sql,
        )

        where = ["s.organization_id = :org_id", "s.status = 'active'"]
        params: dict[str, Any] = {"org_id": organization_id, "report_date": report_date}
        if project_ids is not None:
            where.append("s.project_id = ANY(:project_ids)")
            params["project_ids"] = list(project_ids)
        rows = (
            await self._conn.execute(
                text(
                    f"""
                    WITH acts AS (
                        SELECT site_id, count(*) AS work_items, max(created_at) AS last_at
                        FROM activities
                        WHERE organization_id = :org_id AND activity_date = :report_date
                          AND deleted_at IS NULL
                        GROUP BY site_id
                    ), latest_act AS (
                        SELECT DISTINCT ON (a.site_id) a.site_id, a.narrative,
                               u.full_name AS reporter_name
                        FROM activities a
                        LEFT JOIN users u ON u.id = a.reported_by_user_id
                        WHERE a.organization_id = :org_id AND a.activity_date = :report_date
                          AND a.deleted_at IS NULL
                        ORDER BY a.site_id, a.created_at DESC
                    ), photos AS (
                        SELECT a.site_id, count(pa.id) AS photos
                        FROM activities a
                        JOIN progress_attachments pa
                          ON pa.parent_type = 'ACTIVITY' AND pa.parent_id = a.id
                        WHERE a.organization_id = :org_id AND a.activity_date = :report_date
                          AND a.deleted_at IS NULL
                        GROUP BY a.site_id
                    ), labour AS (
                        SELECT lar.site_id,
                               sum(COALESCE(NULLIF(lal.headcount, 0), 1)) AS workers,
                               max(lar.created_at) AS last_at
                        FROM labour_attendance_lines lal
                        JOIN labour_attendance_reports lar ON lar.id = lal.report_id
                        WHERE lar.organization_id = :org_id AND lar.occurred_date = :report_date
                          AND {live_report_sql("lar")}
                          AND {counted_line_sql("lal", "lar")}
                        GROUP BY lar.site_id
                    ), issues AS (
                        SELECT site_id, count(*) AS open_issues
                        FROM site_issues
                        WHERE organization_id = :org_id AND status IN ('OPEN', 'ACKNOWLEDGED')
                        GROUP BY site_id
                    )
                    SELECT s.id AS site_id, s.name AS site_name,
                           p.id AS project_id, p.name AS project_name,
                           dr.id AS daily_report_id, dr.code,
                           COALESCE(LOWER(dr.status::text), 'draft') AS status,
                           dr.missing_sections, dr.site_working,
                           COALESCE(labour.workers, 0) AS workers,
                           COALESCE(acts.work_items, 0) AS work_items,
                           COALESCE(photos.photos, 0) AS photos,
                           COALESCE(issues.open_issues, 0) AS open_issues,
                           GREATEST(acts.last_at, labour.last_at) AS last_update_at,
                           latest_act.reporter_name AS last_update_by,
                           latest_act.narrative AS latest_update
                    FROM sites s
                    JOIN projects p ON p.id = s.project_id
                    LEFT JOIN daily_reports dr
                      ON dr.site_id = s.id AND dr.level = 'SITE'
                     AND dr.report_date = :report_date
                     AND dr.organization_id = s.organization_id
                    LEFT JOIN acts ON acts.site_id = s.id
                    LEFT JOIN latest_act ON latest_act.site_id = s.id
                    LEFT JOIN photos ON photos.site_id = s.id
                    LEFT JOIN labour ON labour.site_id = s.id
                    LEFT JOIN issues ON issues.site_id = s.id
                    WHERE {" AND ".join(where)}
                    ORDER BY p.name, s.name
                    """
                ),
                params,
            )
        ).mappings().all()
        days = []
        for row in rows:
            day = dict(row)
            if isinstance(day["missing_sections"], str):
                day["missing_sections"] = json.loads(day["missing_sections"])
            for key in ("workers", "work_items", "photos", "open_issues"):
                day[key] = int(day[key] or 0)
            days.append(day)
        return days

    async def list_project_days(
        self,
        *,
        organization_id: uuid.UUID,
        project_ids: set[uuid.UUID] | None,
        report_date: datetime.date,
    ) -> list[dict[str, Any]]:
        """Each project's side of the day for the Today page (WEB-03): its
        cutoff and send deadline, how many active sites it has, its PROJECT
        roll-up status, and whether the DPR went out (BE-16)."""
        where = ["p.organization_id = :org_id", "p.status != 'archived'"]
        params: dict[str, Any] = {"org_id": organization_id, "report_date": report_date}
        if project_ids is not None:
            where.append("p.id = ANY(:project_ids)")
            params["project_ids"] = list(project_ids)
        rows = (
            await self._conn.execute(
                text(
                    f"""
                    SELECT p.id AS project_id, p.name AS project_name,
                           p.reporting_cutoff_time, p.dpr_send_deadline, p.auto_generate_dpr,
                           (p.dpr_last_sent_on = :report_date) AS sent,
                           (p.dpr_send_requested_on = :report_date) AS send_requested,
                           (SELECT count(*) FROM sites s
                             WHERE s.project_id = p.id AND s.status = 'active') AS site_count,
                           LOWER(pr.status::text) AS project_report_status,
                           pr.id AS project_report_id
                    FROM projects p
                    LEFT JOIN daily_reports pr
                      ON pr.project_id = p.id AND pr.level = 'PROJECT'
                     AND pr.report_date = :report_date
                    WHERE {" AND ".join(where)}
                    ORDER BY p.name
                    """
                ),
                params,
            )
        ).mappings().all()
        projects = []
        for row in rows:
            project = dict(row)
            project["site_count"] = int(project["site_count"] or 0)
            project["sent"] = bool(project["sent"])
            project["send_requested"] = bool(project["send_requested"])
            project["auto_generate_dpr"] = bool(project["auto_generate_dpr"])
            if project["site_count"]:
                projects.append(project)
        return projects

    async def get_report_scope(
        self, *, organization_id: uuid.UUID, report_id: uuid.UUID
    ) -> dict[str, Any] | None:
        """The raw project_id/site_id/report_date/level/status a revision
        needs to re-assemble a payload -- distinct from get_report/
        get_report_for_pdf, which return display-shaped rows (names, joined
        text), not the FK/date values assemble_site_report_payload takes."""
        row = (
            await self._conn.execute(
                text(
                    """
                    SELECT project_id, site_id, report_date, level, status::text AS status,
                           current_version_id
                    FROM daily_reports
                    WHERE organization_id = :org_id AND id = :id
                    """
                ),
                {"org_id": organization_id, "id": report_id},
            )
        ).mappings().first()
        return dict(row) if row else None

    async def revise_version(
        self,
        *,
        daily_report_id: uuid.UUID,
        payload: dict[str, Any],
        narrative_summary: str | None,
        revision_reason: str,
        reset_status: bool = True,
    ) -> dict[str, Any]:
        """Create a new version that supersedes the current one, for a
        report already APPROVED/PUBLISHED -- the counterpart create_version
        deliberately refuses (see its docstring). Requires a non-empty
        `revision_reason`, written to the version row alongside
        `supersedes_version_id` so the correction is auditable, not a silent
        overwrite.

        Resets `daily_reports.status` back to DRAFT so the corrected
        version goes through submit-for-review/approve/publish again, the
        same lifecycle a fresh day's report follows -- P7's freeze exists to
        stop an approved day being overwritten *silently*, not to make it
        permanently uncorrectable.

        `reset_status=False` (BE-13, a late entry for a day whose report was
        already sent) records the revised version but leaves the status
        alone, so nothing is confirmed or sent again.
        """
        if not revision_reason or not revision_reason.strip():
            raise ValueError("revision_reason is required to revise an approved report")

        report_row = (
            await self._conn.execute(
                text(
                    "SELECT status, current_version_id FROM daily_reports WHERE id = :id"
                ),
                {"id": daily_report_id},
            )
        ).mappings().first()
        if report_row is None:
            raise ValueError(f"daily_report {daily_report_id} not found")
        if report_row["status"] not in ("APPROVED", "PUBLISHED"):
            raise ValueError(
                f"daily_report {daily_report_id} is {report_row['status']}, not "
                "APPROVED/PUBLISHED -- use create_version for a pre-approval correction"
            )

        next_version_row = (
            await self._conn.execute(
                text(
                    "SELECT COALESCE(MAX(version_no), 0) + 1 AS next FROM daily_report_versions "
                    "WHERE daily_report_id = :id"
                ),
                {"id": daily_report_id},
            )
        ).mappings().first()
        version_no = next_version_row["next"]

        version_id = uuid.uuid4()
        import json

        await self._conn.execute(
            text(
                """
                INSERT INTO daily_report_versions (
                    id, daily_report_id, version_no, payload, narrative_summary,
                    supersedes_version_id, revision_reason
                ) VALUES (
                    :id, :daily_report_id, :version_no, CAST(:payload AS JSONB), :narrative_summary,
                    :supersedes_version_id, :revision_reason
                )
                """
            ),
            {
                "id": version_id,
                "daily_report_id": daily_report_id,
                "version_no": version_no,
                "payload": json.dumps(payload),
                "narrative_summary": narrative_summary,
                "supersedes_version_id": report_row["current_version_id"],
                "revision_reason": revision_reason,
            },
        )
        status_sql = "status = 'DRAFT', " if reset_status else ""
        await self._conn.execute(
            text(
                "UPDATE daily_reports SET current_version_id = :version_id, "
                f"{status_sql}updated_at = now() WHERE id = :id"
            ),
            {"version_id": version_id, "id": daily_report_id},
        )
        return {
            "id": version_id,
            "daily_report_id": daily_report_id,
            "version_no": version_no,
            "supersedes_version_id": report_row["current_version_id"],
        }

    async def get_current_payload(
        self, *, organization_id: uuid.UUID, report_id: uuid.UUID
    ) -> dict[str, Any] | None:
        """The payload of a report's current version, or None when it has
        none yet (WEB-05: the project DPR as it was sent)."""
        row = (
            await self._conn.execute(
                text(
                    """
                    SELECT v.payload
                    FROM daily_reports dr
                    JOIN daily_report_versions v ON v.id = dr.current_version_id
                    WHERE dr.organization_id = :org_id AND dr.id = :id
                    """
                ),
                {"org_id": organization_id, "id": report_id},
            )
        ).mappings().first()
        if row is None:
            return None
        payload = row["payload"]
        if isinstance(payload, str):
            import json

            payload = json.loads(payload)
        return payload

    async def list_versions(
        self, *, organization_id: uuid.UUID, report_id: uuid.UUID
    ) -> list[dict[str, Any]]:
        """Every version of one report, newest first (WEB-04): when it was
        made, who approved it, why it was revised, and which is current."""
        rows = (
            await self._conn.execute(
                text(
                    """
                    SELECT v.id, v.version_no, v.created_at, v.approved_at,
                           u.full_name AS approved_by, v.revision_reason,
                           (v.id = dr.current_version_id) AS is_current
                    FROM daily_report_versions v
                    JOIN daily_reports dr ON dr.id = v.daily_report_id
                    LEFT JOIN users u ON u.id = v.approved_by_user_id
                    WHERE dr.organization_id = :org_id AND dr.id = :id
                    ORDER BY v.version_no DESC
                    """
                ),
                {"org_id": organization_id, "id": report_id},
            )
        ).mappings().all()
        return [
            {
                "id": str(r["id"]),
                "version_no": r["version_no"],
                "created_at": r["created_at"].isoformat(),
                "approved_at": r["approved_at"].isoformat() if r["approved_at"] else None,
                "approved_by": r["approved_by"],
                "revision_reason": r["revision_reason"],
                "is_current": bool(r["is_current"]),
            }
            for r in rows
        ]

    async def get_report_for_pdf(
        self,
        *,
        organization_id: uuid.UUID,
        report_id: uuid.UUID,
        version_id: uuid.UUID | None = None,
    ) -> dict[str, Any] | None:
        """Everything a PDF export needs for one report: its current
        version's `payload` (the same JSON the assistant-side Playwright
        renderer already consumes, see application/dpr/assembly.py) plus
        whatever `rendered_object_key` that version already has, if the
        nightly cron (runtime/render_pending_dpr_pdfs.py) got to it first.

        Returns None for a report with no `current_version_id` at all --
        i.e. one created through the manual-entry form (create_report),
        which never gets a payload/version row. There is nothing real to
        render for those; the router surfaces that as a 404 rather than
        fabricating a PDF from fields that don't exist.
        """
        row = (
            await self._conn.execute(
                text(
                    """
                    SELECT
                        dr.id, dr.code, dr.report_date::text AS report_date,
                        dr.status::text AS workflow_status,
                        p.name AS project_name,
                        s.name AS site_name,
                        v.id AS version_id, v.payload, v.rendered_object_key
                    FROM daily_reports dr
                    JOIN projects p ON p.id = dr.project_id
                    LEFT JOIN sites s ON s.id = dr.site_id
                    LEFT JOIN daily_report_versions v
                           ON v.daily_report_id = dr.id
                          AND v.id = COALESCE(CAST(:version_id AS uuid), dr.current_version_id)
                    WHERE dr.organization_id = :org_id AND dr.id = :id
                    """
                ),
                {"org_id": organization_id, "id": report_id, "version_id": version_id},
            )
        ).mappings().first()
        if row is None or row["version_id"] is None:
            return None
        return dict(row)

    async def set_rendered_object_key(self, *, version_id: uuid.UUID, object_key: str) -> None:
        await self._conn.execute(
            text(
                "UPDATE daily_report_versions SET rendered_object_key = :key WHERE id = :id"
            ),
            {"key": object_key, "id": version_id},
        )

    async def list_unrendered_versions(self, *, limit: int = 20) -> list[dict[str, Any]]:
        """Versions with a payload but no PDF yet -- what the assistant-side
        render script (runtime/render_pending_dpr_pdfs.py) drains. Crosses
        the same backend/assistant boundary #9 Notifications' queue does:
        this repository (backend) only ever writes rows and the object key
        column; rendering itself needs Playwright, which lives on the
        assistant side (ADR-D8 -- reuses channel/receipt/'s pipeline)."""
        rows = (
            await self._conn.execute(
                text(
                    """
                    SELECT v.id AS version_id, v.daily_report_id, v.payload,
                           dr.code, dr.report_date::text AS report_date
                    FROM daily_report_versions v
                    JOIN daily_reports dr ON dr.id = v.daily_report_id
                    WHERE v.rendered_object_key IS NULL
                    ORDER BY v.created_at
                    LIMIT :limit
                    """
                ),
                {"limit": limit},
            )
        ).mappings().all()
        return [dict(r) for r in rows]
