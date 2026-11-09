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


# Who may change where the company's money is kept and move it (SEC-03 and PRC-35, approved in session by the
# owner, 7 Nov 2026): add, edit or close a money account, transfer between accounts or undo a transfer, and mark an
# expense paid or repay someone who paid from their own pocket. The owner/admin and finance -- not project managers
# or site roles. Recording an expense paid from one's own cash box (WhatsApp, WEB-68) stays open: that is spending,
# not moving money.
MONEY_MANAGE_ROLES: frozenset[str] = frozenset({"ADMIN", "OWNER", "SUPER_ADMIN", "FINANCE"})


def may_manage_money(role: str | None) -> bool:
    """True if `role` may change money accounts, undo a transfer or take back an expense, or pay an expense."""
    return str(role or "").strip().upper() in MONEY_MANAGE_ROLES


# Moving money between accounts (a site's petty cash top-up) is also for project managers. One list for the dashboard
# and WhatsApp (application/finance/transfer_validation.py read its own copy until 7 Nov).
MONEY_TRANSFER_ROLES: frozenset[str] = MONEY_MANAGE_ROLES | {"PROJECT_MANAGER"}


def may_transfer_money(role: str | None) -> bool:
    """True if `role` may transfer money between the company's accounts."""
    return str(role or "").strip().upper() in MONEY_TRANSFER_ROLES


# Who may set how many of a unit make one stock unit of a material ("28 bags
# of sand = 1 m³") for the whole company (WA-41, decided by Ilan 21 Oct 2026):
# it changes every later stock figure for that material, so admins and
# project managers, not every engineer.
UNIT_CONVERSION_ROLES: frozenset[str] = frozenset({"ADMIN", "OWNER", "SUPER_ADMIN", "PROJECT_MANAGER"})


def may_set_unit_conversions(role: str | None) -> bool:
    """True if `role` may set a company-wide unit conversion."""
    return str(role or "").strip().upper() in UNIT_CONVERSION_ROLES


# Who may act on a site's material request -- order it, send it from another site, say no, mark it
# received (PRC-22, 7 Nov 2026). The default until PRC-12 (who may order, Alan's decision D1) is
# made: the people who run the projects, the same group that sets company-wide sizes. Anyone in the
# project may ask, and cancel their own request while it waits.
MATERIAL_REQUEST_ROLES: frozenset[str] = frozenset({"ADMIN", "OWNER", "SUPER_ADMIN", "PROJECT_MANAGER"})


def may_act_on_material_requests(role: str | None) -> bool:
    """True if `role` may decide a material request (within the projects it can reach)."""
    return str(role or "").strip().upper() in MATERIAL_REQUEST_ROLES


# Who may read the company's activity log, who changed what and when (ADM-02, decided in session by Ilan 9 Nov 2026):
# the owner and admins, for the whole company. Nobody edits or deletes an entry.
ACTIVITY_LOG_ROLES: frozenset[str] = frozenset({"ADMIN", "OWNER", "SUPER_ADMIN"})


def may_read_activity_log(role: str | None) -> bool:
    """True if `role` may read the company activity log."""
    return str(role or "").strip().upper() in ACTIVITY_LOG_ROLES


# Who may hand a person's open work to someone else (ADM-03, decided in session by Ilan 9 Nov 2026): the owner and
# admins, the roles that run the Team page.
HANDOVER_ROLES: frozenset[str] = frozenset({"ADMIN", "OWNER", "SUPER_ADMIN"})


def may_hand_over_work(role: str | None) -> bool:
    """True if `role` may move a person's open tasks and schedule activities to another person."""
    return str(role or "").strip().upper() in HANDOVER_ROLES


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
