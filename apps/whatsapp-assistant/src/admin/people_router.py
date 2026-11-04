"""Find a person across every company, for the control panel (SA-24).

A company's own Users tab lists only that company, so "where is this number?"
meant opening every company or writing SQL on the Database page. This route
answers it: a name, email or WhatsApp number in, every matching user out,
with the company they belong to.

The number is matched on its digits, the way the unique index matches it
(BE-04, migration 0483): "79077 93657", "+91 7907793657" and "917907793657"
all find the same person, including a deactivated or suspended one, whose
number still blocks a new signup. Read-only and platform-admin only.
"""

from __future__ import annotations

import re
import uuid

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from admin.router import get_engine, organizations_table, users_table
from mesiri.domains.shared.auth import require_platform_admin

router = APIRouter(prefix="/admin/people", tags=["admin"])

#: Fewer characters than this match too much to be useful.
MIN_QUERY = 3
#: A number is searched once it has this many digits (the last 4 is how the panel shows one).
MIN_DIGITS = 4
#: An Indian mobile number without its country code.
NATIONAL_DIGITS = 10
LIMIT = 25

_DIGITS = sa.func.regexp_replace(users_table.c.whatsapp_number, r"\D", "", "g")


class PersonMatch(BaseModel):
    id: uuid.UUID
    full_name: str
    email: str | None = None
    whatsapp_number: str | None = None
    role: str
    status: str
    organization_id: uuid.UUID | None = None
    #: None for a platform admin (no company).
    company: str | None = None


def _like(text: str) -> str:
    """`text` as a contains-pattern, with LIKE's own wildcards taken literally."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def search_clause(q: str) -> sa.ColumnElement[bool] | None:
    """What `q` matches: name or email (contains, any case), or the number's digits.
    None when `q` is too short to search."""
    text = q.strip()
    if len(text) < MIN_QUERY:
        return None
    pattern = _like(text)
    clauses = [
        users_table.c.full_name.ilike(pattern, escape="\\"),
        users_table.c.email.ilike(pattern, escape="\\"),
    ]
    # A full number drops its country code, so "+91 79077 93657" also finds one saved as "7907793657".
    digits = re.sub(r"\D", "", text)[-NATIONAL_DIGITS:]
    if len(digits) >= MIN_DIGITS:
        clauses.append(_DIGITS.like(f"%{digits}%"))
    return sa.or_(*clauses)


@router.get("/search", response_model=list[PersonMatch])
async def search_people(
    q: str = Query("", max_length=120),
    _admin: dict = Depends(require_platform_admin),
):
    """Every user whose name, email or WhatsApp number matches `q`, in any company."""
    clause = search_clause(q)
    if clause is None:
        return []
    statement = (
        sa.select(
            users_table.c.id,
            users_table.c.full_name,
            users_table.c.email,
            users_table.c.whatsapp_number,
            users_table.c.role,
            users_table.c.status,
            users_table.c.organization_id,
            organizations_table.c.name.label("company"),
        )
        .select_from(
            users_table.outerjoin(
                organizations_table, organizations_table.c.id == users_table.c.organization_id
            )
        )
        .where(clause)
        .order_by(users_table.c.full_name)
        .limit(LIMIT)
    )
    async with get_engine().connect() as conn:
        rows = (await conn.execute(statement)).fetchall()
    return [
        PersonMatch(
            id=row.id,
            full_name=row.full_name or "",
            email=row.email,
            whatsapp_number=row.whatsapp_number,
            role=row.role or "",
            status=row.status or "active",
            organization_id=row.organization_id,
            company=row.company,
        )
        for row in rows
    ]
