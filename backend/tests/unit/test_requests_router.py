"""TM-19: the control panel's Requests page reads the team bot's request log server-side.
No token -> a clear 503; the token goes only in the server's request; the bot's own pseudonym
(asked_who) never reaches the page; counts per stage; platform admins only."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi import HTTPException

from mesiri.domains.admin import requests_router as rr

TOKEN = "k" * 64
ITEMS = [
    {"id": 81, "title": "Create a project from WhatsApp", "stage": "verified", "status": "done", "asked_by": "Ilan (admin, Paraclette)",
     "asked_who": "md5-pseudonym", "tried_at": "2026-11-01T16:00:00Z", "created_at": "2026-11-01T14:30:00Z"},
    {"id": 82, "title": "Report date wrong", "stage": "building", "status": "in_progress", "created_by": "Ravi via bot"},
    {"id": 83, "title": "Odd", "stage": "something-new", "status": "open"},
]


@pytest.fixture(autouse=True)
def _fresh_settings():
    from mesiri.bootstrap.settings import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class _Client:
    seen: list[dict[str, Any]] = []

    def __init__(self, *a: Any, **kw: Any) -> None:
        pass

    async def __aenter__(self) -> _Client:
        return self

    async def __aexit__(self, *a: Any) -> None:
        return None

    async def get(self, url: str, params: dict[str, str], headers: dict[str, str]) -> httpx.Response:
        _Client.seen.append({"url": url, "params": params, "headers": headers})
        if url.endswith("/items"):
            return httpx.Response(200, json={"items": ITEMS})
        if url.endswith("/items/81"):
            return httpx.Response(200, json={"item": {**ITEMS[0], "log": [{"at": "t", "status": "open", "ref": None, "note": "logged; asked by Ilan", "x": 1}]}})
        return httpx.Response(404, json={"error": "no such item"})


async def test_without_the_token_the_page_says_not_connected(monkeypatch) -> None:
    monkeypatch.delenv("MESIRI_TEAMMATE_API_TOKEN", raising=False)
    with pytest.raises(HTTPException) as off:
        await rr.list_requests(project="mesiri", _admin={})
    assert off.value.status_code == 503
    assert "not connected" in off.value.detail


async def test_the_list_counts_stages_hides_the_pseudonym_and_sends_the_token_server_side(monkeypatch) -> None:
    monkeypatch.setenv("MESIRI_TEAMMATE_API_TOKEN", TOKEN)
    monkeypatch.setattr(rr.httpx, "AsyncClient", _Client)
    _Client.seen = []
    out = await rr.list_requests(project="mesiri", _admin={})
    assert _Client.seen[0]["url"] == "http://127.0.0.1:8790/items"
    assert _Client.seen[0]["headers"] == {"authorization": f"Bearer {TOKEN}"}
    assert all("asked_who" not in i for i in out["items"])
    assert out["items"][2]["stage"] == "asked"  # an unknown stage is shown as asked, never breaks the page
    c = out["counts"]
    assert (c["total"], c["verified"], c["building"], c["asked"]) == (3, 1, 1, 1)
    assert (c["from_users"], c["shipped"], c["open"], c["tried"]) == (1, 1, 2, 1)


async def test_one_request_with_its_history_and_a_missing_one_is_404(monkeypatch) -> None:
    monkeypatch.setenv("MESIRI_TEAMMATE_API_TOKEN", TOKEN)
    monkeypatch.setattr(rr.httpx, "AsyncClient", _Client)
    one = await rr.get_request(81, project="mesiri", _admin={})
    assert one["asked_by"] == "Ilan (admin, Paraclette)"
    assert one["log"] == [{"at": "t", "status": "open", "ref": None, "note": "logged; asked by Ilan"}]
    with pytest.raises(HTTPException) as missing:
        await rr.get_request(99, project="mesiri", _admin={})
    assert missing.value.status_code == 404


async def test_the_bot_not_answering_is_a_502_with_the_reason(monkeypatch) -> None:
    monkeypatch.setenv("MESIRI_TEAMMATE_API_TOKEN", TOKEN)

    class _Down(_Client):
        async def get(self, *a: Any, **kw: Any) -> httpx.Response:
            raise httpx.ConnectError("refused")

    monkeypatch.setattr(rr.httpx, "AsyncClient", _Down)
    with pytest.raises(HTTPException) as down:
        await rr.list_requests(project="mesiri", _admin={})
    assert down.value.status_code == 502 and "ConnectError" in down.value.detail


def test_every_route_is_platform_admin_only() -> None:
    for route in rr.router.routes:
        deps = [d.call for d in route.dependant.dependencies]
        assert rr.require_platform_admin in deps, route.path
