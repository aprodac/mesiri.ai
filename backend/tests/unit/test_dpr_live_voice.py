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
        self.codecs: list[str | None] = []

    async def speak(self, text: str, language: str, codec: str | None = None) -> bytes:
        if self.broken:
            raise RuntimeError("sarvam down")
        self.said.append((language, text))
        self.codecs.append(codec)
        return (b"ID3" if codec == "mp3" else b"RIFF") + text.encode()


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    dpr_router._voice_cache.clear()
    voice = _Voice()
    monkeypatch.setattr(dpr_router, "_voices", {"live": voice, "guide": voice})
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
    monkeypatch.setattr(dpr_router, "_voices", {"live": _Voice(configured=False)})
    with pytest.raises(HTTPException) as exc:
        await dpr_router.live_voice("Hello", _auth=ME, settings=None)
    assert exc.value.status_code == 503


async def test_sarvam_down_is_a_502_and_nothing_is_cached(monkeypatch):
    monkeypatch.setattr(dpr_router, "_voices", {"live": _Voice(broken=True)})
    with pytest.raises(HTTPException) as exc:
        await dpr_router.live_voice("Hello", _auth=ME, settings=None)
    assert exc.value.status_code == 502 and not dpr_router._voice_cache


async def test_blank_says_nothing():
    with pytest.raises(HTTPException) as exc:
        await dpr_router.live_voice("   ", _auth=ME, settings=None)
    assert exc.value.status_code == 422


# -- SS-61: the walkthroughs' narrator ----------------------------------------------------------------------------------

STEP = ("The material plan. What each material is needed for, week by week from the schedule, against stock and what "
        "is on order. Red weeks run short; Order opens a purchase order already filled in.")


async def test_a_walkthrough_step_is_read_by_the_narrator_as_mp3_and_cached_apart_from_live(_fresh):
    guide = await dpr_router.live_voice(STEP, voice_name="guide", _auth=ME, settings=None)
    again = await dpr_router.live_voice(STEP, voice_name="guide", _auth=ME, settings=None)
    assert guide.media_type == "audio/mpeg" and guide.body.startswith(b"ID3") and again.body == guide.body
    assert _fresh.codecs == ["mp3"]  # spoken once
    live = await dpr_router.live_voice("Saved.", _auth=ME, settings=None)
    assert live.media_type == "audio/wav" and _fresh.codecs == ["mp3", None]  # Live is unchanged


async def test_a_step_may_be_longer_than_a_live_line(_fresh):
    long_step = STEP + " " + STEP
    assert len(long_step) > dpr_router.VOICE_MAX_CHARS
    assert (await dpr_router.live_voice(long_step, voice_name="guide", _auth=ME, settings=None)).status_code == 200
    with pytest.raises(HTTPException) as exc:
        await dpr_router.live_voice(long_step, voice_name="live", _auth=ME, settings=None)
    assert exc.value.status_code == 422


def test_the_narrator_is_its_own_voice_from_the_settings(monkeypatch):
    from types import SimpleNamespace

    from mesiri.bootstrap.settings import SarvamSettings

    assert SarvamSettings().guide_tts_speaker == "shubh"  # chosen 16 Nov: Indian English, male (bulbul:v3's default)
    monkeypatch.setattr(dpr_router, "_voices", {})
    sarvam = SimpleNamespace(api_key=None, guide_tts_speaker="rahul", tts_speaker="priya", tts_model="bulbul:v3")
    settings = SimpleNamespace(sarvam=sarvam)
    assert dpr_router._voice_for(settings, "guide")._speaker == "rahul"
    assert dpr_router._voice_for(settings, "live")._speaker == "priya"
