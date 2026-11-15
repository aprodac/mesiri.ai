"""DOC-05: "send me the latest S-101" -- the file itself in the chat.

The model finds the document with ``find_documents`` (an API route; current revisions only, only what this person
may see) and calls ``send_document`` with its id. The code fetches the file through the same API (the role check
is the API's) and sends it; it never sends a revision that is out of date, and says plainly when it could not send.
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from mesiri_ai.models import ToolSpec

from .client import ApiClient

_log = logging.getLogger(__name__)

SEND_DOCUMENT = "send_document"
TOOL = ToolSpec(name=SEND_DOCUMENT, description=(
    "Send one project document (a drawing, permit, report) as a file in this chat: document_id from "
    "find_documents. Only after find_documents gave it; never for a document they did not ask for."),
    parameters={"type": "object", "required": ["document_id"],
                "properties": {"document_id": {"type": "string"}}})


async def send(client: ApiClient, send_document: Callable[..., Awaitable[Any]], wa_id: str,
               arguments: dict[str, Any]) -> dict[str, Any]:
    raw = str(arguments.get("document_id") or "").strip()
    try:
        doc_id = uuid.UUID(raw)
    except ValueError:
        return {"status": "not sent: that is not a document id from find_documents"}
    status, data, headers = await client.fetch_bytes(f"/documents/{doc_id}/file")
    if status == 404:
        return {"status": "not sent: no such document for this person (or they may not see it)"}
    if status != 200 or not data:
        return {"status": "not sent; tell them to ask again in a minute"}
    lower = {k.lower(): v for k, v in headers.items()}
    if lower.get("x-document-status") != "current":
        # Plan risk 1: sending a superseded drawing is worse than sending none.
        return {"status": "not sent: that revision is out of date. Call find_documents again for the current one."}
    name = _file_name(lower.get("content-disposition"), raw)
    shown = " ".join(x for x in (lower.get("x-document-number"), lower.get("x-document-title")) if x) or name
    revision = lower.get("x-document-revision") or ""
    caption = f"{shown}{' rev ' + revision if revision else ''}"
    try:
        sent = await send_document(wa_id, data, filename=name, caption=caption,
                                   mime_type=lower.get("content-type", "application/pdf").split(";")[0],
                                   shows=f"document {caption}")
    except Exception:  # noqa: BLE001 -- the model tells them it did not go
        _log.exception("agent_api.send_document_failed")
        sent = False
    if not sent:
        return {"status": "not sent; tell them to ask again in a minute"}
    return {"status": "sent to their WhatsApp", "sent": caption, "current": True}


def _file_name(disposition: str | None, fallback: str) -> str:
    if disposition and 'filename="' in disposition:
        return disposition.split('filename="', 1)[1].split('"', 1)[0] or fallback
    return f"{fallback}.pdf"


# -- PRC-20: "send me last week's report" -- the report PDF itself, in this chat ------------------------------------

SEND_REPORT = "send_report"
REPORT_TOOL = ToolSpec(name=SEND_REPORT, description=(
    "Send the weekly or monthly report as a PDF in this chat, to the person asking: scope project (project_id; "
    "site_id for one site) or portfolio (all their projects); period week or month. window: \"recent\" (the "
    "default) is the last 7 days or the last 30 ending today, for \"a week's report\", \"1 month report\", "
    "\"orazhchathe report\"; \"named\" only when they named WHICH week or month (\"last week\", \"this week\", "
    "\"October\", \"last month\"), with date = any day in it. Only when they ask for the report itself."),
    parameters={"type": "object", "required": ["scope", "period"], "properties": {
        "scope": {"type": "string", "enum": ["project", "portfolio"]},
        "project_id": {"type": "string"}, "site_id": {"type": "string"},
        "period": {"type": "string", "enum": ["week", "month"]},
        "window": {"type": "string", "enum": ["recent", "named"]},
        "date": {"type": "string", "description": "YYYY-MM-DD, any day of the week or month they named"}}})


#: [302]: the reads and the send whose "week" is the last 7 days when no week is named.
#: [302]: a week or a month nobody named is this many days ending today.
ROLLING_DAYS = {"week": 7, "month": 30}
ROLLING_WEEK_TOOLS = frozenset({"period_report", "portfolio_report", SEND_REPORT, "send_report_to"})


def report_words(body: dict[str, Any], today: dt.date | None = None) -> tuple[str, str]:
    """The card's words for a report to send or schedule: ("Weekly report", "9 – 15 Nov 2026"), ("Monthly report",
    "October 2026"), or ("Monthly report", "last month") when the API picks it. Live, 15 Nov: the card said only
    "Send report"."""
    from mesiri.domains.reports.period import periods

    kind = str(body.get("period") or body.get("frequency") or "week").lower()
    try:
        start = dt.date.fromisoformat(str(body.get("date_from") or "")[:10])
        end = dt.date.fromisoformat(str(body.get("date_to") or "")[:10])
    except ValueError:
        start = end = None
    if start and end:
        days = (end - start).days + 1
        word = "Weekly" if days == 7 else "Monthly" if 28 <= days <= 31 or kind == "month" else "Period"
        return f"{word} report", periods.range_text(start, end)
    try:
        day = dt.date.fromisoformat(str(body.get("date") or "")[:10])
    except ValueError:
        day = None
    if kind in ("month", "monthly"):
        return "Monthly report", periods.month_of(day).label if day else "last month"
    if day:
        return "Weekly report", periods.week_of(day).range_text
    return "Weekly report", "every week" if body.get("frequency") else "last 7 days"


def rolling_week(arguments: dict[str, Any], today: dt.date) -> dict[str, Any]:
    """[302] (15 Nov, Ilan: "orazhchathe mottham progress report" on a Sunday got 2-8 Nov, the week before last): a
    week nobody named is the last 7 days ending today, never the API's "last finished week" (the Monday report's
    default, which the dashboard and the schedules keep). A named week (``date``) or dates stay as they are."""
    period = str(arguments.get("period") or "week")
    if period not in ROLLING_DAYS or any(arguments.get(k) for k in ("date", "date_from", "date_to")):
        return arguments
    # Live, 15 Nov 16:28: "1 month progress report ayakk" got October; a month nobody named is the last 30 days,
    # as a week is the last 7 ("last month" / "October" pass a date and keep the calendar month).
    return {**arguments, "period": "custom",
            "date_from": (today - dt.timedelta(days=ROLLING_DAYS[period] - 1)).isoformat(), "date_to": today.isoformat()}


def report_caption(arguments: dict[str, Any]) -> str:
    """[303]: what the PDF covers, under the file in the chat ("Weekly report · 9 – 15 Nov 2026"); "" when the API
    chose the dates (a named week or month: the file name carries them)."""
    from mesiri.domains.reports.period.periods import range_text

    try:
        start = dt.date.fromisoformat(str(arguments.get("date_from") or "")[:10])
        end = dt.date.fromisoformat(str(arguments.get("date_to") or "")[:10])
    except ValueError:
        return ""
    days = (end - start).days + 1
    word = "Weekly report" if days == 7 else "Monthly report" if 28 <= days <= 31 else "Report"
    return f"{word} · {range_text(start, end)}"


def report_path(arguments: dict[str, Any]) -> str | None:
    """The PDF route for the report asked for, as the person (the API's own access rules); None when it cannot be."""
    from urllib.parse import urlencode

    scope = arguments.get("scope")
    params: dict[str, str] = {"period": str(arguments.get("period") or "week")}
    if params["period"] not in ("week", "month", "custom"):
        return None
    for key in ("date", "date_from", "date_to"):
        if arguments.get(key):
            params[key] = str(arguments[key])[:10]
    if scope == "portfolio":
        return f"/reports/portfolio/pdf?{urlencode(params)}"
    if scope != "project":
        return None
    for key in ("project_id", "site_id"):
        raw = str(arguments.get(key) or "").strip()
        if not raw:
            continue
        try:
            params[key] = str(uuid.UUID(raw))
        except ValueError:
            return None
    if "project_id" not in params:
        return None
    return f"/reports/period/pdf?{urlencode(params)}"


async def send_report(client: ApiClient, send_document: Callable[..., Awaitable[Any]], wa_id: str,
                      arguments: dict[str, Any], today: dt.date | None = None) -> dict[str, Any]:
    if today is not None:
        if str(arguments.get("window") or "recent") != "named" and arguments.get("period") in ROLLING_DAYS:
            # Live, 15 Nov 16:37: "1 month progress report ayakk" came with date 2026-10-15 (the model's "a month ago")
            # and October went. Unless they named which week or month, the report is the recent one: the code's dates.
            arguments = {k: v for k, v in arguments.items() if k not in ("date", "date_from", "date_to")}
        arguments = rolling_week(arguments, today)
    path = report_path(arguments)
    if path is None:
        return {"status": "not sent: say which project (project_id from list_projects), or all projects"}
    status, data, headers = await client.fetch_bytes(path)
    if status in (403, 404):
        return {"status": "not sent: this person cannot open that project's report"}
    if status == 422:
        return {"status": "not sent: that period is not possible (not started yet, or more than 92 days)"}
    if status != 200 or not data:
        return {"status": "not sent; tell them to ask again in a minute"}
    name = _file_name({k.lower(): v for k, v in headers.items()}.get("content-disposition"), "report")
    try:
        sent = await send_document(wa_id, data, filename=name, caption=report_caption(arguments),
                                   mime_type="application/pdf",
                                   shows=f"period report {name}")
    except Exception:  # noqa: BLE001 -- the model tells them it did not go
        _log.exception("agent_api.send_report_failed")
        sent = False
    if not sent:
        return {"status": "not sent; tell them to ask again in a minute"}
    return {"status": "sent to their WhatsApp", "sent": name}


# -- WA-311: "innathe report pdf ayakk" -- the day's DPR, as the person sees it, in this chat -------------------------

SEND_DAY_REPORT = "send_day_report"
DAY_REPORT_TOOL = ToolSpec(name=SEND_DAY_REPORT, description=(
    "Send the DAILY report (DPR) of a day as a PDF in this chat, to the person asking: \"innathe report\", \"today's "
    "report pdf\", \"DPR ayakk\", \"yesterday's report\". project_id, and site_id when they named one site (none: "
    "each site of the project that has anything that day). date YYYY-MM-DD, default today. Not for a week or a "
    "month (send_report), and not for sending the DPR to the client or others (send_dpr)."),
    parameters={"type": "object", "required": ["project_id"], "properties": {
        "project_id": {"type": "string"}, "site_id": {"type": "string"},
        "date": {"type": "string", "description": "YYYY-MM-DD; default today"}}})
#: At most this many site PDFs for one ask.
DAY_REPORT_MAX_SITES = 4
#: What a site's document says when the day has nothing on it.
_NOTHING = ("No activities logged", "No attendance recorded", "No material movements recorded")


def _uuid_or_none(value: Any) -> str | None:
    try:
        return str(uuid.UUID(str(value or "").strip()))
    except ValueError:
        return None


def day_file(project: str, site: str, day: dt.date) -> str:
    import re

    words = f"Daily report {project} {site if site and site != project else ''} {day.day} {day:%b %Y}"
    return (re.sub(r"[^A-Za-z0-9]+", "-", words).strip("-")[:90] or "Daily-report") + ".pdf"


async def send_day_report(client: ApiClient, send_document: Callable[..., Awaitable[Any]],
                          render_pdf: Callable[[str], Awaitable[bytes]], wa_id: str, ctx: Any, today: dt.date,
                          arguments: dict[str, Any]) -> dict[str, Any]:
    """The day's DPR document of each site (the dashboard's own page, read as the person), printed to PDF and sent."""
    project_id = _uuid_or_none(arguments.get("project_id"))
    if project_id is None:
        return {"status": "not sent: say which project (project_id from the facts)"}
    try:
        day = dt.date.fromisoformat(str(arguments.get("date") or "")[:10]) if arguments.get("date") else today
    except ValueError:
        day = today
    if day > today:
        return {"status": "not sent: that day has not come yet"}
    projects = {str(p.id): str(p.name) for p in getattr(ctx, "projects", None) or []}
    sites = [(str(s.id), str(s.name)) for s in getattr(ctx, "sites", None) or [] if str(s.project_id) == project_id]
    named = _uuid_or_none(arguments.get("site_id"))
    if named:
        sites = [s for s in sites if s[0] == named] or [(named, "")]
    if not sites:
        return {"status": "not sent: this project has no site to report on"}
    sent: list[str] = []
    empty: list[str] = []
    for site_id, site_name in sites[:DAY_REPORT_MAX_SITES]:
        status, data, _ = await client.fetch_bytes(f"/dpr/site-days/{site_id}/document?date={day.isoformat()}")
        if status in (403, 404):
            continue
        if status != 200 or not data:
            return {"status": "not sent; tell them to ask again in a minute"}
        html = data.decode("utf-8", errors="replace")
        if not named and all(n in html for n in _NOTHING):
            empty.append(site_name)
            continue
        try:
            pdf = await render_pdf(html)
            went = await send_document(wa_id, pdf, filename=day_file(projects.get(project_id, ""), site_name, day),
                                       caption=f"Daily report · {site_name or projects.get(project_id, '')} · "
                                               f"{day:%a} {day.day} {day:%b}",
                                       mime_type="application/pdf", shows=f"Daily report PDF {site_name}")
        except Exception:  # noqa: BLE001 -- the model says it did not go
            _log.exception("agent_api.send_day_report_failed site=%s", site_id)
            went = False
        if went:
            sent.append(site_name or "the site")
    if not sent:
        return {"status": "nothing sent: nothing is recorded there for that day" if empty or not named
                else "not sent; tell them to ask again in a minute"}
    out = {"status": f"sent {len(sent)} daily report PDF(s) to their WhatsApp: {', '.join(sent)}",
           "note": "Reply in one short line that it went (the day and the site). Never the report in words."}
    if empty:
        out["nothing_recorded_at"] = ", ".join(empty)
    return out

