"""BE-04: every dashboard / control-panel route that saves a WhatsApp number
refuses one already held by another person, with a message that names nobody.

The digits comparison itself is tested against Postgres in
backend/tests/integration/test_whatsapp_number_unique_postgres.py; here the
check is stubbed to "taken" and the routes must stop before writing.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from admin import router as admin_router
from mesiri.application.identity.phone_numbers import NUMBER_TAKEN_MESSAGE
from mesiri.domains.users import router as backend_users_router
from users import router as users_router

_ORG = uuid.uuid4()
_USER = uuid.uuid4()


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def first(self):
        return self._rows[0] if self._rows else None


class _Conn:
    def __init__(self, results):
        self._results = list(results)
        self.executed = []

    async def execute(self, statement, *_args):
        self.executed.append(statement)
        return _Result(self._results.pop(0))


class _Ctx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *_exc):
        return None


class _Engine:
    def __init__(self, conn):
        self._conn = conn

    def begin(self):
        return _Ctx(self._conn)

    connect = begin


def _taken(calls: list):
    async def fake(_conn, number, *, except_user_id=None):
        calls.append((number, except_user_id))
        return True

    return fake


def _assert_refused(exc: pytest.ExceptionInfo[HTTPException]) -> None:
    assert exc.value.status_code == 409
    assert exc.value.detail == NUMBER_TAKEN_MESSAGE


async def test_dashboard_add_user_refuses_a_taken_number(monkeypatch):
    calls: list = []
    conn = _Conn([[]])  # email free
    monkeypatch.setattr(users_router, "get_engine", lambda: _Engine(conn))
    monkeypatch.setattr(users_router, "whatsapp_number_taken", _taken(calls))

    body = users_router.UserCreate(
        email="a@x.example", password="pw", full_name="A", role="SITE_ENGINEER",
        whatsapp_number="+91 98765 43210",
    )
    with pytest.raises(HTTPException) as exc:
        await users_router.create_user(body, admin_payload={"org": str(_ORG)})

    _assert_refused(exc)
    assert calls == [("+91 98765 43210", None)]
    assert len(conn.executed) == 1  # no insert


async def test_dashboard_edit_user_refuses_a_taken_number(monkeypatch):
    calls: list = []
    conn = _Conn([[SimpleNamespace(id=_USER)]])
    monkeypatch.setattr(users_router, "get_engine", lambda: _Engine(conn))
    monkeypatch.setattr(users_router, "whatsapp_number_taken", _taken(calls))

    with pytest.raises(HTTPException) as exc:
        await users_router.update_user(
            _USER,
            users_router.UserUpdate(whatsapp_number=" 919876543210 "),
            admin_payload={"org": str(_ORG)},
        )

    _assert_refused(exc)
    assert calls == [("919876543210", _USER)]
    assert len(conn.executed) == 1  # no update


async def test_control_panel_add_user_refuses_a_taken_number(monkeypatch):
    calls: list = []
    conn = _Conn([[SimpleNamespace(id=_ORG)], []])  # org exists, email free
    monkeypatch.setattr(admin_router, "get_engine", lambda: _Engine(conn))
    monkeypatch.setattr(admin_router, "whatsapp_number_taken", _taken(calls))

    body = admin_router.OrgUserCreate(
        email="a@x.example", password="pw", full_name="A", role="SITE_ENGINEER",
        whatsapp_number="919876543210",
    )
    with pytest.raises(HTTPException) as exc:
        await admin_router.create_organization_user(_ORG, body, _admin={})

    _assert_refused(exc)
    assert calls == [("919876543210", None)]
    assert len(conn.executed) == 2  # no insert


async def test_control_panel_edit_user_refuses_a_taken_number(monkeypatch):
    calls: list = []
    row = SimpleNamespace(id=_USER, role="SITE_ENGINEER", whatsapp_number=None, full_name="A")
    conn = _Conn([[row]])
    monkeypatch.setattr(admin_router, "get_engine", lambda: _Engine(conn))
    monkeypatch.setattr(admin_router, "whatsapp_number_taken", _taken(calls))

    with pytest.raises(HTTPException) as exc:
        await admin_router.update_organization_user_profile(
            _ORG, _USER, admin_router.OrgUserProfileUpdate(whatsapp_number="919876543210"),
            _admin={},
        )

    _assert_refused(exc)
    assert calls == [("919876543210", _USER)]
    assert len(conn.executed) == 1  # no update


async def test_backend_add_and_edit_user_refuse_a_taken_number(monkeypatch):
    calls: list = []
    monkeypatch.setattr(backend_users_router, "whatsapp_number_taken", _taken(calls))
    admin = {"org": str(_ORG)}

    conn = _Conn([[]])  # email free
    body = backend_users_router.UserCreate(
        email="a@x.example", password="pw", full_name="A", role="SITE_ENGINEER",
        whatsapp_number="919876543210",
    )
    with pytest.raises(HTTPException) as exc:
        await backend_users_router.create_user(body, admin=admin, conn=conn)
    _assert_refused(exc)
    assert len(conn.executed) == 1

    conn = _Conn([[SimpleNamespace(id=_USER)]])
    with pytest.raises(HTTPException) as exc:
        await backend_users_router.update_user(
            _USER, backend_users_router.UserUpdate(whatsapp_number="919876543210"),
            admin=admin, conn=conn,
        )
    _assert_refused(exc)
    assert len(conn.executed) == 1
    assert calls == [("919876543210", None), ("919876543210", _USER)]
