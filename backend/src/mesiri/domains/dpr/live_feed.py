"""What each message to Mesiri was, for the company Live (WEB-53).

One table owns the decision: the tools a turn called (the dashboard's own API
routes, ``agent_api/tools.py`` ``ALLOWED``, and classic's tool names) -> the
kind of message the Live screen shows. A new tool is one new entry here. The
write tools only *prepare* an entry; what the turn saved, held for Save or
asked back says how far it got (``state``).

Read-only and pure: the router reads the rows and applies who may see what.
"""

from __future__ import annotations

from typing import Any

#: Tool -> kind. The first write tool in the turn wins; a turn that only
#: looked things up is a question.
WRITE_KINDS: dict[str, str] = {
    "record_attendance": "attendance",
    "record_work": "work",
    "correct_work": "correction",
    "record_receipt": "delivery",
    "record_usage": "usage",
    "record_transfer": "transfer",
    "record_expense": "expense",
    "report_issue": "issue",
    "resolve_issue": "issue_closed",
    "wont_fix_issue": "issue_closed",
    "acknowledge_issue": "issue_closed",
    "undo_receipt": "undo",
    "undo_usage": "undo",
    "undo_transfer": "undo",
    "undo_expense": "undo",
    "create_project": "setup",
    "update_project": "setup",
    "add_site": "setup",
    "update_site": "setup",
    "add_project_member": "setup",
    "add_material": "catalogue",
    "update_material": "catalogue",
    "add_material_alias": "catalogue",
    "set_unit_conversion": "catalogue",
    "add_standard_categories": "catalogue",
    "add_expense_category": "catalogue",
    "answer_size_request": "catalogue",
    "set_reply_language": "language",
    "send_dpr": "report",
    # Classic's one write-like tool (its other entries go through workflows, not traced tools; classic is
    # deleted once every customer is on v3, so they show as plain messages until then).
    "request_dpr": "report",
}

#: A turn that only read: what it was about. Expenses are a question too, and
#: hidden from roles that may not see spending (the router's SEC-01 rule).
EXPENSE_TOOLS: frozenset[str] = frozenset({"list_expenses", "money_accounts", "list_vendors", "query_expenses"})

#: WEB-60: the assistant's mark that the person asked what Mesiri can do (it writes nothing); Live plays the introduction.
INTRO_TOOLS: frozenset[str] = frozenset({"explain_mesiri"})

#: The kinds that carry the company's spending (SEC-01).
MONEY_KINDS: frozenset[str] = frozenset({"expense"})

#: An expense's fields the screen shows (Live's bill moment), as (key on screen, request field).
EXPENSE_FIELDS: tuple[tuple[str, str], ...] = (
    ("amount", "amount"),
    ("vendor", "vendor_text"),
    ("category", "category_text"),
    ("date", "occurred_date"),
    ("tax", "tax_amount"),
    ("what", "description"),
)

#: What every kind is called on screen, so the dashboard and the API agree.
KIND_LABELS: dict[str, str] = {
    "attendance": "Attendance",
    "work": "Work done",
    "correction": "Correction",
    "delivery": "Material in",
    "usage": "Material used",
    "transfer": "Transfer",
    "expense": "Expense",
    "issue": "Issue",
    "issue_closed": "Issue closed",
    "undo": "Taken back",
    "setup": "Setup",
    "catalogue": "Catalogue",
    "language": "Language",
    "report": "Report",
    "question": "Question",
    "intro": "About Mesiri",
    "saved": "Saved",
    "cancelled": "Cancelled",
    "photo": "Photo",
    "chat": "Message",
}


#: What Mesiri did along the way, in plain words, for the screen's "brain" line. A tool not here is left out.
TOOL_WORDS: dict[str, str] = {
    "list_projects": "Looked up the projects",
    "list_sites": "Found the site",
    "day_summary": "Read the day's updates",
    "timeline": "Read who reported what",
    "site_day": "Read the site's report",
    "search_materials": "Found the material",
    "list_units": "Checked the unit",
    "stock_levels": "Checked the stock",
    "stock_check": "Checked the stock",
    "stock_summary": "Worked out the stock",
    "list_receipts": "Read what came in",
    "list_usage": "Read what was used",
    "labour_attendance": "Read the attendance",
    "list_workers": "Looked up the workers",
    "work_progress": "Read the work done",
    "work_item": "Found the work item",
    "list_issues": "Read the open issues",
    "list_expenses": "Read the expenses",
    "expense_categories": "Checked the categories",
    "money_accounts": "Checked the accounts",
    "list_vendors": "Looked up the vendor",
    "material_categories": "Checked the categories",
    "size_requests": "Checked the sizes asked",
    "my_requests": "Read your requests",
    "record_attendance": "Prepared the attendance",
    "record_work": "Prepared the work entry",
    "correct_work": "Prepared the correction",
    "record_receipt": "Prepared the delivery",
    "record_usage": "Prepared the usage",
    "record_transfer": "Prepared the transfer",
    "record_expense": "Prepared the expense",
    "report_issue": "Prepared the issue",
    "resolve_issue": "Prepared closing the issue",
    "send_dpr": "Prepared the report",
}


