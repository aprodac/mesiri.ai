"""Tools on demand (WA-277 step E; approved by Ilan, 11 Nov 2026).

Every model call used to carry all 131 tool definitions: about 22,000 tokens, more than half the call, paid on
every message, when 38 tools were ever called in production and about 20 carried nearly all of it.

With ``tools_on_demand`` on for a company, a call carries the **core** tools (everything the daily site talk
uses: every tool production called in the ten days to 11 Nov stays core) and one small tool, ``open_tools``, that
lists the other **areas** with one line each. The model opens an area with one call and its tools are then in the
tool list for the rest of the turn (and for the rest of the day in that chat).

A tool is core unless it is named in an area below, so a route added to ``ALLOWED`` is offered at once and only
moves out of the core when someone puts it in an area. ``tests/agent_api/test_api_tools_on_demand_277e.py`` holds
the rules: every named tool exists, no tool is in two areas, and the tools production used are all core.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from mesiri_ai.models import ToolSpec

OPEN = "open_tools"
#: The areas a turn may open at most (each one is another model call).
OPENS_PER_TURN = 2


@dataclass(frozen=True)
class Area:
    #: What the model reads to decide: the things a person says that need this area, in plain words.
    line: str
    tools: tuple[str, ...]


AREAS: dict[str, Area] = {
    "orders": Area(
        "an order or a material request after it is made: approve or refuse a request, cancel a request, change, "
        "cancel or close an order, say which order a delivery belongs to",
        ("delivery_order", "decide_material_request", "cancel_material_request", "change_order", "cancel_order",
         "close_order")),
    "quotes": Area(
        "quotes from suppliers (RFQ): ask suppliers for a price, record a quote, compare, choose the supplier",
        ("rfqs", "rfq", "ask_for_quotes", "record_quote", "decline_quote", "award_quotes")),
    "stock_control": Area(
        "minimum stock and what is below it, a physical stock count, material sent back to a supplier",
        ("below_minimum", "minimum_stock", "suggest_minimum_stock", "set_minimum_stock", "returns",
         "return_to_supplier", "settle_return", "stock_counts", "start_stock_count", "count_stock")),
    "wages": Area(
        "labour money: an advance to a worker or a team, the wage sheet, approving and paying wages, labour teams",
        ("labour_teams", "labour_advance_balances", "give_labour_advance", "wage_sheet", "approve_wage_sheet",
         "pay_wages")),
    "machines": Area(
        "machines and equipment: JCB, mixer, crane hours and fuel, a machine added, moved or sent back, hire cost",
        ("machines", "machine_logs", "log_machines", "add_machine", "move_machine", "off_hire_machine",
         "hire_check")),
    "take_back": Area(
        "undo something saved on an earlier day (a delivery, usage, transfer or expense taken back), correct a "
        "saved work entry, acknowledge an issue or mark it won't-fix",
        ("work_item", "correct_work", "acknowledge_issue", "wont_fix_issue", "undo_receipt", "undo_usage",
         "undo_transfer", "undo_expense")),
    "payments": Area(
        "money paid or owed: pay a bill or a supplier, an advance to a supplier, what we owe and to whom, money "
        "received from the client, client bills, bank and cash accounts, vendors, expense categories, a bill photo "
        "for a saved expense",
        ("expense_categories", "money_accounts", "list_vendors", "add_bill_photo", "expense_payments", "pay_expense",
         "supplier_payables", "supplier_account", "pay_supplier", "link_bill_deliveries", "add_expense_category",
         "ra_bills", "receivables", "record_client_receipt")),
    "plan_and_cost": Area(
        "the plan and the budget: the schedule and its dates, the material plan, cost against budget, materials "
        "and labour against the BOQ, progress floor by floor, finding a drawing or a document, what a drawing says",
        ("schedule", "update_schedule_activity", "material_plan", "cost_today", "budget_vs_actual",
         "materials_vs_boq", "labour_not_on_boq", "put_labour_on_boq", "place_progress", "find_documents",
         "drawing_facts")),
    "subcontractors": Area(
        "subcontractors: a work order, measured work, a subcontractor's bill (record, approve, reject), an advance "
        "to one, their statement",
        ("list_work_orders", "work_order", "create_work_order", "measure_work", "record_subcontract_bill",
         "subcontract_bills_waiting", "approve_subcontract_bill", "reject_subcontract_bill",
         "give_subcontract_advance", "subcontractor_statement")),
    "setup": Area(
        "setting things up: add or change a site, change a material or its category, another name for a material, "
        "add a new person by phone number, sizes other people are waiting for, weather and site conditions of a day",
        ("update_material", "material_categories", "add_standard_categories", "size_requests", "add_site",
         "update_site", "add_material_alias", "add_person", "set_site_conditions")),
    "reports_out": Area(
        "reports beyond one project's week or month: all projects together (the owner's brief), send a report to "
        "other people, set a report to go by itself, what is waiting for this person's approval",
        ("portfolio_report", "send_report_to", "schedule_report", "waiting")),
}

#: The numbered rules of ``SOP.md`` that are only about one area. With tools on demand they leave the prompt with
#: the area's tools (one line stays in their place, so the numbering and "rule 16" still mean something) and come
#: back, word for word, when the area is opened. A rule that also guides a core tool stays (2, 6, 14, 17, 23).
AREA_RULES: dict[str, tuple[int, ...]] = {
    "machines": (13,),
    "plan_and_cost": (15, 16, 18, 19, 20),
    "payments": (21,),
    "wages": (22,),
    "stock_control": (24, 25, 26),
}
_RULE_START = re.compile(r"(?m)^(\d+)\. ")


def rule_blocks(sop: str) -> dict[int, tuple[int, int]]:
    """Each numbered rule of the SOP: its number -> (start, end) in the text. A rule runs to the next rule."""
    starts = [(int(m.group(1)), m.start()) for m in _RULE_START.finditer(sop)]
    return {number: (start, starts[i + 1][1] if i + 1 < len(starts) else len(sop))
            for i, (number, start) in enumerate(starts)}


def sop_for(sop: str, opened: Iterable[str]) -> str:
    """The SOP a call carries with tools on demand: the rules of the areas still closed are one line each."""
    open_now = set(opened)
    blocks = rule_blocks(sop)
    cuts = sorted(((blocks[n], n, area) for area, numbers in AREA_RULES.items() if area not in open_now
                   for n in numbers if n in blocks), reverse=True)
    for (start, end), number, area in cuts:
        sop = (sop[:start] + f"{number}. (This is in the {area} tools: open them with `{OPEN}` first; the rule "
               "comes with them.)\n" + sop[end:])
    return sop


def area_rules(sop: str, area: str) -> str:
    """The SOP rules that belong to ``area``, word for word."""
    blocks = rule_blocks(sop)
    return "".join(sop[blocks[n][0]:blocks[n][1]] for n in AREA_RULES.get(area, ()) if n in blocks).strip()


_AREA_OF: dict[str, str] = {tool: area for area, spec in AREAS.items() for tool in spec.tools}


def area_of(tool: str) -> str | None:
    """The area ``tool`` is in, None when it is core."""
    return _AREA_OF.get(tool)


def default_on() -> bool:
    """Where no company setting is read (the saved conversations on the real model, the terminal chat): the
    environment decides, off unless ``MESIRI_TOOLS_ON_DEMAND`` says so."""
    return os.environ.get("MESIRI_TOOLS_ON_DEMAND", "").strip().lower() in ("1", "true", "on", "yes")


def offered(tools: dict[str, Any], opened: Iterable[str]) -> list[str]:
    """The tool names a call carries: the core, and the tools of the opened areas (in ``tools``' own order)."""
    open_now = set(opened)
    return [name for name in tools if (area := _AREA_OF.get(name)) is None or area in open_now]


def closed_areas(tools: dict[str, Any], opened: Iterable[str]) -> list[str]:
    """The areas still closed that hold at least one tool this agent has."""
    open_now = set(opened)
    return [name for name, spec in AREAS.items() if name not in open_now and any(t in tools for t in spec.tools)]


def open_spec(tools: dict[str, Any], opened: Iterable[str]) -> ToolSpec | None:
    """``open_tools`` for the areas still closed; None when nothing is left to open."""
    closed = closed_areas(tools, opened)
    if not closed:
        return None
    listed = "\n".join(f"- {name}: {AREAS[name].line}" for name in closed)
    return ToolSpec(name=OPEN, description=(
        "You have MORE tools than the ones listed: they are kept in areas and opened when a message needs them. "
        "When my message is about one of these, call this FIRST with that area, before answering and before saying "
        "something cannot be done; its tools are then yours and you do what I asked with them. It writes nothing "
        "and I never see it. Areas:\n" + listed),
        parameters={"type": "object", "required": ["area"],
                    "properties": {"area": {"type": "string", "enum": closed,
                                            "description": "The one area my message needs."}}})


def opened_note(area: str, tools: dict[str, Any], prepared: list[str], sop: str = "") -> str:
    """What the model is told when the turn goes on with an area's tools (and the area's rules of ``sop``)."""
    names = ", ".join(t for t in AREAS[area].tools if t in tools)
    note = (f"\n\nYou opened the {area} tools for this message: {names}. They are in your tools now. Do what my "
            "message asks with them now. This note is for you only: never mention it, an area or a tool.")
    if prepared:
        note += (" Already prepared in this turn, waiting for Save (never prepare these again): "
                 + "; ".join(prepared) + ".")
    if rules := area_rules(sop, area):
        note += f"\n\nThe rules for the {area} tools:\n{rules}"
    return note
