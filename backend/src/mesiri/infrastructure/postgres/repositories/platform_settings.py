"""PostgreSQL store for platform-wide settings (migration 0464, SS-02).

Reads fall back to the spec default when no row exists, and fill in any
field a stored row is missing (see domains/organizations/platform_settings).

Takes an externally-supplied connection and never commits, matching
organization_settings.py and the transaction-ownership rule.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert

from mesiri.domains.organizations import platform_settings as spec

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection

_platform_settings = sa.Table(
    "platform_settings",
    sa.MetaData(),
    sa.Column("key", sa.String, primary_key=True),
    sa.Column("value", JSONB),
    sa.Column("updated_at", sa.DateTime(timezone=True)),
    sa.Column("updated_by", sa.UUID(as_uuid=True)),
)


class PostgresPlatformSettingsRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def get(self, key: str) -> dict[str, Any]:
        """The value for `key`, defaults filled in."""
        row = (
            await self._conn.execute(
                sa.select(_platform_settings.c.value).where(_platform_settings.c.key == key)
            )
        ).first()
        return spec.with_defaults(key, row.value if row is not None else None)

    async def get_all(self) -> dict[str, dict[str, Any]]:
        """Every known setting, defaults filled in."""
        rows = (
            await self._conn.execute(
                sa.select(_platform_settings.c.key, _platform_settings.c.value)
            )
        ).all()
        stored = {row.key: row.value for row in rows}
        return {s.key: spec.with_defaults(s.key, stored.get(s.key)) for s in spec.all_specs()}

    async def set(
        self, key: str, value: dict[str, Any], *, updated_by: uuid.UUID | None
    ) -> dict[str, Any]:
        """Validate and upsert one setting; returns what was stored."""
        validated = spec.validate(key, value)
        stmt = (
            pg_insert(_platform_settings)
            .values(key=key, value=validated, updated_at=sa.func.now(), updated_by=updated_by)
            .on_conflict_do_update(
                index_elements=[_platform_settings.c.key],
                set_={"value": validated, "updated_at": sa.func.now(), "updated_by": updated_by},
            )
        )
        await self._conn.execute(stmt)
        return validated
