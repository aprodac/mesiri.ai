"""PostgreSQL store for self-serve signup attempts (migration 0480, SS-09).

One row per `check_signup` call, allowed or refused, with the flags it
earned. It is the per-IP count behind the web limit and the record the
control panel reads flags from. Append-only; takes an externally-supplied
connection and never commits.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection

signup_attempts = sa.Table(
    "signup_attempts",
    sa.MetaData(),
    sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
    sa.Column("created_at", sa.DateTime(timezone=True)),
    sa.Column("phone", sa.String),
    sa.Column("signup_source", sa.String),
    sa.Column("ip_address", sa.String),
    sa.Column("outcome", sa.String),
    sa.Column("reason", sa.String),
    sa.Column("flags", ARRAY(sa.String)),
)

ALLOWED = "allowed"
REFUSED = "refused"


class PostgresSignupAttemptRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def record(
        self,
        *,
        phone: str,
        signup_source: str,
        ip_address: str | None,
        reason: str | None,
        flags: tuple[str, ...],
        at: dt.datetime,
    ) -> None:
        await self._conn.execute(
            signup_attempts.insert().values(
                id=uuid.uuid4(),
                created_at=at,
                phone=phone,
                signup_source=signup_source,
                ip_address=ip_address,
                outcome=REFUSED if reason else ALLOWED,
                reason=reason,
                flags=list(flags),
            )
        )

    async def other_phones_from_ip(self, ip_address: str, phone: str, *, since: dt.datetime) -> int:
        """Distinct numbers other than `phone` seen from this IP since `since`."""
        return (
            await self._conn.execute(
                sa.select(sa.func.count(sa.distinct(signup_attempts.c.phone))).where(
                    signup_attempts.c.ip_address == ip_address,
                    signup_attempts.c.phone != phone,
                    signup_attempts.c.created_at >= since,
                )
            )
        ).scalar_one()

    async def flags_for_phone(self, phone: str) -> list[str]:
        """Every flag this number's signup attempts earned, oldest first,
        without repeats -- for the control panel's company view."""
        rows = (
            await self._conn.execute(
                sa.select(signup_attempts.c.flags)
                .where(signup_attempts.c.phone == phone)
                .order_by(signup_attempts.c.created_at)
            )
        ).scalars()
        seen: dict[str, None] = {}
        for flags in rows:
            for flag in flags or ():
                seen.setdefault(flag, None)
        return list(seen)
