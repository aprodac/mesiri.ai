"""Delete a company and everything it has: the one step (SA-30, 2 Nov 2026).

Found by the demo reset's test on a real Postgres: deleting a company with records failed two ways.

1. **People first fails.** 57 links point at ``users`` (``created_by`` ...) without ON DELETE, so the company's people
   can only go after its records. Every company table cascades from ``organizations``, so the company goes first,
   then its people (``users.organization_id`` is not a foreign key, so nothing cascades to them).
2. **Some cascades meet in the wrong order.** A row that is deleted through one cascade path can still be pointed at
   by a row deleted through another path, with a NO ACTION link between them (attendance lines -> workers,
   interactions -> workflow instances, budget allocations -> expense categories, report sources -> daily reports).
   Postgres checks that link before the other cascade has removed the pointing row, and refuses.

So: the blocking links are read from the catalogue (not listed by hand, so a new table can't break it again), the
pointing rows of this company are deleted first, then the company, then its people. All in the caller's transaction:
a failure leaves everything as it was.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import sqlalchemy as sa

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection

#: NO ACTION / RESTRICT links from a table to a company table (one that cascades from organizations), where the
#: pointing table is not itself a company table: (pointing table, its column, company table).
_BLOCKING_LINKS = sa.text("""
SELECT c.conrelid::regclass::text AS child, a.attname::text AS col, c.confrelid::regclass::text AS parent
FROM pg_constraint c
JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
WHERE c.contype = 'f' AND array_length(c.conkey, 1) = 1 AND c.confdeltype IN ('a', 'r')
  AND c.confrelid <> 'users'::regclass
  AND c.confrelid IN (SELECT conrelid FROM pg_constraint WHERE contype = 'f' AND confrelid = 'organizations'::regclass
                      AND confdeltype = 'c')
""")


#: NO ACTION / RESTRICT links to users (what is left of them once the company tables are gone).
_USER_LINKS = sa.text("""
SELECT c.conrelid::regclass::text AS child, a.attname::text AS col
FROM pg_constraint c
JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
WHERE c.contype = 'f' AND array_length(c.conkey, 1) = 1 AND c.confdeltype IN ('a', 'r')
  AND c.confrelid = 'users'::regclass
""")


def _ident(name: str) -> str:
    """A catalogue name, quoted (it comes from pg_catalog, never from a caller)."""
    return '"' + name.replace('"', '""') + '"'


async def delete_company(conn: AsyncConnection, organization_id: uuid.UUID) -> None:
    """Delete the company, every record it has and its people, inside the caller's transaction."""
    for link in (await conn.execute(_BLOCKING_LINKS)).mappings().all():
        child, col, parent = (link["child"].split(".")[-1], link["col"], link["parent"].split(".")[-1])
        await conn.execute(sa.text(
            f"DELETE FROM {_ident(child)} WHERE {_ident(col)} IN "  # noqa: S608 -- names from pg_catalog
            f"(SELECT id FROM {_ident(parent)} WHERE organization_id = :o)"), {"o": organization_id})
    await conn.execute(sa.text("DELETE FROM organizations WHERE id = :o"), {"o": organization_id})
    # Rows outside the company tables that still point at its people (e.g. interactions.user_id) go with them.
    for link in (await conn.execute(_USER_LINKS)).mappings().all():
        await conn.execute(sa.text(
            f"DELETE FROM {_ident(link['child'].split('.')[-1])} WHERE {_ident(link['col'])} IN "  # noqa: S608
            "(SELECT id FROM users WHERE organization_id = :o)"), {"o": organization_id})
    await conn.execute(sa.text("DELETE FROM users WHERE organization_id = :o"), {"o": organization_id})
