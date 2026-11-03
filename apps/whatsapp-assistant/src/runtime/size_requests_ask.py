"""WA-168: once a day, the company's admins and project managers are asked for the sizes nobody on site knew
(approved by Alan, 3 Nov 2026).

One message per person per day, listing every open size request of their company: the material and unit, how
many lines wait for it, and any size someone proposed. A proposal gets a button (one tap sets it for the company
and saves the lines that waited; ``agent_api/whatsapp.py`` ``SIZE_PREFIX``); anything else is answered by
replying ("M-sand load 60"), which the assistant prepares like any entry. Queued on the scheduler's tick
(automation_runner.py) and sent by the shared send step: inside the 24-hour window, quiet hours and opt-outs
respected. A request is asked again only a day after it was last asked (``asked_at``).
"""

from __future__ import annotations

import datetime
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)

RULE_KEY = "size_requests_ask"
SIZE_PREFIX = "apiag:size:"  # the same as agent_api.whatsapp.SIZE_PREFIX
ANSWERERS = ("ADMIN", "OWNER", "PROJECT_MANAGER")
REASK_HOURS = 20
MAX_LISTED = 8


def ask_message(requests: list[dict[str, Any]]) -> tuple[str, list[dict[str, str]]]:
    """The day's message and its buttons (a proposed size: one tap; at most 3, WhatsApp's limit)."""
    lines, buttons = [], []
    for i, r in enumerate(requests[:MAX_LISTED], 1):
        waiting = int(r.get("waiting") or 0)
        wait = f" · {waiting} line{'s' if waiting != 1 else ''} waiting" if waiting else ""
        if r.get("proposed_one_unit_equals"):
            who = f" ({r['proposed_by_name']} says)" if r.get("proposed_by_name") else ""
            lines.append(f"{i}. 1 {r['unit_name']} {r['material']} = {r['proposed_one_unit_equals']} "
                         f"{r['stock_unit_name']}?{who}{wait}")
            if len(buttons) < 3:
                buttons.append({"id": f"{SIZE_PREFIX}{r['id']}",
                                "title": f"✅ {i}. {r['proposed_one_unit_equals']} {r['stock_unit']}"[:20]})
        else:
            lines.append(f"{i}. 1 {r['unit_name']} {r['material']} = how many {r['stock_unit_name']}?{wait}")
    more = f"\n…and {len(requests) - MAX_LISTED} more on the dashboard (Materials → Sizes)." if len(requests) > MAX_LISTED else ""
    text = ("📏 Sizes needed for your stock. Set once, they convert every line from now on, and the lines "
            "waiting save by themselves.\n\n" + "\n".join(lines) + more +
            "\n\nReply with the number, like \"M-sand load 60\"" + (", or tap to confirm." if buttons else "."))
    return text, buttons


async def _open_requests(conn: Any) -> dict[uuid.UUID, list[dict[str, Any]]]:
    from sqlalchemy import text

    rows = (await conn.execute(text(
        f"""
        SELECT r.id, r.organization_id, m.name AS material, fu.display_name AS unit_name, su.code AS stock_unit,
               su.display_name AS stock_unit_name, r.proposed_one_unit_equals, pu.full_name AS proposed_by_name,
               jsonb_array_length(r.held_lines) AS waiting
        FROM material_size_requests r
        JOIN materials_catalog m ON m.id = r.material_id
        JOIN units_of_measure fu ON fu.id = r.from_unit_id
        LEFT JOIN units_of_measure su ON su.id = m.default_unit_id
        LEFT JOIN users pu ON pu.id = r.proposed_by
        WHERE r.status = 'open' AND (r.asked_at IS NULL OR r.asked_at < now() - interval '{REASK_HOURS} hours')
        ORDER BY r.created_at
        """))).mappings().all()
    by_org: dict[uuid.UUID, list[dict[str, Any]]] = {}
    for row in rows:
        item = dict(row)
        if item.get("proposed_one_unit_equals") is not None:
            item["proposed_one_unit_equals"] = f"{item['proposed_one_unit_equals'].normalize():f}"
        by_org.setdefault(item["organization_id"], []).append(item)
    return by_org


async def _answerers(conn: Any, organization_id: uuid.UUID) -> list[uuid.UUID]:
    from sqlalchemy import text

    rows = (await conn.execute(text(
        "SELECT id FROM users WHERE organization_id = :org AND upper(role) = ANY(:roles) "
        "AND lower(coalesce(status, 'active')) = 'active'"), {"org": organization_id, "roles": list(ANSWERERS)})).all()
    return [r[0] for r in rows]


async def queue_size_asks(
    conn: Any,
    *,
    today: datetime.date | None = None,
    open_requests: Callable[[Any], Awaitable[dict[uuid.UUID, list[dict[str, Any]]]]] = _open_requests,
    answerers: Callable[[Any, uuid.UUID], Awaitable[list[uuid.UUID]]] = _answerers,
    claim: Callable[..., Awaitable[Any]] | None = None,
    mark_asked: Callable[[Any, list[uuid.UUID]], Awaitable[None]] | None = None,
) -> int:
    """Queue today's ask for each company with open size requests. Returns how many messages were queued."""
    today = today or datetime.datetime.now(datetime.UTC).date()
    if claim is None:
        from mesiri.infrastructure.postgres.repositories.notifications import (
            PostgresNotificationRepository,
        )

        claim = PostgresNotificationRepository(conn).claim
    if mark_asked is None:
        from mesiri.domains.materials.size_requests import mark_asked as _mark

        mark_asked = _mark
    queued = 0
    for organization_id, requests in (await open_requests(conn)).items():
        text, buttons = ask_message(requests)
        for user_id in await answerers(conn, organization_id):
            try:
                if await claim(organization_id=organization_id, rule_key=RULE_KEY, subject_id=str(user_id),
                               occurred_on=today, recipient_user_id=user_id,
                               payload={"message": text, **({"buttons": buttons} if buttons else {})}) is not None:
                    queued += 1
            except Exception:  # noqa: BLE001 -- one person must not stop the others
                logger.exception("size_requests_ask.failed org=%s user=%s", organization_id, user_id)
        await mark_asked(conn, [r["id"] for r in requests])
    return queued
