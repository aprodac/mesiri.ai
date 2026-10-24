"""domains/progress/validation.py::validate_report_site_issue -- pure
function, no I/O. Mirrors validate_create_activity/validate_add_progress_
update's test-free precedent (this domain has no existing unit test file for
its confirmed-command validation), added as this feature's own coverage.
"""

from __future__ import annotations

import datetime
import uuid

from mesiri.domains.progress.validation import validate_report_site_issue
from mesiri_contracts.application.commands.progress import ReportSiteIssueCommand

_ORG_ID = str(uuid.uuid4())
_PROJECT_ID = str(uuid.uuid4())
_SITE_ID = str(uuid.uuid4())
_USER_ID = str(uuid.uuid4())


def _command(**overrides) -> ReportSiteIssueCommand:
    fields = {
        "command_id": "cmd_1",
        "idempotency_key": "wf_1",
        "correlation_id": "cor_1",
        "organization_id": _ORG_ID,
        "project_id": _PROJECT_ID,
        "site_id": _SITE_ID,
        "issue_type": "MATERIAL_SHORTAGE",
        "severity": "HIGH",
        "occurred_date": datetime.date(2026, 7, 20),
        "created_by": _USER_ID,
    }
    fields.update(overrides)
    return ReportSiteIssueCommand(**fields)


def test_valid_command_has_no_violations():
    assert validate_report_site_issue(_command()) == []


def test_rejects_missing_project():
    reasons = validate_report_site_issue(_command(project_id=None))
    assert reasons == ["project is not resolved"]


def test_rejects_unrecognized_issue_type():
    reasons = validate_report_site_issue(_command(issue_type="ALIEN_INVASION"))
    assert reasons == ["unrecognized issue_type: ALIEN_INVASION"]


def test_rejects_unrecognized_severity():
    reasons = validate_report_site_issue(_command(severity="APOCALYPTIC"))
    assert reasons == ["unrecognized severity: APOCALYPTIC"]


def test_accepts_every_real_issue_type_and_severity():
    for issue_type in (
        "WEATHER",
        "MATERIAL_SHORTAGE",
        "LABOUR_SHORTAGE",
        "DRAWING_PENDING",
        "EQUIPMENT_BREAKDOWN",
        "INSPECTION_WAITING",
        "ACCESS",
        "SAFETY",
        "QUALITY",
        "OTHER",
    ):
        assert validate_report_site_issue(_command(issue_type=issue_type)) == []
    for severity in ("LOW", "MEDIUM", "HIGH", "CRITICAL"):
        assert validate_report_site_issue(_command(severity=severity)) == []
