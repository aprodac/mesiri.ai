"""assistant_mode: the agent for every company; "off" is the per-company fallback."""

from __future__ import annotations

import pytest

from mesiri.domains.organizations import settings as s


def test_default_is_the_agent() -> None:
    assert s.default_for(s.ASSISTANT_MODE) == "agent"
    assert s.agent_mode(s.default_for(s.ASSISTANT_MODE)) is True


def test_only_off_keeps_the_classic_pipeline() -> None:
    for stored in ("off", "OFF", " off "):
        assert s.agent_mode(stored) is False
    for stored in ("agent", None, "", "Agent ", 1, ["agent"]):
        assert s.agent_mode(stored) is True


def test_validate_normalises_and_rejects() -> None:
    assert s.validate(s.ASSISTANT_MODE, " Agent ") == "agent"
    assert s.validate(s.ASSISTANT_MODE, "OFF") == "off"
    with pytest.raises(ValueError):
        s.validate(s.ASSISTANT_MODE, "turbo")
    with pytest.raises(ValueError):
        s.validate(s.ASSISTANT_MODE, None)


def test_a_company_cannot_switch_it_itself() -> None:
    assert s.ASSISTANT_MODE in s.SUPERADMIN_ONLY_KEYS
