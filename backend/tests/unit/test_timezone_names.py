"""V1 audit DSH-03: a time zone the tz database doesn't know is never saved
(it was read as UTC, so the 6 PM check came at 11:30 PM)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mesiri.domains.automations.router import AutomationUpdateRequest
from mesiri.domains.organizations.router import CompanyUpdate
from mesiri.domains.projects.router import ProjectCreate, ProjectUpdate
from mesiri.domains.shared.timezones import normalize_timezone


@pytest.mark.parametrize(
    "said", ["IST", "ist", "India", "Indian Standard Time", "UTC+5:30", "+05:30", "Asia/Calcutta", " Asia/Kolkata "]
)
def test_the_words_indian_sites_type_mean_asia_kolkata(said):
    assert normalize_timezone(said) == "Asia/Kolkata"


@pytest.mark.parametrize("name", ["UTC", "Asia/Dubai", "Europe/London"])
def test_real_zone_names_are_kept(name):
    assert normalize_timezone(name) == name


@pytest.mark.parametrize("bad", ["", "Kerala", "UTC+99", "Asia/Nowhere", "asia/dubai"])
def test_anything_else_is_refused(bad):
    with pytest.raises(ValueError, match="Unknown time zone"):
        normalize_timezone(bad)


def test_the_api_models_normalise_or_refuse():
    assert ProjectCreate(name="P", reportingTimezone="IST").reportingTimezone == "Asia/Kolkata"
    assert ProjectUpdate(reportingTimezone="India").reportingTimezone == "Asia/Kolkata"
    assert ProjectUpdate().reportingTimezone is None
    assert CompanyUpdate(timezone="IST").timezone == "Asia/Kolkata"
    with pytest.raises(ValidationError):
        ProjectUpdate(reportingTimezone="Kerala")
    with pytest.raises(ValidationError):
        CompanyUpdate(timezone="Kerala")
    assert AutomationUpdateRequest(timezone="IST").timezone == "Asia/Kolkata"
    with pytest.raises(ValidationError):
        AutomationUpdateRequest(timezone="Kerala")
