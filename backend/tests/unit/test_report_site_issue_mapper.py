"""application/progress/mapper.py::build_report_site_issue_command -- pure
shape-mapping, no I/O. Mirrors the (currently untested) build_create_activity_
command/build_add_progress_update_command siblings, added alongside them.
"""

from __future__ import annotations

import datetime
import uuid

from mesiri.application.progress.mapper import build_report_site_issue_command
from mesiri_contracts.assistant.draft_action import DraftActionType
from mesiri_contracts.assistant.v2.confirmed_action import ConfirmedActionV2
from mesiri_contracts.assistant.v2.draft_action import DraftActionV2

_ORG_ID = str(uuid.uuid4())
_PROJECT_ID = str(uuid.uuid4())
_SITE_ID = str(uuid.uuid4())
_USER_ID = str(uuid.uuid4())


def _confirmed(fields: dict) -> ConfirmedActionV2:
    draft = DraftActionV2(
        draft_id="draft_1",
        correlation_id="cor_1",
        workflow_instance_id="wf_1",
        action_type=DraftActionType.RECORD_SITE_ISSUE,
        organization_id=_ORG_ID,
        user_id=_USER_ID,
        project_id=_PROJECT_ID,
        site_id=_SITE_ID,
        fields=fields,
    )
    return ConfirmedActionV2(
        confirmed_action_id="conf_1",
        workflow_instance_id="wf_1",
        correlation_id="cor_1",
        draft_action=draft,
        confirmed_by_user_id=_USER_ID,
    )


def test_maps_a_fully_populated_draft():
    confirmed = _confirmed(
        {
            "issue_type": "material_shortage",
            "severity": "high",
            "narrative": "Ran out of cement, work stopped",
            "delay_duration_minutes": "120",
            "occurred_date": "2026-07-20",
        }
    )
    cmd = build_report_site_issue_command(confirmed)
    assert cmd.organization_id == _ORG_ID
    assert cmd.project_id == _PROJECT_ID
    assert cmd.site_id == _SITE_ID
    assert cmd.issue_type == "MATERIAL_SHORTAGE"
    assert cmd.severity == "HIGH"
    assert cmd.narrative == "Ran out of cement, work stopped"
    assert cmd.delay_duration_minutes == 120
    assert cmd.occurred_date == datetime.date(2026, 7, 20)
    assert cmd.created_by == _USER_ID
    assert cmd.idempotency_key == "wf_1"


def test_defaults_issue_type_and_severity_when_missing():
    """A draft missing issue_type should never happen in practice (it's the
    one required field, per canonicalization/mapping.py's REQUIRED_FIELDS),
    but the mapper itself must not crash -- validation catches this instead."""
    cmd = build_report_site_issue_command(_confirmed({}))
    assert cmd.issue_type == "OTHER"
    assert cmd.severity == "MEDIUM"
    assert cmd.narrative is None
    assert cmd.delay_duration_minutes is None


def test_delay_duration_minutes_ignores_unparseable_values():
    cmd = build_report_site_issue_command(_confirmed({"delay_duration_minutes": "not-a-number"}))
    assert cmd.delay_duration_minutes is None


def test_delay_is_at_most_one_day_and_never_negative():
    # BE-48: "no work for 2 days" is a full day, as the dashboard allows.
    assert build_report_site_issue_command(_confirmed({"delay_duration_minutes": 2880})).delay_duration_minutes == 1440
    assert build_report_site_issue_command(_confirmed({"delay_duration_minutes": -30})).delay_duration_minutes is None
    assert build_report_site_issue_command(_confirmed({"delay_duration_minutes": 0})).delay_duration_minutes is None


def test_occurred_date_falls_back_to_today_when_absent():
    cmd = build_report_site_issue_command(_confirmed({}))
    assert cmd.occurred_date == datetime.date.today()
