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

Those pointing rows can be pointed at too (4 Nov 2026, from the control panel: a reversed material receipt, pointed at
by its reversal, failed the delete). So clearing a row first clears whatever points at it, all the way down: a row
pointing at it is deleted (it is the company's, and goes anyway; emptying its link instead could break a CHECK, e.g. a
transfer needs both accounts), except where the link closes a loop back to a table already being cleared (a reversal
of a reversal, a sub-category, a correction of a correction), where the link is emptied to break the loop.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
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


#: Every NO ACTION / RESTRICT link: (pointing table, its column, whether it may be empty, table, column it points at).
_ALL_LINKS = sa.text("""
SELECT c.conrelid::regclass::text AS child, a.attname::text AS col, NOT a.attnotnull AS nullable,
       c.confrelid::regclass::text AS parent, p.attname::text AS ref
FROM pg_constraint c
JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
JOIN pg_attribute p ON p.attrelid = c.confrelid AND p.attnum = c.confkey[1]
WHERE c.contype = 'f' AND array_length(c.conkey, 1) = 1 AND c.confdeltype IN ('a', 'r')
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


def _table(name: str) -> str:
    return name.split(".")[-1]


async def _clear(conn: AsyncConnection, links_to: dict, table: str, where: str, params: dict,
                 path: tuple[str, ...] = ()) -> None:
    """Delete the rows of ``table`` matching ``where``, after whatever points at them (see the module docstring)."""
    path = (*path, table)
    for child, col, nullable, ref in links_to[table]:
        picked = f"SELECT {_ident(ref)} FROM {_ident(table)} WHERE {where}"  # noqa: S608 -- names from pg_catalog
        if child in path:
            if not nullable:
                continue  # a required link in a loop can't hold data; Postgres says so if it does
            await conn.execute(sa.text(
                f"UPDATE {_ident(child)} SET {_ident(col)} = NULL WHERE {_ident(col)} IN ({picked})"), params)  # noqa: S608
        else:
            await _clear(conn, links_to, child, f"{_ident(col)} IN ({picked})", params, path)
    await conn.execute(sa.text(f"DELETE FROM {_ident(table)} WHERE {where}"), params)  # noqa: S608


async def delete_company(conn: AsyncConnection, organization_id: uuid.UUID) -> None:
    """Delete the company, every record it has and its people, inside the caller's transaction."""
    links_to: dict[str, list[tuple[str, str, bool, str]]] = defaultdict(list)
    for link in (await conn.execute(_ALL_LINKS)).mappings().all():
        links_to[_table(link["parent"])].append((_table(link["child"]), link["col"], link["nullable"], link["ref"]))
    params = {"o": organization_id}
    for link in (await conn.execute(_BLOCKING_LINKS)).mappings().all():
        child, col, parent = _table(link["child"]), link["col"], _table(link["parent"])
        await _clear(conn, links_to, child,
                     f"{_ident(col)} IN (SELECT id FROM {_ident(parent)} WHERE organization_id = :o)", params)  # noqa: S608
    await conn.execute(sa.text("DELETE FROM organizations WHERE id = :o"), params)
    # Rows outside the company tables that still point at its people (e.g. interactions.user_id) go with them.
    for link in (await conn.execute(_USER_LINKS)).mappings().all():
        await conn.execute(sa.text(
            f"DELETE FROM {_ident(_table(link['child']))} WHERE {_ident(link['col'])} IN "  # noqa: S608
            "(SELECT id FROM users WHERE organization_id = :o)"), params)
    await conn.execute(sa.text("DELETE FROM users WHERE organization_id = :o"), params)
