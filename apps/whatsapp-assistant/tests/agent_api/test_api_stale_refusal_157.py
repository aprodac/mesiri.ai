"""WA-157 (3 Nov, test company): "add Rajesh to Zeta Plaza" was refused after [207] shipped the feature: the same
request had been refused three times that morning, and the model repeated its own remembered "Sorry, I cannot".
Each reply is remembered with the tools Mesiri had; a reply from another or an unknown tool set is read back marked
as said by an older version. Guard: replies from the current tools, and the person's own words, read as they were."""

from __future__ import annotations

from types import SimpleNamespace

from agent_api.memory import OLDER_NOTE, DayMemory, tools_version
from mesiri.infrastructure.redis.client import FakeRedis

CTX = SimpleNamespace(organization_id="o1", user_id="u1", timezone="Asia/Kolkata")
BEFORE = tools_version(["record_receipt", "create_project"])
NOW = tools_version(["record_receipt", "create_project", "add_project_member"])


async def test_a_refusal_from_before_the_new_tool_is_read_as_possibly_stale() -> None:
    redis = FakeRedis()
    await DayMemory(None, redis, version=BEFORE).remember(CTX, "Sahal-ine Live Mart B-il add cheyyu", "Sorry, I cannot add members to a project.")
    said = await DayMemory(None, redis, version=NOW).load(CTX)
    assert said[0].text == "Sahal-ine Live Mart B-il add cheyyu"  # the person's words: as they were
    assert said[1].text == OLDER_NOTE + "Sorry, I cannot add members to a project."
    assert "[tools:" not in said[1].text


async def test_sibling_a_reply_stored_before_any_tag_is_marked_too() -> None:
    redis = FakeRedis()
    await DayMemory(None, redis).remember(CTX, "add Sahal", "Sorry, I cannot add members to a project.")  # untagged: the 3 Nov history
    said = await DayMemory(None, redis, version=NOW).load(CTX)
    assert said[1].text.startswith(OLDER_NOTE)


async def test_guard_a_reply_from_the_same_tools_reads_as_it_was() -> None:
    redis = FakeRedis()
    await DayMemory(None, redis, version=NOW).remember(CTX, "50 bag cement vannu", "Ready: 50 bags cement.")
    said = await DayMemory(None, redis, version=NOW).load(CTX)
    assert [m.text for m in said] == ["50 bag cement vannu", "Ready: 50 bags cement."]
    assert tools_version(["b", "a"]) == tools_version(["a", "b"])
