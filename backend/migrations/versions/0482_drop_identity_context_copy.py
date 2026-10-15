"""BE-01 step 3: drop the WhatsApp assistant's ``context_*`` copy of identity.

WhatsApp now reads people, companies, projects, sites and memberships straight
from the main tables (context/main_table_repositories.py), so the copy, the
projection that filled it, the reconcile watchdog and the shadow comparison are
gone, and with them their tables:

- the copy (migration 0040, extended by 0190/0195/0210/0364): context_organizations,
  context_users, external_identities, organization_memberships, roles,
  permissions, membership_roles, role_permissions, context_projects,
  context_sites, project_memberships, site_memberships, user_context_preferences
- identity_reconcile_runs (0366, the watchdog's run log)
- identity_shadow_mismatches (0465, the step-0 comparison)

The copy also held ON DELETE RESTRICT foreign keys onto organizations, users,
projects and sites, which is why deletes had to clear it first; those go too.

Adds ix_users_whatsapp_digits: every inbound message finds its sender by the
digits of users.whatsapp_number (MainExternalIdentityRepository.find_identity),
which the existing index on the raw number cannot serve.

Drops are plain (no CASCADE), so an unexpected dependent object fails the
migration loudly instead of being removed with it. The copy holds only data
derived from the main tables, so nothing is lost; back the tables up first all
the same (see the BE-01 tracker row).

Downgrade recreates the tables empty with their exact schema at 0481 (taken
from pg_dump). Refilling them needs the pre-BE-01-step-3 code (its reconcile
watchdog rebuilds the copy from the main tables) or the backup.

Revision ID: 0482
Revises: 0481
Create Date: 2026-10-15
"""

from __future__ import annotations

from alembic import op

revision = "0482"
down_revision = "0481"
branch_labels = None
depends_on = None

# Children before parents, so plain DROP TABLE works.
_TABLES = (
    "user_context_preferences",
    "site_memberships",
    "project_memberships",
    "context_sites",
    "context_projects",
    "role_permissions",
    "membership_roles",
    "permissions",
    "roles",
    "organization_memberships",
    "external_identities",
    "context_users",
    "context_organizations",
    "identity_reconcile_runs",
    "identity_shadow_mismatches",
)

# Same expression and predicate as MainExternalIdentityRepository.find_identity.
_DIGITS_INDEX = (
    "CREATE INDEX ix_users_whatsapp_digits ON users "
    "(regexp_replace(whatsapp_number, '\\D', '', 'g')) WHERE whatsapp_number IS NOT NULL"
)


def upgrade() -> None:
    for table in _TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table}")
    op.execute(_DIGITS_INDEX)


