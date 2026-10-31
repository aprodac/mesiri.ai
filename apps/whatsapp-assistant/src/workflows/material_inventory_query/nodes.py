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
        asking = fields.get("asking")
        return {"pending_prompt": _period_reply(period["label"], levels, material_name, asking)}

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


def _period_reply(label: str, levels: list[dict], material_name: str | None, asking: str | None = None) -> str:
    """MAT-03: a day's or period's received/used from the movements, with the
    stock now: "Yesterday (24 Oct): 10 bags cement used. 495 bags left now." """
    head = label[:1].upper() + label[1:]
    if material_name and len(levels) == 1:
        level = levels[0]
        name = level["material_name"].lower()
        moved = _moved(level)
        left = f"{_fmt(level['current_stock'])} {level['unit']} left now."
        if asking == "loss":
            from runtime.loss_rules import loss_line

            return f"{head}: " + loss_line(
                name, level["unit"], float(level.get("period_received") or 0), float(level.get("period_used") or 0),
                level.get("period_rate"), _fmt,
            )
        if asking in ("used", "received"):
            # Request 114: "cement used yesterday?" leads with what was used,
            # and says so when it was nothing, never only what arrived.
            other = "received" if asking == "used" else "used"
            first, second = f"period_{asking}", f"period_{other}"
            lead = (
                f"{_fmt(level[first])} {level['unit']} {name} {asking}."
                if level.get(first)
                else f"No {name} {asking}."
            )
            more = f" {_fmt(level[second])} {level['unit']} {other}." if level.get(second) else ""
            return f"{head}: {lead}{more} {left}"
        if not moved:
            return f"{head}: no {name} was used or received. {left}"
        words = []
        if level.get("period_used"):
            words.append(f"{_fmt(level['period_used'])} {level['unit']} {name} used")
        if level.get("period_received"):
            words.append(f"{_fmt(level['period_received'])} {level['unit']} {name} received")
        return f"{head}: {' and '.join(words)}. {left}"
    if asking == "loss":
        from runtime.loss_rules import loss_line

        rows = [
            loss_line(lv["material_name"], lv["unit"], float(lv.get("period_received") or 0),
                      float(lv.get("period_used") or 0), lv.get("period_rate"), _fmt)
            for lv in levels if lv.get("period_received")
        ]
        return f"📉 *Material loss — {label}*\n\n" + "\n".join(rows) if rows else f"Nothing was received {label}."
    lines = [f"📦 *Materials — {label}*", ""]
    for level in levels:
        moved = _moved(level)
        if moved:
            lines.append(f"{level['material_name'].title()} — {moved} · {_fmt(level['current_stock'])} {level['unit']} now")
    if len(lines) == 2:
        return f"Nothing was received or used {label}."
    return "\n".join(lines)
