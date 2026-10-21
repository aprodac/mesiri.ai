"""WA-36: the agent reads a material message against the sender's site stock."""

from __future__ import annotations

import asyncio
import datetime as dt
from types import SimpleNamespace
from unittest.mock import AsyncMock

from runtime.agent.prompt import AgentContext, render_context
from runtime.today_context import build_stock_line, render_stock_line

SITE = SimpleNamespace(id="site-1", name="Green Villa", project_id="proj-1")


def _actor(*sites):
    return SimpleNamespace(organization_id="org-1", full_name="Anil K", sites=list(sites))


def _level(name, stock, unit):
    return {"material_name": name, "unit": unit, "received": stock, "used": 0.0, "current_stock": stock}


def test_the_line_lists_the_largest_stock_first_with_units():
    line = render_stock_line("Green Villa", [_level("Sand", 2.0, "load"), _level("Cement", 140.0, "bag")])
    assert line == "Stock now at Green Villa (from the records): Cement 140 bag, Sand 2 load."


def test_a_long_list_is_cut_and_says_how_many_more():
    levels = [_level(f"M{i}", float(i), "nos") for i in range(1, 10)]
    line = render_stock_line(None, levels)
    assert line.startswith("Stock now (from the records): M9 9 nos, M8 8 nos")
    assert line.endswith("(+3 more).")


def test_no_stock_means_no_line():
    assert render_stock_line("Green Villa", []) is None
    assert render_stock_line("Green Villa", None) is None


async def test_the_line_is_the_senders_one_site():
    query = AsyncMock(return_value=[_level("Cement", 140.0, "bag")])
    line = await build_stock_line(SimpleNamespace(query=query), _actor(SITE))
    assert line == "Stock now at Green Villa (from the records): Cement 140 bag."
    assert query.await_args.kwargs == {
        "organization_id": "org-1",
        "project_id": "proj-1",
        "site_id": "site-1",
        "material_name": None,
    }


async def test_several_sites_or_none_means_no_line():
    query = AsyncMock(return_value=[_level("Cement", 140.0, "bag")])
    service = SimpleNamespace(query=query)
    assert await build_stock_line(service, _actor()) is None
    assert await build_stock_line(service, _actor(SITE, SITE)) is None
    query.assert_not_awaited()


async def test_a_slow_failing_or_missing_lookup_is_left_out():
    async def slow(**_kw):
        await asyncio.sleep(1)
        return []

    assert await build_stock_line(SimpleNamespace(query=slow), _actor(SITE), timeout=0.01) is None
    boom = SimpleNamespace(query=AsyncMock(side_effect=RuntimeError("db")))
    assert await build_stock_line(boom, _actor(SITE)) is None
    assert await build_stock_line(None, _actor(SITE)) is None


def test_the_model_sees_the_stock_line():
    ctx = AgentContext(
        user_name="Anil",
        role="S",
        company="Acme",
        now=dt.datetime(2026, 10, 21, 9),
        stock_line="Stock now at Green Villa (from the records): Cement 140 bag.",
    )
    assert "Cement 140 bag" in render_context(ctx)


async def test_the_turn_gives_the_model_both_lines_and_survives_a_failing_one():
    from tests.unit.test_agent_routing import _message

    from runtime.agent.turn import AgentTurnDeps, run_agent_turn

    seen = {}

    class _Runner:
        async def run(self, *, ctx, **_kw):
            seen["ctx"] = ctx
            from runtime.agent.runner import AgentResult

            box = SimpleNamespace(saved=[], attempted_writes=0, parked=None, answers=["x"], notes=[])
            from channel.replies import ReplySpec

            return AgentResult("ok", ReplySpec(text="ok"), box)

    deps = AgentTurnDeps(
        runner=_Runner(),
        make_gateway=lambda message, language: SimpleNamespace(handled=[], finish=AsyncMock()),
        send_spec=AsyncMock(),
        transcribe=None,
        message_logger=AsyncMock(),
        today_line=AsyncMock(side_effect=RuntimeError("down")),
        stock_line=AsyncMock(return_value="Stock now (from the records): Cement 140 bag."),
    )
    actor = SimpleNamespace(
        organization_id="org-1", user_id="u1", full_name="Anil", role="SUPERVISOR",
        org_name="Acme", projects=[], sites=[],
    )
    await run_agent_turn(_message("how much cement left"), actor, deps)
    assert seen["ctx"].today_line is None
    assert seen["ctx"].stock_line == "Stock now (from the records): Cement 140 bag."
