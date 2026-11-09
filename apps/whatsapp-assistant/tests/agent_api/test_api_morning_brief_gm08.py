"""GM-08 (9 Nov 2026): "stop the morning message" turns off the person's own brief through /me, held for Save."""

from __future__ import annotations

from pathlib import Path

from tests.agent_api.replaykit import _real_tools


def test_the_switch_is_the_persons_own_route_and_held_for_save() -> None:
    tool = _real_tools()["set_morning_brief"]
    assert (tool.method, tool.path) == ("PUT", "/me/morning-brief") and tool.is_write and "on" in tool.body_fields


def test_the_sop_keeps_it_to_their_own_setting() -> None:
    sop = (Path(__file__).resolve().parents[2] / "src/agent_api/SOP.md").read_text(encoding="utf-8")
    assert "`set_morning_brief` with on false or true" in sop and "never turn it off for someone else" in sop
