"""WA-277 step E: tools on demand (approved by Ilan, 11 Nov 2026).

Every model call carried all 131 tool definitions (about 22,000 tokens, more than half the call) when production
had called 38 of them in ten days. With the company's ``tools_on_demand`` on, a call carries the core tools and
``open_tools``, which lists the other areas; the model opens one and the turn goes on with that area's tools.

What is held here:
- the map: every tool named in an area exists, none is in two areas, and every tool production called up to
  11 Nov is core (the promise the plan made);
- the size: the on-demand tool list is under half of the full one;
- the flow: an area's tool is not offered until its area is opened; opening it goes on in the same turn, with what
  was already prepared named so it is not prepared twice; the opened area is returned so the chat keeps it;
- a waiting entry of an area keeps that area open (its correction needs the tool's fields);
- "can't" with an area still closed is told where the other tools are;
- the guard: with the setting off nothing changes, every tool is offered and there is no ``open_tools``.
"""

from __future__ import annotations

import json
import time

from tests.agent_api.test_api_new_material_210b import ACTOR, LITRE, PAINT, Store, _receipt

from agent_api import tool_areas
from agent_api import whatsapp as wa
from agent_api.agent import ApiAgent, PendingWrite
from agent_api.app import build_api_app
from agent_api.client import ApiClient
from agent_api.tools import ALLOWED, build_tools
from mesiri.domains.organizations import settings
from mesiri_ai.fakes import FakeToolCallingProvider

#: The tools production called from 2 to 11 Nov 2026 (journey_traces, stage agent_api_turn). They stay core.
USED_IN_PRODUCTION = (
    "record_receipt", "record_usage", "record_attendance", "add_material", "create_project", "set_unit_conversion",
    "list_projects", "stock_check", "purchase_orders", "ask_for_material", "record_work", "report_issue",
    "search_materials", "add_project_member", "day_summary", "stock_levels", "set_reply_language", "list_issues",
    "stock_summary", "record_expense", "site_day", "my_requests", "labour_attendance", "update_project",
    "list_receipts", "change_material_request", "place_order", "resolve_issue", "send_dpr",
    "answer_size_request", "period_report", "list_sites", "list_units", "material_requests",
)
NAMES = {a.name for a in ALLOWED}


class Recording(FakeToolCallingProvider):
    """The scripted model, keeping the tool names and system prompt of every run."""

    def __init__(self, script: list) -> None:
        super().__init__(script)
        self.offered: list[set[str]] = []
        self.prompts: list[str] = []

    async def run_tools(self, system_prompt, messages, tools, handler, **kwargs):  # noqa: ANN001, ANN003, ANN201
        self.offered.append({t.name for t in tools})
        self.prompts.append(system_prompt)
        return await super().run_tools(system_prompt, messages, tools, handler, **kwargs)


class Runs:
    """One scripted run per model run: the fake keeps one script, a turn that opens an area runs twice."""

    def __init__(self, *scripts: list) -> None:
        self._scripts = list(scripts)
        self.offered: list[set[str]] = []
        self.prompts: list[str] = []

    async def run_tools(self, system_prompt, messages, tools, handler, **kwargs):  # noqa: ANN001, ANN003, ANN201
        self.offered.append({t.name for t in tools})
        self.prompts.append(system_prompt)
        kwargs.pop("capability", None)
        return await FakeToolCallingProvider(self._scripts.pop(0)).run_tools(
            system_prompt, messages, tools, handler, **kwargs)


def _tools() -> dict:
    return build_tools(build_api_app(None).openapi())


TOOLS = _tools()


async def _run(provider, text: str, **kwargs):  # noqa: ANN001, ANN003, ANN202
    client = ApiClient(ACTOR, app=Store().api())
    try:
        return await ApiAgent(provider, TOOLS).run(client, text, **kwargs)
    finally:
        await client.close()


# --- the map ---------------------------------------------------------------------------------------------------------

def test_every_area_tool_exists_and_is_in_one_area() -> None:
    seen: dict[str, str] = {}
    for area, spec in tool_areas.AREAS.items():
        assert spec.line.strip() and spec.tools, area
        for tool in spec.tools:
            assert tool in NAMES, f"{tool} ({area}) is not on ALLOWED"
            assert tool not in seen, f"{tool} is in {seen.get(tool)} and {area}"
            seen[tool] = area


def test_what_production_used_stays_core() -> None:
    for tool in USED_IN_PRODUCTION:
        assert tool in NAMES, tool
        assert tool_areas.area_of(tool) is None, f"{tool} was called in production and must stay core"


def test_a_tool_in_no_area_is_core() -> None:
    assert tool_areas.offered({"record_receipt": 1, "brand_new_route": 1, "pay_supplier": 1}, []) == [
        "record_receipt", "brand_new_route"]


