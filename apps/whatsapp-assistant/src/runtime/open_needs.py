"""Request 171: what is still to get -- the open material requests, the shortages
reported, and the materials at or below zero -- as one answer.

Material requests are not a table of their own: a request is a card the sender sends to
the engineer, and that Send is a notification row whose text starts with
``REQUEST_PREFIX`` (``agent/actions.py``). They are read from those rows, one per
request (the rows of one request share the action id in ``subject_id``), and a request
counts as delivered once a receipt for that material was saved at that site on or after
the day it was asked. Read-only.
"""

from __future__ import annotations

import re
import uuid
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mesiri.infrastructure.postgres.database import PostgresDatabase

#: How a Send of ``request_material`` starts (``actions.material_request_message``).
REQUEST_PREFIX = "📦 Material request"
#: Older than this and a request is no longer "to get".
LOOKBACK_DAYS = 30
#: The receipts that are not a delivery (a count or the starting stock).
_NOT_DELIVERIES = ("ADJUSTMENT_IN", "OPENING_STOCK", "TRANSFER_IN")
_BODY = re.compile(r"^📦 Material request[^\n]*:\n(?P<what>[^\n]+)", re.MULTILINE)


def request_text(message: str) -> str:
    """"50 bags cement (needed tomorrow)" out of the engineer's message."""
    hit = _BODY.search(message or "")
    return hit.group("what").strip() if hit else ""


class OpenNeedsQueryService:
    def __init__(self, db: PostgresDatabase) -> None:
        self._db = db

    async def open_requests(
        self, *, organization_id: str, project_id: str | None, site_id: str | None, today: date
    ) -> list[dict[str, Any]]:
        """The requests asked in the last 30 days that nothing delivered since,
        newest first: ``{"request", "site_id", "asked_on", "sent_to"}``."""
        import sqlalchemy as sa

        where = [
            "organization_id = :org",
            "rule_key LIKE 'engineer_question:%'",
            "payload->>'message' LIKE :prefix",
            "occurred_on >= :since",
        ]
        params: dict[str, Any] = {
            "org": uuid.UUID(organization_id),
            "prefix": f"{REQUEST_PREFIX}%",
            "since": today - timedelta(days=LOOKBACK_DAYS),
        }
        if project_id:
            where.append("project_id = :project")
            params["project"] = uuid.UUID(project_id)
        if site_id:
            where.append("site_id = :site")
            params["site"] = uuid.UUID(site_id)
        async with self._db.transaction() as conn:
            rows = (
                await conn.execute(
                    sa.text(
                        "SELECT split_part(subject_id, ':', 1) AS request_id, site_id, "
                        "MIN(occurred_on) AS asked_on, MIN(payload->>'message') AS message, "
                        "COUNT(*) AS sent_to FROM notifications WHERE "
                        + " AND ".join(where)
                        + " GROUP BY split_part(subject_id, ':', 1), site_id ORDER BY MIN(occurred_on) DESC LIMIT 50"
                    ),
                    params,
                )
            ).mappings().all()
            if not rows:
                return []
            receipts = (
                await conn.execute(
                    sa.text(
                        "SELECT material_name, site_id, occurred_date FROM material_receipts "
                        "WHERE organization_id = :org AND occurred_date >= :since "
                        "AND movement_reason <> ALL(:skip) "
                        "AND reverses_movement_id IS NULL"
                    ),
                    {"org": params["org"], "since": params["since"], "skip": list(_NOT_DELIVERIES)},
                )
            ).mappings().all()
        out = []
        for row in rows:
            what = request_text(str(row["message"] or ""))
            if not what:
                continue
            if _delivered(what, row["site_id"], row["asked_on"], receipts):
                continue
            out.append({"request": what, "site_id": row["site_id"], "asked_on": row["asked_on"], "sent_to": int(row["sent_to"])})
        return out


def _delivered(request: str, site_id: Any, asked_on: date, receipts: Any) -> bool:
    said = request.casefold()
    for receipt in receipts:
        name = str(receipt["material_name"] or "").casefold().strip()
        if not name or name not in said:
            continue
        if site_id is not None and receipt["site_id"] is not None and receipt["site_id"] != site_id:
            continue
        if receipt["occurred_date"] >= asked_on:
            return True
    return False


# -- the answer ------------------------------------------------------------------


def _amount(value: Any) -> str:
    number = float(value)
    return str(int(round(number))) if abs(number - round(number)) < 0.005 else f"{number:.2f}".rstrip("0").rstrip(".")


def needs_reply(
    *, requests: list[dict[str, Any]], shortages: list[dict[str, Any]], levels: list[dict[str, Any]], where: str | None = None
) -> str:
    """The list, in plain English (the model puts it in their language). Each part is
    left out when empty; all empty says there is nothing open."""
    lines: list[str] = []
    if requests:
        lines.append("*To get*")
        lines.extend(f"• {r['request']}" for r in requests)
    out = [lv for lv in levels if float(lv.get("current_stock") or 0) <= 0]
    asked = " ".join(r["request"].casefold() for r in requests)
    # A shortage about a material already listed as out of stock is not said twice.
    listed = [str(lv["material_name"]).casefold() for lv in out]
    reported = [s for s in shortages if not any(name in str(s.get("narrative") or "").casefold() for name in listed)]
    if out:
        if lines:
            lines.append("")
        lines.append("*Out of stock*")
        for lv in out:
            name = str(lv["material_name"]).title()
            stock = float(lv["current_stock"])
            ask = " (asked, not delivered yet)" if str(lv["material_name"]).casefold() in asked else ""
            if stock < 0:
                lines.append(
                    f"• ⚠️ {name} −{_amount(abs(stock))} {lv['unit']}: used more than received, record a delivery?{ask}"
                )
            else:
                lines.append(f"• {name}{ask}")
    if reported:
        if lines:
            lines.append("")
        lines.append("*Shortages reported*")
        for s in reported:
            lines.append(f"• {str(s.get('narrative') or 'material shortage').strip()[:100]}")
    if not lines:
        return "Nothing is open: no material request waiting, no shortage reported, and nothing is out of stock."
    head = f"📋 *What to get{' · ' + where if where else ''}*"
    return head + "\n\n" + "\n".join(lines)
