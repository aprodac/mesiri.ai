"""SS-05: the join code and join request rules (pure)."""

from __future__ import annotations

import datetime as dt

import pytest

from mesiri.domains.organizations import team_join as rules

NOW = dt.datetime(2026, 10, 19, 9, 0, tzinfo=dt.UTC)


def test_code_prefix_comes_from_the_company_name() -> None:
    assert rules.code_prefix("Acme Builders") == "ACME"
    assert rules.code_prefix("Sri Sai Constructions") == "SRI"
    assert rules.code_prefix("Mahalakshmi Infra") == "MAHALA"
    assert rules.code_prefix("A1 Builders") == "BUILDE"  # "A1" has one letter
    assert rules.code_prefix("123") == "TEAM"


def test_new_codes_have_the_shape_and_vary() -> None:
    codes = {rules.new_code("Acme Builders") for _ in range(50)}
    assert all(rules.normalize_code(c) == c and c.startswith("ACME-") for c in codes)
    assert len(codes) > 40


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("JOIN ACME-4821", "ACME-4821"),
        ("join acme 4821", "ACME-4821"),
        ("  Join: ACME-4821 ", "ACME-4821"),
        ("JOIN ACME4821", "ACME-4821"),
        ("join the team", None),
        ("ACME-4821", None),
        ("JOIN ACME-482", None),
        ("please join ACME-4821", None),
    ],
)
def test_code_in_message(text: str, code: str | None) -> None:
    assert rules.code_in_message(text) == code


def test_a_second_ask_while_open_returns_the_same_request() -> None:
    stored, first, new = rules.add_request([], phone="919876500001", name="Ravi", now=NOW)
    assert new and first["status"] == rules.OPEN
    stored, again, new = rules.add_request(
        stored, phone="919876500001", name="Ravi K", now=NOW + dt.timedelta(hours=1)
    )
    assert not new and again["id"] == first["id"] and len(stored) == 1


def test_an_expired_request_lets_them_ask_again() -> None:
    stored, first, _ = rules.add_request([], phone="919876500001", name="Ravi", now=NOW)
    later = NOW + dt.timedelta(days=rules.OPEN_FOR_DAYS)
    _, second, new = rules.add_request(stored, phone="919876500001", name="Ravi", now=later)
    assert new and second["id"] != first["id"]


def test_a_company_holds_at_most_max_open_requests() -> None:
    stored: list = []
    for i in range(rules.MAX_OPEN):
        stored, _, _ = rules.add_request(stored, phone=f"9198765{i:05d}", name="X", now=NOW)
    with pytest.raises(rules.TooManyRequests):
        rules.add_request(stored, phone="919999999999", name="Y", now=NOW)


def test_decide_once_only() -> None:
    stored, request, _ = rules.add_request([], phone="919876500001", name="Ravi", now=NOW)
    stored, decided_request, decided = rules.decide(
        stored, request_id=request["id"], approve=True, by="admin-1", now=NOW
    )
    assert decided and decided_request["status"] == rules.APPROVED
    assert decided_request["decided_by"] == "admin-1"
    # A second admin tapping Reject afterwards changes nothing.
    stored, again, decided = rules.decide(
        stored, request_id=request["id"], approve=False, by="admin-2", now=NOW
    )
    assert not decided and again["status"] == rules.APPROVED
    _, missing, decided = rules.decide(
        stored, request_id="nope", approve=True, by="admin-1", now=NOW
    )
    assert missing is None and not decided


def test_an_expired_request_cannot_be_approved() -> None:
    stored, request, _ = rules.add_request([], phone="919876500001", name="Ravi", now=NOW)
    later = NOW + dt.timedelta(days=rules.OPEN_FOR_DAYS, minutes=1)
    _, same, decided = rules.decide(
        stored, request_id=request["id"], approve=True, by="admin-1", now=later
    )
    assert not decided and same["status"] == rules.OPEN


# -- WEB-71: an approved request's steps, for the company's Live screen -----------


def _approved():
    requests, request, _ = rules.add_request([], phone="919800000001", name="Ravi", now=NOW)
    requests, _, _ = rules.decide(requests, request_id=request["id"], approve=True, by="admin", now=NOW)
    return requests, request["id"]


def test_steps_are_noted_on_an_approved_request() -> None:
    requests, rid = _approved()
    requests, changed = rules.note_step(requests, request_id=rid, role="SITE_ENGINEER")
    assert changed and requests[-1]["role"] == "SITE_ENGINEER" and requests[-1]["status"] == rules.APPROVED
    later = NOW + dt.timedelta(minutes=1)
    requests, changed = rules.note_step(requests, request_id=rid, project="Skyline", joined_at=later)
    assert changed
    assert requests[-1]["status"] == rules.JOINED
    assert requests[-1]["project"] == "Skyline" and requests[-1]["joined_at"] == later.isoformat()


def test_an_open_or_unknown_request_takes_no_steps() -> None:
    requests, request, _ = rules.add_request([], phone="919800000001", name="Ravi", now=NOW)
    assert rules.note_step(requests, request_id=request["id"], role="ADMIN")[1] is False
    assert rules.note_step(requests, request_id="nope", role="ADMIN")[1] is False


def test_recent_is_the_last_day_only() -> None:
    old, _, _ = rules.add_request([], phone="919800000001", name="Old", now=NOW - dt.timedelta(hours=30))
    both, _, _ = rules.add_request(old, phone="919800000002", name="New", now=NOW)
    assert [r["name"] for r in rules.recent(both, now=NOW)] == ["New"]
