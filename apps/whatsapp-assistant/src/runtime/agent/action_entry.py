"""Request 104: place a card for something that is not a record.

``engineer_question`` (a question for the site's engineer), ``site_conditions``
(weather, site working, hours lost, tomorrow's plan) and ``close_issues`` come
here from their agent tools. Like the other entries this settles who the sender
is and which project/site it is for (``EntryScope.settle``, unchanged), then
prepares a ``PendingAction`` and writes nothing: the Save tap runs it
(``actions.py``). What cannot be done is said plainly, with no card.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from canonicalization.occurred_date import resolve_occurred_date
from channel.receipt.data import company_zone
from mesiri_contracts.assistant.planner_decision import WorkflowKey
from workflows.registry import module_for_workflow

from .actions import (
    CLOSE_ISSUES,
    ENGINEER_QUESTION,
    MATERIAL_REQUEST,
    SITE_CONDITIONS,
    ActionService,
    PendingAction,
    material_request_line,
    new_action,
)
from .entry_base import EntryScope, Say, Scoped, choose

_log = logging.getLogger("mesiri.agent")

WEATHER_WORDS = {
    "sunny": "Sunny",
    "cloudy": "Cloudy",
    "rainy": "Rainy",
    "windy": "Windy",
    "extreme_heat": "Extreme heat",
}
WORKING_WORDS = {"full": "Full day", "half": "Half day", "none": "No work"}

NO_ONE = (
    "Not sent: I couldn't find a site engineer or project manager with WhatsApp for this site, "
    "so there is nobody to send it to. Please ask them directly, or ask your admin to add them."
)


@dataclass(slots=True)
class ActionEntry(EntryScope):
    context_resolver: Any
    org_settings_query: Any | None
    actor: Any
    service: ActionService
    active_context: Any | None = None
    #: ``(scoped) -> list[open issue dict]`` for ``close_issues`` (request 104, C).
    open_issues: Any | None = None

    async def prepare(self, message: Any, understanding: Any, candidate: Any) -> PendingAction | Say:
        kind = candidate.fields["_action"]
        if kind == ENGINEER_QUESTION:
            return await self._engineer_question(message, understanding, candidate)
        if kind == SITE_CONDITIONS:
            return await self._conditions(message, understanding, candidate)
        if kind == CLOSE_ISSUES:
            return await self._close_issues(message, understanding, candidate)
        if kind == MATERIAL_REQUEST:
            return await self._material_request(message, understanding, candidate)
        return Say("error", "Not done: that can't be done here yet.")

    # -- material to order (request 143) ------------------------------------------

    async def _material_request(self, message: Any, understanding: Any, candidate: Any) -> PendingAction | Say:
        request = material_request_line(candidate.fields)
        if not str(candidate.fields.get("material") or "").strip():
            return Say("error", "Not sent: say which material is needed.")
        scoped = await self.settle(
            message, understanding, candidate, module=module_for_workflow(WorkflowKey.MATERIAL_RECEIPT)
        )
        if isinstance(scoped, Say):
            return scoped
        people = await self.service.engineers(
            organization_id=scoped.organization_id,
            project_id=str(scoped.project_id) if scoped.project_id else None,
            site_id=str(scoped.site_id) if scoped.site_id else None,
            exclude_user=str(scoped.ctx.user_id),
        )
        if not people:
            return Say("info", NO_ONE)
        payload = {
            "request": request,
            "asker": str(getattr(self.actor, "full_name", None) or getattr(self.actor, "name", None) or "A teammate"),
            "site_name": self._site_name(scoped),
            "project_id": str(scoped.project_id) if scoped.project_id else None,
            "site_id": str(scoped.site_id) if scoped.site_id else None,
            "recipients": people,
        }
        return new_action(MATERIAL_REQUEST, payload, f"Material request: {request}")

    # -- a question for the engineer ----------------------------------------------

    async def _engineer_question(self, message: Any, understanding: Any, candidate: Any) -> PendingAction | Say:
        question = " ".join(str(candidate.fields.get("question") or "").split())[:500]
        if not question:
            return Say("error", "Not sent: there was no question to send.")
        scoped = await self.settle(
            message, understanding, candidate, module=module_for_workflow(WorkflowKey.SITE_UPDATE)
        )
        if isinstance(scoped, Say):
            return scoped
        people = await self.service.engineers(
            organization_id=scoped.organization_id,
            project_id=str(scoped.project_id) if scoped.project_id else None,
            site_id=str(scoped.site_id) if scoped.site_id else None,
            exclude_user=str(scoped.ctx.user_id),
        )
        if not people:
            return Say("info", NO_ONE)
        payload = {
            "question": question,
            "asker": str(getattr(self.actor, "full_name", None) or getattr(self.actor, "name", None) or "A teammate"),
            "site_name": self._site_name(scoped),
            "project_id": str(scoped.project_id) if scoped.project_id else None,
            "site_id": str(scoped.site_id) if scoped.site_id else None,
            "recipients": people,
        }
        return new_action(ENGINEER_QUESTION, payload, f"Send to engineer: {question}")

    def _site_name(self, scoped: Scoped) -> str | None:
        for site in getattr(self.actor, "sites", None) or []:
            if str(site.id) == str(scoped.site_id):
                return str(site.name)
        return None

    # -- the day's conditions -----------------------------------------------------

    async def _conditions(self, message: Any, understanding: Any, candidate: Any) -> PendingAction | Say:
        fields = candidate.fields
        changes = conditions_from(fields)
        if not changes:
            return Say("error", "Not saved: say the weather, whether the site worked, or tomorrow's plan.")
        scoped = await self.settle(
            message,
            understanding,
            candidate,
            module=module_for_workflow(WorkflowKey.SITE_UPDATE),
            site_required=True,
            site_prompt=True,
        )
        if isinstance(scoped, Say):
            return scoped
        if scoped.site_id is None:
            return Say("info", "Not saved: weather and plans belong to a site, and you are not on one yet.")
        zone = str(company_zone(scoped.ctx.timezone))
        day = resolve_occurred_date({"occurred_on": fields.get("occurred_on")}, timezone_name=zone)
        report_date = _iso_day(day.get("occurred_date"), zone)
        payload = {
            "organization_id": scoped.organization_id,
            "project_id": str(scoped.project_id),
            "site_id": str(scoped.site_id),
            "report_date": report_date.isoformat(),
            "changes": changes,
        }
        return new_action(
            SITE_CONDITIONS, payload, conditions_summary(changes, report_date, zone, site=self._site_name(scoped))
        )

    # -- issues to close ----------------------------------------------------------

    async def _close_issues(self, message: Any, understanding: Any, candidate: Any) -> PendingAction | Say:
        from .issue_match import closing_action

        if candidate.fields.get("issue_refs") and self.open_issues is not None:
            # Live 29 Oct: a tap on a row of "which issue is fixed?" names its issues by id.
            # It carries no project or site (the model's call had them from the chat), so
            # settling it asked "Which project is this for?" again and again. The issues'
            # own site and project stand; the company's open issues are searched for them.
            scoped = Scoped(SimpleNamespace(timezone=None), str(self.actor.organization_id), None, None, None, None)
            return closing_action(await self.open_issues(scoped), candidate.fields, scoped, choose)
        scoped = await self.settle(
            message,
            understanding,
            candidate,
            module=module_for_workflow(WorkflowKey.SITE_ISSUE_CLOSE),
            ask_site=False,
        )
        if isinstance(scoped, Say):
            return scoped
        if self.open_issues is None:
            return Say("error", "Not done: I can't look up the open issues here.")
        issues = await self.open_issues(scoped)
        return closing_action(issues, candidate.fields, scoped, choose)


def conditions_from(fields: dict[str, Any]) -> dict[str, Any]:
    """The setter's ``changes`` from the tool's arguments; only what was said."""
    changes: dict[str, Any] = {}
    if fields.get("weather"):
        changes["weather"] = str(fields["weather"]).strip().lower()
    if fields.get("site_working"):
        changes["site_working"] = str(fields["site_working"]).strip().lower()
    if fields.get("hours_lost") not in (None, ""):
        try:
            changes["hours_lost"] = float(fields["hours_lost"])
        except (TypeError, ValueError):
            pass
    plan = " ".join(str(fields.get("tomorrow_plan") or "").split())
    if plan:
        changes["tomorrow_plan"] = plan[:500]
    return changes


def _iso_day(value: Any, zone: str) -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        from zoneinfo import ZoneInfo

        return dt.datetime.now(ZoneInfo(zone)).date()


def conditions_summary(changes: dict[str, Any], day: dt.date, zone: str, *, site: str | None = None) -> str:
    """"Weather: Rainy · Site working: Half day" / "Tomorrow's plan: ..." --
    from the data, with the day when it is not today."""
    from zoneinfo import ZoneInfo

    parts = []
    today = dt.datetime.now(ZoneInfo(zone)).date()
    if "weather" in changes:
        parts.append(f"Weather: {WEATHER_WORDS.get(changes['weather'], changes['weather'])}")
    if changes.get("site_working") == "none":
        # Request 132: "Site B: Holiday, no work today", naming the site (it read
        # "Site working: No work" with no site on the card).
        parts.append("Holiday, no work today" if day == today else "Holiday, no work")
    elif "site_working" in changes:
        parts.append(f"Site working: {WORKING_WORDS.get(changes['site_working'], changes['site_working'])}")
    if "hours_lost" in changes:
        hours = changes["hours_lost"]
        parts.append(f"{hours:g} h lost")
    line = " · ".join(parts)
    if "tomorrow_plan" in changes:
        plan = f"Tomorrow's plan: {changes['tomorrow_plan']}"
        line = f"{line}; {plan}" if line else plan
    if day != today:
        line += f" ({day.day} {day.strftime('%b')})"
    if site and changes.get("site_working") == "none":
        line = f"{site}: {line}"
    return line
