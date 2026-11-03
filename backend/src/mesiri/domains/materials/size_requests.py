"""WA-168: size requests -- a size nobody on site knew, asked of the company's admin (approved by Alan, 3 Nov 2026).

A line in a unit its material is not counted in, with no size known ("1 load M-sand", M-sand in bags), is held
here instead of being refused: everything else saves, an admin or project manager is asked, and when they answer
the size is set for the whole company and the held lines save, converted, as the people who reported them. A site
engineer's own size comes here as a proposal the admin confirms with one tap. One open request per material and
unit; the table is ``material_size_requests`` (migration 0500). Storage only; the routes are in ``router.py``.
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

#: The lines that can wait for a size (what the person reported), and the routes that save them.
HELD_PATHS = frozenset({"/materials/inflows", "/materials/outflows"})

_COLUMNS = """
    r.id, r.material_id, m.name AS material, r.from_unit_id, fu.code AS unit, fu.display_name AS unit_name,
    su.code AS stock_unit, su.display_name AS stock_unit_name, r.proposed_one_unit_equals, r.proposed_by,
    pu.full_name AS proposed_by_name, r.requested_by, ru.full_name AS requested_by_name, r.held_lines, r.status,
    r.one_unit_equals, r.answered_by, r.answered_at, r.outcome, r.asked_at, r.created_at
"""
_FROM = """
    FROM material_size_requests r
    JOIN materials_catalog m ON m.id = r.material_id
    JOIN units_of_measure fu ON fu.id = r.from_unit_id
    LEFT JOIN units_of_measure su ON su.id = m.default_unit_id
    LEFT JOIN users pu ON pu.id = r.proposed_by
    LEFT JOIN users ru ON ru.id = r.requested_by
"""


def held_line(path: str, body: dict[str, Any], summary: str, key: str | None, user_id: uuid.UUID, role: str) -> dict:
    """A line as it waits: what it saves through, its body as reported, its words, and who reported it."""
    if path not in HELD_PATHS:
        raise ValueError(f"only a receipt or a use can wait for a size, not {path}")
    return {"path": path, "body": body, "summary": summary[:300], "idempotency_key": key,
            "user_id": str(user_id), "role": role}


def _row(row: Any) -> dict[str, Any]:
    out = dict(row._mapping)
    for k in ("proposed_one_unit_equals", "one_unit_equals"):
        if out.get(k) is not None:
            out[k] = f"{Decimal(out[k]).normalize():f}"
    out["held_lines"] = out.get("held_lines") or []
    out["waiting"] = len(out["held_lines"])
    return out


async def open_request(conn: AsyncConnection, organization_id: uuid.UUID, material_id: uuid.UUID,
                       from_unit_id: uuid.UUID, user_id: uuid.UUID, *, proposed: Decimal | None = None,
                       line: dict | None = None) -> dict[str, Any]:
    """The open request for this material and unit, made or added to: a held line appended, a proposal kept
    (the latest one wins)."""
    row = (await conn.execute(text(
        """
        INSERT INTO material_size_requests (organization_id, material_id, from_unit_id, requested_by,
                                            proposed_one_unit_equals, proposed_by, held_lines)
        VALUES (:org, :material, :unit, :user, :proposed, :proposed_by, CAST(:lines AS jsonb))
        ON CONFLICT (organization_id, material_id, from_unit_id) WHERE status = 'open' DO UPDATE SET
            held_lines = material_size_requests.held_lines || EXCLUDED.held_lines,
            proposed_one_unit_equals = COALESCE(EXCLUDED.proposed_one_unit_equals,
                                                material_size_requests.proposed_one_unit_equals),
            proposed_by = COALESCE(EXCLUDED.proposed_by, material_size_requests.proposed_by),
            updated_at = now()
        RETURNING id
        """), {
            "org": organization_id, "material": material_id, "unit": from_unit_id, "user": user_id,
            "proposed": proposed, "proposed_by": user_id if proposed is not None else None,
            "lines": json.dumps([line] if line else []),
        })).first()
    return await get_request(conn, organization_id, row[0])  # type: ignore[index, return-value]


async def get_request(conn: AsyncConnection, organization_id: uuid.UUID, request_id: uuid.UUID,
                      *, lock: bool = False) -> dict[str, Any] | None:
    sql = f"SELECT {_COLUMNS} {_FROM} WHERE r.id = :id AND r.organization_id = :org"
    if lock:
        sql += " FOR UPDATE OF r"
    row = (await conn.execute(text(sql), {"id": request_id, "org": organization_id})).first()
    return _row(row) if row else None


async def list_requests(conn: AsyncConnection, organization_id: uuid.UUID, status: str | None = "open") -> list[dict]:
    rows = (await conn.execute(text(
        f"SELECT {_COLUMNS} {_FROM} WHERE r.organization_id = :org AND (CAST(:status AS text) IS NULL OR "
        "r.status = :status) ORDER BY r.created_at DESC LIMIT 200"), {"org": organization_id, "status": status})).all()
    return [_row(r) for r in rows]


async def close_request(conn: AsyncConnection, request_id: uuid.UUID, status: str, user_id: uuid.UUID,
                        one_unit_equals: Decimal | None, outcome: list[dict]) -> None:
    await conn.execute(text(
        "UPDATE material_size_requests SET status = :status, one_unit_equals = :size, answered_by = :user, "
        "answered_at = now(), outcome = CAST(:outcome AS jsonb), updated_at = now() WHERE id = :id"),
        {"status": status, "size": one_unit_equals, "user": user_id, "outcome": json.dumps(outcome), "id": request_id})


async def mark_asked(conn: AsyncConnection, ids: list[uuid.UUID]) -> None:
    """The daily ask went out for these (so the next one waits a day)."""
    if ids:
        await conn.execute(text("UPDATE material_size_requests SET asked_at = now() WHERE id = ANY(:ids)"),
                           {"ids": ids})


async def list_conversions(conn: AsyncConnection, organization_id: uuid.UUID) -> list[dict[str, Any]]:
    """Every size the company has set: material, unit, how many stock units one is."""
    rows = (await conn.execute(text(
        """
        SELECT c.material_id, m.name AS material, c.from_unit_id, fu.code AS unit, fu.display_name AS unit_name,
               su.code AS stock_unit, su.display_name AS stock_unit_name, c.per_stock_unit, c.updated_at
        FROM material_unit_conversions c
        JOIN materials_catalog m ON m.id = c.material_id
        JOIN units_of_measure fu ON fu.id = c.from_unit_id
        LEFT JOIN units_of_measure su ON su.id = m.default_unit_id
        WHERE c.organization_id = :org ORDER BY m.name, fu.display_name
        """), {"org": organization_id})).all()
    out = []
    for r in rows:
        item = dict(r._mapping)
        per = Decimal(item.pop("per_stock_unit"))
        item["one_unit_equals"] = f"{(Decimal(1) / per).quantize(Decimal('0.001')).normalize():f}" if per > 0 else None
        out.append(item)
    return out
