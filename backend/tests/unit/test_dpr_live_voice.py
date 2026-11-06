"""WEB-63: Mesiri's voice on Live (GET /dpr/live/voice): the voice follows the line's script, a line is spoken once
and then comes from the cache, and Live stays silent (a clear error, never a crash) with no key or with Sarvam down."""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from mesiri.authorization.context import AccessPolicy, AuthorizationContext, ProjectAccessScope
from mesiri.domains.dpr import router as dpr_router

ME = AuthorizationContext(
    user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role="SITE_ENGINEER", status="active",
    access_policy=AccessPolicy(mode="all_projects", projects=[]),
    project_scope=ProjectAccessScope(mode="all_projects", project_ids=set()), site_scopes={},
)


class _Voice:
    def __init__(self, configured: bool = True, broken: bool = False) -> None:
        self.configured = configured
        self.broken = broken
        self.said: list[tuple[str, str]] = []

    async def speak(self, text: str, language: str) -> bytes:
        if self.broken:
            raise RuntimeError("sarvam down")
        self.said.append((language, text))
        return b"RIFF" + text.encode()


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    dpr_router._voice_cache.clear()
    voice = _Voice()
    monkeypatch.setattr(dpr_router, "_voice", voice)
    return voice


@pytest.mark.parametrize(
    ("text", "language"),
    [
        ("Saved: 50 bags of cement.", "en-IN"),
        ("Tower A-ൽ ഇപ്പോൾ 210 ചാക്ക് Cement ഉണ്ട്.", "ml-IN"),
        ("आज का अपडेट भेजिए", "hi-IN"),
        ("Innu 8 mason, 4 helper", "en-IN"),  # Manglish is read in English letters
    ],
)
def test_the_voice_follows_the_script(text, language):
    assert dpr_router.voice_language(text) == language


async def test_a_line_is_spoken_once_then_cached(_fresh):
    first = await dpr_router.live_voice("Saved:  50 bags of cement.", _auth=ME, settings=None)
    again = await dpr_router.live_voice("Saved: 50 bags of cement.", _auth=ME, settings=None)
    assert first.body == again.body and first.media_type == "audio/wav"
    assert _fresh.said == [("en-IN", "Saved: 50 bags of cement.")]
    assert "max-age" in first.headers["cache-control"]


async def test_no_key_is_a_clear_503(monkeypatch):
    monkeypatch.setattr(dpr_router, "_voice", _Voice(configured=False))
    with pytest.raises(HTTPException) as exc:
        await dpr_router.live_voice("Hello", _auth=ME, settings=None)
    assert exc.value.status_code == 503


async def test_sarvam_down_is_a_502_and_nothing_is_cached(monkeypatch):
    monkeypatch.setattr(dpr_router, "_voice", _Voice(broken=True))
    with pytest.raises(HTTPException) as exc:
        await dpr_router.live_voice("Hello", _auth=ME, settings=None)
    assert exc.value.status_code == 502 and not dpr_router._voice_cache


async def test_blank_says_nothing():
    with pytest.raises(HTTPException) as exc:
        await dpr_router.live_voice("   ", _auth=ME, settings=None)
    assert exc.value.status_code == 422
