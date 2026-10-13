"""BE-07: organization status is stored lowercase but must still read the
capitalised spelling written before migration 0463 (or by an older build
after a rollback) instead of failing validation in API responses."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from mesiri.infrastructure.postgres.models.organization import OrganizationStatus


class _Response(BaseModel):
    status: OrganizationStatus


def test_values_are_lowercase():
    assert OrganizationStatus.ACTIVE.value == "active"
    assert OrganizationStatus.SUSPENDED.value == "suspended"


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        ("active", OrganizationStatus.ACTIVE),
        ("Active", OrganizationStatus.ACTIVE),
        (" ACTIVE ", OrganizationStatus.ACTIVE),
        ("Suspended", OrganizationStatus.SUSPENDED),
    ],
)
def test_any_casing_reads_back(stored: str, expected: OrganizationStatus):
    assert OrganizationStatus(stored) is expected
    assert _Response(status=stored).status is expected


def test_unknown_value_still_rejected():
    with pytest.raises(ValueError):
        OrganizationStatus("archived")
