"""The single definition of "who can reach every project in the org".

This rule decides which project and site a WhatsApp report is filed against,
what the dashboard lets someone read and write, and what the control panel
reports about their access. It was previously written out independently in
five places:

  - apps/whatsapp-assistant/src/backend/postgres/actor.py   (WhatsApp)
  - apps/whatsapp-assistant/src/context/main_table_repositories.py (WhatsApp scope)
  - apps/whatsapp-assistant/src/projects/router.py          (dashboard API)
  - apps/whatsapp-assistant/src/admin/router.py             (control panel)
  - backend/src/mesiri/authorization/service.py             (dashboard authz)

Four applied it correctly; the control panel one omitted the role half and
reported an ADMIN with the default policy as "No projects assigned" while
both other surfaces gave that same person every project. Under-reporting
privilege is the dangerous direction: an operator auditing permissions sees
"no access" and moves on.

Keeping the rule in one importable place is the point of this module -- a
future change to who counts as org-wide has exactly one edit site, and
tests/unit/test_org_wide_access_rule.py fails if a copy reappears.
"""

from __future__ import annotations

from typing import Any

# Roles that reach every project in their organization without needing an
# explicit project_members row. Deliberately a frozenset so a caller can't
# mutate the shared rule.
ORG_WIDE_ROLES: frozenset[str] = frozenset({"ADMIN"})

# access_policy.mode granting the same thing to a non-admin. It is a *live*
# standing bypass, not a snapshot: a project created after the grant is made
# must be reachable without re-saving the grant, which is why it is never
# materialized into project_members rows.
ALL_PROJECTS_MODE = "all_projects"


def role_is_org_wide(role: str | None) -> bool:
    """True if `role` alone grants org-wide project access."""
    return str(role or "").strip().upper() in ORG_WIDE_ROLES


def policy_is_org_wide(access_policy: Any) -> bool:
    """True if `access_policy` grants org-wide project access.

    Tolerates the shapes this value really arrives in: None, a dict from
    JSONB, or an object with a `.mode` attribute (the parsed AccessPolicy
    model on the dashboard side).
    """
    if access_policy is None:
        return False
    if isinstance(access_policy, dict):
        return access_policy.get("mode") == ALL_PROJECTS_MODE
    return getattr(access_policy, "mode", None) == ALL_PROJECTS_MODE


def is_org_wide(role: str | None, access_policy: Any = None) -> bool:
    """The whole rule: an org-wide role, or an all_projects access policy.

    Every surface that decides "can this person reach every project?" must
    call this rather than re-deriving it.
    """
    return role_is_org_wide(role) or policy_is_org_wide(access_policy)


# Who may read the company's expenses (SEC-01, decided by Ilan 21 Oct 2026):
# the owner/admin, finance and project managers -- each only within the
# projects they can reach (ProjectAccessScope on the dashboard, the sender's
# own projects on WhatsApp). Everyone else (a site engineer, a supervisor)
# records expenses but does not see the company's spending. One rule for the
# dashboard API and the WhatsApp assistant: both import it from here.
EXPENSE_VIEW_ROLES: frozenset[str] = frozenset(
    {"ADMIN", "OWNER", "SUPER_ADMIN", "FINANCE", "PROJECT_MANAGER"}
)


def may_view_expenses(role: str | None) -> bool:
    """True if `role` may read expenses (within the projects it can reach)."""
    return str(role or "").strip().upper() in EXPENSE_VIEW_ROLES


# Who may set how many of a unit make one stock unit of a material ("28 bags
# of sand = 1 m³") for the whole company (WA-41, decided by Ilan 21 Oct 2026):
# it changes every later stock figure for that material, so admins and
# project managers, not every engineer.
UNIT_CONVERSION_ROLES: frozenset[str] = frozenset({"ADMIN", "OWNER", "SUPER_ADMIN", "PROJECT_MANAGER"})


def may_set_unit_conversions(role: str | None) -> bool:
    """True if `role` may set a company-wide unit conversion."""
    return str(role or "").strip().upper() in UNIT_CONVERSION_ROLES


# Who may give which role when adding a person (WA-67, audit SET-01). An
# admin may give any role; a project manager only their own level or below,
# as the dashboard (Team page, admins only) never lets anyone else make an
# admin. The WhatsApp add-person flows check this before asking to confirm;
# the backend validations check it again when the change is saved.
GRANTABLE_ROLES: dict[str, frozenset[str]] = {
    "ADMIN": frozenset({"ADMIN", "PROJECT_MANAGER", "SITE_ENGINEER", "FINANCE"}),
    "PROJECT_MANAGER": frozenset({"PROJECT_MANAGER", "SITE_ENGINEER"}),
}


def may_grant_role(creator_role: str | None, role: str | None) -> bool:
    """True if someone with `creator_role` may give a person `role`."""
    creator = str(creator_role or "").strip().upper()
    return str(role or "").strip().upper() in GRANTABLE_ROLES.get(creator, frozenset())
