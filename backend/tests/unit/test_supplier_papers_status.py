"""PRC-52: a supplier paper's status -- valid, expiring within 15 days, expired, missing (required) or none."""

from __future__ import annotations

import datetime

from mesiri.domains.procurement.grn import needs_certificate
from mesiri.domains.vendors import documents as papers

TODAY = datetime.date(2026, 11, 11)


def _doc(days: int | None) -> dict:
    return {"valid_until": None if days is None else TODAY + datetime.timedelta(days=days)}


def test_status_by_valid_until():
    assert papers.status_of(_doc(None), True, TODAY) == ("valid", None)
    assert papers.status_of(_doc(16), True, TODAY) == ("valid", 16)
    assert papers.status_of(_doc(15), True, TODAY) == ("expiring", 15)
    assert papers.status_of(_doc(0), True, TODAY) == ("expiring", 0)
    assert papers.status_of(_doc(-1), True, TODAY) == ("expired", -1)
    assert papers.status_of(None, True, TODAY) == ("missing", None)
    assert papers.status_of(None, False, TODAY) == ("none", None)


def test_gst_and_pan_are_required_only_with_a_gstin_and_pan_is_read_from_it():
    registered = papers.describe([], gstin="32ABCDE1234F1Z5", today=TODAY, see_restricted=True)
    kinds = {k["kind"]: k for k in registered["kinds"]}
    assert (kinds["gst"]["status"], kinds["pan"]["status"], kinds["pan"]["on_record"]) == ("missing", "missing", "ABCDE1234F")
    assert registered["attention"] == "missing"
    shop = papers.describe([], gstin=None, today=TODAY, see_restricted=True)
    assert shop["attention"] == "ok" and all(k["status"] == "none" for k in shop["kinds"])


def test_restricted_kinds_are_left_out_for_roles_that_do_not_see_spending():
    kinds = papers.describe([], gstin=None, today=TODAY, see_restricted=False)["kinds"]
    assert {k["kind"] for k in kinds} == {"gst", "iso_bis", "other"}


def test_steel_cement_and_rmc_deliveries_get_the_certificate_hint():
    assert needs_certificate("TMT bar 12 mm", "Steel") and needs_certificate("RMC M25", "Concrete")
    assert needs_certificate("Cement OPC 53", "Masonry") and not needs_certificate("M-sand", "Masonry")