def test_the_on_demand_list_is_under_half_the_full_one() -> None:
    def size(specs: list) -> int:
        return sum(len(json.dumps({"n": s.name, "d": s.description, "p": s.parameters})) for s in specs)

    full = size([t.spec for t in TOOLS.values()])
    core = size([TOOLS[n].spec for n in tool_areas.offered(TOOLS, [])] + [tool_areas.open_spec(TOOLS, [])])
    assert core < full * 0.5, (core, full)
    # the biggest area opened on top is still well under the full list
    biggest = max(tool_areas.AREAS, key=lambda a: size([TOOLS[n].spec for n in tool_areas.AREAS[a].tools]))
    with_one = size([TOOLS[n].spec for n in tool_areas.offered(TOOLS, [biggest])])
    assert with_one < full * 0.7, (biggest, with_one, full)


def test_open_tools_lists_only_closed_areas_and_goes_when_all_are_open() -> None:
    spec = tool_areas.open_spec(TOOLS, ["payments"])
    assert spec is not None
    assert "payments" not in spec.parameters["properties"]["area"]["enum"]
    assert "wages" in spec.parameters["properties"]["area"]["enum"]
    assert tool_areas.open_spec(TOOLS, list(tool_areas.AREAS)) is None


# --- the rules that travel with an area ------------------------------------------------------------------------------

def test_each_area_rule_is_about_that_area() -> None:
    """A renumbered SOP must not send the wrong rule away: every rule listed for an area names one of its tools."""
    from agent_api.agent import SOP

    blocks = tool_areas.rule_blocks(SOP)
    for area, numbers in tool_areas.AREA_RULES.items():
        for number in numbers:
            assert number in blocks, f"SOP rule {number} ({area}) is gone"
            start, end = blocks[number]
            assert any(f"`{t}`" in SOP[start:end] for t in tool_areas.AREAS[area].tools), (area, number)


def test_closed_rules_are_one_line_and_come_back_whole() -> None:
    from agent_api.agent import SOP

    closed = tool_areas.sop_for(SOP, [])
    assert len(closed) < len(SOP) - 10_000
    assert "22. Wages and advances" not in closed and "22. (This is in the wages tools" in closed
    assert "rule 22" in closed  # the cross-reference in rule 2 still points at something
    assert "`record_receipt`" in closed or "record_receipt" in closed
    assert "22. Wages and advances" in tool_areas.sop_for(SOP, ["wages"])
    assert tool_areas.sop_for(SOP, list(tool_areas.AREAS)) == SOP
    assert tool_areas.area_rules(SOP, "wages").startswith("22. ")
    assert tool_areas.area_rules(SOP, "quotes") == ""


async def test_the_areas_rules_come_with_the_opened_tools() -> None:
    model = Runs([[(tool_areas.OPEN, {"area": "wages"})]], ["Sheri."])
    await _run(model, "Ravi-kku 500 advance koduthu", on_demand=True)
    assert "22. Wages and advances" not in model.prompts[0]
    assert "The rules for the wages tools" in model.prompts[1] and "22. Wages and advances" in model.prompts[1]


async def test_off_keeps_the_whole_sop() -> None:
    from agent_api.agent import SOP

    model = Recording(["Sheri."])
    await _run(model, "hi", on_demand=False)
    assert model.prompts[0].startswith(SOP)


# --- the flow --------------------------------------------------------------------------------------------------------

async def test_off_offers_every_tool_and_no_door() -> None:
    model = Recording(["Sheri."])
    turn = await _run(model, "hi", on_demand=False)
    assert NAMES <= model.offered[0]
    assert tool_areas.OPEN not in model.offered[0]
    assert turn.opened == []


async def test_on_offers_the_core_and_the_door_only() -> None:
    model = Recording(["Sheri."])
    await _run(model, "hi", on_demand=True)
    first = model.offered[0]
    assert tool_areas.OPEN in first
    assert "record_receipt" in first and "record_attendance" in first and "period_report" in first
    assert "pay_supplier" not in first and "give_labour_advance" not in first and "log_machines" not in first


async def test_opening_an_area_goes_on_in_the_same_turn_with_its_tools() -> None:
    model = Runs([[(tool_areas.OPEN, {"area": "payments"})]],
                 [[("supplier_payables", {})], "Malabar-inu 50,000 kodukkaanundu."])
    turn = await _run(model, "Malabar-inu ethra kodukkaanundu?", on_demand=True)
    assert len(model.offered) == 2
    assert "supplier_payables" not in model.offered[0]
    assert "supplier_payables" in model.offered[1] and "pay_supplier" in model.offered[1]
    assert "wages" in model.offered[1] or tool_areas.OPEN in model.offered[1]  # other areas can still be opened
    assert "You opened the payments tools" in model.prompts[1]
    assert turn.opened == ["payments"]
    assert [c["tool"] for c in turn.calls][:2] == [tool_areas.OPEN, "supplier_payables"]
    assert "50,000" in turn.reply


