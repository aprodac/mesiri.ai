"""WA-246 (Ilan, 5 Nov 2026): the control panel sets a person's own "show what was heard" switch on a voice note's
reply: "on", "off", or "company" (NULL: follow the company's voice_transcript setting, off by default)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from tests.unit.test_whatsapp_number_taken_routes import _Conn, _Engine

from admin import router as admin_router

_ORG, _USER = uuid.uuid4(), uuid.uuid4()


@pytest.mark.parametrize(("choice", "stored"), [("on", True), ("off", False), ("company", None)])
async def test_the_persons_switch_is_stored(monkeypatch, choice, stored) -> None:  # noqa: ANN001
    row = SimpleNamespace(id=_USER, role="SITE_ENGINEER", whatsapp_number=None, full_name="A", voice_transcript=None)
    conn = _Conn([[row], []])
    audits: list = []

    async def record(_conn, **kwargs):  # noqa: ANN001, ANN003, ANN202
        audits.append(kwargs)

    async def fetched(_conn, org_id, user_id=None):  # noqa: ANN001, ANN202
        return [admin_router.OrgUserResponse(id=user_id, voice_transcript=stored)]

    monkeypatch.setattr(admin_router, "get_engine", lambda: _Engine(conn))
    monkeypatch.setattr(admin_router, "record_admin_action", record)
    monkeypatch.setattr(admin_router, "_fetch_org_users", fetched)

    out = await admin_router.update_organization_user_profile(
        _ORG, _USER, admin_router.OrgUserProfileUpdate(voice_transcript=choice), _admin={})

    update = conn.executed[-1].compile().params
    assert update["voice_transcript"] is stored
    assert audits[0]["details"]["after"] == {"voice_transcript": stored}
    assert out.voice_transcript is stored


def test_an_unknown_choice_is_refused() -> None:
    with pytest.raises(ValueError):
        admin_router.OrgUserProfileUpdate(voice_transcript="maybe")
