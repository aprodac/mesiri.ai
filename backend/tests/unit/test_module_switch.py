"""Unit tests for the per-company module switch (V1 tracker BE-06).

Two halves: the `enabled_modules` setting in the settings catalogue
(domains/organizations/settings.py), and the router gate that enforces it
(domains/shared/modules.py). The gate's most important property is what it
does NOT do: it never turns a request it can't attribute to a company into an
error, so adding it to a router can't break a route that worked before.
"""

from __future__ import annotations

import uuid

import jwt
import pytest
from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

from mesiri.domains.identity.auth_service import ALGORITHM, SECRET_KEY
from mesiri.domains.organizations import router as org_router
from mesiri.domains.organizations import settings
from mesiri.domains.shared import modules
from mesiri.infrastructure.postgres.dependency import get_db_conn

# --- the setting -------------------------------------------------------------


def test_default_is_every_module_on():
    """No row exists for any company until someone changes it, so the default
    is the behaviour of every existing company: everything on, as before."""
    assert settings.default_for(settings.ENABLED_MODULES) == list(settings.MODULES)


def test_v1_modules_are_known_and_include_dpr():
    assert set(settings.V1_MODULES) <= set(settings.MODULES)
    assert "dpr" in settings.V1_MODULES


def test_validate_canonicalises_order_case_and_duplicates():
    result = settings.validate(settings.ENABLED_MODULES, ["Materials", "labour", "labour"])
    assert result == ["dpr", "labour", "materials"]


def test_validate_always_keeps_dpr():
    assert settings.validate(settings.ENABLED_MODULES, []) == ["dpr"]


def test_validate_rejects_unknown_module():
    with pytest.raises(ValueError, match="unknown module"):
        settings.validate(settings.ENABLED_MODULES, ["dpr", "payroll"])


def test_validate_rejects_non_list():
    with pytest.raises(ValueError):
        settings.validate(settings.ENABLED_MODULES, "dpr")


@pytest.mark.parametrize(
    ("module", "stored", "expected"),
    [
        ("finance", ["dpr", "labour"], False),
        ("labour", ["dpr", "labour"], True),
        ("dpr", [], True),  # always on, even if a stored row omits it
        ("finance", "garbage", True),  # malformed row falls back to the default
        ("finance", None, True),
    ],
)
def test_module_enabled(module, stored, expected):
    assert settings.module_enabled(module, stored) is expected


def test_enabled_modules_is_superadmin_only():
    assert settings.ENABLED_MODULES in settings.SUPERADMIN_ONLY_KEYS


# --- the gate ----------------------------------------------------------------

ORG = uuid.uuid4()


def _token(org: str) -> str:
    return "Bearer " + jwt.encode(
        {"sub": str(uuid.uuid4()), "org": org, "role": "ADMIN"}, SECRET_KEY, algorithm=ALGORITHM
    )


@pytest.fixture
def client(monkeypatch):
    """A one-route app gated on `finance`, with the settings read faked."""
    stored: dict[uuid.UUID, object] = {}

    class FakeRepo:
        def __init__(self, conn):
            pass

        async def get(self, organization_id, key):
            assert key == settings.ENABLED_MODULES
            return stored.get(organization_id, settings.default_for(key))

    monkeypatch.setattr(modules, "PostgresOrganizationSettingsRepository", FakeRepo)

    router = APIRouter(dependencies=[Depends(modules.require_module("finance"))])

    @router.get("/thing")
    async def thing() -> dict:
        return {"ok": True}

    app = FastAPI()
    app.include_router(router)

    async def fake_conn():
        yield object()

    app.dependency_overrides[get_db_conn] = fake_conn
    test_client = TestClient(app)
    test_client.stored = stored  # type: ignore[attr-defined]
    return test_client


def test_gate_passes_when_module_is_on(client):
    assert client.get("/thing", headers={"Authorization": _token(str(ORG))}).status_code == 200


def test_gate_blocks_when_module_is_off(client):
    client.stored[ORG] = ["dpr", "labour"]
    response = client.get("/thing", headers={"Authorization": _token(str(ORG))})
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "MODULE_DISABLED"
    assert response.json()["detail"]["module"] == "finance"


def test_gate_never_rejects_a_request_without_a_company(client):
    """No token, a bad token, or a platform admin (empty org): the gate steps
    aside and leaves auth to the route, exactly as before it existed."""
    client.stored[ORG] = ["dpr"]
    assert client.get("/thing").status_code == 200
    assert client.get("/thing", headers={"Authorization": "Bearer nonsense"}).status_code == 200
    assert client.get("/thing", headers={"Authorization": _token("")}).status_code == 200


def test_unknown_module_name_fails_at_declaration():
    with pytest.raises(ValueError, match="unknown module"):
        modules.require_module("payroll")


# --- the customer settings endpoint -------------------------------------------


async def test_company_admin_cannot_change_modules():
    body = org_router.OrganizationSettingUpdate(key=settings.ENABLED_MODULES, value=["dpr"])
    with pytest.raises(HTTPException) as exc:
        await org_router.update_company_setting(
            body, admin={"org": str(ORG), "sub": str(uuid.uuid4())}, conn=None
        )
    assert exc.value.status_code == 403
