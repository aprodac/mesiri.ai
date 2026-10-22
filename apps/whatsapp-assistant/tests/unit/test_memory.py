"""Conversation memory (M19): loader/coordinator composition, TTL cap, and
the "Redis is a hint, never authoritative" degrade-on-failure behaviour.
"""

from __future__ import annotations

from context.active_context import RedisActiveContextStore
from interactions.pending_media import PendingMediaStore
from memory.context_loader import ConversationMemoryLoader
from memory.conversation_scope import CurrentActivityStore, CurrentDateStore
from memory.coordinator import ConversationMemoryCoordinator
from memory.recent_turns import ConversationTurn, RecentTurnsStore
from memory.requirements import RECENT_TURNS_MAX_ENTRIES
from mesiri.infrastructure.redis.client import FakeRedis

ORG = "11111111-1111-4111-8111-111111111111"
USR = "22222222-2222-4222-8222-222222222222"


class _NoAwaiting:
    """WorkflowRuntime stand-in with no open confirmation/slot question."""

    async def get_awaiting_confirmation(self, user_id: str) -> object | None:
        return None

    async def get_awaiting_input(self, user_id: str) -> object | None:
        return None


class _RaisingAwaiting:
    async def get_awaiting_confirmation(self, user_id: str) -> object | None:
        raise RuntimeError("boom")

    async def get_awaiting_input(self, user_id: str) -> object | None:
        raise RuntimeError("boom")


def _loader(redis: FakeRedis, workflow_runtime=None) -> ConversationMemoryLoader:
    return ConversationMemoryLoader(
        active_context=RedisActiveContextStore(redis),
        current_activity=CurrentActivityStore(redis),
        current_date=CurrentDateStore(redis),
        recent_turns=RecentTurnsStore(redis),
        pending_media=PendingMediaStore(redis),
        workflow_runtime=workflow_runtime or _NoAwaiting(),
    )


async def test_empty_state_yields_all_none_and_no_pending_flags():
    redis = FakeRedis()
    await redis.connect()
    pack = await _loader(redis).load(organization_id=ORG, user_id=USR)

    assert pack.current_project_id is None
    assert pack.current_site_id is None
    assert pack.current_activity_id is None
    assert pack.current_date is None
    assert pack.has_pending_confirmation is False
    assert pack.has_pending_media is False
    assert pack.recent_turns == ()
    assert pack.is_mid_interaction is False


async def test_loader_composes_active_context_store_not_a_duplicate():
    redis = FakeRedis()
    await redis.connect()
    active_context = RedisActiveContextStore(redis)
    await active_context.set_active_context(
        organization_id=ORG, user_id=USR, project_id="proj-1", site_id="site-1", ttl_seconds=1800
    )

    pack = await _loader(redis).load(organization_id=ORG, user_id=USR)

    assert pack.current_project_id == "proj-1"
    assert pack.current_site_id == "site-1"




async def test_pending_confirmation_flag_reflects_workflow_runtime():
    redis = FakeRedis()
    await redis.connect()

    class _HasConfirmation:
        async def get_awaiting_confirmation(self, user_id: str) -> object | None:
            return object()

        async def get_awaiting_input(self, user_id: str) -> object | None:
            return None

    pack = await _loader(redis, workflow_runtime=_HasConfirmation()).load(
        organization_id=ORG, user_id=USR
    )
    assert pack.has_pending_confirmation is True
    assert pack.is_mid_interaction is True


async def test_a_failing_scope_degrades_to_none_rather_than_raising():
    redis = FakeRedis()
    await redis.connect()
    # No connect() call error possible here; instead simulate a raising
    # workflow_runtime port, the one scope with no built-in try/except of
    # its own before reaching ConversationMemoryLoader._safe.
    pack = await _loader(redis, workflow_runtime=_RaisingAwaiting()).load(
        organization_id=ORG, user_id=USR
    )
    assert pack.has_pending_confirmation is False  # degraded, not raised


async def test_recent_turns_store_is_capped_and_oldest_first():
    redis = FakeRedis()
    await redis.connect()
    store = RecentTurnsStore(redis)

    for i in range(RECENT_TURNS_MAX_ENTRIES + 4):
        await store.append(
            user_id=USR,
            turn=ConversationTurn(
                user_text=f"msg-{i}", assistant_reply=f"reply-{i}", correlation_id=f"cor-{i}"
            ),
        )

    turns = await store.recent(user_id=USR)
    assert len(turns) == RECENT_TURNS_MAX_ENTRIES
    # Oldest entries were trimmed from the front -- the newest one survives.
    assert turns[-1].user_text == f"msg-{RECENT_TURNS_MAX_ENTRIES + 3}"
    # The cap held even though 4 more than the max were appended.
    oldest_survivor_index = RECENT_TURNS_MAX_ENTRIES + 4 - RECENT_TURNS_MAX_ENTRIES
    assert turns[0].user_text == f"msg-{oldest_survivor_index}"


async def test_current_activity_store_set_get_clear():
    redis = FakeRedis()
    await redis.connect()
    store = CurrentActivityStore(redis)

    assert await store.get_current(user_id=USR) is None

    await store.set_current(user_id=USR, activity_id="act-1")
    assert await store.get_current(user_id=USR) == "act-1"

    await store.clear(user_id=USR)
    assert await store.get_current(user_id=USR) is None


async def test_coordinator_record_turn_feeds_the_loader():
    redis = FakeRedis()
    await redis.connect()
    coordinator = ConversationMemoryCoordinator(
        current_activity=CurrentActivityStore(redis),
        current_date=CurrentDateStore(redis),
        recent_turns=RecentTurnsStore(redis),
    )
    await coordinator.record_turn(
        user_id=USR, user_text="hi", assistant_reply="hello", correlation_id="cor_1"
    )

    pack = await _loader(redis).load(organization_id=ORG, user_id=USR)
    assert len(pack.recent_turns) == 1
    assert pack.recent_turns[0].user_text == "hi"
    assert pack.recent_turns[0].assistant_reply == "hello"


async def test_coordinator_record_turn_skips_empty_pairs():
    redis = FakeRedis()
    await redis.connect()
    coordinator = ConversationMemoryCoordinator(
        current_activity=CurrentActivityStore(redis),
        current_date=CurrentDateStore(redis),
        recent_turns=RecentTurnsStore(redis),
    )
    await coordinator.record_turn(
        user_id=USR, user_text="", assistant_reply="", correlation_id="cor_1"
    )
    turns = await RecentTurnsStore(redis).recent(user_id=USR)
    assert turns == ()


async def test_coordinator_record_activity_is_read_back_by_seed_open_activity_via_store():
    redis = FakeRedis()
    await redis.connect()
    coordinator = ConversationMemoryCoordinator(
        current_activity=CurrentActivityStore(redis),
        current_date=CurrentDateStore(redis),
        recent_turns=RecentTurnsStore(redis),
    )
    await coordinator.record_activity(user_id=USR, activity_id="act-42")

    pack = await _loader(redis).load(organization_id=ORG, user_id=USR)
    assert pack.current_activity_id == "act-42"
