"""SS-74d: save points and Go back in a learning sample company (docs/plans/guided-demo-plan.md 18.5, 18.12).

When a day begins for the person (the cast has played it, their own entries wait), every row the sample company has is
saved, per table, as JSON (``sandbox_days``, gzip). Go back puts those rows back exactly and sets the company's date to
that day; the save points after it go (one line of days, D-GC4). Going forth again is Next day: the plan is fixed and
the cast follows the company, so the days come back the same except where the person does differently. Going back to
today's own save point is "try today again".

**Which rows are the company's** is read from the catalogue, not listed by hand, so a new table is saved without
anyone remembering to add it: every table with an ``organization_id`` (those rows), and every table that has none but
links to one of them or to the company's people (the rows that link to this company's). Not saved: the company's
people (``users``: the cast never changes), the company row itself (only its date moves), the admin audit log (kept
by design, as when a sample company is removed) and the save points themselves.

**Putting rows back passes every check the database has** (no constraint is switched off; the app's login could not
anyway). Rows are deleted children first and inserted parents first, one statement per table, so a table's links to
itself hold at the end of that statement. Where links loop between tables (a receipt reversing a use and back, a report
and its current version, an RFQ line and its awarded quote) the optional ones are emptied before deleting and filled in
after inserting, and the order follows the required ones. A loop of required links would make any order impossible,
and ``layout_from`` says so.

Every statement runs scoped to the sample company (row-level security), and every entry point refuses a company that
is not a sample (``sandbox_of``).
"""

from __future__ import annotations

import datetime as dt
import gzip
import json
import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa

from mesiri.infrastructure.postgres.tenant import apply_tenant

#: Save points kept per sample company (D-GC4).
KEEP = 30
#: Tables with company rows that a save point leaves alone (see the module docstring).
NOT_SAVED = frozenset({"admin_audit_log", "sandbox_days"})
#: Parents whose rows are never put back, but whose rows mark a table's rows as this company's.
_ANCHORS = {"users": "organization_id = :o", "organizations": "id = :o"}


class NotASample(Exception):
    pass


def _q(name: str) -> str:
    """A catalogue name, quoted (it comes from pg_catalog, never from a caller)."""
    return '"' + name.replace('"', '""') + '"'


_ORG_TABLES = sa.text("""
SELECT c.relname::text FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
JOIN pg_attribute a ON a.attrelid = c.oid AND a.attname = 'organization_id' AND NOT a.attisdropped
WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
""")

#: Single-column foreign keys in public: (child, column, nullable, parent, parent column).
_LINKS = sa.text("""
SELECT c.conrelid::regclass::text AS child, a.attname::text AS col, NOT a.attnotnull AS nullable,
       c.confrelid::regclass::text AS parent, p.attname::text AS ref, array_length(c.conkey, 1) AS width
FROM pg_constraint c
JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
JOIN pg_attribute p ON p.attrelid = c.confrelid AND p.attnum = c.confkey[1]
JOIN pg_namespace n ON n.oid = c.connamespace
WHERE c.contype = 'f' AND n.nspname = 'public'
""")

_COLUMNS = sa.text("""
SELECT c.relname::text AS t, a.attname::text AS col, a.attgenerated <> '' AS generated,
       EXISTS (SELECT 1 FROM pg_index i WHERE i.indrelid = c.oid AND i.indisprimary AND a.attnum = ANY (i.indkey)) AS pk
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
ORDER BY c.relname, a.attnum
""")


@dataclass(frozen=True)
class Layout:
    #: Parents before children.
    order: tuple[str, ...]
    #: Which of a table's rows are this company's (``:o`` is the company).
    where: dict[str, str]
    #: Optional links that loop between tables: emptied before deleting, filled in after inserting.
    loops: dict[str, tuple[str, ...]]
    #: Columns written on insert (not generated), and the primary key.
    columns: dict[str, tuple[str, ...]]
    pk: dict[str, tuple[str, ...]]


