"""Joining a company with its code (SS-05). Pure rules, no I/O.

A company has one join code, e.g. ``ACME-4821``: up to six letters from its
name and four digits. An admin or project manager gets it on WhatsApp
("join code") with a link that opens a chat with Mesiri, "JOIN ACME-4821"
already typed. Someone not on Mesiri sends it; the company's admins are
asked to approve or reject. **A code alone adds nobody**: a leaked code
can only produce requests an admin has to approve, and "new join code"
replaces it.

Stored per company in `organization_settings`:

    join_code      {"code": "ACME-4821", "created_at": ISO}
    join_requests  [JoinRequest-shaped dicts, newest last]

A request is {"id", "phone" (digits), "name", "requested_at", "status"
("open" | "approved" | "rejected"), "decided_at", "decided_by"}.
"""

from __future__ import annotations

import datetime as dt
import re
import secrets
import uuid
from typing import Any

OPEN = "open"
APPROVED = "approved"
REJECTED = "rejected"

#: Open requests a company can hold at once: a leaked code can't flood the
#: admins' WhatsApp.
MAX_OPEN = 20
#: Wrong codes a number may send in a day before JOIN is refused.
MAX_WRONG_CODES_PER_DAY = 5
#: Requests older than this are kept for the record but no longer open.
OPEN_FOR_DAYS = 7
#: How many decided requests are kept per company.
KEEP_DECIDED = 50

_PREFIX_MAX = 6
_FALLBACK_PREFIX = "TEAM"
_CODE = re.compile(r"^([A-Z]{2,6})-(\d{4})$")
#: "JOIN ACME-4821", "join acme 4821", "Join: ACME-4821".
_JOIN_MESSAGE = re.compile(r"^\s*join\s*[:\-]?\s*([A-Za-z]{2,6})\s*[- ]?\s*(\d{4})\s*$", re.I)


def code_prefix(company_name: str) -> str:
    """Up to six capital letters from the company's first word with letters
    (`Sri Sai Constructions` -> `SRI`, `Acme Builders` -> `ACME`)."""
    for word in str(company_name or "").split():
        letters = "".join(ch for ch in word.upper() if "A" <= ch <= "Z")
        if len(letters) >= 2:
            return letters[:_PREFIX_MAX]
    return _FALLBACK_PREFIX


def new_code(company_name: str) -> str:
    """A fresh code for the company. Random digits (`secrets`), so codes
    can't be predicted from one another."""
    return f"{code_prefix(company_name)}-{secrets.randbelow(10_000):04d}"


def normalize_code(value: object) -> str | None:
    """`acme 4821` / `ACME-4821` -> `ACME-4821`; None if it isn't a code."""
    text = " ".join(str(value or "").split()).upper().replace(" ", "-")
    return text if _CODE.match(text) else None


def code_in_message(text: object) -> str | None:
    """The code in a "JOIN ACME-4821" message, or None if it isn't one."""
    match = _JOIN_MESSAGE.match(str(text or ""))
    return f"{match.group(1).upper()}-{match.group(2)}" if match else None


def join_text(code: str) -> str:
    return f"JOIN {code}"


def _requests(stored: object) -> list[dict[str, Any]]:
    return [dict(r) for r in stored if isinstance(r, dict)] if isinstance(stored, list) else []


def _is_open(request: dict[str, Any], now: dt.datetime) -> bool:
    if request.get("status") != OPEN:
        return False
    try:
        at = dt.datetime.fromisoformat(str(request.get("requested_at")))
    except ValueError:
        return False
    return now - at < dt.timedelta(days=OPEN_FOR_DAYS)


def open_requests(stored: object, *, now: dt.datetime) -> list[dict[str, Any]]:
    return [r for r in _requests(stored) if _is_open(r, now)]


def add_request(
    stored: object, *, phone: str, name: str, now: dt.datetime
) -> tuple[list[dict[str, Any]], dict[str, Any], bool]:
    """(the new list, the request, whether it is new). The same number asking
    again while its request is open gets that request back (no second alert).
    Raises TooManyRequests when the company already has MAX_OPEN open."""
    requests = _requests(stored)
    for request in requests:
        if request.get("phone") == phone and _is_open(request, now):
            return requests, request, False
    if len(open_requests(requests, now=now)) >= MAX_OPEN:
        raise TooManyRequests()
    request = {
        "id": uuid.uuid4().hex[:12],
        "phone": phone,
        "name": name,
        "requested_at": now.isoformat(),
        "status": OPEN,
        "decided_at": None,
        "decided_by": None,
    }
    decided = [r for r in requests if r.get("status") != OPEN][-KEEP_DECIDED:]
    still_open = [r for r in requests if r.get("status") == OPEN]
    return [*decided, *still_open, request], request, True


def decide(
    stored: object, *, request_id: str, approve: bool, by: str, now: dt.datetime
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, bool]:
    """(the new list, the request, whether this call decided it). A request
    already decided (or expired) is returned unchanged with False, so two
    admins tapping at once can't both act on it."""
    requests = _requests(stored)
    for request in requests:
        if request.get("id") != request_id:
            continue
        if not _is_open(request, now):
            return requests, request, False
        request.update(
            status=APPROVED if approve else REJECTED, decided_at=now.isoformat(), decided_by=by
        )
        return requests, request, True
    return requests, None, False


class TooManyRequests(Exception):
    """The company already has MAX_OPEN open requests."""
