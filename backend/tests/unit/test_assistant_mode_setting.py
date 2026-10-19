"""assistant_mode: off by default, agent only when a platform admin says so."""

from __future__ import annotations

import pytest

from mesiri.domains.organizations import settings as s


def test_default_is_off() -> None:
    assert s.default_for(s.ASSISTANT_MODE) == "off"
    assert s.agent_mode(s.default_for(s.ASSISTANT_MODE)) is False


def test_only_the_agent_value_turns_it_on() -> None:
    assert s.agent_mode("agent") is True
    for stored in ("off", None, "", "Agent ", 1, ["agent"]):
        assert s.agent_mode(stored) is False


def test_validate_normalises_and_rejects() -> None:
    assert s.validate(s.ASSISTANT_MODE, " Agent ") == "agent"
    assert s.validate(s.ASSISTANT_MODE, "OFF") == "off"
    with pytest.raises(ValueError):
        s.validate(s.ASSISTANT_MODE, "turbo")
    with pytest.raises(ValueError):
        s.validate(s.ASSISTANT_MODE, None)


def test_a_company_cannot_switch_it_itself() -> None:
    assert s.ASSISTANT_MODE in s.SUPERADMIN_ONLY_KEYS
