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