# The schema as it stood at 0481 (pg_dump -s), recreated empty on downgrade.
_SCHEMA = (
    """
    CREATE TABLE context_organizations (
        id character varying NOT NULL,
        name character varying NOT NULL,
        is_active boolean DEFAULT true NOT NULL,
        created_at timestamp with time zone DEFAULT now() NOT NULL,
        canonical_organization_id uuid NOT NULL,
        updated_at timestamp with time zone DEFAULT now() NOT NULL
    )
    """,
    """
    CREATE TABLE context_projects (
        id character varying NOT NULL,
        organization_id character varying NOT NULL,
        name character varying NOT NULL,
        is_active boolean DEFAULT true NOT NULL,
        canonical_project_id uuid NOT NULL,
        updated_at timestamp with time zone DEFAULT now() NOT NULL
    )
    """,
    """
    CREATE TABLE context_sites (
        id character varying NOT NULL,
        project_id character varying NOT NULL,
        organization_id character varying NOT NULL,
        name character varying NOT NULL,
        is_active boolean DEFAULT true NOT NULL,
        canonical_site_id uuid NOT NULL,
        updated_at timestamp with time zone DEFAULT now() NOT NULL
    )
    """,
    """
    CREATE TABLE context_users (
        id character varying NOT NULL,
        full_name character varying,
        is_active boolean DEFAULT true NOT NULL,
        locale character varying,
        timezone character varying,
        created_at timestamp with time zone DEFAULT now() NOT NULL,
        canonical_user_id uuid NOT NULL,
        updated_at timestamp with time zone DEFAULT now() NOT NULL,
        is_org_wide boolean DEFAULT false NOT NULL
    )
    """,
    """
    CREATE TABLE external_identities (
        id character varying NOT NULL,
        provider character varying NOT NULL,
        external_subject character varying NOT NULL,
        user_id character varying NOT NULL,
        created_at timestamp with time zone DEFAULT now() NOT NULL
    )
    """,
    """
    CREATE TABLE identity_reconcile_runs (
        id uuid NOT NULL,
        status character varying NOT NULL,
        started_at timestamp with time zone DEFAULT now() NOT NULL,
        finished_at timestamp with time zone,
        duration_ms integer,
        counts jsonb,
        error_count integer DEFAULT 0 NOT NULL,
        errors jsonb,
        trigger character varying DEFAULT 'scheduled'::character varying NOT NULL
    )
    """,
    """
    CREATE TABLE identity_shadow_mismatches (
        fingerprint character varying(64) NOT NULL,
        port character varying(64) NOT NULL,
        method character varying(64) NOT NULL,
        args jsonb NOT NULL,
        context_result jsonb,
        main_result jsonb,
        hits integer DEFAULT 1 NOT NULL,
        first_seen_at timestamp with time zone DEFAULT now() NOT NULL,
        last_seen_at timestamp with time zone DEFAULT now() NOT NULL
    )
    """,
    """
    CREATE TABLE membership_roles (
        membership_id character varying NOT NULL,
        role_id character varying NOT NULL,
        created_at timestamp with time zone DEFAULT now() NOT NULL
    )
    """,
    """
    CREATE TABLE organization_memberships (
        id character varying NOT NULL,
        organization_id character varying NOT NULL,
        user_id character varying NOT NULL,
        is_active boolean DEFAULT true NOT NULL
    )
    """,
    """
    CREATE TABLE permissions (
        id character varying NOT NULL,
        code character varying NOT NULL,
        created_at timestamp with time zone DEFAULT now() NOT NULL
    )
    """,
    """
    CREATE TABLE project_memberships (
        user_id character varying NOT NULL,
        project_id character varying NOT NULL,
        created_at timestamp with time zone DEFAULT now() NOT NULL
    )
    """,
    """
    CREATE TABLE role_permissions (
        role_id character varying NOT NULL,
        permission_id character varying NOT NULL,
        created_at timestamp with time zone DEFAULT now() NOT NULL
    )
    """,
    """
    CREATE TABLE roles (
        id character varying NOT NULL,
        organization_id character varying NOT NULL,
        name character varying NOT NULL,
        created_at timestamp with time zone DEFAULT now() NOT NULL
    )
    """,
    """
    CREATE TABLE site_memberships (
        user_id character varying NOT NULL,
        site_id character varying NOT NULL,
        created_at timestamp with time zone DEFAULT now() NOT NULL
    )
    """,
    """
    CREATE TABLE user_context_preferences (
        organization_id character varying NOT NULL,
        user_id character varying NOT NULL,
        default_project_id character varying,
        default_site_id character varying,
        locale character varying,
        timezone character varying
    )
    """,
    """
    ALTER TABLE ONLY context_organizations
        ADD CONSTRAINT context_organizations_pkey PRIMARY KEY (id)
    """,
    """
    ALTER TABLE ONLY context_projects
        ADD CONSTRAINT context_projects_pkey PRIMARY KEY (id)
    """,
    """
    ALTER TABLE ONLY context_sites
        ADD CONSTRAINT context_sites_pkey PRIMARY KEY (id)
    """,
    """
    ALTER TABLE ONLY context_users
        ADD CONSTRAINT context_users_pkey PRIMARY KEY (id)
    """,
    """
    ALTER TABLE ONLY external_identities
        ADD CONSTRAINT external_identities_pkey PRIMARY KEY (id)
    """,
    """
    ALTER TABLE ONLY identity_reconcile_runs
        ADD CONSTRAINT identity_reconcile_runs_pkey PRIMARY KEY (id)
    """,
    """
    ALTER TABLE ONLY identity_shadow_mismatches
        ADD CONSTRAINT identity_shadow_mismatches_pkey PRIMARY KEY (fingerprint)
    """,
    """
    ALTER TABLE ONLY membership_roles
        ADD CONSTRAINT membership_roles_pkey PRIMARY KEY (membership_id, role_id)
    """,
    """
    ALTER TABLE ONLY organization_memberships
        ADD CONSTRAINT organization_memberships_pkey PRIMARY KEY (id)
    """,
    """
    ALTER TABLE ONLY permissions
        ADD CONSTRAINT permissions_code_key UNIQUE (code)
    """,
    """
    ALTER TABLE ONLY permissions
        ADD CONSTRAINT permissions_pkey PRIMARY KEY (id)
    """,
    """
    ALTER TABLE ONLY project_memberships
        ADD CONSTRAINT project_memberships_pkey PRIMARY KEY (user_id, project_id)
    """,
    """
    ALTER TABLE ONLY role_permissions
        ADD CONSTRAINT role_permissions_pkey PRIMARY KEY (role_id, permission_id)
    """,
    """
    ALTER TABLE ONLY roles
        ADD CONSTRAINT roles_pkey PRIMARY KEY (id)
    """,
    """
    ALTER TABLE ONLY site_memberships
        ADD CONSTRAINT site_memberships_pkey PRIMARY KEY (user_id, site_id)
    """,
    """
    ALTER TABLE ONLY external_identities
        ADD CONSTRAINT uq_external_identity UNIQUE (provider, external_subject)
    """,
    """
    ALTER TABLE ONLY organization_memberships
        ADD CONSTRAINT uq_membership UNIQUE (organization_id, user_id)
    """,
    """
    ALTER TABLE ONLY user_context_preferences
        ADD CONSTRAINT user_context_preferences_pkey PRIMARY KEY (organization_id, user_id)
    """,
    """
    CREATE UNIQUE INDEX ix_context_organizations_canonical_organization_id ON context_organizations USING btree (canonical_organization_id)
    """,
    """
    CREATE UNIQUE INDEX ix_context_projects_canonical_project_id ON context_projects USING btree (canonical_project_id)
    """,
    """
    CREATE INDEX ix_context_projects_org ON context_projects USING btree (organization_id)
    """,
    """
    CREATE INDEX ix_context_projects_org_name ON context_projects USING btree (organization_id, name)
    """,
    """
    CREATE UNIQUE INDEX ix_context_sites_canonical_site_id ON context_sites USING btree (canonical_site_id)
    """,
    """
    CREATE INDEX ix_context_sites_org_name ON context_sites USING btree (organization_id, name)
    """,
    """
    CREATE INDEX ix_context_sites_project ON context_sites USING btree (project_id)
    """,
    """
    CREATE UNIQUE INDEX ix_context_users_canonical_user_id ON context_users USING btree (canonical_user_id)
    """,
    """
    CREATE INDEX ix_external_identities_user ON external_identities USING btree (user_id)
    """,
    """
    CREATE INDEX ix_identity_reconcile_runs_started_at ON identity_reconcile_runs USING btree (started_at DESC)
    """,
    """
    CREATE INDEX ix_memberships_org ON organization_memberships USING btree (organization_id)
    """,
    """
    CREATE INDEX ix_memberships_user ON organization_memberships USING btree (user_id)
    """,
    """
    CREATE TRIGGER trg_context_organizations_updated BEFORE UPDATE ON context_organizations FOR EACH ROW EXECUTE FUNCTION set_updated_at()
    """,
    """
    CREATE TRIGGER trg_context_projects_updated BEFORE UPDATE ON context_projects FOR EACH ROW EXECUTE FUNCTION set_updated_at()
    """,
    """
    CREATE TRIGGER trg_context_sites_updated BEFORE UPDATE ON context_sites FOR EACH ROW EXECUTE FUNCTION set_updated_at()
    """,
    """
    CREATE TRIGGER trg_context_users_updated BEFORE UPDATE ON context_users FOR EACH ROW EXECUTE FUNCTION set_updated_at()
    """,
    """
    ALTER TABLE ONLY context_projects
        ADD CONSTRAINT context_projects_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES context_organizations(id)
    """,
    """
    ALTER TABLE ONLY context_sites
        ADD CONSTRAINT context_sites_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES context_organizations(id)
    """,
    """
    ALTER TABLE ONLY context_sites
        ADD CONSTRAINT context_sites_project_id_fkey FOREIGN KEY (project_id) REFERENCES context_projects(id)
    """,
    """
    ALTER TABLE ONLY external_identities
        ADD CONSTRAINT external_identities_user_id_fkey FOREIGN KEY (user_id) REFERENCES context_users(id)
    """,
    """
    ALTER TABLE ONLY context_organizations
        ADD CONSTRAINT fk_context_organizations_canonical_organization_id FOREIGN KEY (canonical_organization_id) REFERENCES organizations(id) ON DELETE RESTRICT
    """,
    """
    ALTER TABLE ONLY context_projects
        ADD CONSTRAINT fk_context_projects_canonical_project_id FOREIGN KEY (canonical_project_id) REFERENCES projects(id) ON DELETE RESTRICT
    """,
    """
    ALTER TABLE ONLY context_sites
        ADD CONSTRAINT fk_context_sites_canonical_site_id FOREIGN KEY (canonical_site_id) REFERENCES sites(id) ON DELETE RESTRICT
    """,
    """
    ALTER TABLE ONLY context_users
        ADD CONSTRAINT fk_context_users_canonical_user_id FOREIGN KEY (canonical_user_id) REFERENCES users(id) ON DELETE RESTRICT
    """,
    """
    ALTER TABLE ONLY membership_roles
        ADD CONSTRAINT membership_roles_membership_id_fkey FOREIGN KEY (membership_id) REFERENCES organization_memberships(id)
    """,
    """
    ALTER TABLE ONLY membership_roles
        ADD CONSTRAINT membership_roles_role_id_fkey FOREIGN KEY (role_id) REFERENCES roles(id)
    """,
    """
    ALTER TABLE ONLY organization_memberships
        ADD CONSTRAINT organization_memberships_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES context_organizations(id)
    """,
    """
    ALTER TABLE ONLY organization_memberships
        ADD CONSTRAINT organization_memberships_user_id_fkey FOREIGN KEY (user_id) REFERENCES context_users(id)
    """,
    """
    ALTER TABLE ONLY project_memberships
        ADD CONSTRAINT project_memberships_project_id_fkey FOREIGN KEY (project_id) REFERENCES context_projects(id)
    """,
    """
    ALTER TABLE ONLY project_memberships
        ADD CONSTRAINT project_memberships_user_id_fkey FOREIGN KEY (user_id) REFERENCES context_users(id)
    """,
    """
    ALTER TABLE ONLY role_permissions
        ADD CONSTRAINT role_permissions_permission_id_fkey FOREIGN KEY (permission_id) REFERENCES permissions(id)
    """,
    """
    ALTER TABLE ONLY role_permissions
        ADD CONSTRAINT role_permissions_role_id_fkey FOREIGN KEY (role_id) REFERENCES roles(id)
    """,
    """
    ALTER TABLE ONLY roles
        ADD CONSTRAINT roles_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES context_organizations(id)
    """,
    """
    ALTER TABLE ONLY site_memberships
        ADD CONSTRAINT site_memberships_site_id_fkey FOREIGN KEY (site_id) REFERENCES context_sites(id)
    """,
    """
    ALTER TABLE ONLY site_memberships
        ADD CONSTRAINT site_memberships_user_id_fkey FOREIGN KEY (user_id) REFERENCES context_users(id)
    """,
    """
    ALTER TABLE ONLY user_context_preferences
        ADD CONSTRAINT user_context_preferences_default_project_id_fkey FOREIGN KEY (default_project_id) REFERENCES context_projects(id)
    """,
    """
    ALTER TABLE ONLY user_context_preferences
        ADD CONSTRAINT user_context_preferences_default_site_id_fkey FOREIGN KEY (default_site_id) REFERENCES context_sites(id)
    """,
    """
    ALTER TABLE ONLY user_context_preferences
        ADD CONSTRAINT user_context_preferences_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES context_organizations(id)
    """,
    """
    ALTER TABLE ONLY user_context_preferences
        ADD CONSTRAINT user_context_preferences_user_id_fkey FOREIGN KEY (user_id) REFERENCES context_users(id)
    """,
)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_users_whatsapp_digits")
    for statement in _SCHEMA:
        op.execute(statement)
