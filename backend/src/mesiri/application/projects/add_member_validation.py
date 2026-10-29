"""Pure structural validation for AddProjectMemberCommand — no DB, no I/O.

Runs after the Handler has already tried to resolve member_name into
member_user_id (see handlers.py) -- an unresolved name is rejected there,
before this ever runs, so member_user_id being unset here would be a bug in
the Handler, not a user-facing case this needs to word nicely. The target
project's existence and any duplicate-membership check happen at persist
time (a DB round trip, mirroring create_site_validation.py's docstring
reasoning) -- this file only rejects a command that's structurally
incomplete before it ever reaches the repository.

Role enforcement lives here too, mirroring create_site_validation.py's
docstring reasoning exactly: this is defense-in-depth, not the only gate --
runtime/inbound_journey.py already refuses to even start the workflow for a
disallowed role.
"""

from __future__ import annotations

from mesiri.authorization.roles import may_grant_role

from .add_member_commands import AddProjectMemberCommand

# Matches create_site_validation.py's _SITE_CREATE_ROLES exactly -- the same
# roles that may create a Site may add a member to a Project.
_ADD_MEMBER_ROLES = frozenset({"ADMIN", "PROJECT_MANAGER"})

_KNOWN_MEMBER_ROLES = frozenset({"ADMIN", "PROJECT_MANAGER", "SITE_ENGINEER", "FINANCE"})


def validate(cmd: AddProjectMemberCommand) -> list[str]:
    reasons: list[str] = []
    if str(cmd.created_by_role or "").strip().upper() not in _ADD_MEMBER_ROLES:
        reasons.append("only an admin or project manager can add a project member")
    if not (cmd.project_id or "").strip():
        reasons.append("a project is required to add a member")
    if not (cmd.member_user_id or "").strip():
        reasons.append("couldn't find who to add")
    if cmd.role.strip().upper() not in _KNOWN_MEMBER_ROLES:
        reasons.append("unrecognized project role")
    elif cmd.created_by_role and not may_grant_role(cmd.created_by_role, cmd.role):
        # WA-67 (audit SET-01): a project manager can't make an admin.
        reasons.append("only an admin can give someone the admin or finance role")
    return reasons
