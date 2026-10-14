"""PostgreSQL owner of `assistant_review_findings` (WA-15, migration 0473).

The nightly reviewer's problem list, one row per problem (keyed by the
reviewer's `fingerprint`), tracked across days. The only file with SQL for
this table; admin/review_router.py reads and writes through it. Unlike the
loggers, nothing here is best-effort -- every caller is an authenticated
admin API request, which should see a real error.
"""

from __future__ import annotations

import json
import uuid
from datetime import date
from typing import Any

from backend.postgres.message_logger import _build_engine

CATEGORIES = ("copy", "understanding", "routing", "flow", "speed", "error", "unmet")
STATUSES = ("open", "fixing", "fixed", "wont_fix")

_COLUMNS = (
    "id, fingerprint, category, title, detail, suspected_location, workflow_key, severity, "
    "occurrences, occurrences_last_day, days_seen, first_seen_on, last_seen_on, examples, "
    "replay_cases, status, fix_commit, note, created_at, updated_at"
)

# One sighting-day per call. Same fingerprint again:
# - a later day adds to the totals and counts one more day seen;
# - the same day (a re-run) replaces that day's count instead of adding it;
# - a problem marked fixed that shows up again is reopened: a regression.
_UPSERT = f"""
INSERT INTO assistant_review_findings AS f
  (id, fingerprint, category, title, detail, suspected_location, workflow_key, severity,
   occurrences, occurrences_last_day, days_seen, first_seen_on, last_seen_on, examples,
   replay_cases)
VALUES
  (:id, :fingerprint, :category, :title, :detail, :suspected_location, :workflow_key, :severity,
   :occurrences, :occurrences, 1, :seen_on, :seen_on, CAST(:examples AS jsonb),
   CAST(:replay_cases AS jsonb))
ON CONFLICT (fingerprint) DO UPDATE SET
  category = EXCLUDED.category,
  title = EXCLUDED.title,
  detail = COALESCE(EXCLUDED.detail, f.detail),
  suspected_location = COALESCE(EXCLUDED.suspected_location, f.suspected_location),
  workflow_key = COALESCE(EXCLUDED.workflow_key, f.workflow_key),
  severity = EXCLUDED.severity,
  occurrences = CASE WHEN f.last_seen_on = EXCLUDED.last_seen_on
                     THEN f.occurrences - f.occurrences_last_day + EXCLUDED.occurrences
                     ELSE f.occurrences + EXCLUDED.occurrences END,
  occurrences_last_day = EXCLUDED.occurrences,
  days_seen = f.days_seen + CASE WHEN f.last_seen_on = EXCLUDED.last_seen_on THEN 0 ELSE 1 END,
  last_seen_on = GREATEST(f.last_seen_on, EXCLUDED.last_seen_on),
  examples = (
    SELECT COALESCE(jsonb_agg(e ORDER BY ord), '[]'::jsonb) FROM (
      SELECT e, min(ord) AS ord
      FROM jsonb_array_elements(EXCLUDED.examples || f.examples) WITH ORDINALITY AS t(e, ord)
      GROUP BY e ORDER BY min(ord) LIMIT 10
    ) AS recent
  ),
  replay_cases = (
    SELECT COALESCE(jsonb_agg(DISTINCT r), '[]'::jsonb)
    FROM jsonb_array_elements(f.replay_cases || EXCLUDED.replay_cases) AS r
  ),
  status = CASE WHEN f.status = 'fixed' THEN 'open' ELSE f.status END,
  note = CASE WHEN f.status = 'fixed'
              THEN concat_ws(E'\\n', f.note, 'Reopened ' || EXCLUDED.last_seen_on || ': seen again after fix ' || coalesce(f.fix_commit, '?'))
              ELSE f.note END,
  updated_at = now()
RETURNING {_COLUMNS}
"""


