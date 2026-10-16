"""BE-03 step 1: the company bound for a request/message, and how it reaches
a transaction (no database)."""

from __future__ import annotations

import uuid

from mesiri.infrastructure.postgres import tenant
from mesiri.infrastructure.postgres.tenant import (
    TENANT_SETTING,
    TenantResetMiddleware,
    TenantScopedEngine,
    apply_tenant,
    bind_tenant,
    current_tenant,
    tenant_scope,
)

ORG = uuid.UUID("11111111-1111-4111-8111-111111111111")
OTHER = uuid.UUID("22222222-2222-4222-8222-222222222222")


class _Conn:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def execute(self, statement, params=None):
        self.calls.append(dict(params or {}))


def test_scope_binds_and_restores() -> None:
    assert current_tenant() is None
    with tenant_scope(ORG):
        assert current_tenant() == ORG
        with tenant_scope(None):
            assert current_tenant() is None
        assert current_tenant() == ORG
    assert current_tenant() is None


def test_ids_in_every_form_the_code_carries() -> None:
    with tenant_scope(str(ORG)):
        assert current_tenant() == ORG
    with tenant_scope(f"ctx_org_{ORG}"):
        assert current_tenant() == ORG
    with tenant_scope("not-a-company"):
        assert current_tenant() is None  # cleared, never guessed


async def test_apply_sets_the_transaction_local_setting_only_when_bound() -> None:
    conn = _Conn()
    await apply_tenant(conn)  # type: ignore[arg-type]
    assert conn.calls == []

    with tenant_scope(ORG):
        await apply_tenant(conn)  # type: ignore[arg-type]
    assert conn.calls == [{"setting": TENANT_SETTING, "org": str(ORG)}]

    await apply_tenant(conn, OTHER)  # type: ignore[arg-type]
    assert conn.calls[-1]["org"] == str(OTHER)


async def test_scoped_engine_applies_on_begin_and_connect() -> None:
    conn = _Conn()

    class _Ctx:
        async def __aenter__(self):
            return conn

        async def __aexit__(self, *exc):
            return None

    class _Engine:
        def begin(self):
            return _Ctx()

        def connect(self):
            return _Ctx()

        dialect = "postgresql"

    engine = TenantScopedEngine(_Engine())  # type: ignore[arg-type]
    with tenant_scope(ORG):
        async with engine.begin() as c:
            assert c is conn
        async with engine.connect():
            pass
    assert [c["org"] for c in conn.calls] == [str(ORG), str(ORG)]
    assert engine.dialect == "postgresql"  # everything else passes through


async def test_every_request_starts_with_no_company_and_leaves_none_behind() -> None:
    seen: list[uuid.UUID | None] = []

    async def app(scope, receive, send):
        seen.append(current_tenant())
        bind_tenant(OTHER)  # what get_auth_context does mid-request

    middleware = TenantResetMiddleware(app)
    with tenant_scope(ORG):  # e.g. left over from a previous request on this task
        await middleware({"type": "http"}, None, None)
        assert current_tenant() == ORG  # restored for the caller
    await middleware({"type": "http"}, None, None)
    assert seen == [None, None]
    assert tenant._current.get() is None
