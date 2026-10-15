"""Daily setup questions for a new company, and branding requests (SS-14).

Pure rules, no I/O. The WhatsApp assistant asks a new company's owner one
setup question a day, right after replying to one of their own messages
(inside WhatsApp's 24-hour window, so no template is needed):

    branding      "send your letterhead / visiting card / logo": the photos
                  go to the Mesiri team, who fill in the letterhead by hand
    report_time   "your report goes out by 9 pm, change it?"
    more_sites    "working on another site too?"

Each is asked once; answered or skipped, it is never asked again. Nothing
is asked after `ASK_WITHIN_DAYS` days from the company's creation.

Stored per company in `organization_settings`:

    setup_progress     {"<question>": {"state": "asked"|"answered"|"skipped",
                                       "on": "YYYY-MM-DD"}, "last_asked_on": ...}
    branding_requests  [BrandingRequest-shaped dicts, newest last]

**Branding requests are the contract with the control panel (SA, Lane B).**
Each holds the object-storage keys of what the owner sent. The team fills
the letterhead in (the existing branding setting and logo upload), then
sets `status` to "done" with `done_at`. The assistant tells the owner on
their next message and sets `owner_notified`.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

BRANDING = "branding"
REPORT_TIME = "report_time"
MORE_SITES = "more_sites"
QUESTIONS: tuple[str, ...] = (BRANDING, REPORT_TIME, MORE_SITES)

ASKED = "asked"
ANSWERED = "answered"
SKIPPED = "skipped"

ASK_WITHIN_DAYS = 30

OPEN = "open"
DONE = "done"

#: Send-deadline choices offered for the report time (HH:MM, local time).
REPORT_TIMES: tuple[str, ...] = ("19:00", "20:00", "21:00")


def _state(progress: dict[str, Any], question: str) -> str | None:
    entry = progress.get(question)
    return entry.get("state") if isinstance(entry, dict) else None


def next_question(progress: object, *, today: dt.date, company_created_on: dt.date) -> str | None:
    """The question to ask today, or None. One a day; a question asked but
    never answered is not asked again; nothing after ASK_WITHIN_DAYS."""
    progress = progress if isinstance(progress, dict) else {}
    if (today - company_created_on).days > ASK_WITHIN_DAYS:
        return None
    if progress.get("last_asked_on") == today.isoformat():
        return None
    for question in QUESTIONS:
        if _state(progress, question) is None:
            return question
    return None


def record(progress: object, question: str, state: str, *, today: dt.date) -> dict[str, Any]:
    """`progress` with `question` set to `state` (asked/answered/skipped)."""
    if question not in QUESTIONS:
        raise ValueError(f"unknown setup question: {question}")
    updated = dict(progress) if isinstance(progress, dict) else {}
    updated[question] = {"state": state, "on": today.isoformat()}
    if state == ASKED:
        updated["last_asked_on"] = today.isoformat()
    return updated


def add_branding_files(
    requests: object,
    *,
    object_key: str,
    content_type: str | None,
    sent_by: str,
    now: dt.datetime,
) -> tuple[list[dict[str, Any]], bool]:
    """`requests` with this file added to the open request (a new one if
    none is open). Returns (requests, started_new_request)."""
    items = [dict(r) for r in requests] if isinstance(requests, list) else []
    open_request = next((r for r in reversed(items) if r.get("status") == OPEN), None)
    started = open_request is None
    if open_request is None:
        open_request = {
            "id": str(uuid.uuid4()),
            "status": OPEN,
            "created_at": now.isoformat(),
            "sent_by_user_id": sent_by,
            "files": [],
            "done_at": None,
            "owner_notified": False,
        }
        items.append(open_request)
    open_request["files"] = [
        *open_request.get("files", []),
        {"object_key": object_key, "content_type": content_type, "received_at": now.isoformat()},
    ]
    return items, started


def request_to_announce(requests: object) -> dict[str, Any] | None:
    """A request the team has finished that the owner hasn't heard about."""
    if not isinstance(requests, list):
        return None
    return next(
        (
            r
            for r in requests
            if isinstance(r, dict) and r.get("status") == DONE and not r.get("owner_notified")
        ),
        None,
    )


def mark_announced(requests: list[dict[str, Any]], request_id: str) -> list[dict[str, Any]]:
    return [{**r, "owner_notified": True} if r.get("id") == request_id else r for r in requests]
