"""WA-141: a link to the right page of the web dashboard, built by the code from a fixed table.

The model names the page and the ids it already has (from the facts or a tool); the code builds
the address, so a link is never invented. The dashboard asks the person to log in as usual and
shows only what their role allows: a link gives no access by itself.
"""

from __future__ import annotations

import os
import re
import uuid
from typing import Any
from urllib.parse import quote

from mesiri_ai.models import ToolSpec

WEB_LINK = "web_link"
#: The dashboard's address (``MESIRI_DASHBOARD_URL`` overrides it, e.g. for staging).
DEFAULT_DASHBOARD_URL = "https://app.whatsapp.mesiri.ai"

#: page -> (path with {placeholders}, what it shows). Paths are the dashboard's own routes
#: (apps/dashboard/src/App.tsx); a page needing an id is listed with it.
PAGES: dict[str, tuple[str, str]] = {
    "today": ("/today", "today across the company's sites"),
    "reports": ("/reports", "the daily reports (DPRs)"),
    "period_reports": ("/reports/period", "the weekly and monthly reports, with what was sent and what goes by itself"),
    "site_day": ("/reports/{date}/sites/{site_id}", "one site's day: work, labour, materials, issues, photos"),
    "project_day": ("/reports/{date}/projects/{project_id}", "one project's day, all its sites"),
    "site_log": ("/site-log", "work done, day by day"),
    "photos": ("/site-log?view=photos", "the site photos"),
    "issues": ("/issues", "open problems on site"),
    "labour": ("/labour", "attendance"),
    "workers": ("/labour?view=workers", "the worker register"),
    "wages": ("/labour/wages", "this week's wages: what each worker and labour team is paid, and what was paid"),
    "advances": ("/labour/advances", "advances given to workers and labour teams, and what is still outstanding"),
    "materials": ("/materials", "stock in and out"),
    "material_requests": ("/materials/requests", "what the sites asked for, before it is ordered"),
    "purchase_orders": ("/procurement/orders", "orders to suppliers: what is still to come, late ones first"),
    "pending_deliveries": ("/procurement/pending", "what is still to come on orders, late first, by date or supplier"),
    "quotations": ("/procurement/quotations", "quotes asked from suppliers, compared side by side"),
    "returns": ("/procurement/returns", "material sent back to suppliers, and the debit notes (what they owe back)"),
    "projects": ("/projects", "all projects"),
    "project": ("/projects/{project_id}", "one project: its sites and members"),
    "team": ("/team", "the company's people and roles"),
    "company": ("/company", "company details, logo, modules"),
    "expenses": ("/finance/expenses", "expenses"),
    "expense_categories": ("/finance/categories", "expense categories"),
    "expense": ("/finance/expenses/{expense_id}", "one expense with its bill photo"),
    "accounts": ("/finance/accounts", "money accounts"),
    "vendors": ("/finance/vendors", "suppliers and what is owed to each"),
    "supplier": ("/finance/vendors/{vendor_id}", "one supplier's account: balance, bills to pay, payments"),
    "work_orders": ("/subcontract/work-orders", "work orders given to subcontractors"),
    "work_order": ("/subcontract/work-orders/{work_order_id}", "one work order: work done, bills, retention"),
    "subcontract_bills": ("/subcontract/bills", "subcontract bills waiting for a check"),
    "analytics": ("/analytics", "charts across sites"),
    "machines": ("/equipment", "machines and vehicles: where each is, today's hours, diesel, hire cost"),
    "machine_log": ("/equipment/log?date={date}", "one day's log of every machine"),
    "schedule": ("/planning/schedule?project={project_id}", "the project's schedule (Gantt)"),
    "places": ("/planning/places?project={project_id}", "progress floor by floor and room by room, with photos"),
    "documents": ("/planning/documents?project={project_id}", "the project's drawings, permits and papers"),
    "material_plan": ("/planning/materials?project={project_id}", "what to order and by when, from the BOQ and schedule"),
    "hire_check": ("/equipment/hire", "hire bills checked against the hours recorded"),
    "receivables": ("/accounts/receivables", "what each client owes, by age, and money received"),
    # CC-11: cost control.
    "cost_today": ("/cost/green-red?project={project_id}", "green / amber / red per BOQ line: labour against the work it earned"),
    "budget_vs_actual": ("/cost/budget?project={project_id}", "budget against actual, and labour to put on BOQ lines"),
}

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def dashboard_url() -> str:
    return (os.environ.get("MESIRI_DASHBOARD_URL") or DEFAULT_DASHBOARD_URL).rstrip("/")


def build_link(arguments: dict[str, Any], *, today: str) -> dict[str, Any]:
    """``{"url": ...}`` for the page, or ``{"error": ...}`` naming what is missing or wrong."""
    page = str(arguments.get("page") or "").strip()
    if page not in PAGES:
        return {"error": f"unknown page {page!r}; one of: {', '.join(PAGES)}"}
    path, _ = PAGES[page]
    values: dict[str, str] = {}
    for name in re.findall(r"{(\w+)}", path):
        raw = str(arguments.get(name) or (today if name == "date" else "")).strip()
        if name == "date":
            if not _DATE.match(raw):
                return {"error": "date must be YYYY-MM-DD"}
        else:
            try:
                raw = str(uuid.UUID(raw))
            except ValueError:
                return {"error": f"missing: {name} (an id from the facts or a tool)"}
        values[name] = quote(raw, safe="")
    return {"url": dashboard_url() + path.format(**values),
            "status": "put this link in your reply as it is, on its own line"}


def spec() -> ToolSpec:
    pages = "; ".join(f"{name}: {what}" for name, (_, what) in PAGES.items())
    return ToolSpec(name=WEB_LINK, description=(
        "A link to a page of the company's web dashboard, when they ask for the link, want to see or change "
        "something there, or the answer is easier to see on the web (a long list, a chart, photos). Pages: "
        f"{pages}. Give the ids the page needs (from the facts or a tool); a day page defaults to today. "
        "Put the returned url in your reply exactly as returned. Never write a dashboard address yourself."),
        parameters={"type": "object", "required": ["page"], "properties": {
            "page": {"type": "string", "enum": list(PAGES)},
            "project_id": {"type": "string"}, "site_id": {"type": "string"},
            "expense_id": {"type": "string"}, "vendor_id": {"type": "string"}, "work_order_id": {"type": "string"},
            "date": {"type": "string", "description": "YYYY-MM-DD"},
        }})
