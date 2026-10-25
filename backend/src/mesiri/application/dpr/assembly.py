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


# BE-12: which movement reasons are a delivery or a use. Everything else
# (adjustments, opening stock, corrections) changes stock without either and
# is shown as `adjusted`, so a stock correction never reads as a delivery.
# A row with no reason (older callers) counts by direction, as before.
_RECEIVED_REASONS = frozenset({None, "RECEIVED", "RETURN_IN", "TRANSFER_IN"})
_USED_REASONS = frozenset({None, "CONSUMED", "WASTAGE", "RETURN_TO_VENDOR", "TRANSFER_OUT"})


def _material_summary(
    movement_rows: list[dict[str, Any]],
    stock_rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Received/used quantities per material for one site+date, derived from
    material_movements the same way runtime/inventory_query.py re-aggregates
    stock levels -- RECEIPT adds to `received`, ISSUE adds to `used`. Day-
    scoped (unlike inventory_query's running stock total), since a DPR
    reports what happened on report_date, not the site's current inventory
    position. Cost is deliberately not included here: material_receipts.
    unit_cost is nullable and inconsistently recorded, unlike labour's wage
    (always copied at recording time) -- a partial cost figure would read as
    complete and mislead more than omitting it.

    `stock_rows` (BE-12) carry each material's `opening` (stock before the
    day) and `closing` (after it) from the whole ledger. With them, `adjusted`
    is whatever moved stock that day besides deliveries and use -- opening
    stock, adjustments, corrections of earlier days -- so opening + received
    + adjusted - used always equals closing. `beyond_stock` flags a closing
    below zero: more used than the site is known to hold. It is a flag, not
    a block (usage is recorded as reported); the usual cause is a delivery
    or opening stock nobody entered."""
    materials: dict[Any, dict[str, Any]] = {}

    def entry_for(row: dict[str, Any]) -> dict[str, Any]:
        return materials.setdefault(
            row.get("material_id"),
            {"material_name": row.get("material_name"), "unit": row.get("unit"),
             "received": Decimal("0"), "used": Decimal("0"), "adjusted": Decimal("0"),
             "opening": None, "closing": None},
        )

    for row in movement_rows:
        entry = entry_for(row)
        quantity = Decimal(str(row.get("quantity") or 0))
        reason = row.get("movement_reason")
        if row.get("movement_type") == "RECEIPT":
            if reason in _RECEIVED_REASONS:
                entry["received"] += quantity
            else:
                entry["adjusted"] += quantity
        elif row.get("movement_type") == "ISSUE":
            if reason in _USED_REASONS:
                entry["used"] += quantity
            else:
                entry["adjusted"] -= quantity

    for row in stock_rows or []:
        opening = Decimal(str(row.get("opening") or 0))
        closing = Decimal(str(row.get("closing") or 0))
        if row.get("material_id") not in materials and opening == closing:
            continue  # moved and was corrected the same day: nothing to show
        entry = entry_for(row)
        entry["opening"] = opening
        entry["closing"] = closing
        entry["adjusted"] = closing - opening - entry["received"] + entry["used"]

    return [
        {
            "material_name": entry["material_name"],
            "unit": entry["unit"],
            "received": str(entry["received"]),
            "used": str(entry["used"]),
            "adjusted": str(entry["adjusted"]),
            "opening": None if entry["opening"] is None else str(entry["opening"]),
            "closing": None if entry["closing"] is None else str(entry["closing"]),
            "beyond_stock": entry["closing"] is not None and entry["closing"] < 0,
        }
        for entry in materials.values()
    ]


def _normalised(text: Any) -> str:
    """Case, spacing and punctuation folded, so "Plastering, 2nd floor" and
    "plastering 2nd floor" compare equal."""
    return " ".join("".join(ch if ch.isalnum() else " " for ch in str(text or "").lower()).split())


def _flag_possible_duplicates(activities: list[dict[str, Any]], rows: list[dict[str, Any]]) -> None:
    """BE-11: mark a work item that repeats an earlier one on the same day.

    Two people (or one person twice) reporting the same work counts it twice.
    A later activity is a possible duplicate of an earlier one when both have
    the same work type and location, and either the same quantities or --
    when neither gave quantities -- the same description. Different
    quantities of the same work (east wing 120 sqm, west wing 80 sqm) are two
    pieces of work, not a duplicate. A flag for the engineer, who confirms or
    rejects the day's drafts; nothing is merged or removed here."""
    seen: set[tuple[Any, ...]] = set()
    for activity, row in zip(activities, rows, strict=True):
        work_type = _normalised(row.get("work_type"))
        quantities = tuple(
            sorted(
                (str(Decimal(str(q.get("quantity") or 0)).normalize()), str(q.get("unit") or ""))
                for q in activity["quantities"]
            )
        )
        what = quantities or _normalised(row.get("narrative"))
        key = (work_type, row.get("location_id"), what)
        activity["possible_duplicate"] = bool(work_type and what) and key in seen
        seen.add(key)


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
    material_stock_rows: list[dict[str, Any]] | None = None,
    conditions: dict[str, Any] | None = None,
    review_states: dict[str, dict[Any, str]] | None = None,
    late_entries: list[dict[str, Any]] | None = None,
    carried_issue_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compose the payload dict. `activity_rows`/`issue_rows`/`labour_lines`/
    `material_movement_rows` are already scoped to the one site+date by the
    caller's query -- this function does no filtering, only shaping.

    `conditions` is the site day's own weather / hours lost / site working /
    tomorrow's plan (BE-14), copied in so a confirmed version keeps them.

    `review_states` (BE-09) is fact type -> {fact id -> draft/confirmed};
    each activity and issue carries its `review`, and `drafts` counts what
    the engineer still has to confirm, per section. A fact not listed is
    confirmed.

    `late_entries` (BE-13) are earlier days' entries that arrived after that
    day was confirmed; this report lists them once, under "Late entries for
    earlier days" (application/dpr/late_entries.py)."""
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
    _flag_possible_duplicates(activities, activity_rows)
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
    # BE-51: earlier days' issues still open on this day (or closed on it),
    # each with the day it was reported. Kept apart from `issues`: they are
    # not this day's entries, so they add no hours lost, no review item and
    # no draft; they count towards the open issues, as the Today page does.
    carried_issues = [
        {
            "issue_type": row.get("issue_type"),
            "severity": row.get("severity"),
            "narrative": row.get("narrative"),
            "status": row.get("status"),
            "reported_on": str(row.get("reported_on") or ""),
        }
        for row in carried_issue_rows or []
    ]
    materials = _material_summary(material_movement_rows or [], material_stock_rows)
    return {
        "level": "SITE",
        "project_name": project_name,
        "site_name": site_name,
        "report_date": report_date.isoformat(),
        "activities": activities,
        "activity_count": len(activities),
        "possible_duplicates": sum(1 for a in activities if a["possible_duplicate"]),
        "issues": issues,
        "carried_issues": carried_issues,
        # Open and acknowledged, the Today page's own rule (list_site_days).
        "open_issue_count": sum(
            1 for i in [*issues, *carried_issues] if i["status"] in ("OPEN", "ACKNOWLEDGED")
        ),
        "evidence_count": sum(a["evidence_count"] for a in activities),
        "labour": _labour_summary(labour_lines or []),
        "materials": materials,
        "stock_flags": sum(1 for m in materials if m["beyond_stock"]),
        "conditions": _conditions(conditions or {}, issues),
        "drafts": fact_review.review_counts(review_states),
        "late_entries": list(late_entries or []),
    }


def _conditions(conditions: dict[str, Any], issues: list[dict[str, Any]]) -> dict[str, Any]:
    """The site day's conditions. Hours lost the engineer entered win; when
    nobody entered a figure it is the day's issue delays added up, marked
    `hours_lost_source: "issues"` so the report can say where it came from.
    BE-48: never more than a day (the dashboard's own limit), however long
    each issue said it lasted -- "no work for 2 days" is not 48 h on one day."""
    from mesiri.application.dpr.site_day import MAX_HOURS_LOST

    hours_lost = conditions.get("hours_lost")
    source = "entered"
    if hours_lost is None:
        minutes = sum(max(int(i.get("delay_duration_minutes") or 0), 0) for i in issues)
        minutes = min(minutes, MAX_HOURS_LOST * 60)
        hours_lost = round(minutes / 60, 1) if minutes else None
        source = "issues" if minutes else None
    return {
        "weather": conditions.get("weather"),
        "site_working": conditions.get("site_working"),
        "tomorrow_plan": conditions.get("tomorrow_plan"),
        "hours_lost": str(hours_lost) if hours_lost is not None else None,
        "hours_lost_source": source,
    }


def build_review_items(
    *,
    payload: dict[str, Any],
    activity_rows: list[dict[str, Any]],
    issue_rows: list[dict[str, Any]],
    labour_lines: list[dict[str, Any]],
    material_movement_rows: list[dict[str, Any]],
    review_states: dict[str, dict[Any, str]],
) -> list[dict[str, Any]]:
    """WEB-04: every item on a site's day the engineer can confirm or remove,
    with its id and fact type (what /dpr/facts/{type}/{id}/... takes), from
    the same rows `build_site_report_payload` used. Kept out of the payload
    on purpose: the payload is what a version stores and the PDF prints.

    Labour and materials are one item per report / receipt-or-usage record,
    the unit people send and the unit BE-09 reviews."""
    from mesiri.application.dpr import fact_review

    def review_of(fact_type: str, fact_id: Any) -> str:
        return (review_states.get(fact_type) or {}).get(fact_id, fact_review.CONFIRMED)

    items: list[dict[str, Any]] = []
    for activity, row in zip(payload["activities"], activity_rows, strict=True):
        items.append(
            {
                "fact_type": fact_review.ACTIVITY,
                "id": str(row["id"]),
                "section": "work",
                "title": row.get("work_type") or "Work",
                "detail": row.get("narrative"),
                "quantities": activity["quantities"],
                "evidence_count": activity["evidence_count"],
                "review": activity["review"],
                "flags": ["possible_duplicate"] if activity.get("possible_duplicate") else [],
            }
        )

    by_report: dict[Any, list[dict[str, Any]]] = {}
    for line in labour_lines:
        by_report.setdefault(line["report_id"], []).append(line)
    for report_id, lines in by_report.items():
        summary = _labour_summary(lines)
        trades = ", ".join(f"{t['trade']} {t['headcount']}" for t in summary["trades"])
        items.append(
            {
                "fact_type": fact_review.LABOUR_REPORT,
                "id": str(report_id),
                "section": "labour",
                "title": f"{summary['headcount']} workers",
                "detail": trades or None,
                "review": review_of(fact_review.LABOUR_REPORT, report_id),
                "flags": [],
            }
        )

    beyond = {
        (m.get("material_name"), m.get("unit"))
        for m in payload["materials"]
        if m.get("beyond_stock")
    }
    seen: set[Any] = set()
    for row in material_movement_rows:
        fact_type = {
            "material_receipt": fact_review.MATERIAL_RECEIPT,
            "material_usage": fact_review.MATERIAL_USAGE,
        }.get(row.get("source_type") or "")
        if fact_type is None or row["source_id"] in seen:
            continue
        seen.add(row["source_id"])
        used = fact_type == fact_review.MATERIAL_USAGE
        flags = ["beyond_stock"] if used and (row.get("material_name"), row.get("unit")) in beyond else []
        items.append(
            {
                "fact_type": fact_type,
                "id": str(row["source_id"]),
                "section": "materials",
                "title": row.get("material_name"),
                "detail": f"{Decimal(str(row['quantity'])).normalize():f} {row.get('unit') or ''} "
                f"{'used' if used else 'received'}".replace("  ", " "),
                "review": review_of(fact_type, row["source_id"]),
                "flags": flags,
            }
        )

    for row in issue_rows:
        items.append(
            {
                "fact_type": fact_review.SITE_ISSUE,
                "id": str(row["id"]),
                "section": "issues",
                "title": row.get("issue_type") or "Issue",
                "detail": row.get("narrative"),
                "severity": row.get("severity"),
                "status": row.get("status"),
                "review": review_of(fact_review.SITE_ISSUE, row["id"]),
                "flags": [],
            }
        )
    return items


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
                    "stock_flags": 0,
                    "possible_duplicates": 0,
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
                "stock_flags": payload.get("stock_flags", 0),
                "possible_duplicates": payload.get("possible_duplicates", 0),
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

        for issue in [*payload.get("issues", []), *payload.get("carried_issues", [])]:
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
        "stock_flags": sum(site["stock_flags"] for site in sites),
        "possible_duplicates": sum(site["possible_duplicates"] for site in sites),
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
