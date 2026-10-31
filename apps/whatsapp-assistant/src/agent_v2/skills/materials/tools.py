"""The materials skill's tools (request 174).

Every tool here either READS (``stock_for``, ``catalog_match``), ASKS (``ask``), or adds ONE line to the sender's open draft card
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
#: Request 178: the tools v1 of v2 lacked.
TRANSFER = "transfer"
CHANGE_LINE = "change_line"
REMOVE_LINE = "remove_line"
REQUEST_NOT_BUILT = "material_request_not_available"

#: v2 name -> today's tool name, for the tools that run through the toolbox.
CLASSIC_NAME = {
    DRAFT_RECEIPT: classic.SAVE_MATERIAL_RECEIPT,
    DRAFT_USAGE: classic.SAVE_MATERIAL_USAGE,
    DRAFT_STOCK_COUNT: classic.ADJUST_STOCK,
    STOCK_FOR: classic.QUERY_MATERIALS,
    ASK: classic.ASK_USER,
    TRANSFER: classic.TRANSFER_MATERIAL,
    CHANGE_LINE: classic.UPDATE_PENDING_CARD,
    REMOVE_LINE: classic.REMOVE_CARD_LINE,
}
#: The tools that put a line on the card (or move one on it).
DRAFT_TOOLS = frozenset({DRAFT_RECEIPT, DRAFT_USAGE, DRAFT_STOCK_COUNT, TRANSFER, CHANGE_LINE, REMOVE_LINE})
#: A call to one of these means v2 took the message: it is never handed to today's agent too.
TAKES_THE_MESSAGE = DRAFT_TOOLS | {STOCK_FOR, ASK, REQUEST_NOT_BUILT}
#: Arguments only v2 has: the model's own account of the figures of the message. They are
#: removed before a call reaches the shared toolbox, so a card line never carries them.
ACCOUNT_KEYS = ("figures_placed", "unplaced")

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
    TRANSFER: (
        "Material SENT FROM one site TO ANOTHER site of the company (kondupoyi, matti, shifted, "
        "sent to Site B, bheja). Takes stock off the sending site and adds it to the receiving one. "
        "`to_site` is where it WENT; never guess it. If the message does not name the receiving site, "
        "call `ask` for the DESTINATION (not the sending site). Never a usage line, never a receipt."
    ),
    CHANGE_LINE: (
        "Change ONE line of the open card (not saved yet): 'alla, 35 aanu', '25... alla 35', 'it was "
        "supplier Raju'. `item_index` is the line's number on the card in your context; `changes` holds "
        "ONLY the fields that change. A correction replaces the figure; it never adds a second line."
    ),
    REMOVE_LINE: (
        "Take ONE line off the open card ('cement venda', 'ath kalayu', 'remove the sand'). "
        "`item_index` is the line's number on the card. Nothing is saved either way."
    ),
    REQUEST_NOT_BUILT: (
        "They are ASKING FOR material to be sent or ordered ('cement venam', 'need 20 bags sand', "
        "'send bricks'): a request, not stock. Mesiri cannot take material requests yet. Call this, "
        "once, and nothing else for that part; it tells them so in one fast line."
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


_ACCOUNT = {
    "figures_placed": {
        "type": "array",
        "items": {"type": "number"},
        "description": (
            "Every number from the supervisor's message that THIS call puts on the card (quantity, "
            "rate, count...). Leave out numbers that are not in their message."
        ),
    },
    "unplaced": {
        "type": "array",
        "description": (
            "Numbers from their message that you deliberately do NOT put on the card, each with the "
            "reason: the OLD figure a correction replaces ('25' in '25... alla 35'), a number that is "
            "what the app shows ('176 = the stock the app shows'), a date, a phone number. Never use "
            "this to drop a quantity they want recorded: ask instead."
        ),
        "items": {
            "type": "object",
            "properties": {"figure": {"type": "number"}, "reason": {"type": "string"}},
            "required": ["figure", "reason"],
        },
    },
}


def _with_account(parameters: dict[str, Any]) -> dict[str, Any]:
    props = {**(parameters.get("properties") or {}), **_ACCOUNT}
    return {**parameters, "properties": props}


def _tool(name: str) -> ToolSpec:
    by_name = {spec.name: spec for spec in classic.tool_specs()}
    source = by_name[CLASSIC_NAME[name]]
    parameters = source.parameters
    if name == CHANGE_LINE:
        props = dict(parameters["properties"])
        props["card_id"] = {
            "type": "string",
            "description": (
                "Leave out for the OPEN card. Only the id of their latest SAVED card, when the context "
                "gives one and they correct something already saved (a Change card is then shown)."
            ),
        }
        props["item_index"] = {
            "type": "integer",
            "description": "The line's number on that card, from 1 (the card is in your context).",
        }
        parameters = {**parameters, "properties": props, "required": ["item_index", "changes"]}
    return ToolSpec(name=name, description=_DESCRIPTIONS[name], parameters=_with_account(parameters))


def specs() -> list[ToolSpec]:
    """The tools the materials skill offers the model."""
    return [
        *(
            _tool(name)
            for name in (DRAFT_RECEIPT, DRAFT_USAGE, DRAFT_STOCK_COUNT, TRANSFER, CHANGE_LINE, STOCK_FOR, ASK)
        ),
        ToolSpec(
            name=REMOVE_LINE,
            description=_DESCRIPTIONS[REMOVE_LINE],
            parameters=_with_account(
                {
                    "type": "object",
                    "properties": {
                        "item_index": {
                            "type": "integer",
                            "description": "The line's number on the open card, from 1.",
                        }
                    },
                    "required": ["item_index"],
                }
            ),
        ),
        ToolSpec(
            name=REQUEST_NOT_BUILT,
            description=_DESCRIPTIONS[REQUEST_NOT_BUILT],
            parameters={"type": "object", "properties": {}},
        ),
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
    ]


def split_account(args: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """``args`` without the v2-only account keys, and the account itself."""
    clean = {k: v for k, v in args.items() if k not in ACCOUNT_KEYS}
    return clean, {k: args[k] for k in ACCOUNT_KEYS if k in args}


_DIGITS = re.compile(r"\d+(?:[.,]\d+)?")


#: A number that is part of WHAT a thing is, not how much of it: "1.5 sq mm wire", "12 mm TMT",
#: "M20 concrete", "4 inch pipe", "20 amp". Never a quantity, so never asked about (request 178:
#: "2 box 1.5 sq mm wire" got "I did not put 1.5 on the card").
_SPEC = re.compile(
    r"\b\d+(?:[.,]\d+)?\s*(?:sq\.?\s*mm|sqmm|mm|cm|inch(?:es)?|in|ft|feet|mtr|metre|meter|amps?|a|w|kw|hp|v|mpa|core)\b"
    r"|\b[mM]\s?\d{2}\b|\b\d+\s*(?:\"|'')",
    re.IGNORECASE,
)


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


def explained_figures(calls: list[tuple[str, dict[str, Any]]]) -> set[str]:
    """Figures the model itself accounted for: the ones its calls say they place and the ones
    it says it left off WITH a reason ("176 = what the app shows"). A figure with no reason is
    not explained."""
    out: set[str] = set()
    for _name, args in calls:
        for raw in args.get("figures_placed") or []:
            out |= figures(str(raw))
        for row in args.get("unplaced") or []:
            if isinstance(row, dict) and len(str(row.get("reason") or "").strip()) >= 3:
                out |= figures(str(row.get("figure")))
    return out


def unplaced_figures(user_text: str, calls: list[tuple[str, dict[str, Any]]], asked: str = "") -> list[str]:
    """Figures of the message that no call placed or carried, that no question carries and that
    the model did not explain: the only ones the code asks about. The model's own account
    (``figures_placed`` / ``unplaced`` with a reason) replaces the old guess that every digit not
    found in a call's arguments was dropped (request 178: "25... alla 35" is a replaced figure,
    "176" is what the app shows)."""
    carried: set[str] = set()
    for _name, args in calls:
        clean, _account = split_account(args)
        carried |= figures(_flatten(clean))
    carried |= figures(asked)
    carried |= explained_figures(calls)
    return sorted(figures(_SPEC.sub(" ", user_text or "")) - carried, key=lambda f: (len(f), f))


def _flatten(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(_flatten(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return " ".join(_flatten(v) for v in value)
    return "" if value is None else str(value)
