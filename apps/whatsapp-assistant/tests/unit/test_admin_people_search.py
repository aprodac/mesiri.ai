"""SA-24: find a person across every company by name, email or WhatsApp number."""

from __future__ import annotations

import datetime as dt
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

    def begin(self):
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


# --- SA-25: a number's free trials, deleted companies included ---------------------


class _Rules:
    def __init__(self, conn, days):
        self._days = days

    async def get(self, key):
        return {"trial_per_phone_days": self._days}


def _trial_row(org_id):
    return SimpleNamespace(
        occurred_at=dt.datetime(2026, 11, 4, 9, 57, tzinfo=dt.UTC),
        company="AD GROUPS",
        number="917907793657",
        signup_source="whatsapp",
        trial_ends_at="2026-11-11T09:57:00+00:00",
        target_id=str(org_id or "6f1c1c8e-0000-4000-8000-000000000001"),
        organization_id=org_id,
    )


class _Audit:
    """SS-24: the Delete Tenant entry the trials route reads; none unless set."""

    deletion = None

    def __init__(self, conn):
        pass

    async def company_deleted(self, organization_id):
        return _Audit.deletion


@pytest.fixture(autouse=True)
def _no_deletion(monkeypatch):
    _Audit.deletion = None
    monkeypatch.setattr(people_router, "PostgresAdminAuditRepository", _Audit)


@pytest.mark.parametrize("days", [365, 0])
@pytest.mark.parametrize("org_id", [uuid.uuid4(), None])
async def test_trials_say_when_a_new_trial_is_possible(monkeypatch, days, org_id):
    conn = _Results([_trial_row(org_id)], [])
    monkeypatch.setattr(people_router, "get_engine", lambda: _Engine(conn))
    monkeypatch.setattr(people_router, "PostgresPlatformSettingsRepository", lambda c: _Rules(c, days))

    [trial] = await people_router.search_trials(q="+91 79077 93657", _admin={})

    assert trial.company == "AD GROUPS" and trial.number == "917907793657"
    assert trial.company_exists is (org_id is not None)
    expected = dt.datetime(2027, 11, 4, 9, 57, tzinfo=dt.UTC) if days else None
    assert trial.new_trial_from == expected
    assert "%7907793657%" in _values(conn.executed[0])


async def test_trials_need_a_number(monkeypatch):
    def _no_engine():
        raise AssertionError("the database must not be read")

    monkeypatch.setattr(people_router, "get_engine", _no_engine)
    assert await people_router.search_trials(q="Ravi", _admin={}) == []


# --- SA-26: Allow a new trial ---------------------------------------------------------


class _Results:
    """Each execute answers from the next list (trials, then allows)."""

    def __init__(self, *lists):
        self._lists = list(lists)
        self.executed = []

    async def execute(self, statement):
        self.executed.append(statement)
        return _Result(self._lists.pop(0))


async def test_an_allow_after_the_trial_makes_a_new_trial_possible_now(monkeypatch):
    allowed = dt.datetime(2026, 11, 4, 12, 0, tzinfo=dt.UTC)
    conn = _Results([_trial_row(None)], [SimpleNamespace(phone="917907793657", at=allowed)])
    monkeypatch.setattr(people_router, "get_engine", lambda: _Engine(conn))
    monkeypatch.setattr(people_router, "PostgresPlatformSettingsRepository", lambda c: _Rules(c, 365))

    [trial] = await people_router.search_trials(q="7907793657", _admin={})

    assert trial.allowed_at == allowed and trial.new_trial_from == allowed


async def test_an_allow_before_the_trial_changes_nothing(monkeypatch):
    earlier = dt.datetime(2026, 11, 1, tzinfo=dt.UTC)
    conn = _Results([_trial_row(None)], [SimpleNamespace(phone="917907793657", at=earlier)])
    monkeypatch.setattr(people_router, "get_engine", lambda: _Engine(conn))
    monkeypatch.setattr(people_router, "PostgresPlatformSettingsRepository", lambda c: _Rules(c, 365))

    [trial] = await people_router.search_trials(q="7907793657", _admin={})

    assert trial.allowed_at is None
    assert trial.new_trial_from == dt.datetime(2027, 11, 4, 9, 57, tzinfo=dt.UTC)


async def test_allow_trial_records_the_numbers_digits(monkeypatch):
    recorded = []

    async def fake_record(conn, **kwargs):
        recorded.append(kwargs)
        return SimpleNamespace(occurred_at=dt.datetime(2026, 11, 4, tzinfo=dt.UTC))

    monkeypatch.setattr(people_router, "get_engine", lambda: _Engine(_Conn([])))
    monkeypatch.setattr(people_router, "record_admin_action", fake_record)
    admin = {"sub": str(uuid.uuid4()), "name": "Adarsh admin"}

    done = await people_router.allow_trial(people_router.AllowTrial(number="+91 79077 93657"), admin=admin)

    assert done.number == "917907793657"
    [entry] = recorded
    assert entry["action"] == "signup.trial_allowed"
    assert entry["details"] == {"phone": "917907793657"} and entry["target_id"] == "917907793657"
    assert entry["actor"].label == "Adarsh admin"


async def test_allow_trial_needs_the_full_number(monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setattr(people_router, "get_engine", lambda: (_ for _ in ()).throw(AssertionError("no write")))
    with pytest.raises(HTTPException) as exc:
        await people_router.allow_trial(people_router.AllowTrial(number="3657"), admin={})
    assert exc.value.status_code == 422


async def test_ss24_a_deleted_trial_shows_what_is_left_and_is_possible_now(monkeypatch):
    deleted_at = dt.datetime(2026, 11, 6, 9, 57, tzinfo=dt.UTC)  # 2 days into 7
    _Audit.deletion = SimpleNamespace(deleted_at=deleted_at, trial_ends_at=None)
    conn = _Results([_trial_row(None)], [])
    monkeypatch.setattr(people_router, "get_engine", lambda: _Engine(conn))
    monkeypatch.setattr(people_router, "PostgresPlatformSettingsRepository", lambda c: _Rules(c, 365))

    [trial] = await people_router.search_trials(q="7907793657", _admin={})

    assert trial.deleted_at == deleted_at
    assert trial.trial_left_seconds == 5 * 86400
    assert trial.new_trial_from == deleted_at


async def test_ss24_a_deleted_trial_used_up_shows_zero_and_waits(monkeypatch):
    _Audit.deletion = SimpleNamespace(deleted_at=dt.datetime(2026, 11, 20, tzinfo=dt.UTC), trial_ends_at=None)
    conn = _Results([_trial_row(None)], [])
    monkeypatch.setattr(people_router, "get_engine", lambda: _Engine(conn))
    monkeypatch.setattr(people_router, "PostgresPlatformSettingsRepository", lambda c: _Rules(c, 365))

    [trial] = await people_router.search_trials(q="7907793657", _admin={})

    assert trial.trial_left_seconds == 0
    assert trial.new_trial_from == dt.datetime(2027, 11, 4, 9, 57, tzinfo=dt.UTC)
