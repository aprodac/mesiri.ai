"""Pure structural validation for CreateUserCommand — no DB, no I/O.

The number-already-registered check happens at persist time (a DB round
trip, mirroring create_site_validation.py's docstring reasoning) -- this
file only rejects a command that's structurally incomplete before it ever
reaches the repository.

Role enforcement lives here too, mirroring add_member_validation.py's
docstring reasoning exactly: this is defense-in-depth, not the only gate --
runtime/inbound_journey.py already refuses to even start the workflow for a
disallowed role.
"""

from __future__ import annotations

from mesiri.authorization.roles import may_grant_role

from .create_user_commands import CreateUserCommand

# Matches process.py's _PROJECT_CREATE_ROLES exactly -- provisioning a new
# person's access is a bigger blast radius than adding an existing person to
# one more project, but the same role set was the explicit product call
# here (not ADMIN-only).
_CREATE_USER_ROLES = frozenset({"ADMIN", "PROJECT_MANAGER"})

_KNOWN_USER_ROLES = frozenset({"ADMIN", "PROJECT_MANAGER", "SITE_ENGINEER", "FINANCE"})

# A sanity floor, not format validation -- see workflows/create_user/
# nodes.py's _normalize_phone docstring for why a stricter E.164 check isn't
# done anywhere in this codebase today.
_MIN_PHONE_DIGITS = 10


def validate(cmd: CreateUserCommand) -> list[str]:
    reasons: list[str] = []
    if str(cmd.created_by_role or "").strip().upper() not in _CREATE_USER_ROLES:
        reasons.append("only an admin or project manager can add a new user")
    if not cmd.full_name.strip():
        reasons.append("a name is required to create a user")
    digits = cmd.whatsapp_number.strip()
    if not digits.isdigit() or len(digits) < _MIN_PHONE_DIGITS:
        reasons.append("a valid WhatsApp number is required to create a user")
    if cmd.role.strip().upper() not in _KNOWN_USER_ROLES:
        reasons.append("unrecognized role")
    elif cmd.created_by_role and not may_grant_role(cmd.created_by_role, cmd.role):
        # WA-67 (audit SET-01): a project manager can't make an admin.
        reasons.append("only an admin can give someone the admin or finance role")
    return reasons
