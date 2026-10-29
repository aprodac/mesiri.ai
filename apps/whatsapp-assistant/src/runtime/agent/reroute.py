"""When the code knows the right call better than the model's (live 29 Oct).

The model reads the message and picks a tool; some picks the code can tell are
wrong from the words themselves ("cement vannu" filed as a usage, "50 bag cement
order cheyyanam" filed as a site issue, "10 helper-um vannu" sent as a correction
of a line that is not there). Each such case used to be its own block in the
toolbox that *told* the model what to call instead, and the model did not always
act on it: after phase 4 it makes its calls in one step, and a second step can
be an apology instead of the call (the "10 helpers" screenshots).

Here every such case is one ``Rule`` in ``RULES``, and the toolbox asks one
function at two moments: ``before`` running a call and ``after`` its step came
back. A rule either names the call to make (the code makes it, in the same turn)
or, when the words do not hold what the call needs, gives the instruction the
model gets instead. A new case is a new entry in ``RULES``, nothing else.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .material_direction import RAN_OUT, asks_direction, is_material_order, says_received
from .tools import (
    ASK_USER,
    REPORT_ISSUE,
    REQUEST_MATERIAL,
    SAVE_LABOUR,
    SAVE_MATERIAL_RECEIPT,
    SAVE_MATERIAL_USAGE,
    SAVE_WORK_DONE,
    UPDATE_PENDING_CARD,
)

#: A step status the toolbox gives a correction with nothing of theirs to correct.
NOT_A_CORRECTION = "not_a_correction"
#: What the model is told when that correction is not a whole entry the code can save.
NEW_INFORMATION = (
    "Nothing was changed because there is nothing of theirs to correct: this is NEW "
    "information. Call the save tool for it now (save_work_done, save_labour, "
    "save_material_receipt, save_material_usage or report_issue) with the full details "
    "from their message. Do not tell them there is no card."
)


@dataclass(frozen=True)
class Call:
    """What the model asked for, with the message it answers and, after the
    step ran, the step's status."""

    tool: str
    args: dict[str, Any]
    text: str
    status: str | None = None


@dataclass(frozen=True)
class Redirect:
    """A rule's answer: ``tool``/``args`` when the code makes the call itself,
    else the ``instruction`` (and ``reason``) the model gets, nothing saved."""

    rule: str
    tool: str | None = None
    args: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    instruction: str = ""


@dataclass(frozen=True)
class Rule:
    name: str
    #: The model's tool this rule looks at.
    tool: str
    #: Whether the call is the wrong one, from the call and their words.
    when: Callable[[Call], bool]
    #: The right call, built from the call and their words; None when the words
    #: do not hold what it needs (then ``instruction`` goes to the model).
    to: Callable[[Call], tuple[str, dict[str, Any]] | None]
    reason: str
    instruction: str
    #: None: looked at before the call runs; a status: after its step came back with it.
    after: str | None = None


# -- what their words hold ------------------------------------------------------

_UNITS = r"bags?|bag|chakk\w*|kgs?|kg|nos|pcs|pieces|loads?|cum|cft|tons?|tonnes?|litres?|liters?|brass|rods?|sqft|trips?"
_AMOUNT = re.compile(rf"(?<![\w.])(\d+(?:\.\d+)?)\s*({_UNITS})(?![\w])", re.IGNORECASE)
_TOMORROW = re.compile(r"\b(?:tomorrow|nale|naale|naaley|kal)\b|നാളെ|कल", re.IGNORECASE)


def said_material(text: str) -> dict[str, Any] | None:
    """The one material, quantity and unit the message gives ("50 bag cement",
    "20 rod steel"); None when it names none, or several of either."""
    from .toolbox import material_named

    material = material_named(text or "")
    amounts = _AMOUNT.findall(text or "")
    if material is None or len(amounts) != 1:
        return None
    number, unit = amounts[0]
    return {"material": material, "quantity": float(number) if "." in number else int(number), "unit": unit.lower()}


