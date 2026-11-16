"""Remove every company's data from the test database, and nothing else (INF-33).

Each contract test file used to empty its own hand-written list of tables. The lists drifted as the schema grew (work
orders, norms, documents...), so a file broke when it ran after another one that had filled a table its list did not
know: "update or delete on table vendors violates foreign key constraint work_orders_vendor_id_fkey". Which file broke
depended on the order they ran in, so most of them could not join CI together.

``wipe_tenant_data`` reads the schema instead of a list, so a new table is covered the day its migration lands:

- a **company row** is a row of ``organizations``, a row with a non-null ``organization_id``, or a row that points
  (by a foreign key) at a company row, through any chain of foreign keys;
- reference data the migrations seed (units, unit aliases, the ``ref_*`` tables) has no company and points at none,
  so it stays;
- rows are deleted children first; when tables point at each other (a cycle), the nullable links between the rows
  still left are cleared first, as the old fixtures did by hand ("UPDATE activities SET work_package_id = NULL").
"""

from __future__ import annotations

from collections import defaultdict

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

_FKS = sa.text(
    """
    SELECT c.conrelid::regclass::text AS child, a.attname AS col, a.attnotnull AS not_null,
           c.confrelid::regclass::text AS parent, pa.attname AS parent_col
    FROM pg_constraint c
    JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
    JOIN pg_attribute pa ON pa.attrelid = c.confrelid AND pa.attnum = c.confkey[1]
    WHERE c.contype = 'f' AND c.connamespace = 'public'::regnamespace AND array_length(c.conkey, 1) = 1
    """
)
_TABLES = sa.text(
    "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
)
_ORG_TABLES = sa.text(
    "SELECT table_name FROM information_schema.columns WHERE table_schema = 'public' AND column_name = 'organization_id'"
)


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


async def wipe_tenant_data(conn: AsyncConnection) -> None:
    """Delete every company row (see the module doc), children first. Reference data is left as it is."""
    tables = {r[0] for r in (await conn.execute(_TABLES)).all()} - {"alembic_version"}
    with_org = {r[0] for r in (await conn.execute(_ORG_TABLES)).all()} & tables
    fks = [dict(r) for r in (await conn.execute(_FKS)).mappings().all()]
    by_child: dict[str, list[dict]] = defaultdict(list)
    for fk in fks:
        if fk["child"] in tables and fk["parent"] in tables:
            by_child[fk["child"]].append(fk)

    # The tables that can hold company rows: organizations, tables with organization_id, and (repeatedly) any table
    # with a foreign key into one of those.
    tenant = {"organizations"} | with_org
    grew = True
    while grew:
        grew = False
        for child, links in by_child.items():
            if child not in tenant and any(fk["parent"] in tenant for fk in links):
                tenant.add(child)
                grew = True

    def condition(table: str, seen: frozenset[str] = frozenset()) -> str:
        """SQL that is true for the table's company rows (rows of an outer query on this table)."""
        if table == "organizations":
            return "TRUE"
        parts = ["organization_id IS NOT NULL"] if table in with_org else []
        for fk in by_child.get(table, ()):
            parent = fk["parent"]
            if parent not in tenant or parent in seen or parent == table:
                continue
            inner = condition(parent, seen | {table})
            parts.append(
                f"{_q(fk['col'])} IN (SELECT {_q(fk['parent_col'])} FROM {_q(parent)} WHERE {inner})"
            )
        return " OR ".join(f"({p})" for p in parts) if parts else "FALSE"

    left = set(tenant)
    while left:
        done = set()
        for table in sorted(left):
            savepoint = await conn.begin_nested()
            try:
                await conn.execute(sa.text(f"DELETE FROM {_q(table)} WHERE {condition(table)}"))  # noqa: S608
                await savepoint.commit()
                done.add(table)
            except sa.exc.IntegrityError:
                await savepoint.rollback()
        if done:
            left -= done
            continue
        # A cycle: every table left is pointed at by another one left. Clear the nullable links between them.
        cleared = False
        for table in sorted(left):
            for fk in by_child.get(table, ()):
                if fk["parent"] in left and not fk["not_null"]:
                    await conn.execute(sa.text(
                        f"UPDATE {_q(table)} SET {_q(fk['col'])} = NULL "  # noqa: S608
                        f"WHERE {_q(fk['col'])} IS NOT NULL AND ({condition(table)})"
                    ))
                    cleared = True
        if not cleared:
            raise RuntimeError(f"Could not remove the company rows of: {', '.join(sorted(left))}")


async def wipe(engine: AsyncEngine) -> None:
    """``wipe_tenant_data`` in a transaction of its own."""
    async with engine.begin() as conn:
        await wipe_tenant_data(conn)
