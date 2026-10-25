"""DSH-03: a project's time zone must be an IANA name."""

import pytest
from pydantic import ValidationError

from mesiri.domains.projects.router import ProjectCreate, ProjectUpdate


@pytest.mark.parametrize("zone", ["Asia/Kolkata", "Asia/Dubai", "UTC", "Europe/London"])
def test_iana_zones_are_accepted(zone):
    assert ProjectUpdate(reportingTimezone=zone).reportingTimezone == zone
    assert ProjectCreate(name="P", reportingTimezone=zone).reportingTimezone == zone


@pytest.mark.parametrize("zone", ["IST", "India", "UTC+5:30", "", "Asia/Nowhere"])
def test_other_words_are_refused(zone):
    with pytest.raises(ValidationError):
        ProjectUpdate(reportingTimezone=zone)
    with pytest.raises(ValidationError):
        ProjectCreate(name="P", reportingTimezone=zone)


def test_an_update_without_a_zone_is_fine():
    assert ProjectUpdate(name="New name").reportingTimezone is None
