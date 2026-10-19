"""WA-13: a photo captioned as a logo sets the company's or a client's logo."""

from __future__ import annotations

import io
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from mesiri_contracts.assistant.enums import InputModality
from runtime import logo_from_whatsapp as mod
from runtime.logo_from_whatsapp import LogoFromWhatsApp, read_caption

ORG = uuid.uuid4()
P1 = SimpleNamespace(id=str(uuid.uuid4()), name="Riverside Tower")
P2 = SimpleNamespace(id=str(uuid.uuid4()), name="Green Villa")
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 100


def test_captions():
    assert read_caption("hello", [P1]) is None
    assert read_caption(None, [P1]) is None
    assert read_caption("our logo", [P1, P2]).kind == "company"
    t = read_caption("client logo for Riverside Tower", [P1, P2])
    assert (t.kind, t.project_id) == ("client", P1.id)
    assert read_caption("green villa logo", [P1, P2]).project_id == P2.id
    assert read_caption("client logo", [P1]).project_id == P1.id
    assert read_caption("client logo", [P1, P2]).unclear


class _Storage:
    def __init__(self, data, content_type="image/png"):
        self.objects = {"in/photo": SimpleNamespace(data=data, content_type=content_type)}
        self.deleted = []

    async def get_object(self, key):
        return self.objects[key]

    async def put_object(self, key, data, content_type=None):
        self.objects[key] = SimpleNamespace(data=data, content_type=content_type)

    async def delete_object(self, key):
        self.deleted.append(key)


class _Conn:
    def __init__(self):
        self.sql = []

    async def execute(self, stmt, params=None):
        self.sql.append((str(stmt), params))
        return SimpleNamespace(scalar_one_or_none=lambda: None)


class _Db:
    def __init__(self):
        self.conn = _Conn()

    @asynccontextmanager
    async def transaction(self):
        yield self.conn


def _msg(caption, modality=InputModality.IMAGE):
    return SimpleNamespace(
        modality=modality,
        text=caption,
        media=SimpleNamespace(object_key="in/photo", mime_type="image/png"),
    )


def _actor(role="ADMIN"):
    return SimpleNamespace(
        organization_id=str(ORG), user_id=str(uuid.uuid4()), role=role, projects=[P1, P2]
    )


async def test_company_logo_is_set_for_the_owner(monkeypatch):
    calls = {}

    async def fake_set(conn, org_id, key, *, updated_by):
        calls["key"] = key
        return None

    monkeypatch.setattr(mod, "set_logo_key", fake_set)
    storage = _Storage(PNG)
    reply = await LogoFromWhatsApp(db=_Db(), storage=storage).handle_media(_msg("logo"), _actor())
    assert reply.text == mod.COMPANY_SAVED
    assert calls["key"].startswith(f"org/{ORG}/branding/logo-") and calls["key"] in storage.objects


async def test_client_logo_is_set_on_the_named_project():
    db, storage = _Db(), _Storage(PNG)
    reply = await LogoFromWhatsApp(db=db, storage=storage).handle_media(
        _msg("client logo for Green Villa"), _actor()
    )
    assert "Green Villa" in reply.text
    update = [p for s, p in db.conn.sql if s.startswith("UPDATE projects")][0]
    assert str(update["p"]) == P2.id and str(update["o"]) == str(ORG)
    assert update["k"].startswith(f"org/{ORG}/projects/{P2.id}/client-logo-")


async def test_only_the_owner_and_only_logo_photos():
    handler = LogoFromWhatsApp(db=_Db(), storage=_Storage(PNG))
    assert (
        await handler.handle_media(_msg("logo"), _actor("SITE_ENGINEER"))
    ).text == mod.ONLY_OWNER
    assert await handler.handle_media(_msg("site photo"), _actor()) is None
    assert await handler.handle_media(_msg("logo", InputModality.TEXT), _actor()) is None
    assert "Which project" in (await handler.handle_media(_msg("client logo"), _actor())).text


async def test_a_big_photo_is_shrunk_and_junk_is_refused():
    pil = pytest.importorskip("PIL.Image")
    buf = io.BytesIO()
    pil.effect_noise((2000, 2000), 100).convert("RGB").save(buf, format="PNG")
    data, content_type = mod.logo_bytes(buf.getvalue(), "image/png")
    assert content_type == "image/jpeg" and len(data) <= 700 * 1024
    with pytest.raises(ValueError):
        mod.logo_bytes(b"not an image", "image/png")
