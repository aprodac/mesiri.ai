"""SA-24: find a person across every company by name, email or WhatsApp number."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from admin import people_router


def _sql(clause) -> str:
    return str(clause.compile(dialect=postgresql.dialect()))


def _values(clause) -> list:
    return list(clause.compile(dialect=postgresql.dialect()).params.values())


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _Conn:
    def __init__(self, rows):
        self._rows = rows
        self.executed = []

    async def execute(self, statement):
        self.executed.append(statement)
        return _Result(self._rows)


class _ConnectContext:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return None


class _Engine:
    def __init__(self, conn):
        self._conn = conn

    def connect(self):
        return _ConnectContext(self._conn)


@pytest.mark.parametrize("q", ["79077 93657", "+91 7907793657", "917907793657", "7907-793-657"])
def test_a_number_in_any_format_matches_on_its_digits(q):
    # "+91 ..." and "91..." drop the country code, so a number saved without it is found too.
    clause = people_router.search_clause(q)
    assert "regexp_replace(users.whatsapp_number" in _sql(clause)
    assert "%7907793657%" in _values(clause)


def test_the_last_digits_find_a_number():
    assert "%3657%" in _values(people_router.search_clause("3657"))


def test_a_name_matches_name_and_email_but_not_the_number():
    clause = people_router.search_clause("Ravi")
    sql = _sql(clause)
    assert "users.full_name ILIKE" in sql and "users.email ILIKE" in sql
    assert "regexp_replace" not in sql
    assert _values(clause) == ["%Ravi%", "%Ravi%"]


def test_a_short_query_searches_nothing():
    assert people_router.search_clause("  ab ") is None


def test_like_wildcards_are_taken_literally():
    assert "%50\\%\\_off%" in _values(people_router.search_clause("50%_off"))


@pytest.mark.asyncio
async def test_search_returns_people_with_their_company(monkeypatch):
    org_id = uuid.uuid4()
    rows = [
        SimpleNamespace(
            id=uuid.uuid4(),
            full_name="Ravi",
            email=None,
            whatsapp_number="+91 79077 93657",
            role="SITE_ENGINEER",
            status="inactive",
            organization_id=org_id,
            company="Acme Builders",
        ),
        SimpleNamespace(
            id=uuid.uuid4(),
            full_name=None,
            email="admin@mesiri.ai",
            whatsapp_number=None,
            role="ADMIN",
            status=None,
            organization_id=None,
            company=None,
        ),
    ]
    conn = _Conn(rows)
    monkeypatch.setattr(people_router, "get_engine", lambda: _Engine(conn))

    found = await people_router.search_people(q="7907793657", _admin={})

    assert [p.company for p in found] == ["Acme Builders", None]
    assert found[0].status == "inactive"
    assert found[1].full_name == "" and found[1].status == "active"
    statement = conn.executed[0]
    assert "LEFT OUTER JOIN organizations" in _sql(statement)
    assert statement._limit == people_router.LIMIT == 25


@pytest.mark.asyncio
async def test_a_short_query_never_touches_the_database(monkeypatch):
    def _no_engine():
        raise AssertionError("the database must not be read")

    monkeypatch.setattr(people_router, "get_engine", _no_engine)

    assert await people_router.search_people(q="ab", _admin={}) == []
