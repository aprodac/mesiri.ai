"""Pure payload shaping for a SITE-level DPR (#16 Daily Report Generation).

Takes raw DB rows (already fetched by infrastructure/postgres/repositories/
dpr.py) and shapes them into the plain JSON-safe dict stored as
`daily_report_versions.payload` and consumed by the assistant-side PDF
renderer (channel/dpr_document/). No I/O here -- the split exists so this
shaping is unit-testable without a live database, same reasoning as
runtime/labour_query_service.py's `_summarize`.

`labour_lines`/`material_movement_rows` are optional (default to empty) so
existing callers/tests built before this data existed keep working -- a
report with nothing recorded in either module still shapes a valid, honest
zeroed section rather than omitting the key.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any


def _labour_summary(labour_lines: list[dict[str, Any]]) -> dict[str, Any]:
    """Headcount, per-trade breakdown, and cost for one site+date -- mirrors
    runtime/labour_query_service.py's `summarize_attendance` shape (the
    WhatsApp "how many workers today?" query), so the same figures a
    supervisor already sees in chat are what a client sees in the report.
    `daily_wage` is copied onto each attendance line at recording time (see
    migration 0371), never re-read from workforce_workers, so this cost is
    what that day actually cost, not what workers are paid today."""
    headcount = 0
    named_count = 0
    trade_counts: dict[str, int] = {}
    total_cost = Decimal("0")
    for line in labour_lines:
        try:
            count = int(line.get("headcount") or 1)
        except (TypeError, ValueError):
            count = 1
        headcount += count
        if str(line.get("worker_name") or "").strip():
            named_count += 1
        trade = str(line.get("trade") or "").strip()
        if trade:
            trade_counts[trade] = trade_counts.get(trade, 0) + count
        wage = line.get("daily_wage")
        if wage is not None:
            total_cost += Decimal(str(wage)) * count
    return {
        "headcount": headcount,
        "named_count": named_count,
        "trades": [{"trade": t, "headcount": c} for t, c in trade_counts.items()],
        "total_cost": str(total_cost),
    }


def _material_summary(movement_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Received/used quantities per material for one site+date, derived from
    material_movements the same way runtime/inventory_query.py re-aggregates
    stock levels -- RECEIPT adds to `received`, ISSUE adds to `used`. Day-
    scoped (unlike inventory_query's running stock total), since a DPR
    reports what happened on report_date, not the site's current inventory
    position. Cost is deliberately not included here: material_receipts.
    unit_cost is nullable and inconsistently recorded, unlike labour's wage
    (always copied at recording time) -- a partial cost figure would read as
    complete and mislead more than omitting it."""
    materials: dict[Any, dict[str, Any]] = {}
    for row in movement_rows:
        key = row.get("material_id")
        entry = materials.setdefault(
            key,
            {"material_name": row.get("material_name"), "unit": row.get("unit"),
             "received": Decimal("0"), "used": Decimal("0")},
        )
        quantity = Decimal(str(row.get("quantity") or 0))
        if row.get("movement_type") == "RECEIPT":
            entry["received"] += quantity
        elif row.get("movement_type") == "ISSUE":
            entry["used"] += quantity
    return [
        {
            "material_name": entry["material_name"],
            "unit": entry["unit"],
            "received": str(entry["received"]),
            "used": str(entry["used"]),
        }
        for entry in materials.values()
    ]


def build_site_report_payload(
    *,
    project_name: str | None,
    site_name: str | None,
    report_date: datetime.date,
    activity_rows: list[dict[str, Any]],
    quantities_by_activity: dict[Any, list[dict[str, Any]]],
    evidence_count_by_activity: dict[Any, int],
    issue_rows: list[dict[str, Any]],
    labour_lines: list[dict[str, Any]] | None = None,
    material_movement_rows: list[dict[str, Any]] | None = None,
    conditions: dict[str, Any] | None = None,
    review_states: dict[str, dict[Any, str]] | None = None,
) -> dict[str, Any]:
    """Compose the payload dict. `activity_rows`/`issue_rows`/`labour_lines`/
    `material_movement_rows` are already scoped to the one site+date by the
    caller's query -- this function does no filtering, only shaping.

    `conditions` is the site day's own weather / hours lost / site working /
    tomorrow's plan (BE-14), copied in so a confirmed version keeps them.

    `review_states` (BE-09) is fact type -> {fact id -> draft/confirmed};
    each activity and issue carries its `review`, and `drafts` counts what
    the engineer still has to confirm, per section. A fact not listed is
    confirmed."""
    from mesiri.application.dpr import fact_review

    review_states = review_states or {}

    def review_of(fact_type: str, fact_id: Any) -> str:
        return (review_states.get(fact_type) or {}).get(fact_id, fact_review.CONFIRMED)

    activities = [
        {
            "work_type": row.get("work_type"),
            "narrative": row.get("narrative"),
            "status": row.get("status"),
            "contractor": row.get("contractor"),
            "quantities": quantities_by_activity.get(row["id"], []),
            "evidence_count": evidence_count_by_activity.get(row["id"], 0),
            "review": review_of(fact_review.ACTIVITY, row["id"]),
        }
        for row in activity_rows
    ]
    issues = [
        {
            "issue_type": row.get("issue_type"),
            "severity": row.get("severity"),
            "narrative": row.get("narrative"),
            "status": row.get("status"),
            "delay_duration_minutes": row.get("delay_duration_minutes"),
            "review": review_of(fact_review.SITE_ISSUE, row.get("id")),
        }
        for row in issue_rows
    ]
    return {
        "level": "SITE",
        "project_name": project_name,
        "site_name": site_name,
        "report_date": report_date.isoformat(),
        "activities": activities,
        "activity_count": len(activities),
        "issues": issues,
        "open_issue_count": sum(1 for i in issues if i["status"] == "OPEN"),
        "evidence_count": sum(a["evidence_count"] for a in activities),
        "labour": _labour_summary(labour_lines or []),
        "materials": _material_summary(material_movement_rows or []),
        "conditions": _conditions(conditions or {}, issues),
        "drafts": fact_review.review_counts(review_states),
    }


