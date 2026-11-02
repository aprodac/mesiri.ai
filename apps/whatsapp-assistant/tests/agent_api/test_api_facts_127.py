"""WA-127: v3 starts with what people call each material and what is already recorded today.

- GET /materials lists each material's aliases; v3 shows them ("also called: kambi");
- today's timeline (newest 40, shown oldest first) is in the instructions, so "did anyone report X"
  needs no lookup and a repeated delivery can be pointed out;
- nothing recorded yet is said plainly; a timeline the API cannot give leaves the section out.
"""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import Depends, FastAPI
from tests.agent_api.standin import BAG, ORG, PROJECT, SITE, STAND_IN_TOOLS, USER, stand_in_api

from agent_api import whatsapp as wa
from mesiri.domains.shared.auth import get_current_user
from mesiri.infrastructure.redis.client import FakeRedis
from mesiri_ai.fakes import FakeToolCallingProvider
from mesiri_contracts.assistant.enums import InputModality
from mesiri_contracts.assistant.normalized_message import NormalizedMessage, SenderInfo

STEEL = str(uuid.uuid4())
CTX = SimpleNamespace(user_id=USER, organization_id=ORG, role="SITE_SUPERVISOR", full_name="Ravi",
                      timezone="Asia/Kolkata", projects=[SimpleNamespace(id=PROJECT, name="Green Villa")],
                      sites=[SimpleNamespace(id=SITE, name="Main block", project_id=PROJECT)])


@pytest.fixture(autouse=True)
def _stand_in_tools(monkeypatch):
    from agent_api import tools as tools_mod

    real = tools_mod.build_tools
    monkeypatch.setattr(wa, "build_tools", lambda openapi: real(
        openapi, tuple(a for a in tools_mod.ALLOWED if a.name in STAND_IN_TOOLS)))


def _app(timeline: list[dict] | None) -> FastAPI:
    app = stand_in_api([])
    app.router.routes = [r for r in app.router.routes if getattr(r, "path", "") != "/materials"]

    @app.get("/materials")
    async def materials(jwt: dict = Depends(get_current_user)):
        return {"items": [{"id": STEEL, "name": "Steel", "default_unit_id": BAG, "aliases": ["kambi", "TMT"]}],
                "total": 1}

    if timeline is not None:
        @app.get("/timeline")
        async def entries(date_from: str, date_to: str, limit: int = 50, jwt: dict = Depends(get_current_user)):
            return {"items": timeline, "total": len(timeline)}

    return app


async def _prompt(app: FastAPI) -> str:
    model = FakeToolCallingProvider(["ok"])
    service = wa.ApiWhatsApp(provider=model, database=None, redis=FakeRedis(), send=AsyncMock(), transcribe=None,
                             message_logger=AsyncMock(), app=app)
    message = NormalizedMessage(message_id="wamid.f", sender=SenderInfo(wa_id="919800000000"),
                                timestamp=dt.datetime(2026, 11, 2, 6, tzinfo=dt.UTC), modality=InputModality.TEXT,
                                text="did anyone report labour today?")
    await service.handle(message, CTX)
    return model.last_system_prompt


async def test_aliases_and_todays_records_are_in_the_instructions() -> None:
    timeline = [  # newest first, as the API answers
        {"occurred_at": "2026-11-02T11:05:00+05:30", "site_id": SITE, "event_type": "labour_attendance",
         "summary": "Ravi: 6 mason, 4 helper"},
        {"occurred_at": "2026-11-02T09:40:00+05:30", "site_id": SITE, "event_type": "material_receipt",
         "summary": "Ravi: 50 bags cement received"},
    ]
    prompt = await _prompt(_app(timeline))
    assert f"- Steel ({STEEL}, bag) also called: kambi, TMT" in prompt
    receipt = prompt.index("09:40 Main block · material_receipt: Ravi: 50 bags cement received")
    labour = prompt.index("11:05 Main block · labour_attendance: Ravi: 6 mason, 4 helper")
    assert receipt < labour and "if a new entry repeats one of these, say so" in prompt


async def test_nothing_recorded_yet_is_said_plainly() -> None:
    assert "so far: nothing yet." in await _prompt(_app([]))


async def test_no_timeline_leaves_the_section_out() -> None:
    assert "Recorded today" not in await _prompt(_app(None))
