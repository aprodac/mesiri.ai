"""Request 124: the `draft_v2` company setting is off unless the Mesiri team turns it on."""

from __future__ import annotations

import pytest

from mesiri.domains.organizations import settings


def test_draft_v2_is_off_by_default_and_only_the_team_changes_it():
    assert settings.is_known_key(settings.DRAFT_V2)
    assert settings.default_for(settings.DRAFT_V2) is False
    assert settings.DRAFT_V2 in settings.SUPERADMIN_ONLY_KEYS
    assert settings.DRAFT_V2 not in settings.DEDICATED_ENDPOINT_KEYS


@pytest.mark.parametrize("value", [True, False])
def test_a_boolean_is_stored_as_it_is(value):
    assert settings.validate(settings.DRAFT_V2, value) is value


@pytest.mark.parametrize("value", ["true", "on", 1, 0, None, ["true"]])
def test_anything_but_a_boolean_is_refused(value):
    with pytest.raises(ValueError):
        settings.validate(settings.DRAFT_V2, value)


@pytest.mark.parametrize(
    ("stored", "expected"),
    [(True, True), (False, False), (None, False), ("true", False), (1, False), ({}, False)],
)
def test_only_an_explicit_true_turns_it_on(stored, expected):
    assert settings.draft_v2_enabled(stored) is expected
