"""WA-57: a message's other parts are not lost behind a question.

Live 23 Oct: "holo bricks came, the scaffolders and plasterers were there" was
asked about the bricks only, and after the bricks were saved the labour part
was gone. Each part not done is now kept, shown to the model every turn,
dropped when its tool saves, and taken up right after the Save tap."""

from __future__ import annotations

import functools
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

from tests.unit.test_agent_routing import _build, _message

from channel.replies import ReplySpec
from mesiri_ai.fakes import FakeToolCallingProvider
from mesiri_contracts.assistant.enums import InputModality
from runtime.agent import later as lt
from runtime.agent import save_button as sb
from runtime.agent import toolbox as tb
from runtime.agent.gateway import StepResult
from runtime.agent.prompt import reply_language, reply_letters_rule
from runtime.agent.runner import AgentResult
from runtime.agent.tools import ScopeLookup, tool_specs
from runtime.agent.turn import AgentTurnDeps, run_agent_turn

LABOUR = lt.LaterItem("save_labour", "scaffolders and plasterers came, no count yet")
ACTOR = SimpleNamespace(
    organization_id="org-1", user_id="u1", full_name="Ilan", role="SUPERVISOR",
    org_name="Acme", projects=[], sites=[],
)


class _Redis:
    def __init__(self) -> None:
        self.data: dict = {}

    def namespaced(self, *parts):  # noqa: ANN002, ANN201
        return ":".join(parts)

    async def set_json(self, key, value, *, ttl_seconds=None):  # noqa: ANN001, ANN201
        self.data[key] = value

    async def get_json(self, key):  # noqa: ANN001, ANN201
        return self.data.get(key)

    async def delete(self, *keys):  # noqa: ANN002, ANN201
        for key in keys:
            self.data.pop(key, None)


class _Gateway:
    def __init__(self, *results: StepResult) -> None:
        self.results = list(results)
        self.runs: list = []

    async def run(self, candidate, *, text):  # noqa: ANN001, ANN201
        self.runs.append(candidate)
        return self.results.pop(0)


def _box(*results: StepResult) -> tb.AgentToolbox:
    return tb.AgentToolbox(_Gateway(*results), ScopeLookup(), "the note")


# -- the list ---------------------------------------------------------------


def test_a_save_takes_off_the_part_it_names_and_new_parts_come_in_once():
    cement = lt.LaterItem("save_material_receipt", "cement came, no count")
    after = lt.merged([LABOUR, cement], saved=[("save_labour", "4 scaffolder, 3 plasterer")], added=[])
    assert after == [cement]
    reworded = lt.LaterItem("save_material_receipt", "cement arrived")
    assert lt.merged([cement], saved=[], added=[reworded]) == [reworded]
    loose = lt.LaterItem("", "Check the crane")
    assert lt.merged([loose], saved=[], added=[lt.LaterItem("", "check the crane")]) == [
        lt.LaterItem("", "check the crane")
    ]


def test_two_materials_are_two_parts_and_saving_one_keeps_the_other():
    """WA-58: one item per tool lost the first of two materials."""
    bricks = lt.LaterItem("save_material_receipt", "holo bricks came, no count")
    cement = lt.LaterItem("save_material_receipt", "cement came, no count")
    both = lt.merged([], saved=[], added=[bricks, cement])
    assert both == [bricks, cement]
    assert lt.merged(both, saved=[("save_material_receipt", "Cement 10 bag")], added=[]) == [bricks]
    assert lt.merged(both, saved=[("save_material_receipt", "Holobricks 100 nos")], added=[]) == [cement]
    # A save of something else of the same kind clears nothing.
    assert lt.merged(both, saved=[("save_material_receipt", "Sand 2 load")], added=[]) == both


def test_a_held_call_and_the_models_note_of_it_are_one_part():
    held = lt.held_item("save_labour", {"workers": [{"trade": "scaffolder"}, {"trade": "plasterer"}]})
    assert lt.merged([], saved=[], added=[held, LABOUR]) == [LABOUR]


def test_the_model_drops_a_part_that_is_done_or_not_needed():
    cement = lt.LaterItem("save_material_receipt", "cement came, no count")
    assert lt.merged([LABOUR, cement], saved=[], added=[], drop={1}) == [cement]


def test_the_list_is_short_and_notes_are_cut():
    many = [lt.LaterItem("", f"part {n}") for n in range(10)]
    assert len(lt.merged([], saved=[], added=many)) == lt.MAX_ITEMS
    long = lt.merged([], saved=[], added=[lt.LaterItem("", "x" * 500)])[0]
    assert len(long.note) == lt.NOTE_LIMIT


