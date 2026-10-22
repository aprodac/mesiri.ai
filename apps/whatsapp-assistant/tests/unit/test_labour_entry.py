"""ARCH-03: labour attendance from the agent without the classic pipeline
(Alan's approval, 22 Oct). The lines come from the pipeline's own normaliser;
the worker roster and the day's existing report are seeded as before."""

from __future__ import annotations

import datetime
from typing import Any
from zoneinfo import ZoneInfo

from tests.unit.test_material_entry import (
    MESSAGE,
    ORG,
    PRJ,
    SITE,
    _actor,
    _Context,
    _Modules,
    _Understanding,
)

from mesiri_contracts.assistant.candidates import Candidate
from mesiri_contracts.assistant.canonical_event import CanonicalEventType
from mesiri_contracts.assistant.enums import SemanticType
from mesiri_contracts.assistant.planner_decision import WorkflowKey
from runtime.agent.entry_base import Ready, Say
from runtime.agent.labour_entry import LabourEntry
from runtime.workforce_query import StubWorkforceQueryService


def _entry(*, modules=None, workforce=None, context=None) -> LabourEntry:
    actor = _actor(SITE)
    actor.organization_id = ORG
    return LabourEntry(context_resolver=context or _Context(), org_settings_query=modules, actor=actor, workforce_query=workforce)


async def _prepare(entry: LabourEntry, **fields: Any):
    candidate = Candidate(semantic_type=SemanticType.LABOUR_UPDATE, fields=fields)
    return await entry.prepare(MESSAGE, _Understanding(candidate), candidate)


def _today() -> str:
    return datetime.datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()


async def test_trades_and_counts_become_the_attendance_lines():
    ready = await _prepare(
        _entry(), workers=[{"trade": "mason", "headcount": 6}, {"trade": "helper", "headcount": 12}], contractor="Sree"
    )
    assert isinstance(ready, Ready)
    assert ready.decision.workflow_key is WorkflowKey.LABOUR_ATTENDANCE
    assert ready.event.event_type is CanonicalEventType.LABOUR_ATTENDANCE_REQUESTED
    lines = ready.event.fields["lines"]
    assert [(line["trade"], line["headcount"], line["contractor"]) for line in lines] == [
        ("mason", 6, "Sree"),
        ("helper", 12, "Sree"),
    ]
    assert ready.event.fields["recorded_via"] == "whatsapp_text"
    assert ready.event.fields["occurred_date"] == _today()
    assert (str(ready.event.project_id), str(ready.event.site_id)) == (PRJ, SITE)


async def test_nobody_named_or_counted_is_not_saved():
    said = await _prepare(_entry(), workers=[])
    assert isinstance(said, Say) and said.status == "error"


async def test_labour_switched_off_is_said_not_saved():
    said = await _prepare(_entry(modules=_Modules(["dpr"])), workers=[{"trade": "mason", "headcount": 6}])
    assert isinstance(said, Say) and said.status == "info"


async def test_the_roster_and_the_days_existing_report_are_seeded():
    """BE-10: the day's existing report becomes the snapshot the save compares
    against; a named worker gets the roster to be matched to."""
    workforce = StubWorkforceQueryService(
        roster=[{"worker_id": "w1", "name": "Ravi", "trade": "mason"}],
        existing_reports={f"{PRJ}|{SITE}|{_today()}": {"report_id": "r1", "counted_lines": [{"trade": "mason", "headcount": 4}]}},
    )
    ready = await _prepare(_entry(workforce=workforce), workers=[{"name": "Ravi", "trade": "mason"}])
    fields = ready.event.fields
    assert fields["worker_candidates"][0]["name"] == "Ravi"
    assert fields["day_counted_lines"] == [{"trade": "mason", "headcount": 4}]


async def test_an_attendance_register_photo_is_attached_and_recorded_as_a_photo():
    """ARCH-06: an entry read from a photo carries the photo, as the pipeline did."""
    from types import SimpleNamespace

    from mesiri_contracts.assistant.enums import InputModality
    from mesiri_contracts.assistant.normalized_message import MediaReference

    photo = SimpleNamespace(
        **vars(MESSAGE), modality=InputModality.IMAGE, media=MediaReference(object_key="media/register.jpg")
    )
    candidate = Candidate(semantic_type=SemanticType.LABOUR_UPDATE, fields={"workers": [{"trade": "mason", "headcount": 6}]})
    ready = await _entry().prepare(photo, _Understanding(candidate), candidate)
    assert isinstance(ready, Ready)
    assert ready.event.fields["media_object_key"] == "media/register.jpg"
    assert ready.event.fields["recorded_via"] == "whatsapp_image"
