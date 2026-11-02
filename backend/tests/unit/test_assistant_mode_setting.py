"""Request 174 / WA-134: the per-company ``assistant_mode`` switch (classic or v3 "api")."""

import pytest

from mesiri.domains.organizations import settings


def test_known_default_classic_and_superadmin_only():
    assert settings.is_known_key(settings.ASSISTANT_MODE)
    assert settings.default_for(settings.ASSISTANT_MODE) == "classic"
    assert settings.ASSISTANT_MODE in settings.SUPERADMIN_ONLY_KEYS
    assert settings.ASSISTANT_MODE not in settings.DEDICATED_ENDPOINT_KEYS


@pytest.mark.parametrize("value", ["classic", "api", " API ", "Classic"])
def test_valid_values_are_canonical(value):
    assert settings.validate(settings.ASSISTANT_MODE, value) == value.strip().lower()


@pytest.mark.parametrize("value", ["v2", "v2_shadow", "v2_adk", "v2_materials", "agent", "off", "", None, True, 3])
def test_retired_and_invalid_values_are_refused(value):
    """WA-134: v2 is retired, so none of its modes can be set any more."""
    with pytest.raises(ValueError):
        settings.validate(settings.ASSISTANT_MODE, value)


@pytest.mark.parametrize("stored", [None, "agent", "off", "", 7, True, "garbage"])
def test_anything_unreadable_is_classic(stored):
    assert settings.assistant_mode(stored) == "classic"


def test_stored_modes_read_back():
    assert settings.assistant_mode("classic") == "classic"
    assert settings.assistant_mode("api") == "api"


@pytest.mark.parametrize("stored", ["v2", "v2_materials", " V2_ADK "])
def test_a_company_left_on_v2_reads_as_v3(stored):
    """WA-134: a company that had opted into the new agent keeps the new agent (no data migration)."""
    assert settings.assistant_mode(stored) == "api"


def test_v2_shadow_reads_as_classic():
    """In shadow mode classic answered and v2 only ran on the side: nothing changes for that company."""
    assert settings.assistant_mode("v2_shadow") == "classic"
