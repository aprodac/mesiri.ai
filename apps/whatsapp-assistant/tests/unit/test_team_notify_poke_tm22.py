"""TM-22: Mesiri pokes the team bot's production watch when a request was just made.
Guards: no token, nothing is sent; a failure never raises."""

from __future__ import annotations

import httpx

from runtime.team_notify import TeamNotifier


async def test_the_poke_goes_to_the_listener_with_the_token() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(202, json={"ok": True})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    notifier = TeamNotifier(token="t" * 20, api="https://x/teammate", project="mesiri", client=client)
    assert await notifier.poke_watch("cor_ab") is True
    (req,) = seen
    assert str(req.url) == "https://x/teammate/watch/poke" and req.headers["authorization"] == "Bearer " + "t" * 20
    assert b'"project":"mesiri"' in req.content.replace(b" ", b"")


async def test_guard_no_token_and_failures_are_quiet() -> None:
    assert await TeamNotifier(token="").poke_watch("x") is False

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    client = httpx.AsyncClient(transport=httpx.MockTransport(boom))
    assert await TeamNotifier(token="t" * 20, api="https://x", client=client).poke_watch() is False


def test_the_servers_bot_token_is_used_when_teammate_token_is_unset(monkeypatch) -> None:
    """2 Nov: production had only MESIRI_TEAMMATE_API_TOKEN (the listener's one API token), so every poke was
    skipped in silence and requests waited for the watch's own check."""
    from runtime.team_notify import TeamNotifier

    monkeypatch.delenv("TEAMMATE_TOKEN", raising=False)
    monkeypatch.setenv("MESIRI_TEAMMATE_API_TOKEN", "bot-token")
    assert TeamNotifier().configured
    monkeypatch.setenv("TEAMMATE_TOKEN", "own-token")
    assert TeamNotifier()._token == "own-token"
    monkeypatch.delenv("TEAMMATE_TOKEN")
    monkeypatch.delenv("MESIRI_TEAMMATE_API_TOKEN")
    assert not TeamNotifier().configured
