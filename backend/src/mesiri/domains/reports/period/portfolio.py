"""The owner's Monday brief (RPT-01, Adarsh #10): every project the person can see, one row each, worst first.

Each row is the project's own period report (``engine.build``, the same sections and rules), so a row and the
project's page never disagree. Archived and completed projects are left out. A project that cannot be read is
named in ``unavailable`` and the rest still show.
"""

from __future__ import annotations

import datetime
import logging
import uuid
from collections.abc import Callable
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.authorization.context import AuthorizationContext
from mesiri.domains.reports.period import engine, periods
from mesiri.domains.reports.period.headline import STATUS_WORD, inr

logger = logging.getLogger(__name__)

#: The sections a row needs (photos and "Needs you" from the inbox are the project page's).
ROW_SECTIONS = ("work", "schedule", "labour", "money", "issues", "completeness")
_LEFT_OUT = ("Archived", "Completed")
_WEIGHT = {"bad": 3, "warn": 1}


def _d(v: Any) -> Decimal:
    return Decimal(str(v)) if v not in (None, "") else Decimal(0)


def row_of(report: dict[str, Any]) -> dict[str, Any]:
    """One project's line in the brief, from its period report. Pure."""
    s = report["sections"]
    w, sc, lb, mo, iss = (s.get(k) or {} for k in ("work", "schedule", "labour", "money", "issues"))
    areas = [a for a in report["areas"] if a["key"] not in ("labour", "materials", "completeness")]
    score = sum(_WEIGHT.get(a["status"], 0) for a in areas) + (3 if _d(mo.get("overdue")) else 0)
    worst = "bad" if any(a["status"] == "bad" for a in areas) else "warn" if any(a["status"] == "warn" for a in areas) \
        else "good" if any(a["status"] == "good" for a in areas) else "none"
    top = report["needs_you"][0]["title"] if report["needs_you"] else None
    return {
        "project_id": report["project"]["id"], "name": report["project"]["name"],
        "client": report["project"].get("client"), "status": worst, "word": STATUS_WORD[worst], "attention": score,
        "progress_to_date": w.get("progress_to_date"), "expected_to_date": w.get("expected_to_date"),
        "done_pct": w.get("done_pct"), "plan_pct": w.get("plan_pct"), "work_status": w.get("status", "none"),
        "cost_status": mo.get("status") if mo else None, "labour_colour": mo.get("labour_colour") if mo else None,
        "spent": mo.get("spent") if mo else None, "billed": mo.get("billed"), "received": mo.get("received"),
        "owed": mo.get("owed"), "overdue": mo.get("overdue"), "oldest_overdue_days": mo.get("oldest_overdue_days", 0),
        "schedule_status": sc.get("status", "none"), "forecast_finish": sc.get("forecast_finish"),
        "slip_days": sc.get("slip_days", 0), "man_days": lb.get("man_days"),
        "open_issues": iss.get("open", 0), "serious_issues": iss.get("serious_open", 0),
        "needs": len(report["needs_you"]), "top": top, "lead": report["headline"]["lead"],
        "facts": report["headline"]["facts"],
    }


def _sum(rows: list[dict], key: str) -> str | None:
    values = [_d(r[key]) for r in rows if r.get(key) is not None]
    return str(sum(values, Decimal(0))) if values else None


