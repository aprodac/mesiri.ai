"""Request 185: v2 on Google ADK, with the conversation kept whole.

A scripted ADK model (``ScriptedLlm``) drives the real journey World, so the card, the reads
and the guards are today's; what is checked here is the engine and the memory:

- the families of the 27-31 Oct cross-check that came from memory (it denied its own reply, lost
  the question it asked, could not see a swiped message) cannot happen: the model is sent them;
- a draft ends the run without a second model call (``done``), a question ends it (``stop``),
  the step limit holds;
- a model failure before any action falls back to today's agent; the card is never lost.
"""

from __future__ import annotations

from dataclasses import replace

from tests.agent_v2.replaykit import AdkEngine, new_world

from agent_v2.adk.agent import SHOWN_PREFIX
from agent_v2.adk.memory import session_keys
from agent_v2.adk.models import ScriptedLlm
from agent_v2.agents.main import MAX_STEPS
from runtime.agent import draft as dr


def seen(model: ScriptedLlm, index: int = -1) -> str:
    return "\n".join(f"{role}: {text}" for role, text in model.seen_texts(index))


async def send(engine: AdkEngine, world, text: str, **ctx_kw):  # noqa: ANN001, ANN201
    card = await world.drafts.open_for(world.actor.organization_id, world.actor.user_id)
    ctx = world.context(card_line=dr.context_line(card), **ctx_kw)
    return await engine.runner.run(ctx=ctx, user_text=text, gateway=world.gateway(text), scope=world.scope(), correlation_id="cor_t")


async def test_a_receipt_goes_on_the_card_in_one_model_call():
    model = ScriptedLlm([[("draft_receipt", {"material": "cement", "quantity": 50, "unit": "bags"})]])
    engine, world = AdkEngine(model), await new_world()
    result = await send(engine, world, "50 bag cement vannu")
    draft = await world.drafts.open_for(world.actor.organization_id, world.actor.user_id)
    assert [i.kind for i in draft.items] == [dr.KIND_MATERIAL_IN]
    assert len(model.requests) == 1  # done: the code writes the reply, no second model call
    assert result.reply is not None and "50" in result.reply.text
    assert engine.classic_calls.calls == 0


async def test_next_turn_the_model_sees_its_own_reply_and_the_card_lines_it_was_shown():
    """Family 1: 'I never said rain' -- it is sent what it said, as the sender saw it."""
    model = ScriptedLlm(
        [
            [("draft_receipt", {"material": "cement", "quantity": 50, "unit": "bags"})],
            "Innu cement 50 bags vannu ennanu paranjathu.",
        ]
    )
    engine, world = AdkEngine(model), await new_world()
    await send(engine, world, "50 bag cement vannu")
    await send(engine, world, "njan enthanu paranjathu?")
    shown = seen(model)
    assert "user: 50 bag cement vannu" in shown
    assert SHOWN_PREFIX in shown and "Cement" in shown  # the card line it showed under its words
    assert "njan enthanu paranjathu?" in shown


async def test_a_question_it_asked_is_in_the_conversation_when_they_answer_it():
    """Family 4: 'which project?' five times -- the model is sent the question it asked."""
    model = ScriptedLlm(
        [
            "Ethu project-ile issue aanu close cheyyendathu?",
            "Sheri, Hospital Project-ile mazha issue close cheyyam.",
        ]
    )
    engine, world = AdkEngine(model), await new_world()
    await send(engine, world, "aa issue close cheyyu")
    await send(engine, world, "Hospital Project")
    shown = seen(model)
    assert "Ethu project-ile issue aanu close cheyyendathu?" in shown
    assert shown.index("Ethu project-ile") < shown.index("user: Hospital Project")


async def test_a_swiped_message_is_in_the_sender_turn_and_stays_in_the_conversation():
    """Family 2: 'I can't see that message' -- the quoted words are part of what they said."""
    model = ScriptedLlm(["Athil 30 workers ennanu.", "Sheri."])
    engine, world = AdkEngine(model), await new_world()
    await send(engine, world, "ith kando?", replying_to=("Innu 30 per vannu.", "mesiri"))
    await send(engine, world, "ok")
    assert 'replying to your earlier message: "Innu 30 per vannu."' in seen(model)


async def test_the_state_of_the_day_is_fresh_each_turn_and_not_stored_in_the_conversation():
    model = ScriptedLlm(["ok", "ok"])
    engine, world = AdkEngine(model), await new_world()
    await send(engine, world, "hi")
    await send(engine, world, "hello")
    conversation = seen(model)
    assert "[context]" not in conversation  # the context is in the instructions, not the turns
    instruction = str(model.requests[-1].config.system_instruction)
    assert "Material catalog" in instruction and "today's, in full" in instruction


async def test_each_person_has_their_own_conversation_per_day():
    model = ScriptedLlm(["ok", "ok"])
    engine, world = AdkEngine(model), await new_world()
    await send(engine, world, "first person says this")
    other = replace(world.actor, user_id="00000000-0000-0000-0000-000000000099")
    world.actor = other
    await send(engine, world, "second person")
    assert "first person says this" not in seen(model)
    a = session_keys("org", "u1")
    assert a[0] == "org:u1" and len(a[1]) == 10


async def test_a_question_tool_ends_the_run_and_the_step_limit_holds():
    looping = ScriptedLlm([[("stock_for", {"material": "cement"})]] * (MAX_STEPS + 3))
    engine, world = AdkEngine(looping), await new_world()
    await send(engine, world, "cement?")
    assert len(looping.requests) == MAX_STEPS + 1  # the last round has no tools
    assert looping.requests[-1].config.tools in (None, [])


async def test_a_model_failure_before_any_action_falls_back_to_todays_agent():
    model = ScriptedLlm([], error=RuntimeError("model down"))
    engine, world = AdkEngine(model), await new_world()
    result = await send(engine, world, "50 bag cement vannu")
    assert engine.classic_calls.calls == 1
    assert result.reply is not None


class _Resolver:
    def __init__(self, routing, key="k"):  # noqa: ANN001
        from types import SimpleNamespace

        self._config = {"routing": routing, "secrets": {"gemini": {"api_key": key}}}
        self._settings = SimpleNamespace(gemini=SimpleNamespace(model="gemini-env"))

    async def _resolve_config(self):  # noqa: ANN202
        return self._config


async def test_production_model_uses_the_v2_route_then_the_agent_route_and_needs_a_gemini_key():
    import pytest

    from agent_v2.adk.models import ResolvedGemini

    own = ResolvedGemini(_Resolver({"agent_v2": {"provider_id": "gemini", "model": "gemini-v2"}, "agent": {"model": "gemini-a"}}))
    assert (await own._inner())[1] == "gemini-v2"
    shared = ResolvedGemini(_Resolver({"agent": {"provider_id": "gemini", "model": "gemini-a"}}))
    assert (await shared._inner())[1] == "gemini-a"
    env = ResolvedGemini(_Resolver({}))
    assert (await env._inner())[1] == "gemini-env"
    with pytest.raises(Exception, match="v2 needs Gemini"):
        await ResolvedGemini(_Resolver({}, key=None))._inner()
