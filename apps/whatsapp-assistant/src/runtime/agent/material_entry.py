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
from mesiri_contracts.assistant.canonical_event import CanonicalEventType, IntentCompleteness
from mesiri_contracts.assistant.planner_decision import (
    PlannerDecisionType,
    PlannerPriority,
    WorkflowKey,
)
from mesiri_contracts.assistant.v2.canonical_event import CanonicalEventV2
from mesiri_contracts.assistant.v2.planner_decision import PlannerDecisionV2
from mesiri_contracts.common.ids import new_id
from runtime.entity_resolution.material_resolution import classify_material_matches
from runtime.material_units import ask_amount_text, fit_stock_unit

_log = logging.getLogger("mesiri.agent")

_MODULE = "materials"
_BY_DIRECTION = {
    "received": (CanonicalEventType.MATERIAL_RECEIPT_REQUESTED, WorkflowKey.MATERIAL_RECEIPT),
    "used": (CanonicalEventType.MATERIAL_USAGE_REQUESTED, WorkflowKey.MATERIAL_USAGE),
}


@dataclass(slots=True)
class Ready:
    """Start this workflow: the event is complete and in the stock unit."""

    decision: PlannerDecisionV2
    event: CanonicalEventV2


@dataclass(slots=True)
class Say:
    """Nothing started; tell the model this (status as ``StepResult``)."""

    status: str
    text: str
    #: "choose" only: the question and its options, shown as buttons by the
    #: code whatever the model writes (round 3c, 21 Oct: it asked in plain
    #: text and the options never appeared).
    question: str | None = None
    options: tuple[str, ...] = ()


@dataclass(slots=True)
class MaterialEntry:
    context_resolver: Any
    catalog_query: Any
    inventory_query: Any | None
    org_settings_query: Any | None
    actor: Any

    async def prepare(self, message: Any, understanding: Any, candidate: Any) -> Ready | Say | None:
        """The workflow to start, a line to say, or None (use the classic route)."""
        fields = dict(candidate.fields)
        direction = fields.get("direction")
        if direction not in _BY_DIRECTION:
            return None
        event_type, workflow_key = _BY_DIRECTION[direction]
        quantity = _number(fields.get("quantity"))
        if quantity is None or quantity <= 0 or not fields.get("material_name"):
            return Say("error", "Not saved: the material and a quantity above zero are needed.")
        fields["quantity"] = quantity

        result = await self.context_resolver.resolve(message, understanding)
        if not result.is_ok:
            return None
        ctx = result.unwrap()
        organization_id = str(ctx.organization_id)

        if not await self._module_on(organization_id):
            from channel.replies import render_module_disabled_reply

            return Say("info", render_module_disabled_reply(_MODULE, getattr(self.actor, "role", None)))

        project_id = ctx.project_id
        site_id = ctx.site_id
        if project_id is None:
            names = [p.name for p in getattr(self.actor, "projects", None) or []]
            if not names:
                return Say("info", "Not saved: you are not on any project yet. Your admin can add you.")
            return _choose("Which project is this for?", names, "project")
        if site_id is None:
            sites = [s for s in getattr(self.actor, "sites", None) or [] if s.project_id == project_id]
            if len(sites) > 1:
                return _choose("Which site is this for?", [s.name for s in sites], "site")
            site_id = sites[0].id if sites else None

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

        for key in ("project_id", "site_id", "project_name", "site_name"):
            fields.pop(key, None)
        fields = resolve_occurred_date(fields, timezone_name=ctx.timezone)
        if direction == "used":
            stock = await self._stock(organization_id, project_id, site_id, fields["material_id"], message)
            if stock is not None:
                fields["available_stock"] = stock

        event = CanonicalEventV2(
            event_id=new_id("evt"),
            correlation_id=message.correlation_id,
            source_message_id=message.message_id,
            conversation_id=ctx.conversation_id,
            event_type=event_type,
            completeness=IntentCompleteness.ACTIONABLE,
            organization_id=ctx.organization_id,
            user_id=ctx.user_id,
            project_id=project_id,
            site_id=site_id,
            permissions=ctx.permissions,
            fields=fields,
        )
        decision = PlannerDecisionV2(
            correlation_id=event.correlation_id,
            source_message_id=event.source_message_id,
            causation_event_id=event.event_id,
            decision_type=PlannerDecisionType.START_WORKFLOW,
            workflow_key=workflow_key,
            reason=event.event_type,
            priority=PlannerPriority.NORMAL,
            organization_id=event.organization_id,
            user_id=event.user_id,
            project_id=event.project_id,
            site_id=event.site_id,
        )
        return Ready(decision=decision, event=event)

    async def _module_on(self, organization_id: str) -> bool:
        if self.org_settings_query is None:
            return True
        try:
            return _MODULE in await self.org_settings_query.enabled_modules(organization_id=organization_id)
        except Exception:  # noqa: BLE001 -- the save path's own MODULE_DISABLED check is the backstop
            _log.warning("material_entry.modules_failed", exc_info=True)
            return True

    async def _material(
        self, organization_id: str, name: str, fields: dict, ctx: Any, message: Any
    ) -> dict | Say | None:
        """The catalogue row, a question for the model to ask (ARCH-04: the
        old picker buttons, as the model's own question), or None when the
        lookup failed (the classic route answers)."""
        from workflows.entities import Ambiguous, Resolved

        try:
            matches = await self.catalog_query.find_materials(organization_id=organization_id, name=name)
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
            return _choose(f'Which material is "{name}"?', names, "material")

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
        return _choose(
            f'"{name}" isn\'t in the material list. Which one is it?',
            [m["name"] for m in listed],
            "material",
            note=" A new material is added by an admin on the dashboard.",
        )

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


def _choose(question: str, options: list[str], arg: str, *, note: str = "") -> Say:
    """The sender must choose (ARCH-04): the model is told, and the options
    go out as buttons under its question."""
    shown = list(options)[:10]
    return Say(
        "choose",
        f"Not saved yet. {question} Options: {', '.join(shown)}. The options are shown as buttons; "
        f"when they answer, call this tool again with that exact {arg}.{note}",
        question=question,
        options=tuple(shown),
    )


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