def _strong(nodes: set[str], edges: dict[str, set[str]]) -> list[set[str]]:
    """Strongly connected groups (Tarjan, iterative)."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on: set[str] = set()
    groups: list[set[str]] = []
    counter = 0
    for root in sorted(nodes):
        if root in index:
            continue
        work = [(root, iter(sorted(edges[root])))]
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on.add(root)
        while work:
            v, it = work[-1]
            w = next(it, None)
            if w is not None:
                if w not in index:
                    index[w] = low[w] = counter
                    counter += 1
                    stack.append(w)
                    on.add(w)
                    work.append((w, iter(sorted(edges[w]))))
                elif w in on:
                    low[v] = min(low[v], index[w])
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[v])
            if low[v] == index[v]:
                group = set()
                while True:
                    w = stack.pop()
                    on.discard(w)
                    group.add(w)
                    if w == v:
                        break
                groups.append(group)
    return groups


def layout_from(org_tables: set[str], links: list[dict[str, Any]], columns: list[dict[str, Any]]) -> Layout:
    """The save point's plan, from the catalogue (pure: tested without a database)."""
    saved = {t for t in org_tables if t not in NOT_SAVED and t not in _ANCHORS}
    # Tables without the company's id whose rows link to the company's rows.
    grew = True
    while grew:
        grew = False
        for link in links:
            if link["parent"] in saved and link["child"] not in saved and link["child"] not in org_tables \
                    and link["child"] not in NOT_SAVED and link["child"] not in _ANCHORS:
                saved.add(link["child"])
                grew = True

    where: dict[str, str] = {t: "organization_id = :o" for t in saved if t in org_tables}

    def condition(table: str, seen: frozenset[str]) -> str:
        if table in where:
            return where[table]
        parts = []
        for link in links:
            if link["child"] != table or link["width"] != 1 or link["parent"] in seen or link["parent"] == table:
                continue
            parent = link["parent"]
            if parent in _ANCHORS:
                inner = _ANCHORS[parent]
            elif parent in saved:
                inner = condition(parent, seen | {table})
            else:
                continue
            parts.append(f"{_q(link['col'])} IN (SELECT {_q(link['ref'])} FROM {_q(parent)} WHERE {inner})")
        return "(" + " OR ".join(parts) + ")" if parts else "FALSE"

    for table in saved - set(where):
        where[table] = condition(table, frozenset())

    edges: dict[str, set[str]] = defaultdict(set)
    for link in links:
        if link["child"] in saved and link["parent"] in saved and link["child"] != link["parent"]:
            edges[link["child"]].add(link["parent"])
    loops: dict[str, list[str]] = defaultdict(list)
    for group in _strong(saved, edges):
        if len(group) < 2:
            continue
        inside = [x for x in links if x["child"] in group and x["parent"] in group and x["child"] != x["parent"]]
        for link in inside:
            if link["nullable"] and link["width"] == 1:
                loops[link["child"]].append(link["col"])
        for link in inside:  # the order follows only the required links
            if all(x["nullable"] and x["width"] == 1 for x in inside
                   if x["child"] == link["child"] and x["parent"] == link["parent"]):
                edges[link["child"]].discard(link["parent"])
    # Parents first (Kahn's order over what is left; ties by name so it is the same every time).
    order: list[str] = []
    waiting = {t: set(edges[t]) for t in saved}
    ready = sorted(t for t, parents in waiting.items() if not parents)
    while ready:
        table = ready.pop(0)
        order.append(table)
        for child, parents in waiting.items():
            if table in parents:
                parents.discard(table)
                if not parents and child not in order and child not in ready:
                    ready.append(child)
                    ready.sort()
    if len(order) != len(saved):
        raise RuntimeError(f"Tables in a loop the save point can't order: {sorted(saved - set(order))}")

    cols: dict[str, list[str]] = defaultdict(list)
    pk: dict[str, list[str]] = defaultdict(list)
    for c in columns:
        if c["t"] in saved:
            if not c["generated"]:
                cols[c["t"]].append(c["col"])
            if c["pk"]:
                pk[c["t"]].append(c["col"])
    for table, looped in loops.items():
        if not pk[table]:
            raise RuntimeError(f"{table} loops with another table and has no primary key to fill the link in by")
        loops[table] = sorted(set(looped))
    return Layout(order=tuple(order), where=where, loops={t: tuple(c) for t, c in loops.items()},
                  columns={t: tuple(c) for t, c in cols.items()}, pk={t: tuple(c) for t, c in pk.items()})


_cached: Layout | None = None


async def layout(conn: Any) -> Layout:
    """The layout for this database (the schema only changes with a deploy, so it is read once per process)."""
    global _cached  # noqa: PLW0603 -- one per process, the schema doesn't change while it runs
    if _cached is None:
        org_tables = {r[0] for r in (await conn.execute(_ORG_TABLES)).all()}
        links = [dict(r) for r in (await conn.execute(_LINKS)).mappings()]
        columns = [dict(r) for r in (await conn.execute(_COLUMNS)).mappings()]
        _cached = layout_from(org_tables, links, columns)
    return _cached


async def _sample_only(conn: Any, org: uuid.UUID) -> None:
    sample = (await conn.execute(sa.text("SELECT sandbox_of FROM organizations WHERE id = :o"), {"o": org})).scalar()
    if sample is None:
        raise NotASample(str(org))
    await apply_tenant(conn, org)


async def snapshot(conn: Any, org: uuid.UUID) -> dict[str, str]:
    """Every row of the company, per table, as JSON text."""
    lay = await layout(conn)
    out: dict[str, str] = {}
    for table in lay.order:
        rows = (await conn.execute(sa.text(
            f"SELECT coalesce(json_agg(t), '[]'::json)::text FROM {_q(table)} t WHERE {lay.where[table]}"),  # noqa: S608
            {"o": org})).scalar_one()
        if rows != "[]":
            out[table] = rows
    return out


