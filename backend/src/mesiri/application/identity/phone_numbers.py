"""One WhatsApp number = one person (BE-04).

A WhatsApp number is how an inbound message finds its sender, compared on its
digits: "+91 98765 43210" and "919876543210" are the same number. The database
enforces it with ``ux_users_whatsapp_digits`` (migration 0483); every place
that saves a number checks here first so the person gets a plain refusal
instead of a raw IntegrityError.

The refusal never names the person who holds the number: they may belong to
another company.
"""

from __future__ import annotations

import re
import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.infrastructure.postgres.tenant import unscoped

NUMBER_TAKEN_MESSAGE = "That WhatsApp number is already registered on Mesiri"

# Same expression as the unique index and the inbound sender lookup.
_DIGITS_SQL = "regexp_replace(whatsapp_number, '\\D', '', 'g')"


def whatsapp_digits(value: object) -> str:
    return re.sub(r"\D", "", str(value or ""))


async def whatsapp_number_taken(
    conn: AsyncConnection,
    number: object,
    *,
    except_user_id: uuid.UUID | str | None = None,
) -> bool:
    """True if another user already holds this number (any company)."""
    digits = whatsapp_digits(number)
    if not digits:
        return False
    sql = f"SELECT 1 FROM users WHERE whatsapp_number IS NOT NULL AND {_DIGITS_SQL} = :d"
    params: dict[str, object] = {"d": digits}
    if except_user_id is not None:
        sql += " AND id <> :uid"
        params["uid"] = uuid.UUID(str(except_user_id))
    # Every company: a number belongs to one person anywhere (BE-03 unscoped).
    async with unscoped(conn):
        row = (await conn.execute(sa.text(sql + " LIMIT 1"), params)).first()
    return row is not None
