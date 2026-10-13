"""BE-01: the main-table lookups answer exactly what the context copy answers.

Builds one company world in the main tables, projects it into the copy with
the real sync (IdentityProjectionService.reconcile_all), then asks every
context port the same questions through both implementations and requires
identical answers. Covers the cases the copy's rules care about: org-wide
users by role and by access policy, plain members, explicit-site members,
inactive users and sites, projects not on track, an expired trial, a
suspended company, replies and open workflows.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from context.identity_bridge import (
    PostgresIdentityBridgeRepository,
    context_organization_id,
    context_project_id,
    context_site_id,
    context_user_id,
)
from context.identity_projection import IdentityProjectionService, build_sync_engine
from context.main_table_repositories import (
    MainContextPreferenceRepository,
    MainExternalIdentityRepository,
    MainIdentityBridgeRepository,
    MainMembershipRepository,
    MainProjectRepository,
    MainReplyContextProvider,
    MainRolePermissionRepository,
    MainSiteRepository,
    MainWorkflowContextProvider,
)
from context.postgres_repositories import (
    PostgresContextPreferenceRepository,
    PostgresExternalIdentityRepository,
    PostgresMembershipRepository,
    PostgresProjectRepository,
    PostgresReplyContextProvider,
    PostgresRolePermissionRepository,
    PostgresSiteRepository,
    PostgresWorkflowContextProvider,
)
from context.runtime import _LazyAsyncEngine
from context.shadow import _plain

pytestmark = pytest.mark.integration

_TAG = uuid.uuid4().hex[:8]


def _phone(n: int) -> str:
    # Unique per run so reruns and other tests never collide on a number.
    return f"+91 {int(_TAG, 16) % 90000 + 10000} {n:05d}"


@pytest.fixture(scope="module")
def world():
    engine = build_sync_engine()
    ids: dict[str, uuid.UUID] = {
        k: uuid.uuid4()
        for k in (
            "org",
            "org_expired",
            "org_suspended",
            "admin",
            "policy_user",
            "member",
            "explicit",
            "inactive",
            "expired_user",
            "suspended_user",
            "no_org",
            "p_alpha",
            "p_beta",
            "p_paused",
            "p_other_org",
            "s_a1",
            "s_a2",
            "s_b1",
            "s_inactive",
            "s_paused",
            "msg",
            "wf",
        )
    }
    now = datetime.now(UTC)
    with engine.begin() as c:

        def org(key, status, trial_ends_at=None):
            c.execute(
                text(
                    "INSERT INTO organizations (id, name, status, trial_ends_at, db_route, "
                    "deployment_type) VALUES (:id, :n, :s, :t, 'shared', 'shared')"
                ),
                {"id": ids[key], "n": f"{key}-{_TAG}", "s": status, "t": trial_ends_at},
            )

        org("org", "active")
        org("org_expired", "trial", now - timedelta(days=1))
        org("org_suspended", "suspended")

        def user(key, org_key, n, role="SITE_ENGINEER", status="active", policy=None):
            c.execute(
                text(
                    "INSERT INTO users (id, full_name, organization_id, whatsapp_number, status, "
                    "role, hashed_password, access_policy) "
                    "VALUES (:id, :n, :o, :wa, :s, :r, 'x', CAST(:p AS jsonb))"
                ),
                {
                    "id": ids[key],
                    "n": key,
                    "o": ids[org_key] if org_key else None,
                    "wa": _phone(n),
                    "s": status,
                    "r": role,
                    "p": json.dumps(policy) if policy is not None else None,
                },
            )

        user("admin", "org", 1, role="ADMIN")
        user("policy_user", "org", 2, policy={"mode": "all_projects"})
        user("member", "org", 3)
        user("explicit", "org", 4)
        user("inactive", "org", 5, status="inactive")
        user("expired_user", "org_expired", 6)
        user("suspended_user", "org_suspended", 7)
        user("no_org", None, 8)

        def project(key, org_key, status="on_track"):
            c.execute(
                text(
                    "INSERT INTO projects (id, organization_id, name, status) "
                    "VALUES (:id, :o, :n, :s)"
                ),
                {"id": ids[key], "o": ids[org_key], "n": f"{key} tower", "s": status},
            )

        project("p_alpha", "org")
        project("p_beta", "org")
        project("p_paused", "org", status="on_hold")
        project("p_other_org", "org_expired")

        def site(key, project_key, org_key="org", status="active", name=None):
            c.execute(
                text(
                    "INSERT INTO sites (id, organization_id, project_id, name, status) "
                    "VALUES (:id, :o, :p, :n, :s)"
                ),
                {
                    "id": ids[key],
                    "o": ids[org_key],
                    "p": ids[project_key],
                    "n": name or key,
                    "s": status,
                },
            )

        site("s_a1", "p_alpha", name="Block A")
        site("s_a2", "p_alpha", name="Block B")
        site("s_b1", "p_beta", name="Block A")
        site("s_inactive", "p_alpha", status="inactive")
        site("s_paused", "p_paused")

        def member(user_key, project_key, mode="all_sites"):
            c.execute(
                text(
                    "INSERT INTO project_members (id, project_id, user_id, role, site_access_mode) "
                    "VALUES (:id, :p, :u, 'member', :m)"
                ),
                {"id": uuid.uuid4(), "p": ids[project_key], "u": ids[user_key], "m": mode},
            )

        member("member", "p_alpha")
        member("member", "p_paused")
        member("explicit", "p_beta", mode="explicit")
        member("inactive", "p_alpha")
        c.execute(
            text("INSERT INTO site_members (id, site_id, user_id) VALUES (:id, :s, :u)"),
            {"id": uuid.uuid4(), "s": ids["s_b1"], "u": ids["explicit"]},
        )
        c.execute(
            text(
                "INSERT INTO inbound_messages (id, correlation_id, dedup_key, message_type, "
                "raw_payload, sender_wa_id, organization_id, project_id, site_id) "
                "VALUES (:id, :c, :d, 'text', '{}', '1', :o, :p, :s)"
            ),
            {
                "id": ids["msg"],
                "c": f"corr-{_TAG}",
                "d": f"wamid-{_TAG}",
                "o": ids["org"],
                "p": ids["p_alpha"],
                "s": ids["s_a2"],
            },
        )
        c.execute(
            text(
                "INSERT INTO workflow_instances (id, organization_id, user_id, workflow_key, "
                "phase, state) VALUES (:id, :o, :u, 'labour', 'awaiting_confirmation', "
                "CAST(:st AS jsonb))"
            ),
            {
                "id": ids["wf"],
                "o": ids["org"],
                "u": ids["member"],
                "st": json.dumps({"project_id": str(ids["p_alpha"]), "site_id": str(ids["s_a1"])}),
            },
        )

    service = IdentityProjectionService(engine=engine)
    report = service.reconcile_all()
    assert not [e for e in report.errors if any(str(v) in e for v in ids.values())]
    # reconcile_all only syncs memberships for users with a project_members
    # row, so an org-wide user with none (the admin here) never gets site
    # memberships from it -- only from a live membership hook. Run that hook
    # for everyone: the copy in its intended, fully synced state is what the
    # main tables must match. (The partial state is drift, which shadow mode
    # will show in production.)
    for key in (
        "admin",
        "policy_user",
        "member",
        "explicit",
        "inactive",
        "expired_user",
        "suspended_user",
        "no_org",
    ):
        service.project_one("membership", ids[key])
    yield ids
    engine.dispose()


def _ports():
    engine = _LazyAsyncEngine()
    return {
        "identities": (
            PostgresExternalIdentityRepository(engine),
            MainExternalIdentityRepository(engine),
        ),
        "memberships": (PostgresMembershipRepository(engine), MainMembershipRepository(engine)),
        "roles": (PostgresRolePermissionRepository(engine), MainRolePermissionRepository()),
        "projects": (PostgresProjectRepository(engine), MainProjectRepository(engine)),
        "sites": (PostgresSiteRepository(engine), MainSiteRepository(engine)),
        "preferences": (
            PostgresContextPreferenceRepository(engine),
            MainContextPreferenceRepository(),
        ),
        "reply": (PostgresReplyContextProvider(engine), MainReplyContextProvider(engine)),
        "workflow": (PostgresWorkflowContextProvider(engine), MainWorkflowContextProvider(engine)),
        "bridge": (PostgresIdentityBridgeRepository(engine), MainIdentityBridgeRepository(engine)),
    }


async def _same(port, method, **kwargs):
    old_impl, new_impl = _ports()[port]
    old = await getattr(old_impl, method)(**kwargs)
    new = await getattr(new_impl, method)(**kwargs)
    assert _plain(old) == _plain(new), f"{port}.{method}({kwargs}): copy={old} main={new}"
    return new


_USERS = (
    "admin",
    "policy_user",
    "member",
    "explicit",
    "inactive",
    "expired_user",
    "suspended_user",
    "no_org",
)


@pytest.mark.anyio
async def test_identity_and_membership_match(world):
    for n, key in enumerate(_USERS, start=1):
        identity = await _same(
            "identities", "find_identity", provider="whatsapp", external_subject=_phone(n)
        )
        assert identity is not None and identity.user_id == context_user_id(world[key])
        await _same("identities", "get_user", user_id=context_user_id(world[key]))
        memberships = await _same(
            "memberships", "list_active_memberships", user_id=context_user_id(world[key])
        )
        for m in memberships:
            await _same("roles", "role_ids_for_membership", membership_id=m.membership_id)
            await _same("roles", "permissions_for_membership", membership_id=m.membership_id)
    await _same("identities", "find_identity", provider="whatsapp", external_subject="+1 000")
    for key in ("org", "org_expired", "org_suspended"):
        await _same(
            "memberships", "get_organization", organization_id=context_organization_id(world[key])
        )


@pytest.mark.anyio
async def test_projects_and_sites_match_for_every_user(world):
    org = context_organization_id(world["org"])
    projects = ("p_alpha", "p_beta", "p_paused", "p_other_org")
    sites = ("s_a1", "s_a2", "s_b1", "s_inactive", "s_paused")
    for key in _USERS:
        u = context_user_id(world[key])
        listed = await _same("projects", "list_authorized_projects", organization_id=org, user_id=u)
        if key == "admin":
            assert {p.project_id for p in listed} == {
                context_project_id(world["p_alpha"]),
                context_project_id(world["p_beta"]),
            }
        for name in ("tower", "alpha", "nothing"):
            await _same(
                "projects",
                "find_authorized_projects_by_name",
                organization_id=org,
                user_id=u,
                name=name,
            )
        for p in projects:
            pid = context_project_id(world[p])
            await _same(
                "projects", "get_authorized_project", organization_id=org, user_id=u, project_id=pid
            )
            await _same("projects", "get_project_in_org", organization_id=org, project_id=pid)
            await _same(
                "sites",
                "find_authorized_sites_by_name",
                organization_id=org,
                user_id=u,
                name="block a",
                project_id=pid,
            )
        await _same(
            "sites", "find_authorized_sites_by_name", organization_id=org, user_id=u, name="Block A"
        )
        for s in sites:
            sid = context_site_id(world[s])
            await _same("sites", "get_authorized_site", organization_id=org, user_id=u, site_id=sid)
            await _same("sites", "get_site_in_org", organization_id=org, site_id=sid)
        await _same("preferences", "get_preferences", organization_id=org, user_id=u)


@pytest.mark.anyio
async def test_reply_workflow_and_bridge_match(world):
    org = context_organization_id(world["org"])
    reply = await _same(
        "reply", "context_for_reply", organization_id=org, replied_to_message_id=f"wamid-{_TAG}"
    )
    assert reply == (context_project_id(world["p_alpha"]), context_site_id(world["s_a2"]))
    await _same("reply", "context_for_reply", organization_id=org, replied_to_message_id="nope")
    await _same(
        "reply",
        "context_for_reply",
        organization_id=context_organization_id(world["org_expired"]),
        replied_to_message_id=f"wamid-{_TAG}",
    )
    for key in ("member", "admin"):
        await _same(
            "workflow",
            "active_workflow_context",
            organization_id=org,
            user_id=context_user_id(world[key]),
        )
    await _same("bridge", "canonical_organization_id", context_organization_id=org)
    await _same("bridge", "canonical_user_id", context_user_id=context_user_id(world["member"]))
    await _same(
        "bridge", "canonical_project_id", context_project_id=context_project_id(world["p_beta"])
    )
    await _same("bridge", "canonical_site_id", context_site_id=context_site_id(world["s_b1"]))
    await _same("bridge", "canonical_user_id", context_user_id="ctx_user_not-a-uuid")
    await _same("bridge", "canonical_site_id", context_site_id=context_site_id(uuid.uuid4()))


@pytest.mark.anyio
async def test_shadow_records_drift_in_the_mismatch_table(world):
    """Drift in the copy (a membership the dashboard granted but the copy
    missed) answers from the copy, and lands in identity_shadow_mismatches."""
    import asyncio

    from context.shadow import MismatchRecorder, ShadowPort

    engine = build_sync_engine()
    member = context_user_id(world["member"])
    with engine.begin() as c:
        c.execute(text("DELETE FROM project_memberships WHERE user_id = :u"), {"u": member})
        c.execute(text("DELETE FROM site_memberships WHERE user_id = :u"), {"u": member})
    lazy = _LazyAsyncEngine()
    port = ShadowPort(
        "projects",
        PostgresProjectRepository(lazy),
        MainProjectRepository(lazy),
        MismatchRecorder(lazy),
    )

    answer = await port.list_authorized_projects(
        organization_id=context_organization_id(world["org"]), user_id=member
    )
    await asyncio.sleep(0.5)  # the write happens off the request path

    assert answer == []  # the copy still answers
    with engine.connect() as c:
        row = c.execute(
            text(
                "SELECT hits, main_result FROM identity_shadow_mismatches "
                "WHERE port = 'projects' AND args->>'user_id' = :u"
            ),
            {"u": member},
        ).one()
    assert row.hits == 1
    assert row.main_result[0]["project_id"] == context_project_id(world["p_alpha"])
    IdentityProjectionService(engine=engine).project_one("membership", world["member"])
    engine.dispose()
