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
