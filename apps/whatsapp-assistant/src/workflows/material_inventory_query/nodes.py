"""Nodes for the material inventory-query workflow."""

from __future__ import annotations

from ..readable import format_quantity
from ..state import WorkflowGraphState

_fmt = format_quantity


def generate_inventory_reply(state: WorkflowGraphState) -> dict:
    """Read the injected stock levels and format the reply. No draft_action --
    this is read-only, so WorkflowRuntime completes it without a confirmation."""
    fields = state.get("collected_fields", {})
    levels: list[dict] = fields.get("inventory_levels") or []
    material_name = fields.get("material_name")

    if not levels:
        if material_name:
            return {"pending_prompt": f"I don't have any recorded stock for {material_name} yet."}
        return {"pending_prompt": "I don't have any recorded material stock yet."}

    period = fields.get("inventory_period")
    if period:
        return {"pending_prompt": _period_reply(period["label"], levels, material_name)}

    if material_name and len(levels) == 1:
        level = levels[0]
        lines = [
            f"📦 {level['material_name'].title()}",
            f"In stock: {_fmt(level['current_stock'])} {level['unit']}",
            "",
            f"Received  {_fmt(level['received'])} {level['unit']}",
            f"Used      {_fmt(level['used'])} {level['unit']}",
        ]
        return {"pending_prompt": "\n".join(lines)}

    lines = ["📦 *Current inventory*", ""]
    for level in levels:
        lines.append(
            f"{level['material_name'].title()} — {_fmt(level['current_stock'])} {level['unit']}"
        )
    return {"pending_prompt": "\n".join(lines)}


def _moved(level: dict) -> str:
    """"10 bags used, 50 bags received" for one material over the period."""
    unit = level["unit"]
    parts = []
    if level.get("period_used"):
        parts.append(f"{_fmt(level['period_used'])} {unit} used")
    if level.get("period_received"):
        parts.append(f"{_fmt(level['period_received'])} {unit} received")
    return ", ".join(parts)


def _period_reply(label: str, levels: list[dict], material_name: str | None) -> str:
    """MAT-03: a day's or period's received/used from the movements, with the
    stock now: "Yesterday (24 Oct): 10 bags cement used. 495 bags left now." """
    head = label[:1].upper() + label[1:]
    if material_name and len(levels) == 1:
        level = levels[0]
        name = level["material_name"].lower()
        moved = _moved(level)
        left = f"{_fmt(level['current_stock'])} {level['unit']} left now."
        if not moved:
            return f"{head}: no {name} was used or received. {left}"
        words = []
        if level.get("period_used"):
            words.append(f"{_fmt(level['period_used'])} {level['unit']} {name} used")
        if level.get("period_received"):
            words.append(f"{_fmt(level['period_received'])} {level['unit']} {name} received")
        return f"{head}: {' and '.join(words)}. {left}"
    lines = [f"📦 *Materials — {label}*", ""]
    for level in levels:
        moved = _moved(level)
        if moved:
            lines.append(f"{level['material_name'].title()} — {moved} · {_fmt(level['current_stock'])} {level['unit']} now")
    if len(lines) == 2:
        return f"Nothing was received or used {label}."
    return "\n".join(lines)
