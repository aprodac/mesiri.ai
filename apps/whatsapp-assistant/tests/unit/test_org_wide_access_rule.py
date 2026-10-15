"""The "who reaches every project" rule must be identical on all surfaces.

Which project and site a WhatsApp report gets filed against, what the web
dashboard lets someone read and write, and what the control panel reports
about their access are all answers to the same question. That rule used to
be written out independently in five places, and one of them silently
disagreed:

  the control panel read access_policy only, without the role half, so an
  ADMIN carrying the default policy ({"mode": "custom_projects",
  "projects": []} — set for every user at creation) rendered as
  "No projects assigned" while both the assistant and the dashboard gave
  that same person every project in the organization.

Under-reporting privilege is the dangerous direction: an operator auditing
permissions sees "no access" and moves on.

The rule now lives in mesiri/authorization/roles.py. These tests pin its
behaviour and fail if a private copy reappears anywhere.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from mesiri.authorization.roles import (
    ALL_PROJECTS_MODE,
    ORG_WIDE_ROLES,
    is_org_wide,
    policy_is_org_wide,
    role_is_org_wide,
)

# The default every user (including admins) is created with — see
# users/router.py's _DEFAULT_ACCESS_POLICY. This exact shape is what made the
# original bug reachable for essentially every admin in the system.
DEFAULT_POLICY = {"mode": "custom_projects", "projects": []}


# ---------------------------------------------------------------------------
# The rule itself
# ---------------------------------------------------------------------------


def test_admin_with_the_default_policy_is_org_wide():
    """The exact regression: this combination is what every freshly created
    admin has, and it must resolve to org-wide on every surface."""
    assert is_org_wide("ADMIN", DEFAULT_POLICY) is True


def test_admin_is_org_wide_regardless_of_policy():
    for policy in (None, {}, DEFAULT_POLICY, {"mode": ALL_PROJECTS_MODE}):
        assert is_org_wide("ADMIN", policy) is True


@pytest.mark.parametrize("role", ["admin", "Admin", " ADMIN ", "aDmIn"])
def test_role_matching_is_case_and_whitespace_insensitive(role):
    """Roles arrive from JWT claims and DB columns with inconsistent casing."""
    assert role_is_org_wide(role) is True


@pytest.mark.parametrize("role", ["PROJECT_MANAGER", "SITE_ENGINEER", "FINANCE", "", None])
def test_non_admin_roles_are_not_org_wide_on_their_own(role):
    assert role_is_org_wide(role) is False
    assert is_org_wide(role, DEFAULT_POLICY) is False


def test_all_projects_policy_grants_org_wide_to_a_non_admin():
    assert is_org_wide("SITE_ENGINEER", {"mode": ALL_PROJECTS_MODE}) is True


def test_policy_accepts_an_object_with_a_mode_attribute():
    """The dashboard passes a parsed AccessPolicy model, not a dict."""

    class _Policy:
        mode = ALL_PROJECTS_MODE

    assert policy_is_org_wide(_Policy()) is True
    assert is_org_wide("SITE_ENGINEER", _Policy()) is True


def test_missing_and_malformed_policies_deny():
    """Deny-by-default: anything unrecognisable must not grant access."""
    for policy in (None, {}, {"mode": None}, {"mode": "custom_projects"}, "all_projects", 42, []):
        assert policy_is_org_wide(policy) is False


def test_org_wide_roles_is_immutable():
    """A caller must not be able to widen the rule for the whole process."""
    assert isinstance(ORG_WIDE_ROLES, frozenset)
    with pytest.raises(AttributeError):
        ORG_WIDE_ROLES.add("FINANCE")  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Drift detector — no surface may re-derive the rule privately
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[4]

_SEARCH_ROOTS = (
    _REPO_ROOT / "apps" / "whatsapp-assistant" / "src",
    _REPO_ROOT / "backend" / "src",
)

# The shared definition itself, and migrations (frozen historical snapshots
# that must not be rewritten to import current code).
_ALLOWED = ("authorization/roles.py", "migrations/versions/")

_PRIVATE_COPY = re.compile(r"_ORG_WIDE_ROLES\s*=\s*[{(]")


def _python_files():
    for root in _SEARCH_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            rel = path.as_posix()
            if "__pycache__" in rel or any(a in rel for a in _ALLOWED):
                continue
            yield path


def test_no_module_defines_its_own_org_wide_roles():
    """Fails if someone reintroduces a private copy of the role set.

    This is the guard that would have caught the original bug: five copies,
    four correct, nothing checking they agreed.
    """
    offenders = [
        str(p.relative_to(_REPO_ROOT))
        for p in _python_files()
        if _PRIVATE_COPY.search(p.read_text(encoding="utf-8"))
    ]
    assert not offenders, (
        "These modules define their own _ORG_WIDE_ROLES instead of importing "
        f"from mesiri.authorization.roles: {offenders}"
    )


def test_the_shared_rule_is_actually_imported_by_the_surfaces_that_need_it():
    """Each surface that answers "can this person reach every project?" must
    import the shared rule rather than re-deriving it."""
    required = [
        "apps/whatsapp-assistant/src/backend/postgres/actor.py",
        "apps/whatsapp-assistant/src/context/main_table_repositories.py",
        "apps/whatsapp-assistant/src/projects/router.py",
        "apps/whatsapp-assistant/src/admin/router.py",
        "backend/src/mesiri/authorization/service.py",
    ]
    # Accept both the absolute form used from the assistant package and the
    # relative form used inside mesiri.authorization itself.
    imports_shared_rule = re.compile(r"from\s+(?:mesiri\.)?\.?(?:authorization\.)?roles\s+import")
    missing = []
    for rel in required:
        path = _REPO_ROOT / rel
        if not path.exists():
            continue  # file moved; the copy-detector test still covers it
        if not imports_shared_rule.search(path.read_text(encoding="utf-8")):
            missing.append(rel)
    assert not missing, f"These surfaces no longer import the shared rule: {missing}"
