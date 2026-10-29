"""The control panel's Overview (SA-18): the super admin's morning screen.

Answers, in order: is anything broken right now (`status`), what needs a
person today (`attention`, most urgent first, each pointing at the screen
where it is fixed), how the business is doing (`today`, `companies`,
`funnel`, `activity`, `cost`) and which companies need a nudge
(`most_active`, `gone_quiet`).

Composes reads that already exist rather than re-deriving them: company
status and setup from companies_overview.list_companies (SA-02), reply time
from the Reply Insights repository (SA-17), cost from the usage-cost
repository (SA-05), and "is today's DPR late" from the DPR sender's own rule
(application/projects/auto_dpr.py: the project's local date, its send
deadline). Usage counts come from PostgresPlatformActivityRepository.
Read-only. The worker/queue state is Redis-only and is read by the page
from /admin/queue/health, not here.
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from mesiri.application.automations.scheduling import local_now, parse_time_of_day
from mesiri.application.organizations.companies_overview import CompanyOverview, list_companies
from mesiri.application.projects.auto_dpr import send_deadline_or_default
from mesiri.domains.organizations import lifecycle
from mesiri.infrastructure.postgres.repositories.platform_activity import (
    PostgresPlatformActivityRepository,
)
from mesiri.infrastructure.postgres.repositories.reply_usage import PostgresReplyUsageRepository
from mesiri.infrastructure.postgres.repositories.usage_costs import PostgresUsageCostRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection

_INDIA = ZoneInfo("Asia/Kolkata")

#: A reply still missing this long after the message came in is "stuck".
UNANSWERED_AFTER = dt.timedelta(minutes=10)
#: The DPR sender ticks every few minutes; give it this long past the deadline.
DPR_GRACE = dt.timedelta(minutes=30)
#: A trial ending within this many days is worth a conversation.
TRIAL_ENDING_DAYS = 3
#: A trial this old with no site update yet is at risk.
AT_RISK_AFTER = dt.timedelta(days=3)
#: A company this old with no site or no reporter is stuck in setup.
SETUP_STUCK_AFTER = dt.timedelta(days=2)
#: No message for this long from a company that may use Mesiri: gone quiet.
QUIET_AFTER = dt.timedelta(days=3)
ACTIVITY_DAYS = 14
LIST_LIMIT = 8

CRITICAL, WARNING, INFO = "critical", "warning", "info"
_RANK = {CRITICAL: 0, WARNING: 1, INFO: 2}


def _company_ref(c: CompanyOverview, note: str) -> dict[str, Any]:
    return {"id": str(c.id), "name": c.name, "note": note}


def _item(
    key: str,
    severity: str,
    title: str,
    detail: str,
    link: str,
    count: int,
    companies: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "key": key,
        "severity": severity,
        "title": title,
        "detail": detail,
        "link": link,
        "count": count,
        "companies": (companies or [])[:5],
    }


def late_dprs(projects: list[dict[str, Any]], now: dt.datetime) -> tuple[list[dict], int, int]:
    """(projects whose DPR is late today, how many are due by now, how many
    went today). Each project's "today" and deadline are its own local ones.
    Pure, so testable without a database."""
    late, due, sent = [], 0, 0
    for p in projects:
        local = local_now(timezone_name=p["reporting_timezone"] or "UTC", now_utc=now)
        deadline = parse_time_of_day(send_deadline_or_default(p["dpr_send_deadline"]))
        deadline_at = dt.datetime.combine(local.date(), deadline, tzinfo=local.tzinfo)
        went_today = p["dpr_last_sent_on"] == local.date()
        sent += went_today
        if local >= deadline_at:
            due += 1
            if not went_today and local >= deadline_at + DPR_GRACE:
                late.append(p)
    return late, due, sent


def attention_items(
    companies: list[CompanyOverview],
    *,
    now: dt.datetime,
    failed_24h: int,
    unanswered: dict[str, Any],
    late: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """What needs a person, most urgent first. Pure."""
    items: list[dict[str, Any]] = []
    if failed_24h:
        items.append(
            _item(
                "failed",
                CRITICAL,
                "Messages failed",
                "WhatsApp messages Mesiri could not handle in the last 24 hours",
                "/logs?status=failed",
                failed_24h,
            )
        )
    if unanswered["count"]:
        items.append(
            _item(
                "unanswered",
                CRITICAL,
                "Messages with no reply",
                "Still waiting 10+ minutes after they came in (a photo waiting for "
                '"what is this for?" shows here too)',
                "/logs?status=pending",
                unanswered["count"],
            )
        )
    if late:
        items.append(
            _item(
                "late_dpr",
                CRITICAL,
                "DPRs late today",
                "Past the project's send time and not sent",
                f"/organizations/{late[0]['organization_id']}",
                len(late),
                [
                    {
                        "id": str(p["organization_id"]),
                        "name": p["organization_name"],
                        "note": f"{p['name']} · due {send_deadline_or_default(p['dpr_send_deadline'])}",
                    }
                    for p in late
                ],
            )
        )

    def companies_where(pred, note) -> list[dict[str, Any]]:
        return [_company_ref(c, note(c)) for c in companies if pred(c)]

    rules = [
        (
            "continue",
            WARNING,
            "Want to continue with Mesiri",
            "Trial owners who asked to buy. Convert or extend them from the company page",
            lambda c: c.open_continue_requests > 0,
            lambda c: "asked to continue",
        ),
        (
            "trial_ending",
            WARNING,
            "Trials ending soon",
            f"On trial with {TRIAL_ENDING_DAYS} days or less left",
            lambda c: (
                c.effective_status == lifecycle.TRIAL
                and c.trial_days_left is not None
                and c.trial_days_left <= TRIAL_ENDING_DAYS
            ),
            lambda c: f"{c.trial_days_left} day{'' if c.trial_days_left == 1 else 's'} left",
        ),
        (
            "at_risk",
            WARNING,
            "Trials with no site update yet",
            "Trial started 3+ days ago and nobody has reported from site",
            lambda c: (
                c.effective_status == lifecycle.TRIAL
                and c.setup.first_update_at is None
                and c.trial_started_at is not None
                and now - c.trial_started_at >= AT_RISK_AFTER
            ),
            lambda c: f"day {(now - c.trial_started_at).days + 1} of trial",
        ),
        (
            "setup_stuck",
            INFO,
            "Stuck in setup",
            "Created 2+ days ago with no site or nobody to report from site",
            lambda c: (
                c.effective_status in (lifecycle.TRIAL, lifecycle.ACTIVE)
                and c.created_at is not None
                and now - c.created_at >= SETUP_STUCK_AFTER
                and not (c.setup.has_site and c.setup.has_team)
            ),
            lambda c: "no site yet" if not c.setup.has_site else "no site reporter yet",
        ),
        (
            "branding",
            INFO,
            "Letterhead requests",
            "Owners' letterhead or logo photos waiting for the team",
            lambda c: c.open_branding_requests > 0,
            lambda c: f"{c.open_branding_requests} open",
        ),
        (
            "deletable",
            INFO,
            "Expired trials to clean up",
            "Trial ended long ago and never converted (nothing is deleted on its own)",
            lambda c: c.eligible_for_deletion,
            lambda c: "expired",
        ),
    ]
    links = {"branding": "/branding-requests", "deletable": "/organizations"}
    for key, severity, title, detail, pred, note in rules:
        found = companies_where(pred, note)
        if found:
            link = links.get(key) or f"/organizations/{found[0]['id']}"
            items.append(_item(key, severity, title, detail, link, len(found), found))
    return sorted(items, key=lambda i: _RANK[i["severity"]])


def company_counts(companies: list[CompanyOverview], now: dt.datetime) -> dict[str, int]:
    """Companies by status, and trials started / conversions lately. Pure."""
    by = {s: 0 for s in (lifecycle.ACTIVE, lifecycle.TRIAL, lifecycle.EXPIRED, lifecycle.SUSPENDED)}
    for c in companies:
        by[c.effective_status] = by.get(c.effective_status, 0) + 1
    week, month = now - dt.timedelta(days=7), now - dt.timedelta(days=30)
    return {
        "total": len(companies),
        **by,
        "new_trials_7d": sum(
            1 for c in companies if c.trial_started_at and c.trial_started_at >= week
        ),
        "trials_started_30d": sum(
            1 for c in companies if c.trial_started_at and c.trial_started_at >= month
        ),
        "converted_30d": sum(1 for c in companies if c.converted_at and c.converted_at >= month),
    }


def onboarding_funnel(companies: list[CompanyOverview], now: dt.datetime) -> dict[str, int]:
    """Companies that started a trial in the last 30 days, and how far they
    got: a site, someone to report from it, a first update, a first DPR,
    paying. Pure."""
    cohort = [
        c
        for c in companies
        if c.trial_started_at and c.trial_started_at >= now - dt.timedelta(days=30)
    ]
    return {
        "started": len(cohort),
        "has_site": sum(c.setup.has_site for c in cohort),
        "has_team": sum(c.setup.has_team for c in cohort),
        "first_update": sum(c.setup.first_update_at is not None for c in cohort),
        "first_dpr": sum(c.setup.first_dpr_sent_at is not None for c in cohort),
        "converted": sum(c.converted_at is not None for c in cohort),
    }


def company_lists(
    companies: list[CompanyOverview], activity: list[dict[str, Any]], now: dt.datetime
) -> tuple[list[dict], list[dict]]:
    """(most active in the last 7 days, gone quiet). Only companies that may
    use Mesiri now count as quiet; the quietest first. Pure."""
    by_org = {a["organization_id"]: a for a in activity}

    def row(c: CompanyOverview) -> dict[str, Any]:
        a = by_org.get(c.id, {})
        last = a.get("last_message_at")
        return {
            "id": str(c.id),
            "name": c.name,
            "status": c.effective_status,
            "trial_days_left": c.trial_days_left,
            "messages_7d": int(a.get("messages") or 0),
            "people_7d": int(a.get("people") or 0),
            "dprs_7d": int(a.get("dprs_sent") or 0),
            "last_message_at": last.isoformat() if last else None,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }

    rows = [(c, row(c)) for c in companies]
    active = sorted(
        (r for _, r in rows if r["messages_7d"]), key=lambda r: (-r["messages_7d"], -r["dprs_7d"])
    )
    quiet = []
    for c, r in rows:
        if c.effective_status not in (lifecycle.TRIAL, lifecycle.ACTIVE):
            continue
        since = by_org.get(c.id, {}).get("last_message_at") or c.created_at
        if since is not None and now - since >= QUIET_AFTER:
            quiet.append({**r, "quiet_days": (now - since).days})
    quiet.sort(key=lambda r: -r["quiet_days"])
    return active[:LIST_LIMIT], quiet[:LIST_LIMIT]


def _start_of_indian_day(now: dt.datetime) -> dt.datetime:
    return dt.datetime.combine(now.astimezone(_INDIA).date(), dt.time.min, tzinfo=_INDIA)


async def platform_overview(
    conn: AsyncConnection, *, now: dt.datetime | None = None
) -> dict[str, Any]:
    """Everything the Overview shows, in one read."""
    now = now or dt.datetime.now(dt.UTC)
    today = now.astimezone(_INDIA).date()
    first_day = today - dt.timedelta(days=ACTIVITY_DAYS - 1)
    activity = PostgresPlatformActivityRepository(conn)
    replies = PostgresReplyUsageRepository(conn)
    costs = PostgresUsageCostRepository(conn)

    companies = await list_companies(conn, now=now)
    last_24h = await replies.summary(since=now - dt.timedelta(hours=24), until=now)
    last_hour = await replies.summary(since=now - dt.timedelta(hours=1), until=now)
    unanswered = await activity.unanswered(older_than=UNANSWERED_AFTER, within=dt.timedelta(days=1))
    dpr_projects = await activity.dpr_projects()
    late, dprs_due, dprs_sent = late_dprs(dpr_projects, now)
    days = await activity.by_day(first_day=first_day, last_day=today)
    day_costs = {
        r["day"]: r
        for r in await costs.costs_by_day(
            since=_start_of_indian_day(now) - dt.timedelta(days=ACTIVITY_DAYS - 1),
            until=None,
            organization_id=None,
        )
    }
    week_ago = now - dt.timedelta(days=7)
    cost_today = await costs.cost_totals(
        since=_start_of_indian_day(now), until=None, organization_id=None
    )
    cost_7d = await costs.cost_totals(since=week_ago, until=None, organization_id=None)
    week_activity = await activity.by_company(since=week_ago)
    most_active, gone_quiet = company_lists(companies, week_activity, now)
    counts = {
        **company_counts(companies, now),
        "active_7d": sum(1 for a in week_activity if a["messages"]),
    }
    today_row = days[-1] if days else {}

    return {
        "generated_at": now.isoformat(),
        "status": {
            "messages_24h": last_24h["messages"],
            "failed_24h": last_24h["failed"],
            "unanswered": unanswered["count"],
            "unanswered_oldest": unanswered["oldest"].isoformat() if unanswered["oldest"] else None,
            "reply_p50_1h_ms": last_hour["p50_ms"],
            "reply_p50_24h_ms": last_24h["p50_ms"],
            "reply_p95_24h_ms": last_24h["p95_ms"],
            "replied_1h": last_hour["replied"],
        },
        "attention": attention_items(
            companies, now=now, failed_24h=last_24h["failed"], unanswered=unanswered, late=late
        ),
        "today": {
            "day": today.isoformat(),
            "messages": today_row.get("messages", 0),
            "active_companies": today_row.get("active_companies", 0),
            "active_people": today_row.get("active_people", 0),
            "dprs_sent": dprs_sent,
            "dprs_due": dprs_due,
            "dprs_late": len(late),
            "dpr_projects": len(dpr_projects),
            "cost_inr": str(cost_today["total_cost_inr"]),
        },
        "companies": counts,
        "funnel": onboarding_funnel(companies, now),
        "activity": [
            {
                "day": d["day"].isoformat(),
                "messages": d["messages"],
                "active_companies": d["active_companies"],
                "active_people": d["active_people"],
                "dprs_sent": d["dprs_sent"],
                "cost_inr": str(day_costs.get(d["day"], {}).get("total_cost_inr", 0)),
            }
            for d in days
        ],
        "cost": {
            "today_inr": str(cost_today["total_cost_inr"]),
            "week_inr": str(cost_7d["total_cost_inr"]),
            "week_ai_inr": str(cost_7d["ai_cost_inr"]),
            "week_whatsapp_inr": str(cost_7d["whatsapp_cost_inr"]),
            "week_unpriced": cost_7d["unpriced"],
        },
        "most_active": most_active,
        "gone_quiet": gone_quiet,
    }