def as_new_entry(call: Call) -> tuple[str, dict[str, Any]] | None:
    """A correction with nothing of theirs to correct, as the save it describes:
    workers are a labour line, quantities with their work type a work line. None
    when the changes are not a whole entry (a bare percent, a material figure that
    could be received or used), or when their words say a figure was wrong ("alla,
    6 mason aanu" on a line the model did not find is a correction, never more
    masons)."""
    from runtime.day_facts import is_correction

    if is_correction(call.text):
        return None
    changes = call.args.get("changes") if isinstance(call.args.get("changes"), dict) else {}
    workers = [w for w in changes.get("workers") or [] if isinstance(w, dict) and w.get("headcount")]
    if workers:
        return SAVE_LABOUR, {"workers": workers}
    quantities = [q for q in changes.get("quantities") or [] if isinstance(q, dict) and q.get("quantity")]
    work_type = changes.get("work_type") or next((q.get("work_type") for q in quantities if q.get("work_type")), None)
    if quantities and work_type:
        return SAVE_WORK_DONE, {
            "work_type": work_type,
            "quantities": quantities,
            **{k: changes[k] for k in ("location", "narrative") if changes.get(k)},
        }
    return None


def _receipt_from_words(call: Call) -> tuple[str, dict[str, Any]] | None:
    said = said_material(call.text)
    return (SAVE_MATERIAL_RECEIPT, said) if said else None


#: "10 bag cement balance und, kooduthal venam": the figure is the stock left, not the order.
_STOCK_WORDS = re.compile(
    r"\b(?:balance|stock|left|remaining|baaki|bakki|baki|ullath\w*|und\s*,?\s*kooduthal)\b|ബാക്കി|बाकी", re.IGNORECASE
)


def _request_from_words(call: Call) -> tuple[str, dict[str, Any]] | None:
    said = None if _STOCK_WORDS.search(call.text or "") else said_material(call.text)
    if said is None:
        return None
    when = {"needed_by": "tomorrow"} if _TOMORROW.search(call.text or "") else {}
    scope = {k: call.args[k] for k in ("project", "site") if call.args.get(k)}
    return REQUEST_MATERIAL, {**said, **when, **scope}


RULES: tuple[Rule, ...] = (
    Rule(
        name="received_not_used",
        tool=SAVE_MATERIAL_USAGE,
        when=lambda c: says_received(c.text),
        to=lambda c: (SAVE_MATERIAL_RECEIPT, dict(c.args)),
        reason="the message says the material arrived, so it was received, not used",
        instruction="Nothing was saved. Call save_material_receipt with the same material, quantity and unit.",
    ),
    Rule(
        # MAT-07: "50 bags cement arrived" is a receipt; it is never asked.
        name="received_not_asked",
        tool=ASK_USER,
        when=lambda c: asks_direction(str(c.args.get("question") or "")) and says_received(c.text),
        to=_receipt_from_words,
        reason="the message says the material arrived, so it was received",
        instruction=(
            "Do not ask 'Received or used?'. Call save_material_receipt now with the "
            "material, quantity and unit from the message."
        ),
    ),
    Rule(
        # Request 143 (E): "50 bag cement order cheyyanam" is material to order, not a problem on site.
        name="order_not_issue",
        tool=REPORT_ISSUE,
        when=lambda c: is_material_order(c.text) and not RAN_OUT.search(c.text or ""),
        to=_request_from_words,
        reason="an order for material is a material request, not a site issue",
        instruction="Nothing was saved. Call request_material with the material, quantity, unit and when it is needed.",
    ),
    Rule(
        # WA-92: "10 helper-um vannu" sent as a correction of a line that is not there.
        name="add_on_not_correction",
        tool=UPDATE_PENDING_CARD,
        after=NOT_A_CORRECTION,
        when=lambda c: True,
        to=as_new_entry,
        reason="there is nothing of theirs to correct: this is new information",
        instruction=NEW_INFORMATION,
    ),
)


def _first(call: Call, stage: str | None) -> Redirect | None:
    for rule in RULES:
        if rule.tool != call.tool or rule.after != stage or not rule.when(call):
            continue
        made = rule.to(call)
        if made is not None:
            return Redirect(rule.name, tool=made[0], args=made[1], reason=rule.reason)
        return Redirect(rule.name, reason=rule.reason, instruction=rule.instruction)
    return None


def before(tool: str, args: dict[str, Any], text: str) -> Redirect | None:
    """The redirect for a call about to run, or None to run it as asked."""
    return _first(Call(tool, args, text), None)


def after(tool: str, args: dict[str, Any], text: str, status: str) -> Redirect | None:
    """The redirect for a call whose step came back with ``status``, or None."""
    return _first(Call(tool, args, text, status), status)
