"""SA-10: an owner's "continue with Mesiri" request is closed by convert / extend."""

from __future__ import annotations

import datetime as dt

from mesiri.domains.organizations import trial_notices as notices

_NOW = dt.datetime(2026, 10, 19, 12, 0, tzinfo=dt.UTC)


def test_closing_marks_open_requests_with_who_and_how():
    requests, _ = notices.add_continue_request([], user_id="u1", via="whatsapp", now=_NOW)
    closed, n = notices.close_continue_requests(requests, resolution="converted", by="Alan", now=_NOW)
    assert n == 1
    assert closed[0]["status"] == "closed"
    assert closed[0]["resolution"] == "converted"
    assert closed[0]["closed_by"] == "Alan"
    # A new request can be opened again afterwards.
    _, added = notices.add_continue_request(closed, user_id="u1", via="dashboard", now=_NOW)
    assert added


def test_nothing_open_closes_nothing():
    closed, n = notices.close_continue_requests(None, resolution="extended", by=None, now=_NOW)
    assert (closed, n) == ([], 0)
