"""BE-01: WhatsApp identity and scope, read straight from the main tables.

Builds one company world in the main tables and checks what every context
port answers. Covers the cases the rules care about: org-wide users by role
and by access policy, plain members, explicit-site members, inactive users and
sites, projects not on track, an expired trial, a suspended company, replies
and open workflows. (Until BE-01 step 3 this compared the answers with the old
``context_*`` copy; they matched.)
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from tests.fixtures.db import build_sync_engine

from context.identity_bridge import (
    context_organization_id,
    context_project_id,
    context_site_id,
    context_user_id,
)
from context.main_table_repositories import (
    MainContextPreferenceRepository,
    MainExternalIdentityRepository,
    MainIdentityBridgeRepository,
    MainMembershipRepository,
    MainProjectRepository,
    MainReplyContextProvider,
    MainSiteRepository,
    MainWorkflowContextProvider,
)
from context.runtime import _LazyAsyncEngine

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

    yield ids
    engine.dispose()


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


@pytest.fixture
def engine():
    return _LazyAsyncEngine()


def _ids(items, attr):
    return {getattr(i, attr) for i in items}


@pytest.mark.anyio
async def test_identity_and_membership(world, engine):
    identities = MainExternalIdentityRepository(engine)
    memberships = MainMembershipRepository(engine)
    for n, key in enumerate(_USERS, start=1):
        identity = await identities.find_identity(provider="whatsapp", external_subject=_phone(n))
        assert identity is not None and identity.user_id == context_user_id(world[key])
        user = await identities.get_user(context_user_id(world[key]))
        assert user.is_active is (key != "inactive")
        listed = await memberships.list_active_memberships(context_user_id(world[key]))
        if key in ("expired_user", "suspended_user", "no_org"):
            assert listed == []
        else:
            assert [m.organization_id for m in listed] == [context_organization_id(world["org"])]
    assert await identities.find_identity(provider="whatsapp", external_subject="+1 000") is None
    assert await identities.find_identity(provider="sms", external_subject=_phone(1)) is None
    for key, active in (("org", True), ("org_expired", False), ("org_suspended", False)):
        org = await memberships.get_organization(context_organization_id(world[key]))
        assert org.is_active is active


@pytest.mark.anyio
async def test_projects_each_user_reaches(world, engine):
    projects = MainProjectRepository(engine)
    org = context_organization_id(world["org"])
    alpha, beta = context_project_id(world["p_alpha"]), context_project_id(world["p_beta"])
    expected = {
        "admin": {alpha, beta},  # org-wide by role; on-track projects only
        "policy_user": {alpha, beta},  # org-wide by access policy
        "member": {alpha},  # p_paused is not on track
        "explicit": {beta},
        "inactive": {alpha},
    }
    for key, want in expected.items():
        u = context_user_id(world[key])
        assert (
            _ids(
                await projects.list_authorized_projects(organization_id=org, user_id=u),
                "project_id",
            )
            == want
        )
        got = await projects.get_authorized_project(
            organization_id=org, user_id=u, project_id=context_project_id(world["p_paused"])
        )
        assert got is None
    member = context_user_id(world["member"])
    found = await projects.find_authorized_projects_by_name(
        organization_id=org, user_id=member, name="ALPHA"
    )
    assert _ids(found, "project_id") == {alpha}
    assert await projects.get_project_in_org(organization_id=org, project_id=beta) is not None
    other = context_project_id(world["p_other_org"])
    assert await projects.get_project_in_org(organization_id=org, project_id=other) is None


@pytest.mark.anyio
async def test_sites_each_user_reaches(world, engine):
    sites = MainSiteRepository(engine)
    org = context_organization_id(world["org"])

    def sid(key):
        return context_site_id(world[key])

    async def reachable(user_key):
        u = context_user_id(world[user_key])
        out = set()
        for key in ("s_a1", "s_a2", "s_b1", "s_inactive", "s_paused"):
            if await sites.get_authorized_site(organization_id=org, user_id=u, site_id=sid(key)):
                out.add(key)
        return out

    assert await reachable("admin") == {"s_a1", "s_a2", "s_b1", "s_paused"}
    # A site is reachable through membership even when its project is not on
    # track (kept as it was, see main_table_repositories.py).
    assert await reachable("member") == {"s_a1", "s_a2", "s_paused"}
    assert await reachable("explicit") == {"s_b1"}
    member = context_user_id(world["member"])
    by_name = await sites.find_authorized_sites_by_name(
        organization_id=org, user_id=member, name="block a"
    )
    assert _ids(by_name, "site_id") == {sid("s_a1")}
    admin = context_user_id(world["admin"])
    by_name = await sites.find_authorized_sites_by_name(
        organization_id=org, user_id=admin, name="Block A"
    )
    assert _ids(by_name, "site_id") == {sid("s_a1"), sid("s_b1")}
    in_beta = await sites.find_authorized_sites_by_name(
        organization_id=org,
        user_id=admin,
        name="Block A",
        project_id=context_project_id(world["p_beta"]),
    )
    assert _ids(in_beta, "site_id") == {sid("s_b1")}
    assert await sites.get_site_in_org(organization_id=org, site_id=sid("s_inactive")) is None
    prefs = MainContextPreferenceRepository()
    assert await prefs.get_preferences(organization_id=org, user_id=member) is None


@pytest.mark.anyio
async def test_reply_workflow_and_bridge(world, engine):
    org = context_organization_id(world["org"])
    reply = MainReplyContextProvider(engine)
    assert await reply.context_for_reply(
        organization_id=org, replied_to_message_id=f"wamid-{_TAG}"
    ) == (context_project_id(world["p_alpha"]), context_site_id(world["s_a2"]))
    assert await reply.context_for_reply(organization_id=org, replied_to_message_id="nope") is None
    other_org = context_organization_id(world["org_expired"])
    assert (
        await reply.context_for_reply(
            organization_id=other_org, replied_to_message_id=f"wamid-{_TAG}"
        )
        is None
    )
    workflow = MainWorkflowContextProvider(engine)
    assert await workflow.active_workflow_context(
        organization_id=org, user_id=context_user_id(world["member"])
    ) == (context_project_id(world["p_alpha"]), context_site_id(world["s_a1"]))
    assert (
        await workflow.active_workflow_context(
            organization_id=org, user_id=context_user_id(world["admin"])
        )
        is None
    )
    bridge = MainIdentityBridgeRepository(engine)
    assert await bridge.canonical_organization_id(org) == str(world["org"])
    member = context_user_id(world["member"])
    assert await bridge.canonical_user_id(member) == str(world["member"])
    beta = context_project_id(world["p_beta"])
    assert await bridge.canonical_project_id(beta) == str(world["p_beta"])
    assert await bridge.canonical_site_id(context_site_id(world["s_b1"])) == str(world["s_b1"])
    assert await bridge.canonical_user_id("ctx_user_not-a-uuid") is None
    assert await bridge.canonical_site_id(context_site_id(uuid.uuid4())) is None
