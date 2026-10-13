"""Local-disk media storage (INF-09): files on this server, served by signed links."""

from __future__ import annotations

import time
from urllib.parse import parse_qs, unquote, urlparse

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from mesiri.bootstrap.settings import ObjectStorageProvider, ObjectStorageSettings, Settings
from mesiri.infrastructure.objectstorage import build_object_storage
from mesiri.infrastructure.objectstorage.dependency import get_object_storage
from mesiri.infrastructure.objectstorage.local_disk import (
    LocalDiskObjectStorage,
    verify_signature,
)
from mesiri_contracts.common.errors import MesiriError


def _settings(root, **overrides) -> ObjectStorageSettings:
    values = {
        "provider": ObjectStorageProvider.LOCAL,
        "local_root": str(root),
        "public_base_url": "https://mesiri.example/",
        "signing_secret": SecretStr("test-secret"),
    }
    values.update(overrides)
    return ObjectStorageSettings(**values)


def _link_parts(url: str) -> tuple[str, int, str]:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    return unquote(parsed.path.removeprefix("/media/")), int(query["exp"][0]), query["sig"][0]


@pytest.mark.anyio
async def test_round_trip_keeps_bytes_and_content_type(tmp_path):
    store = LocalDiskObjectStorage(_settings(tmp_path))

    meta = await store.put_object("org/1/photo.jpg", b"jpeg-bytes", content_type="image/jpeg")
    got = await store.get_object("org/1/photo.jpg")
    head = await store.head_object("org/1/photo.jpg")

    assert meta.size_bytes == 10
    assert got.data == b"jpeg-bytes"
    assert got.content_type == "image/jpeg"
    assert head.size_bytes == 10 and head.content_type == "image/jpeg"
    assert (tmp_path / "org/1/photo.jpg").read_bytes() == b"jpeg-bytes"


@pytest.mark.anyio
async def test_files_survive_a_new_store_instance(tmp_path):
    """The whole point of INF-09: a restart must not lose photos."""
    await LocalDiskObjectStorage(_settings(tmp_path)).put_object("k", b"x")

    assert (await LocalDiskObjectStorage(_settings(tmp_path)).get_object("k")).data == b"x"


@pytest.mark.anyio
async def test_missing_and_deleted_objects_are_not_found(tmp_path):
    store = LocalDiskObjectStorage(_settings(tmp_path))
    await store.put_object("a/b", b"x", content_type="image/png")
    await store.delete_object("a/b")
    await store.delete_object("never-existed")  # deleting nothing is fine

    with pytest.raises(MesiriError):
        await store.get_object("a/b")
    assert not (tmp_path / "a/b.content-type").exists()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "key", ["../escape", "a/../../escape", "/etc/passwd", "a\\b", "", "x.content-type"]
)
async def test_keys_cannot_leave_the_media_directory(tmp_path, key):
    store = LocalDiskObjectStorage(_settings(tmp_path / "media"))

    with pytest.raises(MesiriError):
        await store.put_object(key, b"x")
    assert not (tmp_path / "escape").exists()


@pytest.mark.anyio
async def test_signed_link_verifies_only_for_its_key_and_until_expiry(tmp_path):
    settings = _settings(tmp_path)
    store = LocalDiskObjectStorage(settings)

    url = await store.generate_presigned_url("org/1/p 1.jpg", expires_in_seconds=60)
    key, exp, sig = _link_parts(url)

    assert url.startswith("https://mesiri.example/media/")
    assert key == "org/1/p 1.jpg"
    assert verify_signature(settings, key, exp, sig)
    assert not verify_signature(settings, "org/1/other.jpg", exp, sig)
    assert not verify_signature(settings, key, exp + 1, sig)
    assert not verify_signature(settings, key, int(time.time()) - 1, sig)
    assert not verify_signature(
        _settings(tmp_path, signing_secret=SecretStr("other")), key, exp, sig
    )


@pytest.mark.anyio
async def test_upload_links_are_refused(tmp_path):
    with pytest.raises(MesiriError):
        await LocalDiskObjectStorage(_settings(tmp_path)).generate_presigned_url("k", method="PUT")


@pytest.mark.parametrize(
    "overrides",
    [{"signing_secret": None}, {"signing_secret": SecretStr("")}, {"public_base_url": None}],
)
def test_store_refuses_to_start_without_its_settings(tmp_path, overrides):
    with pytest.raises(MesiriError):
        LocalDiskObjectStorage(_settings(tmp_path, **overrides))


def test_factory_selects_local_disk(tmp_path):
    settings = Settings(object_storage=_settings(tmp_path))

    assert isinstance(build_object_storage(settings), LocalDiskObjectStorage)


def test_production_check_names_missing_local_settings(tmp_path):
    settings = Settings(
        environment="production",
        object_storage=_settings(tmp_path, public_base_url=None, signing_secret=None),
    )

    with pytest.raises(MesiriError) as excinfo:
        settings.validate_runtime()
    message = str(excinfo.value.internal_message)
    assert "MESIRI_OBJECT_STORAGE__PUBLIC_BASE_URL" in message
    assert "MESIRI_OBJECT_STORAGE__SIGNING_SECRET" in message


@pytest.fixture
def media_client(tmp_path, monkeypatch):
    storage_settings = _settings(tmp_path)
    store = LocalDiskObjectStorage(storage_settings)
    from mesiri.domains.shared import media_router

    monkeypatch.setattr(
        media_router, "get_settings", lambda: Settings(object_storage=storage_settings)
    )
    app = FastAPI()
    app.include_router(media_router.router)
    app.dependency_overrides[get_object_storage] = lambda: store
    return TestClient(app), store


@pytest.mark.anyio
async def test_media_route_serves_a_signed_link(media_client):
    client, store = media_client
    await store.put_object("org/1/photo.jpg", b"jpeg-bytes", content_type="image/jpeg")
    url = await store.generate_presigned_url("org/1/photo.jpg")

    resp = client.get(url.removeprefix("https://mesiri.example"))

    assert resp.status_code == 200
    assert resp.content == b"jpeg-bytes"
    assert resp.headers["content-type"] == "image/jpeg"


@pytest.mark.anyio
async def test_media_route_rejects_a_tampered_link(media_client):
    client, store = media_client
    await store.put_object("org/1/photo.jpg", b"x")
    await store.put_object("org/2/secret.jpg", b"y")
    url = await store.generate_presigned_url("org/1/photo.jpg")

    resp = client.get(
        url.removeprefix("https://mesiri.example").replace("org/1/photo", "org/2/secret")
    )

    assert resp.status_code == 403


def test_media_route_is_off_for_other_providers(tmp_path, monkeypatch):
    from mesiri.domains.shared import media_router

    monkeypatch.setattr(media_router, "get_settings", lambda: Settings())
    app = FastAPI()
    app.include_router(media_router.router)

    assert TestClient(app).get("/media/k?exp=1&sig=x").status_code == 404
