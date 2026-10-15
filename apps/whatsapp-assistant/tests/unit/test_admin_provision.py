"""SS-03: the control panel's `/provision` goes through the one create-company
step, and the new rows are made visible to WhatsApp afterwards."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from fastapi import HTTPException

from admin import router as admin_router
from mesiri.application.organizations.create_company import (
    CompanyCreationError,
    CreatedCompany,
    CreatedSite,
)


class _Begin:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return None


class _Engine:
    def begin(self):
        return _Begin()


def _created(**overrides) -> CreatedCompany:
    fields = {
        "organization_id": uuid.uuid4(),
        "name": "Acme Construction",
        "deployment_type": "SaaS",
        "db_route": "shared-cluster-01",
        "status": "active",
        "signup_source": "superadmin",
        "timezone": "Asia/Kolkata",
        "created_at": dt.datetime(2026, 10, 15, tzinfo=dt.UTC),
        "trial_started_at": None,
        "trial_ends_at": None,
        "owner_user_id": uuid.uuid4(),
        "owner_email": "john@acme.example",
        "owner_whatsapp_number": None,
        "project_id": None,
        "site_id": None,
    }
    fields.update(overrides)
    return CreatedCompany(**fields)


@pytest.fixture
def wired(monkeypatch):
    calls: dict[str, list] = {"new": [], "projected": []}
    result: dict[str, object] = {}

    async def fake_create(conn, new, *, actor=None):
        calls["new"].append(new)
        calls.setdefault("actor", []).append(actor)
        if isinstance(result.get("value"), Exception):
            raise result["value"]
        return result["value"]

    async def fake_project(entity_type, entity_id):
        calls["projected"].append((entity_type, entity_id))

    monkeypatch.setattr(admin_router, "get_engine", lambda: _Engine())
    monkeypatch.setattr(admin_router, "create_company", fake_create)
    from context import projection_hooks

    monkeypatch.setattr(projection_hooks, "project_entity", fake_project)
    return calls, result


async def test_original_control_panel_request_still_works(wired) -> None:
    calls, result = wired
    created = _created()
    result["value"] = created
    body = admin_router.OrganizationProvision(
        name="Acme Construction",
        deployment_type="SaaS",
        db_route="shared-cluster-01",
        admin_name="John Doe",
        admin_email="john@acme.example",
        admin_password="Temp-pass-1",
    )

    admin_id = uuid.uuid4()
    response = await admin_router.provision_tenant(body, {"sub": str(admin_id), "name": "Ops"})

    # Recorded in the audit log as the platform admin who did it (BE-05).
    actor = calls["actor"][0]
    assert (actor.kind, actor.user_id, actor.label) == ("platform_admin", admin_id, "Ops")
    new = calls["new"][0]
    assert new.owner_email == "john@acme.example"
    assert new.owner_password == "Temp-pass-1"
    assert new.start_as == "active"
    assert new.signup_source == "superadmin"
    assert response.id == created.organization_id
    assert response.status == "active"
    assert response.owner_user_id == created.owner_user_id
    assert calls["projected"] == [
        ("organization", created.organization_id),
        ("user", created.owner_user_id),
        ("membership", created.owner_user_id),
    ]


async def test_first_project_and_site_are_projected(wired) -> None:
    calls, result = wired
    created = _created(project_id=uuid.uuid4(), site_id=uuid.uuid4(), status="trial")
    result["value"] = created
    body = admin_router.OrganizationProvision(
        name="Suresh Builders",
        admin_name="Suresh",
        admin_whatsapp_number="9876543210",
        project_name="Green Villa",
        start_as="trial",
    )

    await admin_router.provision_tenant(body, {})

    assert calls["new"][0].owner_phone == "9876543210"
    assert ("project", created.project_id) in calls["projected"]
    assert ("site", created.site_id) in calls["projected"]


async def test_several_sites_are_passed_on_returned_and_projected(wired) -> None:
    calls, result = wired
    sites = (CreatedSite(uuid.uuid4(), "Block A"), CreatedSite(uuid.uuid4(), "Block B"))
    created = _created(project_id=uuid.uuid4(), site_id=sites[0].site_id, sites=sites)
    result["value"] = created
    body = admin_router.OrganizationProvision(
        name="Skyline Builders",
        admin_name="Ravi",
        admin_whatsapp_number="9876543210",
        project_name="Skyline Apartments",
        site_names=["Block A", "Block B"],
        start_as="trial",
    )

    response = await admin_router.provision_tenant(body, {})

    assert calls["new"][0].site_names == ("Block A", "Block B")
    assert [(s.site_id, s.name) for s in response.sites] == [
        (sites[0].site_id, "Block A"),
        (sites[1].site_id, "Block B"),
    ]
    assert response.site_id == sites[0].site_id
    projected_sites = [eid for kind, eid in calls["projected"] if kind == "site"]
    assert projected_sites == [sites[0].site_id, sites[1].site_id]


@pytest.mark.parametrize(("conflict", "status"), [(True, 409), (False, 400)])
async def test_refusals_map_to_http_errors_and_project_nothing(wired, conflict, status) -> None:
    calls, result = wired
    result["value"] = CompanyCreationError("nope", conflict=conflict)
    body = admin_router.OrganizationProvision(name="X", admin_name="Y", admin_email="y@x.example")

    with pytest.raises(HTTPException) as exc:
        await admin_router.provision_tenant(body, {})

    assert exc.value.status_code == status
    assert exc.value.detail == "nope"
    assert calls["projected"] == []
