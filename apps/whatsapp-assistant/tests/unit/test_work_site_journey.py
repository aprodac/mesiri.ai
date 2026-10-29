"""WA-45 through the real message handler: the morning question holds the
day's first message, the tap runs it at the chosen site, and "now at Site B"
switches mid-day. Services are mocks; the journey and the agent are real, with
the model's tool calls scripted."""

from __future__ import annotations

import datetime as dt
import inspect
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import runtime.message_journey as mj
from backend.ports import ProjectSummary, SiteSummary
from context.active_context import RedisActiveContextStore
from mesiri.infrastructure.redis.client import FakeRedis
from mesiri_ai.fakes import FakeToolCallingProvider
from mesiri_contracts.assistant.enums import InputModality
from mesiri_contracts.assistant.normalized_message import NormalizedMessage, SenderInfo
from runtime.agent.work_site import WorkSite

ORG = str(uuid.uuid4())
USER = str(uuid.uuid4())
PROJECTS = [ProjectSummary("pa", "Project A"), ProjectSummary("pb", "Project B")]
SITES = [SiteSummary("a1", "Site A", "pa"), SiteSummary("b2", "Site B", "pb")]


def _message(text, *, tap=None, n=1):
    return NormalizedMessage(
        message_id=f"wamid.in.{n}",
        sender=SenderInfo(wa_id="919000000002", profile_name="Suresh"),
        timestamp=dt.datetime(2026, 10, 22, 1, tzinfo=dt.UTC),
        modality=InputModality.INTERACTIVE if tap else InputModality.TEXT,
        text=text,
        metadata={"interactive_reply_id": tap} if tap else {},
    )


def _build(monkeypatch, provider, work_site):
    async def fake_resolve(_reader, wa_id):
        return SimpleNamespace(
            organization_id=ORG,
            org_active=True,
            user_id=USER,
            full_name="Suresh Kumar",
            role="SITE_ENGINEER",
            org_name="Acme Builders",
            timezone="Asia/Kolkata",
            projects=list(PROJECTS),
            sites=list(SITES),
        )

    monkeypatch.setattr(mj, "resolve_sender", fake_resolve)
    params = inspect.signature(mj.build_message_handlers).parameters
    deps = {n: AsyncMock() for n, p in params.items() if p.default is inspect.Parameter.empty}
    handler = deps["interaction_handler"]
    handler.handle_fast_path.return_value = None
    handler.handle_slot_answer.return_value = None
    for sync_name in (
        "handle_category_tap",
        "handle_material_direction_tap",
        "handle_image_purpose_tap",
        "handle_greeting_trigger",
        "handle_whoami_trigger",
    ):
        setattr(handler, sync_name, MagicMock(return_value=None))
    handler.undo_latest_draft.return_value = None
    deps["org_settings_query"].enabled_modules.return_value = ["dpr", "labour"]
    deps["org_settings_query"].get.return_value = "agent"
    deps["category_hint_store"].pop_hint.return_value = None
    deps["memory_loader"].load.return_value = SimpleNamespace(recent_turns=(), has_pending_confirmation=False)
    monkeypatch.setattr(mj, "try_hold_new_image_for_purpose_picker", AsyncMock(return_value=None))
    monkeypatch.setattr(mj.workflow_registry, "set_enabled_modules", MagicMock())
    on_normalized, _ = mj.build_message_handlers(**deps, agent_provider=provider, work_site=work_site)
    return on_normalized, deps


def _work_site():
    redis = FakeRedis()
    now = dt.datetime(2026, 10, 22, 1, tzinfo=dt.UTC)  # 06:30 India time
    store = RedisActiveContextStore(redis, clock=lambda: now)
    return WorkSite(active_context=store, redis=redis, clock=lambda: now), store


