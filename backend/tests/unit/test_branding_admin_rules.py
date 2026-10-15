"""SA-09: the control panel's branding-request rules (no database)."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest

from mesiri.application.organizations.branding_admin import (
    BrandingAdminError,
    mark_done,
    request_items,
    sort_for_team,
    validate_contact,
)
from mesiri.domains.organizations import setup_questions

_NOW = dt.datetime(2026, 10, 15, 12, 0, tzinfo=dt.UTC)
_ORG = uuid.uuid4()


def _requests(*files_per_request: int) -> list[dict]:
    requests: list = []
    for n, count in enumerate(files_per_request):
        for i in range(count):
            requests, _ = setup_questions.add_branding_files(
                requests,
                object_key=f"k/{n}/{i}.jpg",
                content_type="image/jpeg",
                sent_by="owner",
                now=_NOW + dt.timedelta(minutes=n),
            )
        if requests and n < len(files_per_request) - 1:
            # Earlier requests: finished and already announced to the owner.
            requests[-1]["status"] = setup_questions.DONE
            requests[-1]["owner_notified"] = True
    return requests


def test_items_carry_company_and_file_count() -> None:
    [item] = request_items(_ORG, "Skyline", _requests(3))
    assert item.organization_name == "Skyline"
    assert item.status == "open"
    assert item.file_count == 3
    assert item.owner_notified is False


def test_malformed_entries_are_skipped() -> None:
    stored = [None, "x", {"status": "open"}, *_requests(1)]
    assert len(request_items(_ORG, "S", stored)) == 1
    assert request_items(_ORG, "S", {"not": "a list"}) == []


def test_open_first_oldest_first_then_done_newest_first() -> None:
    def item(rid: str, status: str, created: str, done: str | None = None):
        return request_items(
            _ORG,
            "S",
            [{"id": rid, "status": status, "created_at": created, "done_at": done, "files": []}],
        )[0]

    ordered = sort_for_team(
        [
            item("done-old", "done", "2026-10-01", "2026-10-02"),
            item("open-new", "open", "2026-10-14"),
            item("done-new", "done", "2026-10-05", "2026-10-09"),
            item("open-old", "open", "2026-10-10"),
        ]
    )
    assert [i.id for i in ordered] == ["open-old", "open-new", "done-new", "done-old"]


def test_mark_done_sets_status_and_date_only_on_that_request() -> None:
    requests = _requests(1, 2)  # an older done one, then an open one
    open_id = requests[-1]["id"]

    after = mark_done(requests, open_id, _NOW)

    assert after[-1]["status"] == "done"
    assert after[-1]["done_at"] == _NOW.isoformat()
    assert after[-1]["owner_notified"] is False
    assert after[0] == requests[0]
    # The assistant's announcement picks it up next.
    assert setup_questions.request_to_announce(after)["id"] == open_id


def test_mark_done_refuses_unknown_and_already_done() -> None:
    requests = _requests(1, 1)
    with pytest.raises(BrandingAdminError) as missing:
        mark_done(requests, "nope", _NOW)
    assert missing.value.status_code == 404
    with pytest.raises(BrandingAdminError) as done:
        mark_done(requests, requests[0]["id"], _NOW)
    assert done.value.status_code == 409


def test_contact_fields_are_trimmed_and_others_ignored() -> None:
    assert validate_contact(
        {"address": "  12  MG Road ", "phone": "", "gstin": "x", "email": None}
    ) == {"address": "12 MG Road", "phone": None, "email": None}
    assert validate_contact({"gstin": "x"}) == {}


@pytest.mark.parametrize("update", [{"phone": 98765}, {"address": "x" * 301}, ["address"]])
def test_bad_contact_fields_are_refused(update) -> None:
    with pytest.raises(BrandingAdminError):
        validate_contact(update)
