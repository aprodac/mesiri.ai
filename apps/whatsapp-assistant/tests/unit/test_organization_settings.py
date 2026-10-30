"""Unit tests for the per-organization settings catalog
(backend domains/organizations/settings.py, migration 0364).

The defaults are the real contract: no row exists for any org until someone
changes something in the control panel, so a wrong default silently changes
behaviour for every existing tenant. Validation matters for the same reason
in reverse — a bad value persisted here is read by the WhatsApp gate on
every material report.
"""

from __future__ import annotations

import pytest

from mesiri.domains.organizations import settings


def test_whatsapp_material_create_defaults_to_admin_pm_and_site_engineer():
    """Site engineers may add a material (owner decision, 30 Oct 2026); an org
    that stored its own list keeps it."""
    assert settings.default_for(settings.WHATSAPP_MATERIAL_CREATE_ROLES) == [
        "ADMIN",
        "PROJECT_MANAGER",
        "SITE_ENGINEER",
    ]


def test_unknown_key_raises():
    with pytest.raises(KeyError):
        settings.default_for("not_a_real_setting")
    assert not settings.is_known_key("not_a_real_setting")


def test_validate_uppercases_and_dedupes_roles():
    result = settings.validate(
        settings.WHATSAPP_MATERIAL_CREATE_ROLES, ["admin", "ADMIN", " project_manager "]
    )
    assert result == ["ADMIN", "PROJECT_MANAGER"]


def test_validate_rejects_unknown_role():
    with pytest.raises(ValueError, match="unknown role"):
        settings.validate(settings.WHATSAPP_MATERIAL_CREATE_ROLES, ["ADMIN", "WIZARD"])


def test_validate_rejects_non_list():
    with pytest.raises(ValueError):
        settings.validate(settings.WHATSAPP_MATERIAL_CREATE_ROLES, "ADMIN")


def test_validate_rejects_unknown_key():
    with pytest.raises(ValueError, match="unknown organization setting"):
        settings.validate("not_a_real_setting", [])


def test_empty_list_is_valid_meaning_nobody():
    """Explicitly granting nobody is a legitimate configuration, distinct
    from never having configured it (which falls back to the default)."""
    assert settings.validate(settings.WHATSAPP_MATERIAL_CREATE_ROLES, []) == []


@pytest.mark.parametrize(
    ("role", "allowed", "expected"),
    [
        ("ADMIN", ["ADMIN"], True),
        ("admin", ["ADMIN"], True),
        ("SITE_ENGINEER", ["ADMIN", "PROJECT_MANAGER"], False),
        (None, ["ADMIN"], False),
        ("ADMIN", [], False),
        # A hand-edited or legacy row that isn't a list of strings must deny
        # rather than raise -- this runs inside the inbound journey, where an
        # exception costs the user their whole reply.
        ("ADMIN", "ADMIN", False),
        ("ADMIN", None, False),
        ("ADMIN", [123, None], False),
    ],
)
def test_role_allowed(role, allowed, expected):
    assert settings.role_allowed(role, allowed) is expected


def test_all_specs_covers_every_known_key():
    keys = {spec.key for spec in settings.all_specs()}
    assert settings.WHATSAPP_MATERIAL_CREATE_ROLES in keys
    for key in keys:
        assert settings.is_known_key(key)
        settings.default_for(key)