def test_the_model_is_told_what_is_left_and_the_follow_up_keeps_their_language():
    assert lt.context_line([]) is None
    line = lt.context_line([LABOUR])
    assert "scaffolders and plasterers came, no count yet (save_labour)" in line
    text = lt.follow_up_text(LABOUR)
    assert text.startswith(lt.FOLLOW_UP_PREFIX)
    # English words of the system's own: no "reply in English" rule.
    assert reply_letters_rule(text) is None
    assert reply_language(text) is None


async def test_the_store_keeps_the_list_and_asks_each_part_once():
    store = lt.LaterStore(_Redis())
    assert await store.get(ACTOR) == []
    cement = lt.LaterItem("save_material_receipt", "cement came, no count")
    await store.put(ACTOR, [LABOUR, cement])
    assert await store.ask_next(ACTOR) == LABOUR
    # Asked, but still on the list until it is saved or dropped.
    assert await store.get(ACTOR) == [lt.LaterItem(LABOUR.tool, LABOUR.note, 1), cement]
    assert await store.ask_next(ACTOR) == cement
    assert await store.ask_next(ACTOR) is None
    await store.put(ACTOR, [])
    assert await store.get(ACTOR) == []
    # No company or user: nothing kept, nothing raised.
    assert await store.get(SimpleNamespace()) == []


# -- the toolbox --------------------------------------------------------------


def test_still_to_do_is_a_tool():
    assert "still_to_do" in {s.name for s in tool_specs()}


async def test_a_call_held_behind_a_waiting_question_is_kept_with_what_it_said():
    gate = ReplySpec(text="How many holo bricks?")
    box = _box(StepResult("needs_answer", text="How many holo bricks?", reply=gate))
    await box.handle("save_material_receipt", {"material": "Holobricks"})
    held = await box.handle("save_labour", {"workers": [{"trade": "scaffolder"}, {"trade": "plasterer"}]})
    assert held.content["status"] == "held"
    assert box.held == ["save_labour"]
    [item] = box.later
    assert item.tool == "save_labour" and "scaffolder" in item.note and "plasterer" in item.note


async def test_the_model_can_note_parts_even_while_a_question_waits():
    gate = ReplySpec(text="How many holo bricks?")
    box = _box(StepResult("needs_answer", text="How many holo bricks?", reply=gate))
    await box.handle("save_material_receipt", {"material": "Holobricks"})
    noted = await box.handle(
        "still_to_do",
        {"items": [{"tool": "save_labour", "what": LABOUR.note}, {"tool": "drop_table", "what": "odd"}]},
    )
    assert noted.content["status"] == "noted"
    assert box.later == [LABOUR, lt.LaterItem("", "odd")]
    assert box.calls == 1  # the bricks; a note is not an action
    empty = await box.handle("still_to_do", {"items": [{"tool": "save_labour"}]})
    assert empty.content["status"] == "error"
    dropped = await box.handle("still_to_do", {"drop": [2, 0, "x"]})
    assert dropped.content["status"] == "noted" and box.later_drop == {2}


async def test_a_question_carries_the_other_parts_of_the_message():
    box = _box()
    asked = await box.handle(
        "ask_user",
        {"question": "Ethra holo bricks?", "other_parts": [{"tool": "save_labour", "what": LABOUR.note}]},
    )
    assert asked.content["status"] == "question_sent"
    assert box.later == [LABOUR]


async def test_a_question_held_behind_a_gate_still_keeps_its_other_parts():
    gate = ReplySpec(text="How many holo bricks?")
    box = _box(StepResult("needs_answer", text="How many holo bricks?", reply=gate))
    await box.handle("save_material_receipt", {"material": "Holobricks"})
    await box.handle(
        "ask_user", {"question": "x?", "other_parts": [{"tool": "save_labour", "what": LABOUR.note}]}
    )
    assert box.later == [LABOUR]


# -- the turn ----------------------------------------------------------------


def _runner(seen: list, box: SimpleNamespace):
    class _Runner:
        async def run(self, *, ctx, **_kw):  # noqa: ANN001, ANN202
            seen.append(ctx)
            return AgentResult("ok", ReplySpec(text="ok"), box)

    return _Runner()


def _deps(runner, store) -> AgentTurnDeps:
    return AgentTurnDeps(
        runner=runner,
        make_gateway=lambda message, language: SimpleNamespace(handled=[], finish=AsyncMock()),
        send_spec=AsyncMock(),
        transcribe=None,
        message_logger=AsyncMock(),
        later=store,
    )


