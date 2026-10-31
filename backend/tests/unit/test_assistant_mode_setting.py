"""Request 174: the per-company ``assistant_mode`` switch of the v2 pilot."""

import pytest

from mesiri.domains.organizations import settings


def test_known_default_classic_and_superadmin_only():
    assert settings.is_known_key(settings.ASSISTANT_MODE)
    assert settings.default_for(settings.ASSISTANT_MODE) == "classic"
    assert settings.ASSISTANT_MODE in settings.SUPERADMIN_ONLY_KEYS
    assert settings.ASSISTANT_MODE not in settings.DEDICATED_ENDPOINT_KEYS


@pytest.mark.parametrize("value", ["classic", "v2_shadow", "v2", " V2 "])
def test_valid_values_are_canonical(value):
    assert settings.validate(settings.ASSISTANT_MODE, value) == value.strip().lower()


@pytest.mark.parametrize("value", ["v2_materials", " V2_Materials "])
def test_the_old_name_is_an_alias_of_v2(value):
    assert settings.validate(settings.ASSISTANT_MODE, value) == "v2"


@pytest.mark.parametrize("value", ["agent", "off", "", None, True, 3])
def test_invalid_values_are_refused(value):
    with pytest.raises(ValueError):
        settings.validate(settings.ASSISTANT_MODE, value)


@pytest.mark.parametrize("stored", [None, "agent", "off", "", 7, True, "garbage"])
def test_anything_unreadable_is_classic(stored):
    assert settings.assistant_mode(stored) == "classic"


def test_stored_modes_read_back():
    assert settings.assistant_mode("v2_shadow") == "v2_shadow"
    assert settings.assistant_mode("v2") == "v2"
    assert settings.assistant_mode("v2_materials") == "v2"  # stored under the old name: no migration