def _tools(turns: list[dict[str, Any]]) -> list[str]:
    return [t for turn in turns for t in (turn.get("tools") or []) if isinstance(t, str) and t]


def _ok(results: Any) -> list[dict[str, Any]]:
    return [r for r in (results or []) if isinstance(r, dict) and 200 <= int(r.get("status") or 0) < 300]


def classify(row: dict[str, Any]) -> dict[str, Any]:
    """The kind of one message and how far it got.

    ``kind`` is a key of ``KIND_LABELS``. ``state``: ``saved`` (in its module),
    ``draft`` (waiting for ✅ Save), ``asked`` (Mesiri asked something back),
    ``answered`` (a question, answered), ``failed`` (a save refused), or
    ``heard`` (nothing more to show). ``summaries``: the entries it saved or
    holds, in Mesiri's words. ``did``: its lookups and preparations in plain
    words (``TOOL_WORDS``). ``transfer``: a transfer's two site ids, for the
    arc between them. ``expense``: the amount, vendor, category, date, tax
    and words Mesiri read (a bill photo's fields). ``language``: the reply
    language chosen. ``money``: about spending (SEC-01).
    """
    turns = [t for t in (row.get("turns") or []) if isinstance(t, dict)]
    tools = _tools(turns)
    saved = [r for t in turns for r in _ok(t.get("saved"))]
    tapped = [r for t in turns for r in _ok(t.get("save_results"))]
    refused = [
        r for t in turns for key in ("saved", "save_results")
        for r in (t.get(key) or []) if isinstance(r, dict) and r not in _ok(t.get(key))
    ]
    pending = [p for t in turns for p in (t.get("pending") or []) if isinstance(p, str) and p]
    asked = next((t["asked"] for t in turns if isinstance(t.get("asked"), str) and t["asked"]), None)
    cancelled = any(t.get("cancelled") for t in turns)

    write = next((WRITE_KINDS[t] for t in tools if t in WRITE_KINDS), None)
    tapped_tool = next((r.get("tool") for r in tapped if r.get("tool") in WRITE_KINDS), None)
    mtype = str(row.get("type") or "").lower()
    is_photo = "image" in mtype or "photo" in mtype

    if write:
        kind = write
    elif tapped:
        kind = "saved"
    elif cancelled:
        kind = "cancelled"
    elif any(t in INTRO_TOOLS for t in tools):
        kind = "intro"
    elif tools:
        kind = "question"
    elif is_photo:
        kind = "photo"
    else:
        kind = "chat"

    if saved or tapped:
        state = "saved"
    elif refused:
        state = "failed"
    elif pending:
        state = "draft"
    elif asked:
        state = "asked"
    elif kind in ("question", "intro"):
        state = "answered"
    else:
        state = "heard"

    summaries = [str(r.get("summary")) for r in (saved or tapped) if r.get("summary")] or pending
    money = kind in MONEY_KINDS or any(t in EXPENSE_TOOLS for t in tools) or (
        tapped_tool is not None and WRITE_KINDS.get(tapped_tool) in MONEY_KINDS
    )
    did: list[str] = []
    for tool in tools:
        words = TOOL_WORDS.get(tool)
        if words and words not in did:
            did.append(words)
    writes = [w for turn in turns for w in (turn.get("writes") or []) if isinstance(w, dict) and isinstance(w.get("args"), dict)]
    transfer = next(
        (
            {"from_site_id": str(w["args"]["from_site_id"]), "to_site_id": str(w["args"]["to_site_id"])}
            for w in writes
            if w.get("tool") == "record_transfer" and w["args"].get("from_site_id") and w["args"].get("to_site_id")
        ),
        None,
    )
    expense = next(
        (
            {key: (str(w["args"][field]) if w["args"].get(field) not in (None, "") else None) for key, field in EXPENSE_FIELDS}
            for w in writes
            if w.get("tool") == "record_expense" and w["args"].get("amount") not in (None, "")
        ),
        None,
    )
    language = next(
        (str(w["args"]["reply_language"]) for w in writes if w.get("tool") == "set_reply_language" and w["args"].get("reply_language")),
        None,
    )
    return {
        "kind": kind,
        "did": did[:5],
        "transfer": transfer,
        "expense": expense,
        "language": language,
        "label": KIND_LABELS[kind],
        "state": state,
        "summaries": summaries[:6],
        "asked": asked,
        # The kind a ✅ Save tap saved, so the screen can send it to its module.
        "saved_kind": WRITE_KINDS.get(tapped_tool or "") if kind == "saved" else None,
        "money": money,
    }