async def test_what_was_prepared_before_opening_is_held_once_and_named() -> None:
    receipt = _receipt(PAINT, "paint", LITRE, 30, "30 litre Paint")
    model = Runs([[receipt, (tool_areas.OPEN, {"area": "payments"})]],
                 [[("supplier_payables", {})], "30 litre Paint ready. Malabar-inu 50,000 kodukkaanundu."])
    turn = await _run(model, "30 litre paint vannu. Malabar-inu ethra kodukkaanundu?", on_demand=True)
    assert [e.tool for e in turn.pending] == ["record_receipt"]
    assert "never prepare these again" in model.prompts[1] and "30 litre Paint" in model.prompts[1]


async def test_an_unknown_area_is_refused_with_the_real_ones() -> None:
    model = Recording([[(tool_areas.OPEN, {"area": "money"})], "Sheri."])
    turn = await _run(model, "hi", on_demand=True)
    assert len(model.offered) == 1  # no second run for a refused open
    assert "payments" in str(turn.calls[0]["result"])
    assert turn.opened == []


async def test_an_area_the_chat_opened_earlier_is_open_from_the_start() -> None:
    model = Recording(["Sheri."])
    turn = await _run(model, "hi", on_demand=True, open_areas=["wages", "not_an_area"])
    assert "give_labour_advance" in model.offered[0] and "pay_supplier" not in model.offered[0]
    assert turn.opened == ["wages"]


async def test_a_waiting_entry_keeps_its_area_open() -> None:
    waiting = PendingWrite(tool="pay_supplier", method="POST", path="/finance/vendors/x/payments", params={}, body={},
                           summary="₹50,000 to Malabar", idempotency_key="k1")
    model = Recording(["Sheri."])
    await _run(model, "alla, 40,000 aanu", on_demand=True, ready=[waiting])
    assert "pay_supplier" in model.offered[0]


async def test_cannot_with_an_area_closed_is_told_where_the_other_tools_are() -> None:
    model = Runs(["Athu Mesiri-kku pattilla."],
                 [[(tool_areas.OPEN, {"area": "machines"})]],
                 [[("machines", {})], "JCB site-il undu."])
    turn = await _run(model, "JCB evide?", on_demand=True)
    assert turn.opened == ["machines"]
    assert "JCB" in turn.reply


async def test_opening_is_not_counted_as_looking_something_up() -> None:
    """The reply checks ("you called no tool", "nothing was looked at") must see a turn that only opened an area
    as a turn that called nothing: the door is kept for the trace, not for them."""
    model = Runs([[(tool_areas.OPEN, {"area": "wages"})]], ["Sheri, parayoo."])
    turn = await _run(model, "wages", on_demand=True)
    assert [c["tool"] for c in turn.calls] == [tool_areas.OPEN]
    assert turn.reply


# --- the setting and the chat ---------------------------------------------------------------------------------------

def test_the_setting_is_off_by_default_and_takes_on_or_off() -> None:
    assert settings.TOOLS_ON_DEMAND_DEFAULT == "off"
    assert settings.validate(settings.TOOLS_ON_DEMAND, "ON") == "on"
    try:
        settings.validate(settings.TOOLS_ON_DEMAND, "maybe")
    except ValueError:
        pass
    else:
        raise AssertionError("an unknown mode must be refused")


def test_the_chat_keeps_opened_areas_for_half_a_day() -> None:
    now = time.time()
    assert wa._open_areas({"areas": {"names": ["wages"], "at": now - 60}}, now) == ["wages"]
    assert wa._open_areas({"areas": {"names": ["wages"], "at": now - wa.AREAS_OPEN_SECONDS - 1}}, now) == []
    assert wa._open_areas({}, now) == []


def test_default_follows_the_environment(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.delenv("MESIRI_TOOLS_ON_DEMAND", raising=False)
    assert tool_areas.default_on() is False
    monkeypatch.setenv("MESIRI_TOOLS_ON_DEMAND", "1")
    assert tool_areas.default_on() is True


def test_the_door_says_what_is_already_in_the_tools() -> None:
    """Round 4 (11 Nov, real model): "Give daily reports" opened reports_out and answered with a link instead of
    the daily report. The door now says what never needs an area, and reports_out says what it is not."""
    spec = tool_areas.open_spec(TOOLS, [])
    assert spec is not None
    assert "Never open an area for what the tools you already have do" in spec.description
    assert "daily report" in spec.description
    assert "NOT the daily report" in tool_areas.AREAS["reports_out"].line
    for core in ("send_dpr", "day_summary", "period_report", "site_day"):
        assert tool_areas.area_of(core) is None
