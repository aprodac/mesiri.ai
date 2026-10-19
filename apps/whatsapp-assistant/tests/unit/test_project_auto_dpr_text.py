"""Request [58]: the line that goes with a project DPR names a site whose
updates are saved but not confirmed, instead of calling it "not reported"."""

from __future__ import annotations

import datetime

from runtime.project_auto_dpr import _send_message, _template_params


def _payload(*, reported: int, sites: list[tuple[str, bool]]) -> dict:
    return {
        "level": "PROJECT",
        "total_site_count": len(sites),
        "reported_site_count": reported,
        "sites": [{"site_name": n, "reported": r} for n, r in sites],
    }


def test_unconfirmed_site_is_named_with_its_updates():
    msg = _send_message(
        code="DPR-P-1",
        payload=_payload(reported=0, sites=[("Green Villa, Kakkanad", False)]),
        reason="deadline",
        unconfirmed={"Green Villa, Kakkanad": 3},
    )
    assert msg == "Today's DPR (DPR-P-1) is attached. Green Villa, Kakkanad: 3 updates, not confirmed yet."
    assert "not reported" not in msg


def test_a_site_with_nothing_saved_is_still_not_reported():
    msg = _send_message(
        code="DPR-P-1",
        payload=_payload(reported=1, sites=[("A", True), ("B", False), ("C", False)]),
        reason="deadline",
        unconfirmed={"B": 1},
    )
    assert msg == (
        "Today's DPR (DPR-P-1) is attached. B: 1 update, not confirmed yet. 1 of 3 site not reported."
    )


def test_without_the_detail_the_old_line_stands():
    msg = _send_message(
        code="DPR-P-1",
        payload=_payload(reported=0, sites=[("A", False)]),
        reason="requested",
    )
    assert msg == "Today's DPR (DPR-P-1) is attached. 1 of 1 site not reported. Sent on request."


def test_template_status_line_uses_the_same_wording():
    params = _template_params(
        code="DPR-P-1",
        payload=_payload(reported=0, sites=[("A", False)]),
        reason="deadline",
        report_date=datetime.date(2026, 10, 19),
        unconfirmed={"A": 2},
    )
    assert params[2] == "A: 2 updates, not confirmed yet."