async def test_the_days_first_message_waits_for_where_and_runs_after_the_tap(monkeypatch):
    work_site, store = _work_site()
    model = FakeToolCallingProvider(
        [
            [("ask_user", {"question": "Received or used?", "options": ["Received", "Used"]})],
            "Received or used?",
        ]
    )
    on_normalized, deps = _build(monkeypatch, model, work_site)

    await on_normalized(_message("50 bags cement"), {})

    # The question went out; the model has not seen the message yet.
    assert model.calls == 0
    sent = deps["sender"].send_list.await_args.kwargs
    assert sent["body"] == "Good morning, Suresh! 👷\nWhere are you working today?"
    assert sent["button_label"] == "Choose site"
    assert [(r.id, r.title, r.description) for r in sent["rows"]] == [
        ("today_site:a1", "Site A", "Project A"),
        ("today_site:b2", "Site B", "Project B"),
    ]

    await on_normalized(_message("Site B", tap="today_site:b2", n=2), {})

    texts = [c.args[1] for c in deps["sender"].send_text.await_args_list]
    assert any(t.startswith("👍 Site B (Project B) for today.") for t in texts)
    active = await store.get_active_context(organization_id=ORG, user_id=USER)
    assert active.site_id == "b2"
    # ...and the waiting message now reached the model, told where they are.
    assert model.calls >= 1
    assert "Working today at: Site B (Project B)" in str(model.last_messages)
    assert "50 bags cement" in str(model.last_messages)
    asked = deps["sender"].send_button.await_args.kwargs
    assert asked["body"] == "Received or used?"


async def test_once_the_site_is_set_the_next_message_goes_straight_on(monkeypatch):
    work_site, _ = _work_site()
    await work_site.set_today(SimpleNamespace(organization_id=ORG, user_id=USER, sites=SITES, timezone=None),
                              project_id="pb", site_id="b2")
    model = FakeToolCallingProvider(["Good morning! 👍"])
    on_normalized, deps = _build(monkeypatch, model, work_site)

    await on_normalized(_message("good morning, on the way"), {})

    assert model.calls == 1
    assert deps["sender"].send_list.await_count == 0


async def test_now_at_site_a_switches_mid_day(monkeypatch):
    work_site, store = _work_site()
    actor = SimpleNamespace(organization_id=ORG, user_id=USER, sites=SITES, timezone=None)
    await work_site.set_today(actor, project_id="pb", site_id="b2")
    model = FakeToolCallingProvider(
        [
            [("set_work_site", {"site": "Site A"})],
            "OK 👍 Site A (Project A) for the rest of today.",
        ]
    )
    on_normalized, deps = _build(monkeypatch, model, work_site)

    await on_normalized(_message("now at site A"), {})

    active = await store.get_active_context(organization_id=ORG, user_id=USER)
    assert (active.project_id, active.site_id) == ("pa", "a1")
    reply = deps["sender"].send_text.await_args.args[1]
    assert reply == "OK 👍 Site A (Project A) for the rest of today."


async def test_sit02_sit03_two_waiting_messages_both_run_when_the_site_is_typed(monkeypatch):
    """V1 audit: the second message does not replace the first, and typing the
    site name answers the question like the tap."""
    work_site, store = _work_site()
    model = FakeToolCallingProvider(["Noted cement 👍", "Noted masons 👍"])
    on_normalized, deps = _build(monkeypatch, model, work_site)

    await on_normalized(_message("50 bags cement arrived", n=1), {})
    await on_normalized(_message("12 masons today", n=2), {})
    assert model.calls == 0  # both wait; the model has seen neither
    assert deps["sender"].send_list.await_count == 2

    await on_normalized(_message("Site B", n=3), {})

    active = await store.get_active_context(organization_id=ORG, user_id=USER)
    assert active.site_id == "b2"
    assert model.calls == 2  # one turn per waiting message, in order
    texts = [c.args[1] for c in deps["sender"].send_text.await_args_list]
    assert any(t.startswith("👍 Site B (Project B) for today.") for t in texts)
