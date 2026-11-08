"""[228]: after Save, a link to the dashboard page of each saved record, built by the code from ids already in hand.

One table maps every write tool to a page of ``links.PAGES`` (the dashboard's own routes) or to ``None``
("no page": the record has none, so no link, never a broken one). The ids come from the request that was
saved (body, path) and the API's answer (the created record's id); nothing is fetched, so the reply is no
slower. No token goes in a link: the dashboard asks for its normal login.
"""

from __future__ import annotations

import re
from typing import Any

from agent_api.links import PAGES, build_link
from agent_api.tools import ALLOWED

#: write tool -> page name in ``links.PAGES``, or None = the record has no page of its own.
#: Day pages (site_day) list the day's work, labour, materials and issues, so a receipt, a usage, a transfer,
#: a work update, an issue and an attendance report open the site's day with the record on it.
RECORD_PAGES: dict[str, str | None] = {
    "record_receipt": "site_day",
    "record_usage": "site_day",
    "record_transfer": "site_day",
    "record_work": "site_day",
    "correct_work": None,  # the entry's site and day are not in the request (only its id)
    "report_issue": "site_day",
    "resolve_issue": "issues",
    "acknowledge_issue": "issues",
    "wont_fix_issue": "issues",
    "record_attendance": "site_day",
    "record_expense": "expense",
    "set_site_conditions": "site_day",
    "send_dpr": "reports",
    "add_material": "materials",
    "update_material": "materials",
    "add_material_alias": "materials",
    "set_unit_conversion": "materials",
    "add_standard_categories": "materials",
    "answer_size_request": "materials",
    "ask_for_material": "material_requests",  # PRC-22
    "decide_material_request": "material_requests",
    "delivery_order": None,  # PRC-23: the saved line already says which order (PO-0003); no page of its own yet
    "cancel_material_request": "material_requests",
    "change_material_request": "material_requests",  # PRC-31
    "place_order": "purchase_orders",  # PRC-09
    "change_order": "purchase_orders",
    "cancel_order": "purchase_orders",
    "close_order": "purchase_orders",
    "add_expense_category": "expense_categories",
    "create_project": "project",
    "update_project": "project",
    "add_site": "project",
    "update_site": "project",
    "add_project_member": "project",
    "add_person": "project",  # WEB-71
    # Taking back an entry or a language setting: nothing to open.
    "undo_receipt": None,
    "undo_usage": None,
    "undo_transfer": None,
    "undo_expense": None,
    "add_bill_photo": None,  # WEB-65: the bill goes on an expense already linked when it was saved
    "pay_expense": "expense",  # PRC-35: the expense it paid, its id in the path
    "pay_supplier": "supplier",  # CC-10: the supplier's account, its id in the path
    "set_reply_language": None,
}

#: Where a page's placeholder is read from, in order: the saved request body, then the API's answer.
_BODY_KEYS = {
    "site_id": ("site_id", "from_site_id"),
    "project_id": ("project_id",),
    "date": ("occurred_date", "activity_date", "date", "report_date", "day"),
}
#: A tool whose created record's id (the API's answer) is the placeholder.
_ANSWER_ID = {"record_expense": "expense_id", "create_project": "project_id"}
_PATH_IDS = (("project_id", r"/projects/([^/]+)"), ("site_id", r"/site-days/([^/]+)"),
             ("expense_id", r"/expenses/([0-9a-f-]{36})/payments"),
             ("vendor_id", r"/finance/vendors/([0-9a-f-]{36})"))
#: More distinct links than this become one link to a list.
MAX_LINKS = 3
LIST_PAGE = "today"


def write_tools() -> list[str]:
    return [a.name for a in ALLOWED if a.method != "GET"]


def _arguments(tool: str, page: str, path: str, body: dict[str, Any], answer: Any) -> dict[str, Any]:
    args: dict[str, Any] = {"page": page}
    for name, keys in _BODY_KEYS.items():
        for key in keys:
            if body.get(key):
                args[name] = body[key]
                break
    for name, pattern in _PATH_IDS:
        m = re.search(pattern, path or "")
        if m and not args.get(name):
            args[name] = m.group(1)
    if tool in _ANSWER_ID and isinstance(answer, dict) and answer.get("id"):
        args[_ANSWER_ID[tool]] = str(answer["id"])
    return args


def record_link(tool: str, path: str, body: dict[str, Any], answer: Any, *, today: str) -> str | None:
    """The dashboard address of one saved record, or None (no page, or an id it needs is missing)."""
    page = RECORD_PAGES.get(tool)
    if page is None or page not in PAGES:
        return None
    built = build_link(_arguments(tool, page, path, body or {}, answer), today=today)
    return built.get("url")


def with_links(lines: list[str], urls: list[str | None], *, today: str) -> list[str]:
    """The Saved lines with "🔗 <link>" under each (one for a site and day shared by several lines); more than
    MAX_LINKS distinct links become one link to a list at the end."""
    distinct = list(dict.fromkeys(u for u in urls if u))
    if len(distinct) > MAX_LINKS:
        listing = build_link({"page": LIST_PAGE}, today=today).get("url")
        return lines + ([f"🔗 {listing}"] if listing else [])
    out: list[str] = []
    shown: set[str] = set()
    for line, url in zip(lines, urls, strict=True):
        out.append(line)
        if url and url not in shown:
            shown.add(url)
            out.append(f"🔗 {url}")
    return out
