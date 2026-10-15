"""PostgreSQL store for one-time login and signup codes (migration 0476).

The rules live in application/identity/login_codes.py; this only reads and
writes rows. Takes an externally-supplied connection and never commits.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import TYPE_CHECKING

import sqlalchemy as sa

from mesiri.application.identity.login_codes import MAX_ATTEMPTS, StoredCode

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection

_login_codes = sa.Table(
    "login_codes",
    sa.MetaData(),
    sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
    sa.Column("phone", sa.String),
    sa.Column("purpose", sa.String),
    sa.Column("code_hash", sa.String),
    sa.Column("expires_at", sa.DateTime(timezone=True)),
    sa.Column("attempts", sa.Integer),
    sa.Column("consumed_at", sa.DateTime(timezone=True)),
    sa.Column("created_at", sa.DateTime(timezone=True)),
)


class PostgresLoginCodeStore:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    def _for(self, phone: str, purpose: str):
        return sa.and_(_login_codes.c.phone == phone, _login_codes.c.purpose == purpose)

    async def sent_since(self, phone: str, purpose: str, since: dt.datetime) -> list[dt.datetime]:
        rows = await self._conn.execute(
            sa.select(_login_codes.c.created_at).where(
                self._for(phone, purpose), _login_codes.c.created_at >= since
            )
        )
        return [row.created_at for row in rows]

    async def add(
        self,
        *,
        phone: str,
        purpose: str,
        code_hash: str,
        expires_at: dt.datetime,
        created_at: dt.datetime,
    ) -> None:
        await self._conn.execute(
            _login_codes.insert().values(
                id=uuid.uuid4(),
                phone=phone,
                purpose=purpose,
                code_hash=code_hash,
                expires_at=expires_at,
                attempts=0,
                created_at=created_at,
            )
        )

    async def void_open(self, phone: str, purpose: str, now: dt.datetime) -> None:
        await self._conn.execute(
            _login_codes.update()
            .where(self._for(phone, purpose), _login_codes.c.consumed_at.is_(None))
            .values(consumed_at=now)
        )

    async def latest_open(self, phone: str, purpose: str, now: dt.datetime) -> StoredCode | None:
        row = (
            await self._conn.execute(
                sa.select(_login_codes.c.id, _login_codes.c.code_hash, _login_codes.c.attempts)
                .where(
                    self._for(phone, purpose),
                    _login_codes.c.consumed_at.is_(None),
                    _login_codes.c.expires_at > now,
                    _login_codes.c.attempts < MAX_ATTEMPTS,
                )
                .order_by(_login_codes.c.created_at.desc())
                .limit(1)
                # Two checks of the same code at once must not both win, or
                # both count one try.
                .with_for_update()
            )
        ).first()
        if row is None:
            return None
        return StoredCode(id=row.id, code_hash=row.code_hash, attempts=row.attempts)

    async def count_attempt(self, code_id: uuid.UUID) -> None:
        await self._conn.execute(
            _login_codes.update()
            .where(_login_codes.c.id == code_id)
            .values(attempts=_login_codes.c.attempts + 1)
        )

    async def consume(self, code_id: uuid.UUID, now: dt.datetime) -> None:
        await self._conn.execute(
            _login_codes.update().where(_login_codes.c.id == code_id).values(consumed_at=now)
        )