def summarise(rows: list[dict[str, Any]], sees_money: bool, noun: str) -> dict[str, Any]:
    """Totals, the headline and the key figures of the brief. Pure."""
    need = [r for r in rows if r["status"] in ("bad", "warn")]
    totals = {k: _sum(rows, k) for k in ("spent", "billed", "received", "owed", "overdue", "man_days")}
    totals["open_issues"] = sum(r["open_issues"] for r in rows)
    totals["serious_issues"] = sum(r["serious_issues"] for r in rows)
    n = len(rows)
    if not n:
        lead = "No running projects to report on."
    elif need:
        lead = f"{n} project{'s' if n != 1 else ''}, {len(need)} need{'s' if len(need) == 1 else ''} you."
    else:
        lead = f"{n} project{'s' if n != 1 else ''}, a good {noun} on all of them."
    facts = [f"{r['name']}: {r['facts'][0]}" for r in need[:2] if r["facts"]]
    if sees_money and totals["owed"] and _d(totals["owed"]):
        over = f", {inr(totals['overdue'])} of it over 30 days" if _d(totals["overdue"]) else ""
        facts.append(f"Clients owe {inr(totals['owed'])}{over}.")
    kpis = []
    if sees_money:
        kpis.append({"key": "spent", "label": f"Spent this {noun}", "value": inr(totals["spent"]),
                     "note": f"{n} project{'s' if n != 1 else ''}", "tone": "none"})
        if any(_d(totals[k]) for k in ("billed", "received", "owed")):  # ₹0 billed, ₹0 owed is noise
            kpis.append({"key": "billed", "label": "Billed · received", "value": inr(totals["billed"]),
                         "note": f"{inr(totals['received'])} received", "tone": "none"})
            kpis.append({"key": "owed", "label": "Clients owe", "value": inr(totals["owed"]),
                         "note": f"{inr(totals['overdue'])} over 30 days" if _d(totals["overdue"]) else "nothing overdue",
                         "tone": "bad" if _d(totals["overdue"]) else "none"})
    kpis.append({"key": "man_days", "label": "Man-days", "value": totals["man_days"] or "0", "note": "all projects",
                 "tone": "none"})
    kpis.append({"key": "issues", "label": "Open issues", "value": str(totals["open_issues"]),
                 "note": f"{totals['serious_issues']} serious" if totals["serious_issues"] else "none serious",
                 "tone": "bad" if totals["serious_issues"] else "warn" if totals["open_issues"] else "good"})
    return {"headline": {"lead": lead, "facts": facts[:3], "more": facts[3:]}, "kpis": kpis[:5], "totals": totals,
            "need_you": len(need)}


async def _projects(conn: AsyncConnection, auth: AuthorizationContext) -> list[dict[str, Any]]:
    """The projects this person can see (the projects list's own rule), without archived or completed ones."""
    from mesiri.domains.projects.router import list_projects

    out = []
    for p in await list_projects(auth_context=auth, conn=conn):
        label = p["statusLabel"] if isinstance(p, dict) else p.statusLabel
        if label in _LEFT_OUT:
            continue
        out.append({"id": p["id"] if isinstance(p, dict) else p.id, "name": p["name"] if isinstance(p, dict) else p.name})
    return out


async def build(conn: AsyncConnection, auth: AuthorizationContext, *, period: periods.Period,
                enabled: Callable[[str], bool], today: datetime.date) -> dict[str, Any]:
    from mesiri.authorization.roles import may_view_expenses

    rows, reports, unavailable = [], {}, []
    for p in await _projects(conn, auth):
        try:
            async with conn.begin_nested():
                report = await engine.build(conn, auth, project_id=uuid.UUID(str(p["id"])), site_id=None,
                                            period=period, enabled=enabled, today=today, only=ROW_SECTIONS,
                                            with_waiting=False)
        except HTTPException:
            continue  # the person may not open it after all: left out, as on the projects list
        except Exception:  # noqa: BLE001 -- the rest of the brief still shows
            logger.exception("portfolio_report.project_failed project=%s", p["id"])
            unavailable.append(p["name"])
            continue
        rows.append(row_of(report))
        reports[str(p["id"])] = report
    rows.sort(key=lambda r: (-r["attention"], r["name"].lower()))
    sees_money = may_view_expenses(auth.role)
    noun = engine.NOUN[period.kind]
    nxt = periods.following(period)
    return {
        "scope": "portfolio", "audience": "internal", "period": period.as_dict(),
        "previous": periods.previous(period).as_dict(), "next": nxt.as_dict() if nxt.start <= today else None,
        "today": today.isoformat(), "running": period.end >= today,
        "generated_at": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        **summarise(rows, sees_money, noun), "projects": rows, "unavailable": unavailable, "sees_money": sees_money,
        "has_bills": sees_money and any(_d(r.get(k)) for r in rows for k in ("billed", "received", "owed")),
    }
