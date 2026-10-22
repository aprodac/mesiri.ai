"""ARCH-01: a material receipt or usage from the agent, without the classic pipeline.

The agent's save_material_receipt / save_material_usage used to run through
``process_inbound_message`` (canonicalize -> gates -> planner -> graph) and
have its replies captured. Here the tool's arguments become the workflow's
event directly (ADR section 10b). What stays exactly as it was:

- who the sender is, their company, and which project/site they may use:
  ``ContextResolver.resolve``, unchanged (no new permission logic);
- the save: ``WorkflowRuntime.start`` + save-first, unchanged (idempotency,
  single-active guard, validation, posting).

What is plain code here instead of pipeline stages: the date, the material
(exact catalogue name only), the stock unit (``runtime/material_units``), the
module switch, and the stock figure (by material id, not by name).

When the sender must choose (which material, project or site, or whether to
add a new material), the model is told the options and asks with its own
``ask_user``; the answer comes back as a new call with the exact name
(ARCH-04: the old picker buttons resumed a held report and saved on the tap,
past the Save card). Only a failed context or catalogue lookup returns
``None``, and the caller runs the classic route for that call.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from canonicalization.occurred_date import resolve_occurred_date
from channel.receipt.data import company_zone
from mesiri_contracts.assistant.canonical_event import CanonicalEventType
from mesiri_contracts.assistant.enums import InputModality
from mesiri_contracts.assistant.planner_decision import WorkflowKey
from runtime.entity_resolution.material_resolution import classify_material_matches
from runtime.material_units import ask_amount_text, fit_stock_unit

from .entry_base import (
    SCOPE_KEYS,
    EntryScope,
    Ready,
    Say,
    choose,
    number,
)

__all__ = ["MaterialEntry", "Ready", "Say"]

_log = logging.getLogger("mesiri.agent")

_MODULE = "materials"
_BY_DIRECTION = {
    "received": (CanonicalEventType.MATERIAL_RECEIPT_REQUESTED, WorkflowKey.MATERIAL_RECEIPT),
    "used": (CanonicalEventType.MATERIAL_USAGE_REQUESTED, WorkflowKey.MATERIAL_USAGE),
}


@dataclass(slots=True)
class MaterialEntry(EntryScope):
    context_resolver: Any
    catalog_query: Any
    inventory_query: Any | None
    org_settings_query: Any | None
    actor: Any
    #: The sender's active project/site (``ContextResolver`` reads it).
    active_context: Any | None = None

    async def prepare(self, message: Any, understanding: Any, candidate: Any) -> Ready | Say | None:
        """The workflow to start, a line to say, or None (use the classic route)."""
        fields = dict(candidate.fields)
        direction = fields.get("direction")
        if direction not in _BY_DIRECTION:
            return None
        event_type, workflow_key = _BY_DIRECTION[direction]
        quantity = number(fields.get("quantity"))
        if quantity is None or quantity <= 0 or not fields.get("material_name"):
            return Say("error", "Not saved: the material and a quantity above zero are needed.")
        fields["quantity"] = quantity

        scoped = await self.settle(message, understanding, candidate, module=_MODULE)
        if isinstance(scoped, Say):
            return scoped
        ctx, organization_id = scoped.ctx, scoped.organization_id
        project_id, site_id = scoped.project_id, scoped.site_id

        found = await self._material(organization_id, str(fields["material_name"]), fields, ctx, message)
        if not isinstance(found, dict):
            return found
        material = found
        fields.pop("new_material", None)
        fields["material_id"] = str(material["id"])
        fields["material_name"] = material["name"]

        fit = await fit_stock_unit(
            fields,
            material,
            catalog_query=self.catalog_query,
            organization_id=organization_id,
            correlation_id=message.correlation_id,
        )
        if fit.kind == "mismatch":
            return Say("info", ask_amount_text(material, fields, fit, role=getattr(self.actor, "role", None)))

        for key in SCOPE_KEYS:
            fields.pop(key, None)
        # The card's rule: a blank or default "UTC" zone is India, so a 2:45 AM
        # entry lands on today, not yesterday (22 Oct).
        fields = resolve_occurred_date(fields, timezone_name=str(company_zone(ctx.timezone)))
        if direction == "used":
            stock = await self._stock(organization_id, project_id, site_id, fields["material_id"], message)
            if stock is not None:
                fields["available_stock"] = stock

        return self.ready(scoped, message, event_type, workflow_key, fields)

    async def _material(
        self, organization_id: str, name: str, fields: dict, ctx: Any, message: Any
    ) -> dict | Say | None:
        """The catalogue row, a question for the model to ask (ARCH-04: the
        old picker buttons, as the model's own question), or None when the
        lookup failed (the classic route answers)."""
        from workflows.entities import Ambiguous, Resolved

        try:
            matches = await self.catalog_query.find_materials(organization_id=organization_id, name=name)
            singular = name.strip()[:-1] if name.strip().lower().endswith("s") else ""
            if not matches and len(singular) > 2:
                # "bricks" never finds "Brick" by substring (review, 22 Oct).
                matches = await self.catalog_query.find_materials(organization_id=organization_id, name=singular)
        except Exception:  # noqa: BLE001 -- the classic route asks or lets it through
            _log.warning("material_entry.lookup_failed correlation_id=%s", message.correlation_id, exc_info=True)
            return None
        outcome = classify_material_matches(name, matches)
        if isinstance(outcome, Resolved):
            material = next(m for m in matches if str(m["id"]) == outcome.entity_id)
            if not material.get("is_active", True):
                return Say("info", f"Not saved: {material['name']} is no longer in use in the material list.")
            return material
        if isinstance(outcome, Ambiguous):
            names = [c.display_name for c in outcome.candidates]
            return choose(f'Which material is "{name}"?', names, "material")

        if getattr(message, "modality", None) in (InputModality.IMAGE, InputModality.DOCUMENT):
            # A bill's trade name ("Cement OPC 53 grade", "TMT steel bars 12mm",
            # "Wire cut bricks"): the one listed material it names (live photo
            # set, 22 Oct: told to give the plain name, the model still passed
            # the bill's). Only for what was read from a bill; typed words ask.
            named = await self._named_on_bill(organization_id, name, message)
            if named is not None:
                return named

        may_create = await self._may_create(organization_id)
        if may_create and fields.get("new_material"):
            return await self._create(organization_id, name, fields, ctx, message)
        if may_create:
            return Say(
                "choose",
                f'Not saved yet: "{name}" is not in the company\'s material list. Ask whether to add it '
                "as a new material. If yes, call this tool again with new_material true; if no, ask "
                "which listed material they meant.",
                question=f'"{name}" isn\'t in your material list yet. Add it as a new material?',
                options=("Yes, add it", "No"),
            )
        try:
            listed = await self.catalog_query.list_active_materials(organization_id=organization_id)
        except Exception:  # noqa: BLE001
            listed = []
        if not listed:
            return Say("info", f'Not saved: "{name}" is not in the material list, and the list is empty. An admin adds materials on the dashboard.')
        return choose(
            f'"{name}" isn\'t in the material list. Which one is it?',
            [m["name"] for m in listed],
            "material",
            note=" A new material is added by an admin on the dashboard.",
        )

    async def _named_on_bill(self, organization_id: str, name: str, message: Any) -> dict | None:
        """The listed material a bill line names, by its words and word pairs
        (singular or plural): the longest exact catalogue name found, when it is
        the only one that long. None when no listed name, or more than one, is in it."""
        import re

        from workflows.entities import Resolved

        words = [w for w in re.findall(r"[a-z]+", name.lower()) if len(w) > 1]
        tries: list[str] = []
        for size in (2, 1):
            for i in range(len(words) - size + 1):
                phrase = " ".join(words[i : i + size])
                tries.append(phrase)
                if phrase.endswith("s") and len(phrase) > 3:
                    tries.append(phrase[:-1])
        found: dict[str, dict] = {}
        for phrase in dict.fromkeys(tries):
            try:
                rows = await self.catalog_query.find_materials(organization_id=organization_id, name=phrase)
            except Exception:  # noqa: BLE001 -- the usual question follows
                _log.warning("material_entry.bill_lookup_failed correlation_id=%s", message.correlation_id, exc_info=True)
                return None
            for row in rows:
                if isinstance(classify_material_matches(phrase, [row]), Resolved) and row.get("is_active", True):
                    found[str(row["id"])] = row
        if not found:
            return None
        longest = max(len(str(r["name"]).split()) for r in found.values())
        best = [r for r in found.values() if len(str(r["name"]).split()) == longest]
        if len(best) != 1:
            return None
        _log.info("material_entry.bill_name correlation_id=%s matched=%s", message.correlation_id, best[0]["name"])
        return best[0]

    async def _may_create(self, organization_id: str) -> bool:
        """STA-139's rule: the org's whatsapp_material_create_roles setting."""
        from types import SimpleNamespace

        from runtime.inbound_journey.seeding import _may_create_material

        try:
            return await _may_create_material(
                SimpleNamespace(organization_id=organization_id),
                actor_role=getattr(self.actor, "role", None),
                org_settings_query=self.org_settings_query,
            )
        except Exception:  # noqa: BLE001 -- unknown rights never grant
            _log.warning("material_entry.create_rights_failed", exc_info=True)
            return False

    async def _create(self, organization_id: str, name: str, fields: dict, ctx: Any, message: Any) -> dict | Say:
        """Add the material (the sender said yes), counted in the unit they used."""
        unit_text = fields.get("unit")
        unit = await self.catalog_query.resolve_unit(str(unit_text)) if unit_text else None
        if unit is None:
            return Say(
                "choose",
                f'Not saved yet: which unit is "{name}" counted in? Ask, then call this tool again with '
                "new_material true and that unit.",
                question=f'Which unit is "{name}" counted in?',
                options=("Bags", "Kg", "Nos", "Cum", "Litres"),
            )
        created = await self.catalog_query.create_material(
            organization_id=organization_id, name=name, unit_id=str(unit["id"]), created_by=str(getattr(self.actor, "user_id", None) or ctx.user_id)
        )
        if created is None:
            return Say("error", f'Not saved: "{name}" could not be added to the material list.')
        _log.info("material_entry.material_created correlation_id=%s", message.correlation_id)
        return created

    async def _stock(
        self, organization_id: str, project_id: Any, site_id: Any, material_id: str, message: Any
    ) -> float | None:
        if self.inventory_query is None:
            return None
        try:
            levels = await self.inventory_query.query(
                organization_id=organization_id,
                project_id=str(project_id) if project_id else None,
                site_id=str(site_id) if site_id else None,
                material_name=None,
                material_id=material_id,
            )
        except Exception:  # noqa: BLE001 -- the stock note is a hint, never a block
            _log.warning("material_entry.stock_failed correlation_id=%s", message.correlation_id, exc_info=True)
            return None
        return levels[0]["current_stock"] if levels else None

