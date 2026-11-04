"""Request 230: a person sees only their own requests to Mesiri, once each, open first, with nothing technical.
The caller is matched through the message log (their own WhatsApp number, their own company), never by name."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from mesiri.domains.admin import my_requests_router as rr
from mesiri.domains.admin import requests_router as admin_rr

ME, ORG = uuid.uuid4(), uuid.uuid4()
OTHER, OTHER_ORG = uuid.uuid4(), uuid.uuid4()
ITEMS = [
    {"id": 1, "title": "Show my complaints", "stage": "building", "asked_by": "Ilan (admin, Paraclette)", "asked_ref": "cor_a", "created_at": "2026-11-04T08:00:00Z", "done_ref": "abc123"},
    {"id": 2, "title": "Report date wrong", "stage": "verified", "asked_by": "Ilan (admin, Paraclette)", "asked_ref": "cor_b,cor_c", "created_at": "2026-11-02T08:00:00Z", "live_at": "2026-11-03T08:00:00Z"},
    {"id": 3, "title": "  [bot upgrade]  Show my  complaints ", "stage": "asked", "asked_by": "Ilan (admin, Paraclette)", "asked_ref": "cor_d", "created_at": "2026-11-04T09:00:00Z"},
    {"id": 4, "title": "Someone else's wish", "stage": "live", "asked_by": "Ravi (engineer, Acme)", "asked_ref": "cor_z", "created_at": "2026-11-01T08:00:00Z", "live_at": "2026-11-02T08:00:00Z"},
    {"id": 5, "title": "Old idea", "stage": "dropped", "asked_by": "Ilan (admin, Paraclette)", "asked_ref": "cor_e", "created_at": "2026-10-30T08:00:00Z"},
    {"id": 6, "title": "Team-only task", "stage": "building", "created_by": "Alan"},
]
# message log: which correlation ids belong to which (user, company)
LOG = {("cor_a", ME, ORG), ("cor_b", ME, ORG), ("cor_d", ME, ORG), ("cor_e", ME, ORG), ("cor_z", OTHER, OTHER_ORG)}


class _Conn:
    async def execute(self, _sql: Any, params: dict[str, Any]) -> Any:
        rows = [SimpleNamespace(correlation_id=c) for c, u, o in LOG if u == params["uid"] and o == params["org"] and c in params["cids"]]
        return SimpleNamespace(all=lambda: rows)


@pytest.fixture(autouse=True)
def _items(monkeypatch):
    async def fake(project: str) -> list[dict[str, Any]]:
        return [admin_rr._public(i) for i in ITEMS]

    monkeypatch.setattr(rr, "_all_items", fake)


async def _call(uid: uuid.UUID, org: Any) -> list[dict[str, Any]]:
    return (await rr.my_requests(project="mesiri", conn=_Conn(), user={"sub": str(uid), "org": str(org)}))["items"]  # type: ignore[arg-type]


async def test_only_my_requests_once_each_open_first() -> None:
    items = await _call(ME, ORG)
    assert [(i["title"], i["stage"]) for i in items] == [
        ("Show my complaints", "asked"),  # the same complaint sent twice is one line (the newer one)
        ("Report date wrong", "live"),
        ("Old idea", "dropped"),
    ]
    assert items[1]["live_at"] == "2026-11-03T08:00:00Z"
    assert items[0]["live_at"] is None


async def test_nothing_technical_or_anyone_elses_leaks() -> None:
    items = await _call(ME, ORG)
    assert all(set(i) == {"title", "stage", "live_at", "created_at"} for i in items)
    text = str(items)
    assert "abc123" not in text and "Ravi" not in text and "Someone else" not in text and "asked_ref" not in text


async def test_other_person_other_company_sees_only_theirs() -> None:
    assert [i["title"] for i in await _call(OTHER, OTHER_ORG)] == ["Someone else's wish"]
    # my message ids asked under someone else's company/user match nothing
    assert await _call(OTHER, ORG) == []
    assert await _call(ME, OTHER_ORG) == []


async def test_nobody_who_never_asked_gets_an_empty_list() -> None:
    assert await _call(uuid.uuid4(), ORG) == []


async def test_platform_admin_without_a_company_gets_an_empty_list() -> None:
    assert (await rr.my_requests(project="mesiri", conn=_Conn(), user={"sub": str(ME), "org": ""}))["items"] == []  # type: ignore[arg-type]
