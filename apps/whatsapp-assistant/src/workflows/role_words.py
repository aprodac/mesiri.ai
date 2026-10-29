"""The words people use for a role on WhatsApp, mapped to the role codes
(WA-67, audit SET-05). One copy for every add-a-person flow (create_user,
add_project_member); before, each kept its own list and "accountant",
"PM" and "owner" all became Site Engineer.

Whole words only: "pm" must not match inside "equipment". The most specific
phrase is listed first ("site engineer" before "engineer"). An unknown word
still means Site Engineer, the standard access ("supervisor": there is no
supervisor role).
"""

from __future__ import annotations

import re

from mesiri.authorization.roles import may_grant_role

DEFAULT_ROLE = "SITE_ENGINEER"

KNOWN_ROLES = frozenset({"ADMIN", "PROJECT_MANAGER", "SITE_ENGINEER", "FINANCE"})

ROLE_ALIASES: tuple[tuple[str, str], ...] = (
    ("project manager", "PROJECT_MANAGER"),
    ("project_manager", "PROJECT_MANAGER"),
    ("site engineer", "SITE_ENGINEER"),
    ("site_engineer", "SITE_ENGINEER"),
    ("engineer", "SITE_ENGINEER"),
    ("supervisor", "SITE_ENGINEER"),
    ("accountant", "FINANCE"),
    ("accounts", "FINANCE"),
    ("finance", "FINANCE"),
    ("admin", "ADMIN"),
    ("owner", "ADMIN"),
    ("director", "ADMIN"),
    ("md", "ADMIN"),
    ("manager", "PROJECT_MANAGER"),
    ("pm", "PROJECT_MANAGER"),
)

ROLE_DISPLAY = {
    "ADMIN": "Admin",
    "PROJECT_MANAGER": "Project Manager",
    "SITE_ENGINEER": "Site Engineer",
    "FINANCE": "Finance",
}


def normalize_role(role_hint: object) -> str:
    """A role code for a free-text role hint; Site Engineer when unknown."""
    text = str(role_hint or "").strip()
    if text.upper() in KNOWN_ROLES:
        return text.upper()
    lowered = text.lower()
    for phrase, role in ROLE_ALIASES:
        if re.search(rf"\b{re.escape(phrase)}\b", lowered):
            return role
    return DEFAULT_ROLE


def role_not_allowed_reply(created_by_role: object, role: str) -> str | None:
    """The reply when the sender may not give ``role`` (a project manager
    making an admin, WA-67 / audit SET-01), else None. Unknown senders are
    left to the role gate that runs before these flows start."""
    if not created_by_role or may_grant_role(str(created_by_role), role):
        return None
    return (
        f"Only an admin can add someone as {ROLE_DISPLAY.get(role, role)}. "
        "You can add them as Project Manager or Site Engineer, or ask your admin."
    )
