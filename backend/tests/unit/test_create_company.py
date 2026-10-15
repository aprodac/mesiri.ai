"""SS-03: the input rules of the one create-company step (no database)."""

from __future__ import annotations

import pytest

from mesiri.application.organizations.create_company import (
    DEFAULT_TIMEZONE,
    CompanyCreationError,
    NewCompany,
    validate,
)


def _new(**overrides) -> NewCompany:
    fields = {"name": "Suresh Builders", "owner_name": "Suresh", "owner_phone": "98765 43210"}
    fields.update(overrides)
    return NewCompany(**fields)


def test_whatsapp_only_owner_is_enough() -> None:
    cleaned = validate(_new())
    assert cleaned.owner_phone == "919876543210"
    assert cleaned.owner_email is None
    assert cleaned.owner_password is None


def test_defaults_are_india_time_active_superadmin() -> None:
    cleaned = validate(_new())
    assert cleaned.timezone == DEFAULT_TIMEZONE == "Asia/Kolkata"
    assert cleaned.start_as == "active"
    assert cleaned.signup_source == "superadmin"
    assert cleaned.deployment_type == "SaaS"


def test_names_are_trimmed_and_email_lowercased() -> None:
    cleaned = validate(
        _new(name="  Suresh   Builders ", owner_email=" Suresh@Example.COM ", owner_phone=None)
    )
    assert cleaned.name == "Suresh Builders"
    assert cleaned.owner_email == "suresh@example.com"


def test_site_defaults_to_project_name() -> None:
    cleaned = validate(_new(project_name="Green Villa, Kakkanad"))
    assert cleaned.site_name == "Green Villa, Kakkanad"


def test_one_site_is_also_listed_in_site_names() -> None:
    cleaned = validate(_new(project_name="Green Villa"))
    assert cleaned.site_names == ("Green Villa",)


def test_several_sites_under_one_project() -> None:
    cleaned = validate(
        _new(project_name="Skyline Apartments", site_names=(" Block  A ", "", "Block B", "  "))
    )
    assert cleaned.site_names == ("Block A", "Block B")  # trimmed, empty rows dropped
    assert cleaned.site_name == "Block A"


def test_only_empty_site_rows_fall_back_to_the_project_name() -> None:
    cleaned = validate(_new(project_name="Skyline", site_names=("", " ")))
    assert cleaned.site_names == ("Skyline",)


def test_validating_twice_gives_the_same_result() -> None:
    once = validate(_new(project_name="Skyline", site_names=("Block A", "Block B")))
    assert validate(once) == once


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"name": "  "}, "Company name is required"),
        ({"owner_name": ""}, "Owner name is required"),
        ({"owner_phone": None}, "needs an email or a WhatsApp number"),
        ({"owner_phone": "12345"}, "Owner WhatsApp number"),
        ({"owner_email": "not-an-email"}, "not a valid email"),
        ({"owner_password": "secret"}, "needs an owner email"),
        ({"site_name": "Tower A"}, "A site needs a project"),
        ({"start_as": "expired"}, "start_as must be one of"),
        ({"signup_source": "carrier-pigeon"}, "signup_source must be one of"),
        ({"name": "x" * 121}, "longer than 120"),
        ({"site_names": ("Block A",)}, "A site needs a project"),
        (
            {"project_name": "P", "site_names": ("Block A", "block a")},
            "'block a' is given twice",
        ),
        (
            {"project_name": "P", "site_name": "Tower", "site_names": ("Block A",)},
            "not both",
        ),
        (
            {"project_name": "P", "site_names": tuple(f"Block {i}" for i in range(21))},
            "At most 20 sites",
        ),
    ],
)
def test_bad_requests_are_refused(overrides, message) -> None:
    with pytest.raises(CompanyCreationError, match=message) as exc:
        validate(_new(**overrides))
    assert exc.value.conflict is False
