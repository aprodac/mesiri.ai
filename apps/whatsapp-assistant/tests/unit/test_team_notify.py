"""SS-14: posting to the Mesiri team's WhatsApp group through the teammate listener."""

from __future__ import annotations

import json

import httpx

from runtime.team_notify import TeamNotifier


def _client(chats, sent):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer t0k"
        if request.url.path.endswith("/chats"):
            assert request.url.params["project"] == "mesiri"
            return httpx.Response(200, json={"chats": chats})
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"chat": "team@g.us"})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


TEAM = {"jid": "team@g.us", "role": "team", "project": "mesiri"}


async def test_posts_text_then_images_to_the_team_chat() -> None:
    sent: list = []
    notifier = TeamNotifier(token="t0k", api="https://x/teammate", client=_client([TEAM], sent))
    assert await notifier.post("hello", images=[(b"img", "Acme")]) is True
    assert sent[0] == {"chat": "team@g.us", "project": "mesiri", "text": "hello"}
    assert sent[1]["caption"] == "Acme" and sent[1]["image_base64"] == "aW1n"


async def test_customer_chats_are_never_used() -> None:
    sent: list = []
    chats = [{"jid": "cust@g.us", "role": "customer", "project": "mesiri"}]
    notifier = TeamNotifier(token="t0k", api="https://x/teammate", client=_client(chats, sent))
    assert await notifier.post("hello") is False
    assert sent == []


async def test_without_a_token_nothing_is_sent() -> None:
    notifier = TeamNotifier(token="", api="https://x/teammate")
    assert notifier.configured is False
    assert await notifier.post("hello") is False


async def test_listener_errors_never_raise() -> None:
    def handler(request):
        return httpx.Response(500)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    notifier = TeamNotifier(token="t0k", api="https://x/teammate", client=client)
    assert await notifier.post("hello") is False