async def save(conn: Any, org: uuid.UUID, day: int, on_date: dt.date) -> int:
    """Save the sample company as it is now, as the start of ``day``. Returns the bytes stored."""
    await _sample_only(conn, org)
    rows = await snapshot(conn, org)
    data = gzip.compress(("{" + ",".join(f"{json.dumps(t)}:{v}" for t, v in rows.items()) + "}").encode(), 6)
    await conn.execute(sa.text(
        "INSERT INTO sandbox_days (organization_id, day, on_date, data) VALUES (:o, :d, :on, :data) "
        "ON CONFLICT (organization_id, day) DO UPDATE SET on_date = EXCLUDED.on_date, data = EXCLUDED.data, "
        "saved_at = now()"), {"o": org, "d": day, "on": on_date, "data": data})
    await conn.execute(sa.text(
        "DELETE FROM sandbox_days WHERE organization_id = :o AND day NOT IN "
        "(SELECT day FROM sandbox_days WHERE organization_id = :o ORDER BY day DESC LIMIT :k)"), {"o": org, "k": KEEP})
    return len(data)


async def days(conn: Any, org: uuid.UUID) -> list[tuple[int, dt.date]]:
    """The save points there are, oldest first."""
    return [(r[0], r[1]) for r in (await conn.execute(sa.text(
        "SELECT day, on_date FROM sandbox_days WHERE organization_id = :o ORDER BY day"), {"o": org})).all()]


async def has(conn: Any, org: uuid.UUID, day: int) -> bool:
    return bool((await conn.execute(sa.text(
        "SELECT 1 FROM sandbox_days WHERE organization_id = :o AND day = :d"), {"o": org, "d": day})).scalar())


async def restore(conn: Any, org: uuid.UUID, day: int) -> dt.date | None:
    """Put the company back as it was at the start of ``day``; later save points go. None when there is none."""
    await _sample_only(conn, org)
    hit = (await conn.execute(sa.text(
        "SELECT on_date, data FROM sandbox_days WHERE organization_id = :o AND day = :d"),
        {"o": org, "d": day})).first()
    if hit is None:
        return None
    rows: dict[str, list[dict[str, Any]]] = json.loads(gzip.decompress(hit[1]))
    lay = await layout(conn)
    params = {"o": org}
    # Out: loops emptied, then children before parents.
    for table, looped in lay.loops.items():
        sets = ", ".join(f"{_q(c)} = NULL" for c in looped)
        await conn.execute(sa.text(f"UPDATE {_q(table)} SET {sets} WHERE {lay.where[table]}"), params)  # noqa: S608
    for table in reversed(lay.order):
        await conn.execute(sa.text(f"DELETE FROM {_q(table)} WHERE {lay.where[table]}"), params)  # noqa: S608
    # In: parents before children, loops left empty, then filled in.
    for table in lay.order:
        if not rows.get(table):
            continue
        cols = lay.columns[table]
        looped = set(lay.loops.get(table, ()))
        picked = ", ".join("NULL" if c in looped else f"j.{_q(c)}" for c in cols)
        await conn.execute(sa.text(
            f"INSERT INTO {_q(table)} ({', '.join(_q(c) for c in cols)}) "  # noqa: S608
            f"SELECT {picked} FROM json_populate_recordset(NULL::{_q(table)}, CAST(:rows AS json)) j"),
            {"rows": json.dumps(rows[table])})
    for table, looped in lay.loops.items():
        if not rows.get(table):
            continue
        sets = ", ".join(f"{_q(c)} = j.{_q(c)}" for c in looped)
        match = " AND ".join(f"t.{_q(k)} = j.{_q(k)}" for k in lay.pk[table])
        await conn.execute(sa.text(
            f"UPDATE {_q(table)} t SET {sets} FROM json_populate_recordset(NULL::{_q(table)}, CAST(:rows AS json)) j "  # noqa: S608
            f"WHERE {match}"), {"rows": json.dumps(rows[table])})
    await conn.execute(sa.text("UPDATE organizations SET sandbox_today = :d WHERE id = :o AND sandbox_of IS NOT NULL"),
                       {"d": hit[0], "o": org})
    await conn.execute(sa.text("DELETE FROM sandbox_days WHERE organization_id = :o AND day > :d"), {"o": org, "d": day})
    return hit[0]


async def hold(conn: Any, org: uuid.UUID) -> bool:
    """Only one Next day or Go back at a time per sample company: a lock held by this connection until ``release``."""
    return bool((await conn.execute(sa.text("SELECT pg_try_advisory_lock(hashtext('sandbox-days'), hashtext(:o))"),
                                    {"o": str(org)})).scalar())


async def release(conn: Any, org: uuid.UUID) -> None:
    await conn.execute(sa.text("SELECT pg_advisory_unlock(hashtext('sandbox-days'), hashtext(:o))"), {"o": str(org)})
