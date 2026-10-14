"""Assistant review export -- shaping and anonymisation (pure, no I/O).

WA-14 (docs/plans/self-improving-assistant-plan.md): a scheduled Claude Code
session reads every conversation the assistant had, judges it against
docs/product/assistant-review-rubric.md, and reports what to improve. This
module turns the raw rows read by admin/review_router.py into that export.

Anonymisation is the point of this module, not a detail of it -- the export
leaves the server and is read by an outside reviewer:

- Senders and companies become stable keyed hashes (``u_…``/``c_…``), so the
  reviewer can see "the same person asked three times" or "two companies want
  this" without ever seeing a phone number or company id. Keyed with
  MESIRI_REVIEW_HASH_KEY (falling back to the JWT secret) so the hashes cannot
  be reversed by hashing every phone number in a country.
- Phone-like numbers (10+ digits) and email addresses inside message text and
  replies are replaced with placeholders.
- Never included: raw_payload, media keys, stage_payload, provider
  error_message -- anything that can carry content the reviewer does not need.

What it does NOT do: remove people's names written inside free text. There is
no reliable way to find them, so the export must still be treated as customer
data (platform-admin only, never published).
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any

from admin.friction import annotate

# A gap longer than this between two messages from one sender starts a new
# conversation. Site workers reply in bursts; half an hour of silence is a
# new task in practice.
CONVERSATION_GAP = timedelta(minutes=30)

# Longer bodies/replies are cut -- a forwarded batch or a receipt can run to
# thousands of characters, and the reviewer judges handling, not every line.
MAX_TEXT_CHARS = 2000

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
# A run of digits with optional spaces/dashes/dots, optionally +-prefixed;
# masked only when it holds 10+ digits (phones, account numbers). Quantities
# and amounts are shorter and stay readable.
_LONG_NUMBER = re.compile(r"\+?\d[\d\s.-]{8,}\d")


def _hash_key() -> bytes:
    key = os.environ.get("MESIRI_REVIEW_HASH_KEY")
    if not key:
        from mesiri.domains.identity.auth_service import SECRET_KEY

        key = SECRET_KEY
    return key.encode("utf-8")


def pseudonym(prefix: str, value: str | None, key: bytes) -> str | None:
    if not value:
        return None
    digest = hmac.new(key, value.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{prefix}_{digest[:12]}"


def _mask_number(match: re.Match[str]) -> str:
    digits = sum(ch.isdigit() for ch in match.group(0))
    return "[number]" if digits >= 10 else match.group(0)


def scrub(text: str | None) -> str | None:
    if text is None:
        return None
    text = _EMAIL.sub("[email]", text)
    text = _LONG_NUMBER.sub(_mask_number, text)
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS] + " …[cut]"
    return text


def _scrub_value(value: Any) -> Any:
    if isinstance(value, str):
        return scrub(value)
    if isinstance(value, dict):
        return {k: _scrub_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub_value(v) for v in value]
    return value


def summarize_understanding(payload: Any) -> dict[str, Any] | None:
    """What the AI made of a message, reduced to what a replay case needs:
    type, language, translation and the first candidate's fields, scrubbed
    like message text. Everything else in the stage payload stays behind."""
    if not isinstance(payload, dict):
        return None
    candidates = payload.get("candidates") or []
    first = candidates[0] if candidates and isinstance(candidates[0], dict) else {}
    return {
        "semantic_type": payload.get("semantic_type"),
        "detected_language": payload.get("detected_language"),
        "translated_text": scrub(payload.get("translated_text")),
        "fields": _scrub_value(first.get("fields") or {}),
        "missing_fields": first.get("missing_fields") or [],
    }


def _ms_between(start: datetime | None, end: datetime | None) -> int | None:
    if start is None or end is None:
        return None
    return int((end - start).total_seconds() * 1000)


def _percentile(values: list[int], q: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def build_export(
    *,
    messages: list[dict[str, Any]],
    stages: list[dict[str, Any]],
    providers: list[dict[str, Any]],
    since: datetime,
    until: datetime,
    truncated: bool,
    understanding: list[dict[str, Any]] | None = None,
    key: bytes | None = None,
) -> dict[str, Any]:
    """Group messages (oldest first) into anonymised conversations.

    `stages`/`providers` are journey_traces/provider_executions rows for the
    same messages, joined back by correlation_id.
    """
    key = key if key is not None else _hash_key()

    stages_by_cid: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in stages:
        stages_by_cid[row["correlation_id"]].append(
            {
                "stage": row["stage"],
                "ms": row.get("duration_ms"),
                "ok": row.get("succeeded"),
                "error_code": row.get("error_code"),
            }
        )
    calls_by_cid: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in providers:
        calls_by_cid[row["correlation_id"]].append(
            {
                "stage": row.get("stage"),
                "provider": row.get("provider"),
                "operation": row.get("operation"),
                "model": row.get("model"),
                "ms": row.get("latency_ms"),
                "ok": row.get("succeeded"),
                "error_code": row.get("error_code"),
            }
        )

    understood_by_cid = {
        row["correlation_id"]: summary
        for row in understanding or []
        if (summary := summarize_understanding(row.get("stage_payload"))) is not None
    }

    conversations: list[dict[str, Any]] = []
    open_by_user: dict[str, dict[str, Any]] = {}
    last_at_by_user: dict[str, datetime] = {}
    wall_by_type: dict[str, list[int]] = defaultdict(list)
    workflows: Counter[str] = Counter()
    statuses: Counter[str] = Counter()
    companies: set[str] = set()

    for row in messages:
        user = pseudonym("u", row.get("sender_wa_id"), key) or "u_unknown"
        company = pseudonym(
            "c", str(row["organization_id"]) if row.get("organization_id") else None, key
        )
        received_at: datetime = row["received_at"]
        wall_ms = _ms_between(received_at, row.get("processed_at"))
        cid = row["correlation_id"]

        message = {
            "at": received_at.isoformat(),
            "type": row.get("message_type"),
            "text": scrub(row.get("body_text")),
            "reply": scrub(row.get("assistant_reply")),
            "status": row.get("processing_status"),
            "error_code": row.get("error_code"),
            "workflow_key": row.get("workflow_key"),
            "workflow_phase": row.get("workflow_phase"),
            "wall_ms": wall_ms,
            "stages": stages_by_cid.get(cid, []),
            "ai_calls": calls_by_cid.get(cid, []),
            "understanding": understood_by_cid.get(cid),
        }

        conversation = open_by_user.get(user)
        last_at = last_at_by_user.get(user)
        if conversation is None or last_at is None or received_at - last_at > CONVERSATION_GAP:
            conversation = {
                "user": user,
                "company": company,
                "started_at": message["at"],
                "messages": [],
            }
            conversations.append(conversation)
            open_by_user[user] = conversation
        if conversation["company"] is None and company is not None:
            conversation["company"] = company
        conversation["messages"].append(message)
        last_at_by_user[user] = received_at

        if wall_ms is not None:
            wall_by_type[str(row.get("message_type"))].append(wall_ms)
        if row.get("workflow_key"):
            workflows[row["workflow_key"]] += 1
        statuses[str(row.get("processing_status"))] += 1
        if company:
            companies.add(company)

    friction = annotate(conversations)
    return {
        "window": {"since": since.isoformat(), "until": until.isoformat()},
        "truncated": truncated,
        "summary": {
            "messages": len(messages),
            "conversations": len(conversations),
            "users": len({c["user"] for c in conversations}),
            "companies": len(companies),
            "by_status": dict(statuses),
            "by_workflow": dict(workflows.most_common()),
            "wall_ms_by_type": {
                t: {"n": len(v), "p50": _percentile(v, 0.5), "p95": _percentile(v, 0.95)}
                for t, v in sorted(wall_by_type.items())
            },
        },
        "friction": friction,
        "conversations": conversations,
    }
