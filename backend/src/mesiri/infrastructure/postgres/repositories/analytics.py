"""Read model for the Analytics page (WEB-24): a date range, aggregated in SQL.

The page used to fetch the first 50-100 rows of four lists and count them in
the browser, so every figure stopped at the page size; two of its charts were
made up outright. Everything here is computed over the whole range.

Same scope rules as the Reports list (dpr/router.py list_daily_reports):
the caller's projects, an optional site, and BE-42's custom site scope
(`restricted_project_ids` / `allowed_site_ids`). Workers use the DPR's own
"live report" + "counted line" rules (workforce.live_report_sql,
counted_line_sql), and a line without a headcount counts as one person, so
these numbers can't disagree with the Today page or a site DPR.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.application.dpr import fact_review


class PostgresAnalyticsRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def summary(
        self,
        *,
        organization_id: uuid.UUID,
        project_ids: set[uuid.UUID] | None,
        site_id: uuid.UUID | None,
        restricted_project_ids: set[uuid.UUID],
        allowed_site_ids: set[uuid.UUID],
        date_from: datetime.date,
        date_to: datetime.date,
    ) -> dict[str, Any]:
        from mesiri.infrastructure.postgres.repositories.workforce import (
            counted_line_sql,
            live_report_sql,
        )

        params: dict[str, Any] = {"org": organization_id, "date_from": date_from, "date_to": date_to}

        def scope(alias: str) -> str:
            """Organization, projects, site and BE-42 site scope on one alias."""
            parts = [f"{alias}.organization_id = :org"]
            if project_ids is not None:
                parts.append(f"{alias}.project_id = ANY(:project_ids)")
                params["project_ids"] = list(project_ids)
            if site_id is not None:
                parts.append(f"{alias}.site_id = :site_id")
                params["site_id"] = site_id
            if restricted_project_ids:
                parts.append(
                    f"(NOT ({alias}.project_id = ANY(:restricted)) OR {alias}.site_id = ANY(:allowed))"
                )
                params["restricted"] = list(restricted_project_ids)
                params["allowed"] = list(allowed_site_ids)
            return " AND ".join(parts)

        # Issues are timestamps; a day is the company's own (organizations.timezone).
        tz = "(SELECT COALESCE(timezone, 'Asia/Kolkata') FROM organizations WHERE id = :org)"

        days = (
            await self._conn.execute(
                text(
                    f"""
                    WITH d AS (
                        SELECT generate_series(CAST(:date_from AS date), CAST(:date_to AS date), interval '1 day')::date AS day
                    ), acts AS (
                        SELECT a.activity_date AS day, count(*) AS work_items
                        FROM activities a
                        WHERE {scope("a")} AND a.deleted_at IS NULL
                          AND {fact_review.counted_sql(fact_review.ACTIVITY, "a.id")}
                          AND a.activity_date BETWEEN :date_from AND :date_to
                        GROUP BY 1
                    ), photos AS (
                        SELECT a.activity_date AS day, count(pa.id) AS photos
                        FROM activities a
                        JOIN progress_attachments pa ON pa.parent_type = 'ACTIVITY' AND pa.parent_id = a.id
                        WHERE {scope("a")} AND a.deleted_at IS NULL
                          AND {fact_review.counted_sql(fact_review.ACTIVITY, "a.id")}
                          AND a.activity_date BETWEEN :date_from AND :date_to
                        GROUP BY 1
                    ), labour AS (
                        SELECT lar.occurred_date AS day,
                               sum(COALESCE(NULLIF(lal.headcount, 0), 1)) AS workers
                        FROM labour_attendance_lines lal
                        JOIN labour_attendance_reports lar ON lar.id = lal.report_id
                        WHERE {scope("lar")}
                          AND lar.occurred_date BETWEEN :date_from AND :date_to
                          AND {live_report_sql("lar")}
                          AND {counted_line_sql("lal", "lar")}
                        GROUP BY 1
                    ), issues AS (
                        SELECT (si.occurred_at AT TIME ZONE {tz})::date AS day,
                               count(*) AS issues,
                               COALESCE(sum(si.delay_duration_minutes), 0) AS delay_minutes
                        FROM site_issues si
                        WHERE {scope("si")}
                          AND {fact_review.counted_sql(fact_review.SITE_ISSUE, "si.id")}
                          AND (si.occurred_at AT TIME ZONE {tz})::date BETWEEN :date_from AND :date_to
                        GROUP BY 1
                    )
                    SELECT d.day,
                           COALESCE(labour.workers, 0) AS workers,
                           COALESCE(acts.work_items, 0) AS work_items,
                           COALESCE(photos.photos, 0) AS photos,
                           COALESCE(issues.issues, 0) AS issues,
                           COALESCE(issues.delay_minutes, 0) AS delay_minutes
                    FROM d
                    LEFT JOIN acts ON acts.day = d.day
                    LEFT JOIN photos ON photos.day = d.day
                    LEFT JOIN labour ON labour.day = d.day
                    LEFT JOIN issues ON issues.day = d.day
                    ORDER BY d.day
                    """
                ),
                params,
            )
        ).mappings().all()

        open_issues = (
            await self._conn.execute(
                text(
                    f"""
                    SELECT si.issue_type::text AS issue_type, si.severity::text AS severity, count(*) AS count
                    FROM site_issues si
                    WHERE {scope("si")} AND si.status IN ('OPEN', 'ACKNOWLEDGED')
                      AND {fact_review.counted_sql(fact_review.SITE_ISSUE, "si.id")}
                    GROUP BY 1, 2
                    """
                ),
                params,
            )
        ).mappings().all()

        # Per active site: days anything was sent, and days its site DPR was
        # confirmed or sent -- the "do my sites report?" view.
        sites = (
            await self._conn.execute(
                text(
                    f"""
                    WITH updates AS (
                        SELECT site_id, activity_date AS day FROM activities a
                        WHERE {scope("a")} AND a.deleted_at IS NULL
                          AND a.activity_date BETWEEN :date_from AND :date_to
                        UNION
                        SELECT site_id, occurred_date FROM labour_attendance_reports lar
                        WHERE {scope("lar")} AND lar.voided_at IS NULL
                          AND lar.occurred_date BETWEEN :date_from AND :date_to
                    ), confirmed AS (
                        SELECT site_id, count(DISTINCT report_date) AS days
                        FROM daily_reports dr
                        WHERE {scope("dr")} AND dr.level = 'SITE'
                          AND dr.status::text IN ('APPROVED', 'PUBLISHED')
                          AND dr.report_date BETWEEN :date_from AND :date_to
                        GROUP BY site_id
                    )
                    SELECT s.id AS site_id, s.name AS site_name, p.name AS project_name,
                           (SELECT count(DISTINCT u.day) FROM updates u WHERE u.site_id = s.id) AS days_with_updates,
                           COALESCE(confirmed.days, 0) AS days_confirmed
                    FROM sites s
                    JOIN projects p ON p.id = s.project_id
                    LEFT JOIN confirmed ON confirmed.site_id = s.id
                    WHERE s.organization_id = :org AND s.status = 'active'
                      AND ({"TRUE" if project_ids is None else "s.project_id = ANY(:project_ids)"})
                      AND ({"TRUE" if site_id is None else "s.id = :site_id"})
                      AND ({"TRUE" if not restricted_project_ids else "(NOT (s.project_id = ANY(:restricted)) OR s.id = ANY(:allowed))"})
                    ORDER BY p.name, s.name
                    """
                ),
                params,
            )
        ).mappings().all()

        return {
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "days": [
                {
                    "day": r["day"].isoformat(),
                    **{k: int(r[k]) for k in ("workers", "work_items", "photos", "issues", "delay_minutes")},
                }
                for r in days
            ],
            "open_issues": [
                {"issue_type": r["issue_type"], "severity": r["severity"], "count": int(r["count"])}
                for r in open_issues
            ],
            "sites": [
                {
                    "site_id": str(r["site_id"]),
                    "site_name": r["site_name"],
                    "project_name": r["project_name"],
                    "days_with_updates": int(r["days_with_updates"]),
                    "days_confirmed": int(r["days_confirmed"]),
                }
                for r in sites
            ],
        }
