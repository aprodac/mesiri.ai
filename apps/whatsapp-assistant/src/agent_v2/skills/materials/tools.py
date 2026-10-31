"""The materials skill's tools (request 174).

Every tool here either READS (``stock_for``, ``catalog_match``), ASKS (``ask``), hands the
message back (``hand_back``), or adds ONE line to the sender's open draft card
(``draft_receipt`` / ``draft_usage`` / ``draft_stock_count``). Nothing writes a record: the
card's Save tap is the only door (runtime/agent/draft_flow.py), and the draft tools run through
the SAME toolbox as today's agent, so the site resolver, unit gate, repeat check and card
are the ones that already exist. The specs are today's specs under the v2 names (one place
owns each tool's arguments).
"""

from __future__ import annotations

import re
from typing import Any

from mesiri_ai.models import ToolSpec
from runtime.agent import tools as classic

DRAFT_RECEIPT = "draft_receipt"
DRAFT_USAGE = "draft_usage"
DRAFT_STOCK_COUNT = "draft_stock_count"
STOCK_FOR = "stock_for"
CATALOG_MATCH = "catalog_match"
ASK = "ask"
HAND_BACK = "hand_back"

#: v2 name -> today's tool name, for the tools that run through the toolbox.
CLASSIC_NAME = {
    DRAFT_RECEIPT: classic.SAVE_MATERIAL_RECEIPT,
    DRAFT_USAGE: classic.SAVE_MATERIAL_USAGE,
    DRAFT_STOCK_COUNT: classic.ADJUST_STOCK,
    STOCK_FOR: classic.QUERY_MATERIALS,
    ASK: classic.ASK_USER,
}
#: The tools that put a line on the card.
DRAFT_TOOLS = frozenset({DRAFT_RECEIPT, DRAFT_USAGE, DRAFT_STOCK_COUNT})
#: A call to one of these means v2 took the message: it is never handed to today's agent too.
TAKES_THE_MESSAGE = DRAFT_TOOLS | {STOCK_FOR, ASK}

_DESCRIPTIONS = {
    DRAFT_RECEIPT: (
        "Put material that ARRIVED on site on the card (came, arrived, vannu, eththi, aaya, "
        "delivered, received). One call per material line. Nothing is saved until they tap Save."
    ),
    DRAFT_USAGE: (
        "Put material that was USED for work on the card (used, use cheythu, for the slab). "
        "Not for a count or 'finished' (draft_stock_count) and not for a delivery. One call per line."
    ),
    DRAFT_STOCK_COUNT: (
        "Put a physical STOCK COUNT on the card: what is on site now ('cement theernnu' = counted 0, "
        "'5 bag ബാക്കി' = counted 5, 'stock count cement 20'). Omit counted when no figure was said."
    ),
    STOCK_FOR: (
        "Answer a question about stock, or about what was received or used on a day or period. "
        "Reads the records; saves nothing."
    ),
    ASK: (
        "Ask ONE short question when the direction (received or used), the material or a figure "
        "is unclear. Ends your turn."
    ),
}


def _tool(name: str) -> ToolSpec:
    by_name = {spec.name: spec for spec in classic.tool_specs()}
    source = by_name[CLASSIC_NAME[name]]
    return ToolSpec(name=name, description=_DESCRIPTIONS[name], parameters=source.parameters)


def specs() -> list[ToolSpec]:
    """The tools the materials skill offers the model."""
    return [
        *(_tool(name) for name in (DRAFT_RECEIPT, DRAFT_USAGE, DRAFT_STOCK_COUNT, STOCK_FOR, ASK)),
        ToolSpec(
            name=CATALOG_MATCH,
            description=(
                "Look a word up in this company's material catalog and its aliases (what the site "
                "calls a material). Returns the matching catalog materials: none, one, or several."
            ),
            parameters={
                "type": "object",
                "properties": {"word": {"type": "string", "description": "The material word as said."}},
                "required": ["word"],
            },
        ),
        ToolSpec(
            name=HAND_BACK,
            description=(
                "The message is not (only) about materials: labour, work done, an issue, money, a "
                "question for the engineer, chat, or materials mixed with any of those. Hands the WHOLE "
                "message to the general assistant. Call it before any draft tool, never after one."
            ),
            parameters={
                "type": "object",
                "properties": {"reason": {"type": "string"}},
            },
        ),
    ]


_DIGITS = re.compile(r"\d+(?:[.,]\d+)?")


def figures(text: str) -> set[str]:
    """The numbers in a message, as plain strings ("1,500" -> "1500", "2.50" -> "2.5")."""
    found: set[str] = set()
    for raw in _DIGITS.findall(text or ""):
        cleaned = raw.replace(",", "")
        try:
            value = float(cleaned)
        except ValueError:
            continue
        found.add(str(int(value)) if value == int(value) else str(value))
    return found


def unplaced_figures(user_text: str, calls: list[tuple[str, dict[str, Any]]], asked: str = "") -> list[str]:
    """Figures in the message that no tool call and no question carries: the rule "every
    number in the message must end up on the card or be asked about", checked in code."""
    carried: set[str] = set()
    for _name, args in calls:
        carried |= figures(_flatten(args))
    carried |= figures(asked)
    return sorted(figures(user_text) - carried, key=lambda f: (len(f), f))


def _flatten(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(_flatten(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return " ".join(_flatten(v) for v in value)
    return "" if value is None else str(value)
