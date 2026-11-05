"""Admin-facing visibility into AI provider configuration and live health.

Exposes which AI providers (Gemini, DeepSeek, Sarvam) have a key configured,
a masked preview of that key, and an on-demand live check that calls the
provider with a minimal, side-effect-free request to confirm the key still
works right now. No secret value is ever returned in full.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.application.audit.record import record_admin_action
from mesiri.bootstrap.settings import Settings, get_settings
from mesiri.domains.audit import actions as audit
from mesiri.domains.shared.auth import require_platform_admin
from mesiri.infrastructure.postgres.dependency import get_db_conn
from mesiri.infrastructure.postgres.repositories.ai_config import PostgresAIConfigRepository

router = APIRouter(prefix="/admin/providers", tags=["admin"])

#: Set 5 Nov 2026 (control panel): Gemini 3.5 Flash is the model every capability starts on.
DEFAULT_GEMINI_MODEL = "gemini-3.5-flash"
#: Shown when Google's model list cannot be read (no key, network); the live list replaces it.
KNOWN_GEMINI_MODELS: tuple[str, ...] = (
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
)
#: Gemini models that cannot answer Mesiri's text, voice or photo calls (speech out, image out, live audio).
_NOT_FOR_MESIRI = ("embedding", "tts", "image-generation", "-image", "live", "native-audio", "aqa")


class CapabilityRouting(BaseModel):
    provider_id: str
    model: str
    fallback_provider_id: str | None = None
    fallback_model: str | None = None


class ProviderSecretInput(BaseModel):
    api_key: str | None
    base_url: str | None = None


class AIConfigResponse(BaseModel):
    routing: dict[str, CapabilityRouting]
    secrets: dict[str, dict[str, str | None]]


class AIConfigUpdateRequest(BaseModel):
    routing: dict[str, CapabilityRouting]
    secrets: dict[str, ProviderSecretInput]


def _mask(key: str | None) -> str | None:
    if not key:
        return None
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}{'*' * (len(key) - 8)}{key[-4:]}"


def _get_redis_client(request: Request) -> Any:
    if hasattr(request.app.state, "container"):
        return request.app.state.container.redis_client
    if hasattr(request.app.state, "lifecycle"):
        return request.app.state.lifecycle.container.redis_client
    return None


async def _get_active_secrets(
    conn: AsyncConnection, settings: Settings
) -> dict[str, dict[str, str | None]]:
    db_secrets = {}
    try:
        repo = PostgresAIConfigRepository(conn)
        db_secrets = await repo.get_provider_secrets()
    except Exception:
        pass

    resolved = {}
    for provider in ("gemini", "deepseek", "sarvam"):
        db_sec = db_secrets.get(provider, {})
        db_key = db_sec.get("api_key")
        db_url = db_sec.get("base_url")

        env_key = None
        if provider == "gemini" and settings.gemini.api_key:
            env_key = settings.gemini.api_key.get_secret_value()
        elif provider == "deepseek" and settings.deepseek.api_key:
            env_key = settings.deepseek.api_key.get_secret_value()
        elif provider == "sarvam" and settings.sarvam.api_key:
            env_key = settings.sarvam.api_key.get_secret_value()

        resolved[provider] = {
            "api_key": db_key or env_key,
            "base_url": db_url or (settings.deepseek.base_url if provider == "deepseek" else None),
        }
    return resolved


@router.get("")
async def list_providers(
    settings: Settings = Depends(get_settings),
    conn: AsyncConnection = Depends(get_db_conn),
    _admin: dict = Depends(require_platform_admin),
) -> list[dict]:
    secrets = await _get_active_secrets(conn, settings)

    gemini_key = secrets["gemini"]["api_key"]
    deepseek_key = secrets["deepseek"]["api_key"]
    sarvam_key = secrets["sarvam"]["api_key"]

    # Detect sources
    db_secrets = {}
    try:
        db_secrets = await PostgresAIConfigRepository(conn).get_provider_secrets()
    except Exception:
        pass

    def get_source(pid: str, active_key: str | None) -> str:
        if pid in db_secrets and db_secrets[pid].get("api_key"):
            return "database"
        return "env" if active_key else "not_configured"

    return [
        {
            "id": "gemini",
            "name": "Gemini",
            "model": settings.gemini.model,
            "configured": gemini_key is not None,
            "key_preview": _mask(gemini_key),
            "source": get_source("gemini", gemini_key),
        },
        {
            "id": "deepseek",
            "name": "DeepSeek",
            "model": settings.deepseek.model,
            "configured": deepseek_key is not None,
            "key_preview": _mask(deepseek_key),
            "source": get_source("deepseek", deepseek_key),
            "base_url": secrets["deepseek"]["base_url"],
        },
        {
            "id": "sarvam",
            "name": "Sarvam",
            "model": None,
            "configured": sarvam_key is not None,
            "key_preview": _mask(sarvam_key),
            "source": get_source("sarvam", sarvam_key),
        },
    ]


@router.get("/config", response_model=AIConfigResponse)
async def get_ai_config(
    settings: Settings = Depends(get_settings),
    conn: AsyncConnection = Depends(get_db_conn),
    _admin: dict = Depends(require_platform_admin),
):
    repo = PostgresAIConfigRepository(conn)
    db_routes = await repo.get_active_routes()
    db_secrets = await repo.get_provider_secrets()

    # Prepopulate default fallback routes if not defined in DB
    default_routes = {
        "voice": {"provider_id": "gemini", "model": DEFAULT_GEMINI_MODEL},
        "extraction": {"provider_id": "gemini", "model": DEFAULT_GEMINI_MODEL},
        "vision": {"provider_id": "gemini", "model": DEFAULT_GEMINI_MODEL},
        "translation": {"provider_id": "gemini", "model": DEFAULT_GEMINI_MODEL},
        # The classic assistant: answers when v3 fails (FallBackToClassic).
        "agent": {"provider_id": "gemini", "model": DEFAULT_GEMINI_MODEL},
        # WA-119: the API agent (v3, every company); unset it uses "agent" (shown here as the
        # model it would use). v2's own "agent_v2" route is gone with v2 (WA-134).
        "api_agent": db_routes.get("agent") or {"provider_id": "gemini", "model": DEFAULT_GEMINI_MODEL},
    }

    resolved_routing = {}
    for cap, default_val in default_routes.items():
        val = db_routes.get(cap, default_val)
        resolved_routing[cap] = CapabilityRouting(
            provider_id=val["provider_id"],
            model=val["model"],
            fallback_provider_id=val.get("fallback_provider_id"),
            fallback_model=val.get("fallback_model"),
        )

    # Expose secrets (masked previews + urls)
    resolved_secrets = {}
    for provider in ("gemini", "deepseek", "sarvam"):
        sec = db_secrets.get(provider, {})
        env_key = None
        if provider == "gemini" and settings.gemini.api_key:
            env_key = settings.gemini.api_key.get_secret_value()
        elif provider == "deepseek" and settings.deepseek.api_key:
            env_key = settings.deepseek.api_key.get_secret_value()
        elif provider == "sarvam" and settings.sarvam.api_key:
            env_key = settings.sarvam.api_key.get_secret_value()

        api_key = sec.get("api_key") or env_key
        base_url = sec.get("base_url") or (
            settings.deepseek.base_url if provider == "deepseek" else None
        )

        resolved_secrets[provider] = {
            "api_key": _mask(api_key),
            "base_url": base_url,
        }

    return {"routing": resolved_routing, "secrets": resolved_secrets}


@router.put("/config")
async def update_ai_config(
    request: Request,
    data: AIConfigUpdateRequest,
    conn: AsyncConnection = Depends(get_db_conn),
    settings: Settings = Depends(get_settings),
    _admin: dict = Depends(require_platform_admin),
):
    repo = PostgresAIConfigRepository(conn)

    # 1. Update capability routing
    for cap, route in data.routing.items():
        await repo.update_active_route(
            capability=cap,
            provider_id=route.provider_id,
            model=route.model,
            fallback_provider_id=route.fallback_provider_id or None,
            fallback_model=route.fallback_model or None,
        )

    # 2. Update provider secrets (skip if key is masked/unchanged)
    for provider, secret in data.secrets.items():
        if secret.api_key and "*" in secret.api_key:
            # Masked key sent -> keep the existing one in DB, only update URL if present
            db_sec = (await repo.get_provider_secrets()).get(provider, {})
            existing_key = db_sec.get("api_key")
            if existing_key:
                await repo.update_provider_secret(
                    provider_id=provider, api_key=existing_key, base_url=secret.base_url
                )
        elif secret.api_key:
            # New key provided -> update
            await repo.update_provider_secret(
                provider_id=provider, api_key=secret.api_key, base_url=secret.base_url
            )
        else:
            # If empty and base_url is provided, just update base_url
            db_sec = (await repo.get_provider_secrets()).get(provider, {})
            existing_key = db_sec.get("api_key")
            if existing_key or secret.base_url:
                await repo.update_provider_secret(
                    provider_id=provider, api_key=existing_key or "", base_url=secret.base_url
                )

    # Audit (BE-05), in the request's transaction. Keys are never stored:
    # only which providers got a new one.
    await record_admin_action(
        conn,
        actor=audit.actor_from_admin(_admin),
        action=audit.AI_CONFIG_CHANGED,
        target_type="ai_config",
        summary="AI routing and provider settings saved",
        details={
            "routing": {cap: route.model_dump() for cap, route in data.routing.items()},
            "providers": {
                provider: {
                    "base_url": secret.base_url,
                    "new_api_key": bool(secret.api_key) and "*" not in secret.api_key,
                }
                for provider, secret in data.secrets.items()
            },
        },
    )

    # 3. Invalidate Redis cache. Best-effort: the DB write above already
    # succeeded, so a cache-layer failure here must not surface as a 500 for
    # a config save that actually went through.
    redis = _get_redis_client(request)
    if redis:
        try:
            await redis.delete("mesiri:ai:config")
        except Exception:  # noqa: BLE001
            import logging

            logging.getLogger("mesiri.admin").warning(
                "Failed to invalidate mesiri:ai:config cache", exc_info=True
            )

    return {"status": "ok"}


def gemini_models_for_mesiri(listing: list[dict[str, Any]]) -> list[str]:
    """The Gemini models in Google's list that can answer Mesiri's calls (generateContent; not embeddings, speech or
    image output), newest name first, ids without the "models/" prefix."""
    out = set()
    for row in listing:
        name = str(row.get("name") or "").removeprefix("models/")
        methods = row.get("supportedGenerationMethods") or []
        if name.startswith("gemini-") and "generateContent" in methods and not any(x in name for x in _NOT_FOR_MESIRI):
            out.add(name)
    return sorted(out, reverse=True)


@router.get("/gemini/models")
async def list_gemini_models(
    conn: AsyncConnection = Depends(get_db_conn),
    settings: Settings = Depends(get_settings),
    _admin: dict = Depends(require_platform_admin),
) -> dict:
    """Every Gemini model the configured key can use, read live from Google (so a new model shows up without a
    deploy), and the default. Unreadable: the built-in list (``source`` says which)."""
    api_key = (await _get_active_secrets(conn, settings)).get("gemini", {}).get("api_key")
    listing: list[dict[str, Any]] = []
    if api_key:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                token = None
                for _ in range(5):  # pages of 1000; Google lists well under that today
                    resp = await client.get("https://generativelanguage.googleapis.com/v1beta/models",
                                            params={"key": api_key, "pageSize": 1000,
                                                    **({"pageToken": token} if token else {})})
                    if resp.status_code != 200:
                        break
                    body = resp.json()
                    listing += body.get("models") or []
                    token = body.get("nextPageToken")
                    if not token:
                        break
        except (httpx.HTTPError, ValueError):
            listing = []
    models = gemini_models_for_mesiri(listing)
    source = "live" if models else "built-in"
    models = models or list(KNOWN_GEMINI_MODELS)
    if DEFAULT_GEMINI_MODEL not in models:
        models.insert(0, DEFAULT_GEMINI_MODEL)
    return {"models": models, "default": DEFAULT_GEMINI_MODEL, "source": source}


async def _check_gemini(api_key: str | None) -> tuple[bool, str | None, float]:
    if not api_key:
        return False, "not configured", 0.0
    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://generativelanguage.googleapis.com/v1beta/models",
                params={"key": api_key},
            )
        latency_ms = (time.monotonic() - start) * 1000
        if resp.status_code == 200:
            return True, None, latency_ms
        return False, f"HTTP {resp.status_code}", latency_ms
    except httpx.HTTPError as exc:
        return False, str(exc), (time.monotonic() - start) * 1000


async def _check_deepseek(api_key: str | None, base_url: str) -> tuple[bool, str | None, float]:
    if not api_key:
        return False, "not configured", 0.0
    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{base_url.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
        latency_ms = (time.monotonic() - start) * 1000
        if resp.status_code == 200:
            return True, None, latency_ms
        return False, f"HTTP {resp.status_code}", latency_ms
    except httpx.HTTPError as exc:
        return False, str(exc), (time.monotonic() - start) * 1000


async def _check_sarvam(api_key: str | None) -> tuple[bool, str | None, float]:
    if not api_key:
        return False, "not configured", 0.0
    return True, None, 0.0


@router.post("/{provider_id}/check")
async def check_provider(
    provider_id: str,
    conn: AsyncConnection = Depends(get_db_conn),
    settings: Settings = Depends(get_settings),
    _admin: dict = Depends(require_platform_admin),
) -> dict:
    secrets = await _get_active_secrets(conn, settings)
    sec = secrets.get(provider_id, {})
    api_key = sec.get("api_key")

    if provider_id == "gemini":
        ok, error, latency_ms = await _check_gemini(api_key)
    elif provider_id == "deepseek":
        base_url = sec.get("base_url") or "https://api.deepseek.com"
        ok, error, latency_ms = await _check_deepseek(api_key, base_url)
    elif provider_id == "sarvam":
        ok, error, latency_ms = await _check_sarvam(api_key)
    else:
        return {"id": provider_id, "ok": False, "error": "unknown provider", "latency_ms": None}

    return {"id": provider_id, "ok": ok, "error": error, "latency_ms": round(latency_ms, 1)}
