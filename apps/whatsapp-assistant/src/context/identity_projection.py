"""M6.5 identity projection — idempotent control-plane → context layer sync."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from mesiri.authorization.roles import is_org_wide
from mesiri.domains.organizations.lifecycle import is_operational

from .identity_bridge import (
    context_organization_id,
    context_project_id,
    context_site_id,
    context_user_id,
)

EntityType = Literal["organization", "user", "project", "site", "membership"]
WHATSAPP_PROVIDER = "whatsapp"


def _status_is(value: object, expected: str) -> bool:
    """Compare a status column case-insensitively.

    Organizations are conventionally stored "Active" and users "active",
    and writers have picked the wrong convention before -- the control
    panel's reactivate wrote "Active" for a user, which a case-sensitive
    check read as inactive and locked that person out of WhatsApp entirely.
    """
    return str(value or "").strip().lower() == expected.lower()


def _digits(value: str | None) -> str:
    """Phone numbers as digits only. Mirrors ``_digits`` in backend/postgres/actor.py."""
    return re.sub(r"\D", "", value or "")


@dataclass(slots=True)
class ReconcileReport:
    organizations: int = 0
    users: int = 0
    projects: int = 0
    sites: int = 0
    external_identities: int = 0
    memberships: int = 0
    errors: list[str] = field(default_factory=list)


def build_sync_engine() -> Engine:
    host = os.environ.get("MESIRI_POSTGRES__HOST", "localhost")
    port = os.environ.get("MESIRI_POSTGRES__PORT", "5432")
    user = os.environ.get("MESIRI_POSTGRES__USER", "mesiri")
    password = os.environ.get("MESIRI_POSTGRES__PASSWORD", "mesiri_local_dev")
    database = os.environ.get("MESIRI_POSTGRES__DATABASE", "mesiri")
    dsn = f"postgresql+psycopg://{user}:{password}@{host}:{port}/{database}"
    return create_engine(dsn, future=True)


class IdentityProjectionService:
    """One-way projection from control plane to context layer."""

    def __init__(self, engine: Engine | None = None) -> None:
        self._engine = engine or build_sync_engine()

    def project_one(self, entity_type: EntityType, canonical_id: UUID) -> None:
        with self._engine.begin() as conn:
            if entity_type == "organization":
                self._project_organization(conn, canonical_id)
            elif entity_type == "user":
                self._project_user(conn, canonical_id)
            elif entity_type == "project":
                self._project_project(conn, canonical_id)
            elif entity_type == "site":
                self._project_site(conn, canonical_id)
            elif entity_type == "membership":
                # canonical_id is the affected user_id here, not a membership
                # row id -- memberships are a set per user, so the natural
                # sync unit is "this user's whole membership set", same as
                # _project_user syncs one user's whole profile.
                self._project_membership(conn, canonical_id)

    def reconcile_all(self) -> ReconcileReport:
        report = ReconcileReport()
        with self._engine.begin() as conn:
            org_rows = conn.execute(text("SELECT id, name, status FROM organizations")).mappings()
            for row in org_rows:
                try:
                    self._project_organization(conn, row["id"])
                    report.organizations += 1
                except Exception as exc:  # noqa: BLE001
                    report.errors.append(f"organization {row['id']}: {exc}")

            user_rows = conn.execute(
                text("SELECT id, full_name, organization_id, whatsapp_number, status FROM users")
            ).mappings()
            for row in user_rows:
                try:
                    self._project_user(conn, row["id"])
                    report.users += 1
                    # _project_user writes an external_identities row for
                    # exactly the users whose whatsapp_number has digits (see
                    # its `if digits:` branch), so counting that condition
                    # here matches what was actually written without
                    # threading a return value back through project_one.
                    # Left uncounted, this field read 0 forever, which is
                    # actively misleading on the Sync Health page -- it looks
                    # like no WhatsApp numbers are linked at all.
                    if _digits(row["whatsapp_number"]):
                        report.external_identities += 1
                except Exception as exc:  # noqa: BLE001
                    report.errors.append(f"user {row['id']}: {exc}")

            project_rows = conn.execute(
                text("SELECT id, organization_id, name, status FROM projects")
            ).mappings()
            for row in project_rows:
                try:
                    self._project_project(conn, row["id"])
                    report.projects += 1
                except Exception as exc:  # noqa: BLE001
                    report.errors.append(f"project {row['id']}: {exc}")

            site_rows = conn.execute(
                text("SELECT id, organization_id, project_id, name, status FROM sites")
            ).mappings()
            for row in site_rows:
                try:
                    self._project_site(conn, row["id"])
                    report.sites += 1
                except Exception as exc:  # noqa: BLE001
                    report.errors.append(f"site {row['id']}: {exc}")

            # One sync unit per user with at least one project_members row --
            # a user with none has nothing to project (an empty membership
            # set is the correct, deny-by-default outcome, not an error).
            member_user_rows = conn.execute(
                text("SELECT DISTINCT user_id FROM project_members")
            ).mappings()
            for row in member_user_rows:
                try:
                    self._project_membership(conn, row["user_id"])
                    report.memberships += 1
                except Exception as exc:  # noqa: BLE001
                    report.errors.append(f"membership {row['user_id']}: {exc}")

        return report

    def _project_organization(self, conn, canonical_id: UUID) -> None:
        row = (
            conn.execute(
                text("SELECT id, name, status, trial_ends_at FROM organizations WHERE id = :id"),
                {"id": canonical_id},
            )
            .mappings()
            .one()
        )
        ctx_id = context_organization_id(canonical_id)
        # lifecycle.is_operational: active, or a trial that hasn't ended
        # (SS-02). A trial that expires between reconciles stays active here
        # until the next sweep; the live gate (backend/postgres/actor.py)
        # checks the date on every message, so access still stops on time.
        is_active = is_operational(row["status"], row.get("trial_ends_at"), datetime.now(UTC))
        conn.execute(
            text(
                """
                INSERT INTO context_organizations (id, name, is_active, canonical_organization_id)
                VALUES (:id, :name, :is_active, :canonical_id)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    is_active = EXCLUDED.is_active,
                    canonical_organization_id = EXCLUDED.canonical_organization_id
                """
            ),
            {
                "id": ctx_id,
                "name": row["name"],
                "is_active": is_active,
                "canonical_id": canonical_id,
            },
        )

    def _project_user(self, conn, canonical_id: UUID) -> None:
        row = (
            conn.execute(
                text(
                    "SELECT id, full_name, organization_id, whatsapp_number, status, "
                    "       role, access_policy "
                    "FROM users WHERE id = :id"
                ),
                {"id": canonical_id},
            )
            .mappings()
            .one()
        )
        ctx_id = context_user_id(canonical_id)
        is_active = _status_is(row["status"], "active")
        policy = row["access_policy"] or {}
        # Same standing-bypass rule _project_membership applies, computed here
        # too so a brand-new ADMIN (created with the role already set, before
        # any "membership" projection ever fires) sees every project on their
        # very first message rather than waiting for an unrelated membership
        # event to happen to sync it.
        org_wide = is_org_wide(row["role"], policy)
        conn.execute(
            text(
                """
                INSERT INTO context_users (id, full_name, is_active, is_org_wide, canonical_user_id)
                VALUES (:id, :name, :is_active, :is_org_wide, :canonical_id)
                ON CONFLICT (id) DO UPDATE SET
                    full_name = EXCLUDED.full_name,
                    is_active = EXCLUDED.is_active,
                    is_org_wide = EXCLUDED.is_org_wide,
                    canonical_user_id = EXCLUDED.canonical_user_id
                """
            ),
            {
                "id": ctx_id,
                "name": row["full_name"],
                "is_active": is_active,
                "is_org_wide": org_wide,
                "canonical_id": canonical_id,
            },
        )
        if row["organization_id"] is not None:
            org_ctx = context_organization_id(row["organization_id"])
            membership_id = f"mbr_{ctx_id}_{org_ctx}"
            conn.execute(
                text(
                    """
                    INSERT INTO organization_memberships
                        (id, organization_id, user_id, is_active)
                    VALUES (:id, :org_id, :user_id, true)
                    ON CONFLICT (organization_id, user_id) DO UPDATE SET is_active = true
                    """
                ),
                {"id": membership_id, "org_id": org_ctx, "user_id": ctx_id},
            )
        # Store the subject as bare digits: Meta's inbound `wa_id` is digit-only,
        # while `users.whatsapp_number` may carry "+", spaces, or dashes. Writing
        # the raw value made lookups depend on how an admin typed the number, and
        # every lookup silently failed with UNKNOWN_EXTERNAL_IDENTITY as a result.
        digits = _digits(row["whatsapp_number"])
        if digits:
            ext_id = f"ext_{WHATSAPP_PROVIDER}_{digits}"
            conn.execute(
                text(
                    """
                    INSERT INTO external_identities (id, provider, external_subject, user_id)
                    VALUES (:id, :provider, :subject, :user_id)
                    ON CONFLICT (provider, external_subject) DO UPDATE SET user_id = EXCLUDED.user_id
                    """
                ),
                {
                    "id": ext_id,
                    "provider": WHATSAPP_PROVIDER,
                    "subject": digits,
                    "user_id": ctx_id,
                },
            )

    def _project_project(self, conn, canonical_id: UUID) -> None:
        row = (
            conn.execute(
                text("SELECT id, organization_id, name, status FROM projects WHERE id = :id"),
                {"id": canonical_id},
            )
            .mappings()
            .one()
        )
        ctx_id = context_project_id(canonical_id)
        org_ctx = context_organization_id(row["organization_id"])
        is_active = _status_is(row["status"], "on_track")
        conn.execute(
            text(
                """
                INSERT INTO context_projects
                    (id, organization_id, name, is_active, canonical_project_id)
                VALUES (:id, :org_id, :name, :is_active, :canonical_id)
                ON CONFLICT (id) DO UPDATE SET
                    organization_id = EXCLUDED.organization_id,
                    name = EXCLUDED.name,
                    is_active = EXCLUDED.is_active,
                    canonical_project_id = EXCLUDED.canonical_project_id
                """
            ),
            {
                "id": ctx_id,
                "org_id": org_ctx,
                "name": row["name"],
                "is_active": is_active,
                "canonical_id": canonical_id,
            },
        )

    def _project_site(self, conn, canonical_id: UUID) -> None:
        row = (
            conn.execute(
                text(
                    "SELECT id, organization_id, project_id, name, status FROM sites WHERE id = :id"
                ),
                {"id": canonical_id},
            )
            .mappings()
            .one()
        )
        ctx_id = context_site_id(canonical_id)
        org_ctx = context_organization_id(row["organization_id"])
        proj_ctx = context_project_id(row["project_id"])
        is_active = _status_is(row["status"], "active")
        conn.execute(
            text(
                """
                INSERT INTO context_sites
                    (id, project_id, organization_id, name, is_active, canonical_site_id)
                VALUES (:id, :proj_id, :org_id, :name, :is_active, :canonical_id)
                ON CONFLICT (id) DO UPDATE SET
                    project_id = EXCLUDED.project_id,
                    organization_id = EXCLUDED.organization_id,
                    name = EXCLUDED.name,
                    is_active = EXCLUDED.is_active,
                    canonical_site_id = EXCLUDED.canonical_site_id
                """
            ),
            {
                "id": ctx_id,
                "proj_id": proj_ctx,
                "org_id": org_ctx,
                "name": row["name"],
                "is_active": is_active,
                "canonical_id": canonical_id,
            },
        )

    def _project_membership(self, conn, canonical_user_id: UUID) -> None:
        """Sync one user's whole project/site membership set into
        project_memberships/site_memberships -- the tables context_resolver
        (M4) actually authorizes against. Without this, project_members/
        site_members (control-plane) and project_memberships/site_memberships
        (context layer) are the same two disconnected mechanisms the
        project/site membership audit flagged: rows exist in the former,
        the latter (queried by the WhatsApp assistant) stays permanently
        empty, so every report resolves to no authorized project at all.

        A user's org-wide role (see mesiri/authorization/roles.py) grants every project in
        their org, all sites -- the same bypass AuthorizationService applies
        on the REST side, kept in sync so a project created after this user's
        last sync is still visible without needing a fresh project_members
        row per admin per project. access_policy.mode == "all_projects" gets
        the identical treatment for a non-admin: it's a live bypass, not a
        project_members snapshot (users/router.py's update_user_access no
        longer writes one), so it must be re-checked here the same way the
        role is, not read off project_members like a normal grant.

        Full replace (delete then reinsert), not a diff -- membership is a
        set, and the set can shrink (a project/site removed via the
        dashboard) as easily as it can grow. Runs inside the same
        transaction as the caller (project_one/reconcile_all's `with
        self._engine.begin()`), so a mid-sync failure can't leave a user with
        a half-updated membership set.
        """
        ctx_user_id = context_user_id(canonical_user_id)
        conn.execute(
            text("DELETE FROM project_memberships WHERE user_id = :user_id"),
            {"user_id": ctx_user_id},
        )
        conn.execute(
            text("DELETE FROM site_memberships WHERE user_id = :user_id"),
            {"user_id": ctx_user_id},
        )

        user_row = (
            conn.execute(
                text("SELECT organization_id, role, access_policy FROM users WHERE id = :id"),
                {"id": canonical_user_id},
            )
            .mappings()
            .one_or_none()
        )
        if user_row is None:
            return  # user deleted between the write and this projection; nothing to sync

        policy = user_row["access_policy"] or {}
        org_wide = is_org_wide(user_row["role"], policy)

        # Keep context_users.is_org_wide -- the live bypass
        # PostgresProjectRepository's _AUTHORIZED_PROJECT_IDS checks directly
        # -- in sync here too, since this is the path update_user_access and
        # role changes actually call (see project_entity("membership", ...)
        # call sites). Without this, only the membership snapshot below
        # updates, which is what let a project created after this grant stay
        # invisible until the next resync -- the exact bug this column
        # exists to close.
        conn.execute(
            text("UPDATE context_users SET is_org_wide = :org_wide WHERE id = :id"),
            {"org_wide": org_wide, "id": ctx_user_id},
        )

        if org_wide:
            memberships = [
                {"project_id": row["id"], "site_access_mode": "all_sites"}
                for row in conn.execute(
                    text("SELECT id FROM projects WHERE organization_id = :org_id"),
                    {"org_id": user_row["organization_id"]},
                ).mappings()
            ]
        else:
            memberships = list(
                conn.execute(
                    text(
                        "SELECT project_id, site_access_mode FROM project_members "
                        "WHERE user_id = :user_id"
                    ),
                    {"user_id": canonical_user_id},
                ).mappings()
            )

        for member in memberships:
            project_id = member["project_id"]
            ctx_project_id = context_project_id(project_id)
            conn.execute(
                text(
                    "INSERT INTO project_memberships (user_id, project_id) "
                    "VALUES (:user_id, :project_id) ON CONFLICT DO NOTHING"
                ),
                {"user_id": ctx_user_id, "project_id": ctx_project_id},
            )

            if member["site_access_mode"] == "all_sites":
                site_id_rows = conn.execute(
                    text("SELECT id FROM context_sites WHERE project_id = :ctx_project_id"),
                    {"ctx_project_id": ctx_project_id},
                ).mappings()
                for site_row in site_id_rows:
                    conn.execute(
                        text(
                            "INSERT INTO site_memberships (user_id, site_id) "
                            "VALUES (:user_id, :site_id) ON CONFLICT DO NOTHING"
                        ),
                        {"user_id": ctx_user_id, "site_id": site_row["id"]},
                    )
            else:
                explicit_site_rows = conn.execute(
                    text(
                        "SELECT sm.site_id FROM site_members sm "
                        "JOIN sites s ON s.id = sm.site_id "
                        "WHERE sm.user_id = :user_id AND s.project_id = :project_id"
                    ),
                    {"user_id": canonical_user_id, "project_id": project_id},
                ).mappings()
                for site_row in explicit_site_rows:
                    conn.execute(
                        text(
                            "INSERT INTO site_memberships (user_id, site_id) "
                            "VALUES (:user_id, :site_id) ON CONFLICT DO NOTHING"
                        ),
                        {"user_id": ctx_user_id, "site_id": context_site_id(site_row["site_id"])},
                    )