def _conditions(conditions: dict[str, Any], issues: list[dict[str, Any]]) -> dict[str, Any]:
    """The site day's conditions. Hours lost the engineer entered win; when
    nobody entered a figure it is the day's issue delays added up, marked
    `hours_lost_source: "issues"` so the report can say where it came from."""
    hours_lost = conditions.get("hours_lost")
    source = "entered"
    if hours_lost is None:
        minutes = sum(int(i.get("delay_duration_minutes") or 0) for i in issues)
        hours_lost = round(minutes / 60, 1) if minutes else None
        source = "issues" if minutes else None
    return {
        "weather": conditions.get("weather"),
        "site_working": conditions.get("site_working"),
        "tomorrow_plan": conditions.get("tomorrow_plan"),
        "hours_lost": str(hours_lost) if hours_lost is not None else None,
        "hours_lost_source": source,
    }


def build_project_report_payload(
    *,
    project_name: str | None,
    report_date: datetime.date,
    site_payloads: list[tuple[str | None, dict[str, Any] | None]],
) -> dict[str, Any]:
    """Compose the PROJECT-level payload (ADR-D9/P8) from each active site's
    own already-approved SITE-level payload -- never independently
    re-derived from raw activities/issues, so a project report can never
    show something its own site reports didn't already sign off on.

    `site_payloads` is `(site_name, payload)` pairs, one per active site
    under the project: `payload` is `build_site_report_payload`'s own
    output when that site has an APPROVED/PUBLISHED version by cutoff, or
    `None` when it doesn't -- recorded as NOT_REPORTED (P8), which does not
    block the project rollup from publishing; a missing site report is the
    single most informative line on the page, not something the rest of
    the project's reporting should wait on.

    Per-trade labour breakdown is deliberately not composed across sites
    for v1 (unlike the SITE payload's `labour.trades`) -- only the
    aggregate headcount/cost, to keep this a genuine roll-up rather than a
    second, subtly-different trade-matching pass across sites that may
    name trades differently.
    """
    sites: list[dict[str, Any]] = []
    activity_count = 0
    open_issue_count = 0
    evidence_count = 0
    headcount = 0
    total_cost = Decimal("0")
    materials: dict[tuple[str | None, str | None], dict[str, Decimal]] = {}
    issues: list[dict[str, Any]] = []

    for site_name, payload in site_payloads:
        if payload is None:
            sites.append(
                {
                    "site_name": site_name,
                    "reported": False,
                    "activity_count": 0,
                    "open_issue_count": 0,
                    "headcount": 0,
                    "labour_cost": "0",
                }
            )
            continue

        labour = payload.get("labour") or {}
        site_activity_count = payload.get("activity_count", 0)
        site_open_issue_count = payload.get("open_issue_count", 0)
        site_headcount = labour.get("headcount", 0)
        site_cost = labour.get("total_cost", "0")
        sites.append(
            {
                "site_name": site_name,
                "reported": True,
                "activity_count": site_activity_count,
                "open_issue_count": site_open_issue_count,
                "headcount": site_headcount,
                "labour_cost": site_cost,
            }
        )
        activity_count += site_activity_count
        open_issue_count += site_open_issue_count
        evidence_count += payload.get("evidence_count", 0)
        headcount += site_headcount
        total_cost += Decimal(str(site_cost))

        for material in payload.get("materials", []):
            key = (material.get("material_name"), material.get("unit"))
            entry = materials.setdefault(key, {"received": Decimal("0"), "used": Decimal("0")})
            entry["received"] += Decimal(str(material.get("received") or 0))
            entry["used"] += Decimal(str(material.get("used") or 0))

        for issue in payload.get("issues", []):
            issues.append({**issue, "site_name": site_name})

    return {
        "level": "PROJECT",
        "project_name": project_name,
        "report_date": report_date.isoformat(),
        "sites": sites,
        "reported_site_count": sum(1 for s in sites if s["reported"]),
        "total_site_count": len(sites),
        "activity_count": activity_count,
        "open_issue_count": open_issue_count,
        "evidence_count": evidence_count,
        "issues": issues,
        "labour": {
            "headcount": headcount,
            "named_count": 0,
            "trades": [],
            "total_cost": str(total_cost),
        },
        "materials": [
            {
                "material_name": name,
                "unit": unit,
                "received": str(entry["received"]),
                "used": str(entry["used"]),
            }
            for (name, unit), entry in materials.items()
        ],
    }