def _validate(finding: dict[str, Any]) -> None:
    if not finding.get("fingerprint") or not finding.get("title"):
        raise ValueError("fingerprint and title are required")
    if finding.get("category") not in CATEGORIES:
        raise ValueError(f"category must be one of {', '.join(CATEGORIES)}")


class PostgresReviewFindings:
    def __init__(self, engine=None) -> None:
        self._engine = engine

    def _get_engine(self):
        if self._engine is None:
            self._engine = _build_engine()
        return self._engine

    async def record(
        self, findings: list[dict[str, Any]], *, seen_on: date
    ) -> list[dict[str, Any]]:
        """Upserts one night's findings in one transaction; returns the stored rows."""
        from sqlalchemy import text

        for finding in findings:
            _validate(finding)
        stored: list[dict[str, Any]] = []
        async with self._get_engine().begin() as conn:
            for f in findings:
                row = (
                    (
                        await conn.execute(
                            text(_UPSERT),
                            {
                                "id": uuid.uuid4(),
                                "fingerprint": f["fingerprint"][:120],
                                "category": f["category"],
                                "title": f["title"][:200],
                                "detail": f.get("detail"),
                                "suspected_location": f.get("suspected_location"),
                                "workflow_key": f.get("workflow_key"),
                                "severity": int(f.get("severity", 2)),
                                "occurrences": int(f.get("occurrences", 1)),
                                "seen_on": seen_on,
                                "examples": json.dumps(list(f.get("examples", []))[:10]),
                                "replay_cases": json.dumps(list(f.get("replay_cases", []))),
                            },
                        )
                    )
                    .mappings()
                    .one()
                )
                stored.append(dict(row))
        return stored

    async def list(self, *, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """Worst first: severity, then how many days it has been seen, then recency."""
        from sqlalchemy import String, bindparam, text

        stmt = text(
            f"SELECT {_COLUMNS} FROM assistant_review_findings "
            "WHERE (:status IS NULL OR status = :status) "
            "ORDER BY severity DESC, days_seen DESC, last_seen_on DESC LIMIT :limit"
        ).bindparams(bindparam("status", type_=String))
        async with self._get_engine().connect() as conn:
            rows = (await conn.execute(stmt, {"status": status, "limit": limit})).mappings().all()
        return [dict(r) for r in rows]

    async def update(
        self,
        fingerprint: str,
        *,
        status: str | None = None,
        fix_commit: str | None = None,
        note: str | None = None,
        replay_cases: list[str] | None = None,
    ) -> dict[str, Any] | None:
        from sqlalchemy import String, bindparam, text

        if status is not None and status not in STATUSES:
            raise ValueError(f"status must be one of {', '.join(STATUSES)}")
        stmt = text(
            "UPDATE assistant_review_findings SET "
            "status = COALESCE(:status, status), "
            "fix_commit = COALESCE(:fix_commit, fix_commit), "
            "note = COALESCE(:note, note), "
            "replay_cases = CASE WHEN CAST(:replay_cases AS jsonb) IS NULL THEN replay_cases "
            "  ELSE (SELECT COALESCE(jsonb_agg(DISTINCT r), '[]'::jsonb) "
            "        FROM jsonb_array_elements(replay_cases || CAST(:replay_cases AS jsonb)) AS r) END, "
            "updated_at = now() "
            f"WHERE fingerprint = :fingerprint RETURNING {_COLUMNS}"
        ).bindparams(
            bindparam("status", type_=String),
            bindparam("fix_commit", type_=String),
            bindparam("note", type_=String),
            bindparam("replay_cases", type_=String),
        )
        async with self._get_engine().begin() as conn:
            row = (
                (
                    await conn.execute(
                        stmt,
                        {
                            "fingerprint": fingerprint,
                            "status": status,
                            "fix_commit": fix_commit,
                            "note": note,
                            "replay_cases": json.dumps(replay_cases)
                            if replay_cases is not None
                            else None,
                        },
                    )
                )
                .mappings()
                .first()
            )
        return dict(row) if row else None
