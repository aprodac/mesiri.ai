"""Sending a period report on WhatsApp (RPT-01, PRC-20): now from the page, or on a schedule (automations).

Each person gets the report **as they are allowed to see it**: it is built with their own access (their projects,
their sites, rupees only when their role sees spending), never the sender's. Then it is frozen (``report_snapshots``:
the figures, the note and the PDF as sent) and queued as one ``notifications`` row, which the assistant's sender
delivers: inside the 24-hour window a short summary and the PDF; outside it the approved template
(``mesiri_period_report``, PRC-13) or, until Meta approves it, skipped with that reason. The backend never talks to
WhatsApp itself.

A person who cannot open the project, has no WhatsApp number, or is not active is skipped with the reason, and the
sender is told: never "sent" for what was not queued.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import re
import uuid
from collections.abc import Callable
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.domains.reports.period import engine, periods, portfolio

logger = logging.getLogger(__name__)

TEMPLATE = "mesiri_period_report"
#: The dashboard's address in a message (``MESIRI_DASHBOARD_URL`` overrides it; the assistant's links use the same).
DEFAULT_DASHBOARD_URL = "https://app.whatsapp.mesiri.ai"
_TITLE = {"week": "Weekly", "month": "Monthly", "custom": "Period"}
_NOTE_MAX = 300


def dashboard_url() -> str:
    return (os.environ.get("MESIRI_DASHBOARD_URL") or DEFAULT_DASHBOARD_URL).rstrip("/")


def page_link(scope: str, period: periods.Period, project_id: Any = None, site_id: Any = None) -> str:
    q = f"period={period.kind}"
    q += f"&from={period.start}&to={period.end}" if period.kind == "custom" else f"&date={period.start}"
    if scope == "project":
        q = f"project={project_id}" + (f"&site={site_id}" if site_id else "") + "&" + q
    return f"{dashboard_url()}/reports/period?{q}"


def _kpi_line(k: dict[str, Any]) -> str:
    note = f" ({k['note']})" if k.get("note") else ""
    return f"• {k['label']}: {k['value']}{note}"


def message_text(report: dict[str, Any], *, where: str, link: str, note: dict | None) -> str:
    """The WhatsApp text that goes with the PDF: what it is, the headline, the key figures, the note, the link. Pure;
    at most 1,000 characters (WhatsApp's caption limit is 1,024)."""
    p = report["period"]
    title = f"*{_TITLE[p['kind']]} report · {where}*"
    when = f"{p['label']}, {p['range']}" if p["kind"] != "custom" else p["range"]
    if report.get("running"):
        when += " (so far)"
    head = " ".join([report["headline"]["lead"], *report["headline"]["facts"]])
    lines = [title, when, "", head, ""] + [_kpi_line(k) for k in report["kpis"][:5]]
    if note and note.get("text"):
        lines += ["", f"Note from {note.get('by') or 'the office'}: {note['text']}"]
    lines += ["", f"Full report: {link}"]
    out = "\n".join(lines)
    if len(out) > 1000:
        out = "\n".join([title, when, "", head[:600], "", f"Full report: {link}"])
    return out[:1000]


def template_params(report: dict[str, Any], where: str) -> list[str]:
    """The template's three body parameters: the kind, the project and period, one line of what matters."""
    p = report["period"]
    when = f"{p['label']} ({p['range']})" if p["kind"] != "custom" else p["range"]
    line = report["headline"]["lead"] + (" " + report["headline"]["facts"][0] if report["headline"]["facts"] else "")
    return [_TITLE[p["kind"]], f"{where}, {when}", line[:180]]


def file_name(where: str, period: periods.Period) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", where).strip("-")[:40] or "report"
    when = {"week": f"week-{period.start.isocalendar()[1]}", "month": f"{period.start:%Y-%m}"}.get(
        period.kind, f"{period.start}-{period.end}")
    return f"{slug}-{when}.pdf"


async def _people(conn: AsyncConnection, org: uuid.UUID, ids: list[uuid.UUID]) -> dict[str, dict[str, Any]]:
    rows = (await conn.execute(text(
        "SELECT id, full_name, role, status, whatsapp_number FROM users WHERE organization_id = :org AND id = ANY(:ids)"),
        {"org": org, "ids": ids})).mappings().all()
    return {str(r["id"]): dict(r) for r in rows}


async def deliver(conn: AsyncConnection, storage: Any, *, org: uuid.UUID, scope: str, period: periods.Period,
                  recipient_ids: list[uuid.UUID], enabled: Callable[[str], bool], today: datetime.date,
                  project_id: uuid.UUID | None = None, site_id: uuid.UUID | None = None,
                  note: str | None = None, sent_by: uuid.UUID | None = None, sent_by_name: str | None = None,
                  trigger: str = "now", automation_id: uuid.UUID | None = None) -> dict[str, Any]:
    """Build, freeze and queue the report for each person. Returns the send id and, per person, queued or skipped
    with the reason."""
    from mesiri.application.organizations.branding_admin import branding_view
    from mesiri.authorization.service import AuthorizationService
    from mesiri.domains.reports.period.pdf import photo_bytes, render, render_portfolio
    from mesiri.infrastructure.postgres.repositories.notifications import (
        PostgresNotificationRepository,
    )

    if scope not in ("project", "portfolio") or (scope == "project" and project_id is None):
        raise ValueError("A report is for one project, or for all projects.")
    send_id = uuid.uuid4()
    clean_note = (note or "").strip()[:_NOTE_MAX] or None
    note_obj = {"text": clean_note, "by": sent_by_name} if clean_note else None
    company = await branding_view(conn, storage, org) or {}
    people = await _people(conn, org, list(dict.fromkeys(recipient_ids)))
    notifications = PostgresNotificationRepository(conn)
    rule_key = f"automation:{automation_id}" if trigger == "schedule" and automation_id else f"period_report:{send_id}"
    results = []
    for rid in dict.fromkeys(recipient_ids):
        person = people.get(str(rid))
        name = (person or {}).get("full_name") or "Someone"
        if person is None:
            results.append({"user_id": str(rid), "name": name, "status": "skipped", "reason": "not in this company"})
            continue
        if (person.get("status") or "active") != "active":
            results.append({"user_id": str(rid), "name": name, "status": "skipped", "reason": "not active"})
            continue
        if not person.get("whatsapp_number"):
            results.append({"user_id": str(rid), "name": name, "status": "skipped", "reason": "no WhatsApp number"})
            continue
        try:
            async with conn.begin_nested():
                auth = await AuthorizationService(conn).resolve_from_jwt(rid, org, str(person.get("role") or ""))
                if scope == "project":
                    report = await engine.build(conn, auth, project_id=project_id, site_id=site_id, period=period,
                                                enabled=enabled, storage=storage, today=today)
                    where = report["project"]["name"] + (f" · {report['site']['name']}" if report.get("site") else "")
                    pdf = render(report, company, await photo_bytes(storage, report["sections"].get("photos")),
                                 note_obj)
                    frozen = engine.public(report)
                else:
                    report = await portfolio.build(conn, auth, period=period, enabled=enabled, today=today)
                    if not report["projects"]:
                        results.append({"user_id": str(rid), "name": name, "status": "skipped",
                                        "reason": "no running project they can see"})
                        continue
                    where = "All projects"
                    pdf = render_portfolio(report, company, note_obj)
                    frozen = report
                snapshot_id = uuid.uuid4()
                key = f"{org}/reports/{snapshot_id}.pdf"
                await storage.put_object(key, pdf, content_type="application/pdf")
                link = page_link(scope, period, project_id, site_id)
                payload = {"message": message_text(report, where=where, link=link, note=note_obj),
                           "document_object_key": key, "document_filename": file_name(where, period),
                           "document_shows": f"{_TITLE[period.kind]} report PDF",
                           "template": {"name": TEMPLATE, "body_params": template_params(report, where)},
                           "snapshot_id": str(snapshot_id)}
                notification_id = await notifications.claim(
                    organization_id=org, rule_key=rule_key, subject_id=str(rid), occurred_on=today,
                    recipient_user_id=rid, project_id=project_id, site_id=site_id, payload=payload)
                if notification_id is None:  # this schedule already reached them today: no second copy
                    results.append({"user_id": str(rid), "name": name, "status": "skipped",
                                    "reason": "already sent to them today"})
                    continue
                await conn.execute(text(
                    "INSERT INTO report_snapshots (id, organization_id, send_id, scope, project_id, site_id, period_kind, "
                    "date_from, date_to, recipient_user_id, sent_by, trigger, automation_id, note, report, "
                    "pdf_object_key, notification_id) VALUES (:id, :org, :send, :scope, :p, :s, :kind, :f, :t, :r, :by, "
                    ":trigger, :auto, :note, CAST(:report AS jsonb), :key, :n)"),
                    {"id": snapshot_id, "org": org, "send": send_id, "scope": scope, "p": project_id, "s": site_id,
                     "kind": period.kind, "f": period.start, "t": period.end, "r": rid, "by": sent_by,
                     "trigger": trigger, "auto": automation_id, "note": clean_note,
                     "report": json.dumps(frozen, default=str), "key": key, "n": notification_id})
        except HTTPException as exc:
            reason = "cannot open this project" if exc.status_code in (403, 404) else "could not be prepared"
            results.append({"user_id": str(rid), "name": name, "status": "skipped", "reason": reason})
            continue
        except Exception:  # noqa: BLE001 -- the others still get theirs; this one is said
            logger.exception("period_report.send_failed recipient=%s", rid)
            results.append({"user_id": str(rid), "name": name, "status": "skipped", "reason": "could not be prepared"})
            continue
        results.append({"user_id": str(rid), "name": name, "status": "queued", "snapshot_id": str(snapshot_id),
                        "sees_money": bool(report.get("sees_money"))})
    return {"send_id": str(send_id), "queued": sum(1 for r in results if r["status"] == "queued"),
            "skipped": sum(1 for r in results if r["status"] == "skipped"), "people": results,
            "period": period.as_dict(), "scope": scope}


# -- reading sent copies -----------------------------------------------------------------------------------------------

#: What a notification's status means to the person who sent the report.
DELIVERY_WORD = {"pending": "Waiting to go", "sent": "Delivered to WhatsApp", "skipped": "Not sent"}
_REASON_WORD = {
    "no_opt_in": "they have not agreed to messages from Mesiri yet",
    "opted_out": "they turned these messages off",
    "no_resolvable_recipient": "no WhatsApp number",
    "send_failed": "WhatsApp did not take it; send it again",
}
_TEMPLATE_WAIT = "they have not messaged Mesiri in 24 hours; it goes once the WhatsApp template is approved"


def reason_words(reason: str | None) -> str | None:
    if not reason:
        return None
    if reason.startswith(("template_not_approved", "outside_whatsapp_session_window", "unknown_template")):
        return _TEMPLATE_WAIT
    return _REASON_WORD.get(reason, reason.replace("_", " "))


async def list_sent(conn: AsyncConnection, org: uuid.UUID, *, project_id: uuid.UUID | None, scope: str,
                    sent_by: uuid.UUID | None, limit: int = 30) -> list[dict[str, Any]]:
    """Sends, newest first, each with who it went to and whether WhatsApp got it. ``sent_by`` limits it to one
    person's own sends (for those who do not manage the project)."""
    where = "{a}.organization_id = :org AND {a}.scope = :scope"
    params: dict[str, Any] = {"org": org, "scope": scope, "n": limit}
    if project_id is not None:
        where += " AND {a}.project_id = :p"
        params["p"] = project_id
    if sent_by is not None:
        where += " AND ({a}.sent_by = :by OR {a}.recipient_user_id = :by)"
        params["by"] = sent_by
    rows = (await conn.execute(text(f"""
        SELECT rs.id, rs.send_id, rs.period_kind, rs.date_from, rs.date_to, rs.trigger, rs.note, rs.created_at,
               rs.recipient_user_id, u.full_name AS recipient, s.full_name AS sent_by_name,
               n.status AS delivery, n.skip_reason, n.sent_at
          FROM report_snapshots rs
          LEFT JOIN users u ON u.id = rs.recipient_user_id
          LEFT JOIN users s ON s.id = rs.sent_by
          LEFT JOIN notifications n ON n.id = rs.notification_id
         WHERE {where.format(a="rs")}
           AND rs.send_id IN (SELECT x.send_id FROM report_snapshots x WHERE {where.format(a="x")}
                              GROUP BY x.send_id ORDER BY max(x.created_at) DESC LIMIT :n)
         ORDER BY rs.created_at DESC, u.full_name"""), params)).mappings().all()  # noqa: S608 (SQL from code)
    sends: dict[str, dict[str, Any]] = {}
    for r in rows:
        s = sends.setdefault(str(r["send_id"]), {
            "send_id": str(r["send_id"]), "period": periods.Period(r["period_kind"], r["date_from"], r["date_to"])
            .as_dict(), "trigger": r["trigger"], "note": r["note"], "sent_by": r["sent_by_name"],
            "created_at": r["created_at"].isoformat(), "people": []})
        s["people"].append({"snapshot_id": str(r["id"]), "name": r["recipient"] or "Someone",
                            "delivery": r["delivery"] or "pending",
                            "word": DELIVERY_WORD.get(r["delivery"] or "pending", r["delivery"]),
                            "reason": reason_words(r["skip_reason"]),
                            "sent_at": r["sent_at"].isoformat() if r["sent_at"] else None})
    return list(sends.values())


async def snapshot(conn: AsyncConnection, org: uuid.UUID, snapshot_id: uuid.UUID) -> dict[str, Any] | None:
    row = (await conn.execute(text(
        "SELECT id, send_id, scope, project_id, site_id, period_kind, date_from, date_to, recipient_user_id, sent_by, "
        "trigger, note, report, pdf_object_key, created_at FROM report_snapshots WHERE organization_id = :org AND id = :id"),
        {"org": org, "id": snapshot_id})).mappings().first()
    return dict(row) if row else None


def changed_since(sent: dict[str, Any], now: dict[str, Any]) -> list[dict[str, str]]:
    """The key figures that moved since the copy was sent (a late attendance, an expense entered after). Pure."""
    before = {k["key"]: k for k in sent.get("kpis") or []}
    out = []
    for k in now.get("kpis") or []:
        b = before.get(k["key"])
        if b and b["value"] != k["value"]:
            out.append({"label": k["label"], "sent": b["value"], "now": k["value"]})
    return out


# -- on a schedule (automations, PRC-20) ------------------------------------------------------------------------------

async def run_scheduled(conn: AsyncConnection, storage: Any, automation: dict[str, Any],
                        recipient_ids: list[str]) -> dict[str, Any]:
    """A due ``SEND_PERIOD_REPORT`` automation: the week just finished (WEEKLY) or last month (MONTHLY), for its
    project, or every project (the owner's brief) when it has none. Called by the assistant's automation runner, which
    resolved the audience; each person still gets the report as their own access shows."""
    from mesiri.application.dpr.project_day import company_today
    from mesiri.domains.organizations import settings as org_settings
    from mesiri.infrastructure.postgres.repositories.organization_settings import (
        PostgresOrganizationSettingsRepository,
    )

    org = uuid.UUID(str(automation["organization_id"]))
    today = await company_today(conn, org)
    kind = "month" if automation.get("frequency") == "MONTHLY" else "week"
    period = periods.resolve(kind, today)
    stored = await PostgresOrganizationSettingsRepository(conn).get(org, org_settings.ENABLED_MODULES)
    if stored is None:
        stored = org_settings.default_for(org_settings.ENABLED_MODULES)
    project_id = automation.get("project_id")
    site_id = automation.get("site_id")
    creator = automation.get("created_by")
    creator_name = None
    if creator:
        creator_name = (await conn.execute(text("SELECT full_name FROM users WHERE id = :id"),
                                           {"id": creator})).scalar()
    return await deliver(
        conn, storage, org=org, scope="project" if project_id else "portfolio", period=period,
        recipient_ids=[uuid.UUID(str(r)) for r in recipient_ids],
        enabled=lambda m: org_settings.module_enabled(m, stored), today=today,
        project_id=uuid.UUID(str(project_id)) if project_id else None,
        site_id=uuid.UUID(str(site_id)) if site_id else None, note=automation.get("message"),
        sent_by=uuid.UUID(str(creator)) if creator else None, sent_by_name=creator_name, trigger="schedule",
        automation_id=uuid.UUID(str(automation["id"])))