def _turn_box(*, later=(), saved=(), drop=()):
    return SimpleNamespace(
        saved=list(saved), attempted_writes=0, parked=None, answers=["x"], notes=[], later=list(later),
        later_drop=set(drop),
    )


async def test_a_turn_keeps_its_parts_and_the_next_one_sees_them_until_saved():
    store = lt.LaterStore(_Redis())
    seen: list = []
    await run_agent_turn(_message("holo bricks came"), ACTOR, _deps(_runner(seen, _turn_box(later=[LABOUR])), store))
    assert await store.get(ACTOR) == [LABOUR]

    await run_agent_turn(_message("100"), ACTOR, _deps(_runner(seen, _turn_box()), store))
    assert any("save_labour" in n for n in seen[-1].notes)
    assert await store.get(ACTOR) == [LABOUR]  # the bricks saved, labour still to do

    saved = [tb.SavedItem("save_labour", "ok", "4 scaffolder, 3 plasterer")]
    await run_agent_turn(_message("4 and 3"), ACTOR, _deps(_runner(seen, _turn_box(saved=saved)), store))
    assert await store.get(ACTOR) == []


# -- the Save tap -------------------------------------------------------------


def _tap(action):
    row = uuid.uuid4()
    return _message(sb.SAVE_TITLE, modality=InputModality.INTERACTIVE).model_copy(
        update={
            "metadata": {
                "interactive_reply_id": sb.tap_id(action, [("material_receipt", row)]),
                "interactive_reply_type": "button_reply",
            }
        }
    )


async def _wired(monkeypatch, provider, items=(LABOUR,)):
    """The real handlers with a Save tap that settles, and a list holding the
    labour part for the sender."""
    import runtime.message_journey as mj
    from runtime.save_first import DraftsSettled

    store = lt.LaterStore(_Redis())
    built = mj.build_message_handlers

    @functools.wraps(built)
    def with_later(**kw):  # noqa: ANN003, ANN202
        return built(**kw, later=store)

    monkeypatch.setattr(mj, "build_message_handlers", with_later)
    on_normalized, deps, _ = _build(monkeypatch, mode="agent", provider=provider)
    deps["interaction_handler"].settle_drafts.return_value = DraftsSettled(done=1)
    actor = await mj.resolve_sender(None, "x")
    monkeypatch.setattr(mj, "resolve_sender", AsyncMock(return_value=actor))
    await store.put(actor, list(items))
    return on_normalized, deps, store, actor


async def test_after_save_the_next_part_is_asked_at_once(monkeypatch):
    question = "Ethra scaffolders, plasterers vannu?"
    provider = FakeToolCallingProvider([[("ask_user", {"question": question})], question])
    on_normalized, deps, store, actor = await _wired(monkeypatch, provider)

    await on_normalized(_tap(sb.SAVE), {})

    sent = [c.args[1] for c in deps["sender"].send_text.await_args_list]
    assert sent[0] == sb.SAVED_DONE
    assert provider.calls == 1
    told = str(provider.last_messages[-1])
    assert lt.FOLLOW_UP_PREFIX in told and "scaffolders and plasterers" in told
    assert question in str(deps["sender"].mock_calls)
    # Asked once; it stays until the answer is saved.
    assert await store.get(actor) == [lt.LaterItem(LABOUR.tool, LABOUR.note, 1)]
    # WA-58: the tap itself is in the conversation the model reads next.
    recorded = [c.kwargs for c in deps["memory_coordinator"].record_turn.await_args_list]
    assert recorded[0]["assistant_reply"] == sb.SAVED_DONE


async def test_cancel_asks_nothing_and_keeps_the_list(monkeypatch):
    provider = FakeToolCallingProvider([])
    on_normalized, deps, store, actor = await _wired(monkeypatch, provider)

    await on_normalized(_tap(sb.CANCEL), {})

    assert provider.calls == 0
    assert await store.get(actor) == [LABOUR]


async def test_one_part_is_asked_per_save_and_the_rest_wait(monkeypatch):
    cement = lt.LaterItem("save_material_receipt", "cement came, no count")
    question = "Ethra scaffolders, plasterers vannu?"
    provider = FakeToolCallingProvider([[("ask_user", {"question": question})], question])
    on_normalized, _, store, actor = await _wired(monkeypatch, provider, items=(LABOUR, cement))

    await on_normalized(_tap(sb.SAVE), {})

    told = str(provider.last_messages[-1])
    follow_up = told[told.index(lt.FOLLOW_UP_PREFIX):]
    assert "scaffolders and plasterers" in follow_up and "cement" not in follow_up
    assert await store.get(actor) == [lt.LaterItem(LABOUR.tool, LABOUR.note, 1), cement]
