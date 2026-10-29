"""assert_downloadable_url — the guard against a memory:// URL reaching a browser.

Real incident: the fake object-storage adapter (local/test only, returns
`memory://...` links) got selected in a production-like deployment, and
every attendance/expense photo silently rendered as a broken image with an
`ERR_UNKNOWN_URL_SCHEME` console error and no server-side signal at all.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from mesiri.domains.shared.media import assert_downloadable_url


@pytest.mark.parametrize("url", ["https://example.com/a.jpg", "http://example.com/a.jpg"])
def test_http_and_https_urls_pass_through_unchanged(url):
    assert assert_downloadable_url(url) == url


def test_a_memory_scheme_url_raises_instead_of_reaching_the_response():
    with pytest.raises(HTTPException) as exc_info:
        assert_downloadable_url("memory://media/wamid.abc?expires_in=600&method=GET")
    assert exc_info.value.status_code == 500


# ── signed_media_url: the gallery (WEB-24) and the DPR sources panel ─────────


class _Storage:
    def __init__(self, url: str | None = None, fail: bool = False) -> None:
        self.url, self.fail, self.calls = url, fail, []

    async def generate_presigned_url(self, key: str, expires_in_seconds: int) -> str:
        self.calls.append((key, expires_in_seconds))
        if self.fail:
            raise RuntimeError("storage down")
        return self.url or f"https://cdn.example/{key}"


async def test_signed_media_url_returns_a_short_lived_link():
    from mesiri.domains.shared.media import MEDIA_URL_TTL_SECONDS, signed_media_url

    storage = _Storage()
    assert await signed_media_url(storage, "photos/a.jpg") == "https://cdn.example/photos/a.jpg"
    assert storage.calls == [("photos/a.jpg", MEDIA_URL_TTL_SECONDS)]


async def test_signed_media_url_is_none_without_a_key_or_when_storage_fails():
    from mesiri.domains.shared.media import signed_media_url

    assert await signed_media_url(_Storage(), None) is None
    assert await signed_media_url(_Storage(fail=True), "photos/a.jpg") is None
    # A memory:// link must not reach the browser: treated as unavailable.
    assert await signed_media_url(_Storage(url="memory://x"), "photos/a.jpg") is None
