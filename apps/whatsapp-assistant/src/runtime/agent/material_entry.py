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
from mesiri.domains.materials.validation import OPENING_STOCK, role_can_adjust
from mesiri_contracts.assistant.canonical_event import CanonicalEventType
from mesiri_contracts.assistant.enums import InputModality
from mesiri_contracts.assistant.planner_decision import WorkflowKey
from runtime.entity_resolution.material_resolution import classify_material_matches
from runtime.material_units import ask_amount_text, conversion_question, fit_stock_unit

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
    # [103]: stock that was on site before Mesiri is a receipt with its own reason.
    "opening_stock": (CanonicalEventType.MATERIAL_RECEIPT_REQUESTED, WorkflowKey.MATERIAL_RECEIPT),
    "transfer": (CanonicalEventType.MATERIAL_TRANSFER_REQUESTED, WorkflowKey.MATERIAL_TRANSFER),
}

#: [103]: the last choice of a long material list: they type the name instead.
SOMETHING_ELSE = "Something else"
#: What an answer fills in (``Say.awaiting``), so a card line waiting on the
#: question can take the answer from a tap (request 127): how many stock units
#: one reported unit is, and whether to add a new material.
AWAIT_UNIT = "unit"
AWAIT_NEW_MATERIAL = "new_material"
ADD_IT = "Yes, add it"
#: WhatsApp lists hold ten rows: nine materials and "Something else".
LIST_MATERIALS = 9


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

        opening = direction == "opening_stock"
        if opening and not role_can_adjust(str(getattr(self.actor, "role", "") or "")):
            # The web's rule (BE-12): stock that changes without a delivery behind it.
            return Say(
                "info",
                "Not saved: opening stock can only be entered by an admin or project manager.",
            )
        transfer = direction == "transfer"
        to_name = str(fields.pop("to_site_name", "") or "").strip()

        scoped = await self.settle(message, understanding, candidate, module=_MODULE, site_required=transfer)
        if isinstance(scoped, Say):
            return scoped
        ctx, organization_id = scoped.ctx, scoped.organization_id
        project_id, site_id = scoped.project_id, scoped.site_id
        destination: dict[str, Any] = {}
        if transfer:
            placed = self._destination(scoped, to_name)
            if isinstance(placed, Say):
                return placed
            destination = placed

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
            role = getattr(self.actor, "role", None)
            text = ask_amount_text(material, fields, fit, role=role)
            ask = conversion_question(material, fit, role=role)
            if ask is None:
                return Say("info", text)
            question, options = ask
            return Say(
                "choose",
                f"{text} The question is shown to them"
                + (f" with buttons {' / '.join(options)}" if options else "")
                + f': "{question}". When they answer with a number, call set_unit_conversion '
                "(unit_amount 1, stock_amount that number), then this tool again with their original "
                "amount and unit. If they pick Other, ask them the number (ask_user, no options).",
                question=question,
                options=options,
                awaiting=AWAIT_UNIT,
            )

        site_name = self._site_name(site_id)
        if transfer:
            fields.update(destination)
            fields["from_site_name"] = site_name
        elif opening:
            fields["movement_reason"] = OPENING_STOCK
            fields["direction"] = "received"
            fields["site_label"] = site_name
        for key in SCOPE_KEYS:
            fields.pop(key, None)
        # The card's rule: a blank or default "UTC" zone is India, so a 2:45 AM
        # entry lands on today, not yesterday (22 Oct).
        fields = resolve_occurred_date(fields, timezone_name=str(company_zone(ctx.timezone)))
        if direction == "used":
            stock = await self._stock(organization_id, project_id, site_id, fields["material_id"], message)
            if stock is not None:
                fields["available_stock"] = stock
                if float(fields["quantity"]) > float(stock) and not await self._has_opening(organization_id, site_id, fields, message):
                    # [103]: used more than the book says and no starting stock was
                    # ever entered: the warning points at "opening stock".
                    fields["no_opening_stock"] = True

        return self.ready(scoped, message, event_type, workflow_key, fields)

    def _site_name(self, site_id: Any) -> str:
        for site in getattr(self.actor, "sites", None) or []:
            if str(site.id) == str(site_id):
                return str(site.name)
        return ""

    def _destination(self, scoped: Any, said: str) -> dict[str, Any] | Say:
        """The site it went to, only ever one of the sender's own sites (their
        company's, by the same list the pickers use); anything else is asked
        as a list, never guessed."""
        sites = list(getattr(self.actor, "sites", None) or [])
        projects = {str(p.id): str(p.name) for p in getattr(self.actor, "projects", None) or []}
        others = [s for s in sites if str(s.id) != str(scoped.site_id)]
        names = [str(s.name) for s in sites]
        # Two sites with one name are told apart by their project.
        labels = {
            str(s.id): (
                f"{s.name} ({projects.get(str(s.project_id), '')})"
                if names.count(str(s.name)) > 1 and projects.get(str(s.project_id))
                else str(s.name)
            )
            for s in sites
        }
        key = " ".join(said.casefold().split())
        hit = [s for s in others if key and " ".join(labels[str(s.id)].casefold().split()) == key]
        if not hit and key:
            hit = [s for s in others if " ".join(str(s.name).casefold().split()) == key]
        if len(hit) != 1:
            if not others:
                return Say("info", "Not saved: you have no other site to send it to. Your admin can add one.")
            question = "Which site did it go to?" if not said else f'"{said}" isn\'t one of your sites. Which site did it go to?'
            return choose(question, [labels[str(s.id)] for s in others], "to_site")
        site = hit[0]
        return {
            "to_site_id": str(site.id),
            "to_project_id": str(site.project_id),
            "to_site_name": str(site.name),
        }

    async def _has_opening(self, organization_id: str, site_id: Any, fields: dict, message: Any) -> bool:
        """Whether opening stock was ever entered for this material here. A
        failed lookup says yes: the hint is never worth a wrong line."""
        check = getattr(self.catalog_query, "has_opening_stock", None)
        if check is None:
            return True
        try:
            return bool(
                await check(
                    organization_id=organization_id,
                    site_id=str(site_id) if site_id else None,
                    material_id=str(fields["material_id"]),
                )
            )
        except Exception:  # noqa: BLE001
            _log.warning("material_entry.opening_lookup_failed correlation_id=%s", message.correlation_id, exc_info=True)
            return True

    async def _pick_material(self, organization_id: str, question: str, name: str, note: str = "") -> Say:
        """The material to choose from. A company with more than ten materials
        gets the nine closest to what was typed (recent use first) and
        "Something else": a WhatsApp list holds ten rows, and the first ten
        alphabetically was all anyone saw."""
        listed: list[dict] = []
        total = 0
        try:
            closest = getattr(self.catalog_query, "closest_materials", None)
            if closest is not None:
                listed, total = await closest(organization_id=organization_id, name=name, limit=LIST_MATERIALS)
            else:
                listed = await self.catalog_query.list_active_materials(organization_id=organization_id)
                total = len(listed)
        except Exception:  # noqa: BLE001
            listed = []
        if not listed:
            return Say(
                "info",
                f'Not saved: "{name}" is not in the material list, and the list is empty. An admin adds materials on the dashboard.',
            )
        names = [m["name"] for m in listed]
        if total > len(names) or total > 10:
            names = names[:LIST_MATERIALS] + [SOMETHING_ELSE]
            note += (
                f' If they pick "{SOMETHING_ELSE}", ask them to type the material name (ask_user, '
                "no options), then call this tool again with what they typed."
            )
        return choose(question, names, "material", note=note)

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
            if len(names) > 10:
                return await self._pick_material(organization_id, f'Which material is "{name}"?', name)
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
                options=(ADD_IT, "No"),
                awaiting=AWAIT_NEW_MATERIAL,
            )
        return await self._pick_material(
            organization_id,
            f'"{name}" isn\'t in the material list. Which one is it?',
            name,
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
                options=("Bags", "Kg", "Nos", "Cum", "Cft", "Tons", "Litres", "Load"),
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
                # WA-77: the hint compares with what was reported, saved or not.
                include_unsaved=True,
            )
        except Exception:  # noqa: BLE001 -- the stock note is a hint, never a block
            _log.warning("material_entry.stock_failed correlation_id=%s", message.correlation_id, exc_info=True)
            return None
        return levels[0]["current_stock"] if levels else None

