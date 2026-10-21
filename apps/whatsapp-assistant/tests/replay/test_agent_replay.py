"""Replay suite for the tool-calling agent (request [40]).

The real journey runs for every tool call -- context, canonicalization, gates,
planner, workflow graphs, save-first -- over the seed company. Only the model
is scripted (`FakeToolCallingProvider`): it decides the tool calls and writes
the final words, exactly the part a live Gemini would do. One more case,
marked `provider`, runs against real Gemini and is skipped without a key.

Needs the `workflow` extra (LangGraph), like the classic replay cases.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest

from backend.ports import ActorIdentity, ProjectSummary, SiteSummary
from context import seed
from context.fakes import FakeActiveContextStore
from context.resolver import ContextResolver
from interactions.category_hint import CategoryHintStore
from interactions.handler import InteractionHandler
from interactions.pending_report import PendingReportStore
from mesiri_ai.fakes import (
    FakeToolCallingProvider,
)
from mesiri_contracts.application.results.execution_result import ExecutionResult, ExecutionStatus
from mesiri_contracts.assistant.enums import InputModality
from mesiri_contracts.assistant.normalized_message import NormalizedMessage, SenderInfo
from planner import Planner
from runtime.agent.journey_gateway import JourneyGateway
from runtime.agent.prompt import AgentContext, Turn
from runtime.agent.runner import AgentRunner
from runtime.agent.tools import ScopeLookup
from runtime.inbound_journey import process_inbound_message, render_workflow_run_reply_spec
from runtime.noop_loggers import RecordingTraceLogger
from workflows import WorkflowRegistry, WorkflowRuntime
from workflows.fakes import FakeWorkflowInstanceRepository

pytest.importorskip("langgraph", reason="needs the `workflow` extra (LangGraph)")

from tests.replay.test_replay_cases import _MemoryRedis  # noqa: E402


class _Dispatcher:
    """Stands in for the backend: every confirmed action 'succeeds'."""

    def __init__(self) -> None:
        self.dispatched: list[Any] = []

    async def dispatch(self, confirmed):  # noqa: ANN001
        self.dispatched.append(confirmed)
        return ExecutionResult(
            status=ExecutionStatus.SUCCEEDED,
            idempotency_key=f"idem_{len(self.dispatched)}",
            material_row_id="33333333-3333-4333-8333-333333333333",
        )


class _SaveFirst:
    async def applies(self, *, workflow_key, organization_id):  # noqa: ANN001
        from runtime.save_first import SAVE_FIRST_KEYS

        return workflow_key in SAVE_FIRST_KEYS

    async def record_draft(self, **kwargs):  # noqa: ANN003
        return True

    async def note_for(self, **kwargs):  # noqa: ANN003
        return "Saved as a draft."

    async def undo_latest_draft(self, **kwargs):  # noqa: ANN003
        return None


@dataclass
class World:
    runtime: WorkflowRuntime
    handler: InteractionHandler
    dispatcher: _Dispatcher
    actor: ActorIdentity
    redis: _MemoryRedis = field(default_factory=_MemoryRedis)
    sent: list[str] = field(default_factory=list)
    journeys: int = 0
    site_ids: dict[str, str] = field(default_factory=dict)
    deps: Any = None
    last_gateway: Any = None

    def message(self, text: str) -> NormalizedMessage:
        return NormalizedMessage(
            message_id="wamid.agent.replay",
            correlation_id="cor_agent_replay",
            sender=SenderInfo(wa_id=seed.WA_ENGINEER, profile_name="Replay"),
            timestamp=datetime(2026, 10, 19, 10, 0, tzinfo=UTC),
            modality=InputModality.TEXT,
            text=text,
        )

    def gateway(self, text: str) -> JourneyGateway:
        async def process(msg, preset, sink):  # noqa: ANN001
            self.journeys += 1
            return await process_inbound_message(
                msg,
                self.actor.user_id,
                actor=self.actor,
                pipeline=preset,
                context_resolver=ContextResolver(self.deps),
                planner=Planner(),
                workflow_runtime=self.runtime,
                interaction_handler=self.handler,
                send_text=sink.send_text,
                send_list=sink.send_list,
                send_button=sink.send_button,
                trace_logger=RecordingTraceLogger(),
                pending_report_store=PendingReportStore(self.redis),
                category_hint_store=CategoryHintStore(self.redis),
            )

        return JourneyGateway(
            message=self.message(text),
            process=process,
            save_now=lambda: self.handler.save_now(self.actor.user_id, actor=self.actor),
            undo=lambda: self.handler.undo_latest_draft(
                organization_id=self.actor.organization_id, user_id=self.actor.user_id
            ),
            followups=lambda handled: _noop(),
            held_prompt=lambda journey: render_workflow_run_reply_spec(journey.workflow_run),
            language=None,
        )

    def context(self, turns: tuple[Turn, ...] = (), **kw: Any) -> AgentContext:
        return AgentContext(
            user_name=self.actor.full_name,
            role=self.actor.role,
            company=self.actor.org_name or "",
            now=datetime(2026, 10, 19, 10, 0),
            projects=(("Project Alpha", None),),
            sites=tuple((s.name, "Project Alpha") for s in self.actor.sites),
            turns=turns,
            **kw,
        )

    def scope(self) -> ScopeLookup:
        return ScopeLookup(
            projects=tuple((p.id, p.name) for p in self.actor.projects),
            sites=tuple((s.id, s.name, s.project_id) for s in self.actor.sites),
        )

    async def say(self, provider: FakeToolCallingProvider, text: str, turns=()):
        result = await AgentRunner(provider).run(
            ctx=self.context(tuple(turns)),
            user_text=text,
            gateway=(gateway := self.gateway(text)),
            scope=self.scope(),
            correlation_id="cor_agent_replay",
        )
        self.last_gateway = gateway
        return result


async def _noop() -> None:
    return None


async def _make_world(*, site_keys: tuple[str, ...], usual_site: str | None = None) -> World:
    """The seed engineer's company, with only ``site_keys`` of Project Alpha's
    sites. ``usual_site`` is the site the system remembers from their last
    message (the active context), as in daily use."""
    # The journey works in canonical (database) ids; the seed's bridge maps
    # its readable ones, as ActorIdentity carries in production.
    seed_world = seed.build_world()
    seed_world.sites = [
        s
        for s in seed_world.sites
        if s.site_id not in (seed.SITE_A1, seed.SITE_A2) or s.site_id in site_keys
    ]
    active = FakeActiveContextStore()
    deps = seed.build_dependencies(seed_world, active_store=active)
    bridge = deps.bridge
    user_id = await bridge.canonical_user_id(seed.USER_ENGINEER)
    org_id = await bridge.canonical_organization_id(seed.ORG_A)
    site_ids = {sid: await bridge.canonical_site_id(sid) for sid in site_keys}
    if usual_site:
        await active.set_active_context(
            organization_id=seed.ORG_A,
            user_id=seed.USER_ENGINEER,
            project_id=seed.PROJ_ALPHA,
            site_id=usual_site,
            ttl_seconds=3600,
        )
    runtime = WorkflowRuntime(registry=WorkflowRegistry(), repo=FakeWorkflowInstanceRepository())
    dispatcher = _Dispatcher()
    handler = InteractionHandler(runtime, dispatcher=dispatcher, save_first=_SaveFirst())
    names = {seed.SITE_A1: "Site A1", seed.SITE_A2: "Site A2"}
    actor = ActorIdentity(
        user_id=user_id,
        full_name="Anil",
        role="SUPERVISOR",
        organization_id=org_id,
        org_name="Acme Builders",
        org_active=True,
        # The context layer's ids (the database's, in production); the journey
        # maps them to canonical ones through the bridge, as `site_ids` shows.
        projects=[ProjectSummary(id=seed.PROJ_ALPHA, name="Project Alpha")],
        sites=[
            SiteSummary(id=k, name=names[k], project_id=seed.PROJ_ALPHA) for k in site_keys
        ],
    )
    world = World(runtime, handler, dispatcher, actor, deps=deps)
    world.site_ids = site_ids
    return world


@pytest.fixture
async def world() -> World:
    """A company with ONE site -- the 19 Oct live test asked "which site?" here."""
    return await _make_world(site_keys=(seed.SITE_A1,))


@pytest.fixture
async def world_two_sites() -> World:
    """Two sites, and the system remembers Site A1 from their last message."""
    return await _make_world(site_keys=(seed.SITE_A1, seed.SITE_A2), usual_site=seed.SITE_A1)


FOUR_PART_NOTE = (
    "Today 3 masons and 12 helpers worked, 180 sqm plastering done on second floor, "
    "50 bags cement arrived from Sharma Traders, and rain stopped work for 2 hours"
)


async def test_a_four_part_note_is_four_saves_one_reply_and_no_site_question(world):
    provider = FakeToolCallingProvider(
        [
            [
                ("save_labour", {"workers": [{"trade": "mason", "headcount": 3}, {"trade": "helper", "headcount": 12}]}),
                ("save_work_done", {"narrative": "180 sqm plastering done on second floor",
                                    "work_type": "plastering", "location": "second floor",
                                    "quantities": [{"work_type": "plastering", "quantity": 180, "unit": "sqm"}]}),
                ("save_material_receipt", {"material": "cement", "quantity": 50, "unit": "bags", "supplier": "Sharma Traders"}),
                ("report_issue", {"issue_type": "WEATHER", "narrative": "rain stopped work", "delay_duration_minutes": 120}),
            ],
            "✅ Saved: 15 workers, 180 sqm plastering, 50 bags cement, rain delay (2 h).",
        ]
    )
    result = await world.say(provider, FOUR_PART_NOTE)
    assert result.outcome == "ok"
    assert len(result.toolbox.saved) == 4, [c.outcome.content for c in result.run.calls]
    assert len(world.dispatcher.dispatched) == 4
    assert result.toolbox.parked is None  # no "which site?"
    assert result.reply.buttons is None and result.reply.list_rows is None
    assert provider.calls == 1  # one model run; the reply is one message
    assert result.reply.text.endswith("Wrong? Reply UNDO.")
    assert "which site" not in result.reply.text.lower()
    # One "Saved:" list from the saved data, one bullet per record.
    lines = result.reply.text.split("\n")
    assert lines[0] == "✅ Saved:"
    assert lines[1] == "• 15 workers (3 mason, 12 helper)"
    assert "• Plastering, second floor: 180 sqm" in lines
    assert "• Cement in: 50 bags (Sharma Traders)" in lines  # WA-37: the supplier shows
    assert any(line.startswith("• Issue (weather)") for line in lines)


async def test_a_malayalam_note_gets_the_saved_list_then_the_models_own_words(world):
    from channel.replies import ReplySpec
    from runtime.reply_language import localize_reply_spec

    provider = FakeToolCallingProvider(
        [
            [("save_labour", {"workers": [{"trade": "mason", "headcount": 3}]})],
            "✅ 3 മേസൺമാരുടെ ഹാജർ സേവ് ചെയ്തു.\nനാളെ കാണാം.",
        ]
    )
    result = await world.say(provider, "ഇന്ന് 3 മേസൺ പണിക്ക് വന്നു")
    # WA-37: the model's own words first; under them the "Saved:" line, written
    # from the saved data, not copied from the model.
    assert result.reply.text.startswith("നാളെ കാണാം.\n\n✅ Saved: 3 workers (3 mason)")
    assert "സേവ് ചെയ്തു" not in result.reply.text  # the model's own saved line is dropped
    # The canned workflow wording ("Labour recorded", "draft", ...) never reaches the user.
    assert "draft" not in result.reply.text.lower()
    # A Malayalam sender gets the label words in Malayalam; numbers and trade stay.
    sent = localize_reply_spec(ReplySpec(text=result.reply.text), "Malayalam", "native").text
    assert "\n✅ സേവ് ചെയ്തു: 3 തൊഴിലാളികൾ (3 mason)" in sent
    # And the model was told the user's own words, untranslated.
    assert provider.last_messages[-1].text.endswith("ഇന്ന് 3 മേസൺ പണിക്ക് വന്നു")


async def test_and_10_more_continues_the_previous_turn(world):
    turns = (Turn("3 masons today", "✅ 3 masons saved. Wrong? Reply UNDO."),)

    def second_step(records):  # noqa: ANN001
        return [("save_labour", {"workers": [{"trade": "mason", "headcount": 10}]})]

    provider = FakeToolCallingProvider([second_step, "✅ 10 more masons saved."])
    result = await world.say(provider, "and 10 more", turns=turns)
    sent = [m.text for m in provider.last_messages]
    assert any("3 masons today" in t for t in sent)  # the model had the previous turn
    assert len(result.toolbox.saved) == 1
    assert world.dispatcher.dispatched[0].draft_action.fields["lines"]


async def test_a_two_part_question_is_two_queries_and_one_answer(world):
    provider = FakeToolCallingProvider(
        [
            [("query_labour", {"date_range": "today"}), ("query_materials", {"material": "cement"})],
            "No attendance yet today, and no cement stock recorded.",
        ]
    )
    result = await world.say(provider, "how many workers today and how much cement is left?")
    assert world.journeys == 2
    assert result.reply.text == "No attendance yet today, and no cement stock recorded."
    assert "UNDO" not in result.reply.text  # nothing was saved
    assert world.dispatcher.dispatched == []


async def test_an_unclear_note_is_one_question_with_buttons(world):
    provider = FakeToolCallingProvider(
        [
            [("ask_user", {"question": "Was that cement received or used?", "options": ["Received", "Used"]})],
            "Was that cement received or used?",
        ]
    )
    result = await world.say(provider, "50 bags cement")
    assert world.journeys == 0  # nothing was run on a guess
    assert result.reply.text == "Was that cement received or used?"
    assert [b.title for b in result.reply.buttons] == ["Received", "Used"]


async def test_green_villa_after_a_which_site_question_is_a_site_not_a_yes(world_two_sites):
    world = world_two_sites
    turns = (
        Turn(
            "3 masons today",
            "Which site was that for?\n[options: Site A1 / Site A2]",
        ),
    )
    # With no confirmation waiting, the classic fast path does not take the reply
    # at all, so it reaches the agent as an ordinary message.
    assert await world.handler.handle_fast_path(world.actor.user_id, world.message("Site A2")) is None

    provider = FakeToolCallingProvider(
        [
            [("save_labour", {"workers": [{"trade": "mason", "headcount": 3}], "site": "Site A2"})],
            "✅ 3 masons saved for Site A2.",
        ]
    )
    result = await world.say(provider, "Site A2", turns=turns)
    assert len(result.toolbox.saved) == 1
    # The site was matched to the user's own site by id, not confirmed or skipped.
    assert world.dispatcher.dispatched[0].draft_action.site_id == world.site_ids[seed.SITE_A2]


async def test_with_two_sites_the_usual_one_is_used_when_the_user_named_none(world_two_sites):
    world = world_two_sites
    provider = FakeToolCallingProvider(
        [[("save_work_done", {"narrative": "shuttering started"})], "✅ Saved."]
    )
    result = await world.say(provider, "shuttering started")
    assert result.toolbox.parked is None
    assert len(result.toolbox.saved) == 1


async def test_real_gemini_saves_a_four_part_note(world):
    """Smoke test: a live Gemini against the same journey and a latency
    reading. Needs GEMINI_API_KEY (skipped without it; never runs in CI)."""
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        pytest.skip("GEMINI_API_KEY not set")
    from pydantic import SecretStr

    from mesiri.bootstrap.settings import GeminiSettings
    from mesiri_ai.adapters.gemini.adapter import GeminiProvider

    provider = GeminiProvider(
        GeminiSettings(api_key=SecretStr(key), model=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"))
    )
    result = await AgentRunner(provider).run(
        ctx=world.context(),
        user_text=FOUR_PART_NOTE,
        gateway=world.gateway(FOUR_PART_NOTE),
        scope=world.scope(),
    )
    assert result.outcome == "ok"
    assert len(result.toolbox.saved) >= 3
    # Latency target (request [40]): text under 4 s with at most 2 tool steps.
    print(f"agent latency_ms={result.run.latency_ms} steps={result.run.steps}")
    assert result.run.steps <= 2
    assert result.run.latency_ms < 4000


async def test_the_pipeline_around_the_model_adds_little_latency(world):
    """With the model scripted, four saves through the real journey must be a
    small fraction of the 4 s budget (the rest is the live model's)."""
    import time

    provider = FakeToolCallingProvider(
        [
            [
                ("save_labour", {"workers": [{"trade": "mason", "headcount": 3}]}),
                ("save_work_done", {"narrative": "plastering 180 sqm"}),
                ("save_material_receipt", {"material": "cement", "quantity": 50, "unit": "bags"}),
                ("report_issue", {"issue_type": "WEATHER", "narrative": "rain"}),
            ],
            "Saved.",
        ]
    )
    started = time.perf_counter()
    await world.say(provider, FOUR_PART_NOTE)
    assert time.perf_counter() - started < 1.0


async def test_one_expense_is_one_question_then_one_saved_reply(world):
    """Request [55]: an expense must not be answered twice (the 19 Oct live
    test showed it, with the menu, twice). The first message ends in ONE reply
    carrying the confirm card once; the Yes tap saves once and is answered
    once -- counted per message, not just by looking at the text."""
    provider = FakeToolCallingProvider(
        [
            [("save_expense", {"amount": 500, "description": "tea and snacks"})],
            "Paid 500 for tea and snacks. Save it?",
        ]
    )
    result = await world.say(provider, "paid 500 for tea and snacks")

    assert provider.calls == 1
    assert world.journeys == 1  # one journey run for one expense
    reply = result.reply
    assert [b.title for b in reply.buttons] == ["Yes", "No"]  # one message, one Yes/No
    assert "Here's what I can help with" not in reply.text  # no menu beside it
    assert world.dispatcher.dispatched == []  # nothing saved before the Yes

    handled = await world.handler.handle_fast_path(world.actor.user_id, world.message("Yes"))
    assert handled is not None
    assert len(world.dispatcher.dispatched) == 1  # saved once
    again = await world.handler.handle_fast_path(world.actor.user_id, world.message("Yes"))
    assert again is None
    assert len(world.dispatcher.dispatched) == 1  # a second Yes saves nothing more


async def test_a_question_in_a_note_is_noted_for_the_engineer_and_the_reply_says_so(world):
    """Request 57, B2/B3: the question is saved (not just echoed), and the saved
    list is built from what was saved, not from the worker's raw words."""
    provider = FakeToolCallingProvider(
        [
            [
                ("save_labour", {"workers": [{"trade": "mason", "headcount": 6}, {"trade": "helper", "headcount": 10}]}),
                ("note_for_engineer", {"question": "Nale slab concrete cheyyan pattumo?"}),
            ],
            "Nale slab concrete cheyyan pattumo?",  # the model only echoes it
        ]
    )
    result = await world.say(provider, "6 mason, 10 helper vannu. Nale slab concrete cheyyan pattumo?")
    assert len(result.toolbox.saved) == 2
    # WA-37: the labour is the one entry to check; the question is passed on,
    # said once on its own line, never listed as saved.
    assert result.reply.text == (
        "✅ Saved: 16 workers (6 mason, 10 helper)\n\n"
        "📨 Question for your engineer: Nale slab concrete cheyyan pattumo?\n\n"
        "Wrong? Reply UNDO."
    )
    assert "vannu" not in result.reply.text
    assert result.reply.text.count("Nale slab concrete cheyyan pattumo?") == 1


async def test_a_figure_the_tools_never_gave_is_not_sent(world):
    """WA-37: the model said 15 workers and 40 bags; the records hold neither.
    The tools' own answers go out instead of the made-up figures."""
    provider = FakeToolCallingProvider(
        [
            [("query_labour", {"date_range": "today"}), ("query_materials", {"material": "cement"})],
            "Today: 15 workers on site. Cement in stock: 40 bags.",
        ]
    )
    result = await world.say(provider, "how many workers today and how much cement is left?")
    assert "15" not in result.reply.text and "40" not in result.reply.text
    assert result.reply.text == "\n\n".join(result.toolbox.answers)
