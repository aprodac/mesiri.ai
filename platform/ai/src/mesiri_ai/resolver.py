"""Dynamic AI Provider Resolver Proxy (M3/M9).

Resolves which AI model/provider to use for each capability dynamically at runtime.
Uses Redis caching to maintain sub-millisecond lookup latency, falling back to
PostgreSQL config tables and then environment settings.

Supports per-capability fallback providers that are automatically invoked when
the primary provider raises an error.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from mesiri_ai import fixtures
from mesiri_ai.model_names import current_model_name
from mesiri_ai.models import (
    DecompositionResult,
    ExtractionResult,
    SpeechResult,
    TranslationResult,
    VisionResult,
)
from mesiri_contracts.common.errors import MesiriError

logger = logging.getLogger(__name__)

# Sentinel for masked/empty keys that should not be used
_MASKED_KEY_PREFIX = "****"


def _build_gemini_provider(config: dict, model: str, env_settings: Any):
    """Instantiate GeminiProvider with resolved credentials."""
    from pydantic import SecretStr

    from mesiri.bootstrap.settings import GeminiSettings
    from mesiri_ai.adapters.gemini.adapter import GeminiProvider

    secret = config["secrets"].get("gemini", {})
    api_key = secret.get("api_key")
    if not api_key:
        raise MesiriError.configuration("Gemini API Key is not configured.", code="CONFIG_MISSING")
    settings = GeminiSettings(
        api_key=SecretStr(api_key),
        model=current_model_name(model or env_settings.gemini.model),
        timeout_seconds=env_settings.gemini.timeout_seconds,
        max_retries=env_settings.gemini.max_retries,
        # Test doubles for env_settings don't always carry this (it's newer
        # than they are), and a missing tuning knob must not break routing.
        max_image_edge=getattr(env_settings.gemini, "max_image_edge", 1568),
    )
    return GeminiProvider(settings)


def _build_deepseek_provider(config: dict, model: str, env_settings: Any):
    """Instantiate DeepSeekExtractionProvider with resolved credentials."""
    from pydantic import SecretStr

    from mesiri.bootstrap.settings import DeepSeekSettings
    from mesiri_ai.adapters.deepseek.adapter import DeepSeekExtractionProvider

    secret = config["secrets"].get("deepseek", {})
    api_key = secret.get("api_key")
    base_url = secret.get("base_url") or "https://api.deepseek.com"
    if not api_key:
        raise MesiriError.configuration(
            "DeepSeek API Key is not configured.", code="CONFIG_MISSING"
        )
    settings = DeepSeekSettings(
        api_key=SecretStr(api_key),
        model=current_model_name(model or env_settings.deepseek.model),
        base_url=base_url,
        timeout_seconds=env_settings.deepseek.timeout_seconds,
        max_retries=env_settings.deepseek.max_retries,
    )
    return DeepSeekExtractionProvider(settings)


def _build_sarvam_provider(config: dict, env_settings: Any):
    """Instantiate SarvamSpeechProvider with resolved credentials."""
    from pydantic import SecretStr

    from mesiri.bootstrap.settings import SarvamSettings
    from mesiri_ai.adapters.sarvam.adapter import SarvamSpeechProvider

    secret = config["secrets"].get("sarvam", {})
    api_key = secret.get("api_key")
    if not api_key:
        raise MesiriError.configuration("Sarvam API Key is not configured.", code="CONFIG_MISSING")
    settings = SarvamSettings(
        api_key=SecretStr(api_key),
        timeout_seconds=env_settings.sarvam.timeout_seconds,
        max_retries=env_settings.sarvam.max_retries,
    )
    return SarvamSpeechProvider(settings)


class DynamicAIProviderResolver:
    """Dynamic resolver implementing AI ports.

    Queries Redis/DB to route calls to the active provider dynamically.
    Supports per-capability fallback providers on primary failure.
    """

    provider = "dynamic"

    def __init__(self, db: Any, redis_client: Any, settings: Any) -> None:
        self._db = db
        self._redis = redis_client
        self._settings = settings
        # Every call used to build a fresh GeminiProvider (-> fresh
        # genai.Client -> fresh TCP+TLS handshake) even though the resolver
        # itself is long-lived. Keyed by api_key too, not just
        # (kind, model), so a rotated key in Redis/DB still gets picked up
        # instead of silently reusing a stale client.
        self._provider_cache: dict[tuple[str, str, str | None], Any] = {}

    def _cached_gemini_provider(self, config: dict, model: str) -> Any:
        api_key = config["secrets"].get("gemini", {}).get("api_key")
        key = ("gemini", model, api_key)
        if key not in self._provider_cache:
            self._provider_cache[key] = _build_gemini_provider(config, model, self._settings)
        return self._provider_cache[key]

    def _cached_deepseek_provider(self, config: dict, model: str) -> Any:
        api_key = config["secrets"].get("deepseek", {}).get("api_key")
        key = ("deepseek", model, api_key)
        if key not in self._provider_cache:
            self._provider_cache[key] = _build_deepseek_provider(config, model, self._settings)
        return self._provider_cache[key]

    def _cached_sarvam_provider(self, config: dict) -> Any:
        api_key = config["secrets"].get("sarvam", {}).get("api_key")
        key = ("sarvam", "", api_key)
        if key not in self._provider_cache:
            self._provider_cache[key] = _build_sarvam_provider(config, self._settings)
        return self._provider_cache[key]

    async def _resolve_config(self) -> dict[str, Any]:
        """Resolve active routing and credentials from Redis -> DB -> Env."""
        cache_key = "mesiri:ai:config"
        # 1. Try Redis cache
        try:
            if self._redis and hasattr(self._redis, "get"):
                cached = await self._redis.get(cache_key)
                if cached:
                    return json.loads(cached)
        except Exception as exc:
            logger.warning("Failed to read AI config from Redis: %s", exc)

        # Default fallback config derived from environment Settings
        config: dict[str, Any] = {
            "routing": {
                "voice": {
                    "provider_id": "sarvam" if self._settings.sarvam.api_key else "fake",
                    "model": "saaras:v2.5",
                    "fallback_provider_id": None,
                    "fallback_model": None,
                },
                "extraction": {
                    "provider_id": (
                        "deepseek"
                        if self._settings.deepseek.api_key
                        else ("gemini" if self._settings.gemini.api_key else "fake")
                    ),
                    "model": (
                        self._settings.deepseek.model
                        if self._settings.deepseek.api_key
                        else self._settings.gemini.model
                    ),
                    "fallback_provider_id": None,
                    "fallback_model": None,
                },
                "vision": {
                    "provider_id": "gemini" if self._settings.gemini.api_key else "fake",
                    "model": self._settings.gemini.model,
                    "fallback_provider_id": None,
                    "fallback_model": None,
                },
                "translation": {
                    "provider_id": "gemini" if self._settings.gemini.api_key else "fake",
                    "model": self._settings.gemini.model,
                    "fallback_provider_id": None,
                    "fallback_model": None,
                },
            },
            "secrets": {
                "gemini": {
                    "api_key": (
                        self._settings.gemini.api_key.get_secret_value()
                        if self._settings.gemini.api_key
                        else None
                    ),
                    "base_url": None,
                },
                "deepseek": {
                    "api_key": (
                        self._settings.deepseek.api_key.get_secret_value()
                        if self._settings.deepseek.api_key
                        else None
                    ),
                    "base_url": self._settings.deepseek.base_url,
                },
                "sarvam": {
                    "api_key": (
                        self._settings.sarvam.api_key.get_secret_value()
                        if self._settings.sarvam.api_key
                        else None
                    ),
                    "base_url": None,
                },
            },
        }

        # 2. Try PostgreSQL database if available
        if self._db and hasattr(self._db, "transaction"):
            try:
                from mesiri.infrastructure.postgres.repositories.ai_config import (
                    PostgresAIConfigRepository,
                )

                async with self._db.transaction() as conn:
                    repo = PostgresAIConfigRepository(conn)
                    db_routes = await repo.get_active_routes()
                    db_secrets = await repo.get_provider_secrets()

                for cap, route in db_routes.items():
                    config["routing"][cap] = {
                        "provider_id": route["provider_id"],
                        "model": route["model"],
                        "fallback_provider_id": route.get("fallback_provider_id"),
                        "fallback_model": route.get("fallback_model"),
                    }

                for provider, sec in db_secrets.items():
                    if sec.get("api_key"):
                        config["secrets"][provider]["api_key"] = sec["api_key"]
                    if sec.get("base_url"):
                        config["secrets"][provider]["base_url"] = sec["base_url"]

            except Exception as exc:
                logger.warning("Failed to query DB for AI routing config: %s", exc)

        # 3. Write back to Redis cache. TTL matters here: this previously
        # cached forever, so a routing change made in the control panel
        # (e.g. switching voice from gemini to sarvam) would silently never
        # take effect until the key was flushed by hand.
        try:
            if self._redis and hasattr(self._redis, "set"):
                await self._redis.set(cache_key, json.dumps(config), ex=300)
        except Exception as exc:
            logger.warning("Failed to write AI config to Redis: %s", exc)

        return config

    async def transcribe(
        self,
        audio: bytes,
        *,
        language_hint: str | None = None,
        correlation_id: str | None = None,
    ) -> SpeechResult:
        """Transcribe voice audio with automatic fallback."""
        config = await self._resolve_config()
        route = config["routing"].get("voice", {"provider_id": "fake", "model": ""})
        provider_id = route["provider_id"]
        model = route["model"]
        fallback_id = route.get("fallback_provider_id")
        fallback_model = route.get("fallback_model") or ""

        async def _call_voice(pid: str, mdl: str) -> SpeechResult:
            if pid == "sarvam":
                provider = self._cached_sarvam_provider(config)
                return await provider.transcribe(
                    audio, language_hint=language_hint, correlation_id=correlation_id
                )
            if pid == "gemini":
                provider = self._cached_gemini_provider(config, mdl)
                return await provider.transcribe(
                    audio, language_hint=language_hint, correlation_id=correlation_id
                )
            # fake
            from mesiri_ai.fakes import FakeSpeechProvider

            return await FakeSpeechProvider(fixtures.MALAYALAM_JCB_SPEECH).transcribe(
                audio, language_hint=language_hint, correlation_id=correlation_id
            )

        try:
            return await _call_voice(provider_id, model)
        except MesiriError:
            if fallback_id:
                logger.warning(
                    "voice primary provider %r failed, trying fallback %r",
                    provider_id,
                    fallback_id,
                )
                return await _call_voice(fallback_id, fallback_model)
            raise

    async def understand_voice(
        self,
        audio: bytes,
        *,
        semantic_hint: str | None = None,
        expense_categories: list[str] | None = None,
        correlation_id: str | None = None,
    ) -> ExtractionResult:
        """Transcribe + extract in one call when voice is routed to Gemini
        (the real win -- previously two sequential calls, ~4.5s combined).
        Sarvam has no extraction capability of its own to merge with, so
        when voice is routed elsewhere this falls back to calling
        transcribe() then extract() internally and composing one
        ExtractionResult from both -- same external contract either way,
        callers never need to know which path ran."""
        config = await self._resolve_config()
        route = config["routing"].get("voice", {"provider_id": "fake", "model": ""})
        if route["provider_id"] == "gemini":
            provider = self._cached_gemini_provider(config, route["model"])
            return await provider.understand_voice(
                audio,
                semantic_hint=semantic_hint,
                expense_categories=expense_categories,
                correlation_id=correlation_id,
            )

        speech = await self.transcribe(audio, correlation_id=correlation_id)
        normalized_text = speech.translated_text or speech.transcript
        extraction = await self.extract(
            normalized_text,
            semantic_hint=semantic_hint,
            expense_categories=expense_categories,
            correlation_id=correlation_id,
        )
        return extraction.model_copy(
            update={
                "transcript": speech.transcript,
                "translated_text": speech.translated_text,
                "detected_language": speech.detected_language or extraction.detected_language,
                # Two real calls happened here (speech + extraction) -- sum
                # their latency so the one provider_execution row callers
                # end up logging for understand_voice reflects the true
                # total cost, not just the second call's.
                "latency_ms": (speech.latency_ms or 0) + (extraction.latency_ms or 0),
            }
        )

    async def extract(
        self,
        text: str,
        *,
        semantic_hint: str | None = None,
        expense_categories: list[str] | None = None,
        correlation_id: str | None = None,
    ) -> ExtractionResult:
        """Extract structured entities from text with automatic fallback."""
        config = await self._resolve_config()
        route = config["routing"].get("extraction", {"provider_id": "fake", "model": ""})
        provider_id = route["provider_id"]
        model = route["model"]
        fallback_id = route.get("fallback_provider_id")
        fallback_model = route.get("fallback_model") or ""

        async def _call_extract(pid: str, mdl: str) -> ExtractionResult:
            if pid == "gemini":
                provider = self._cached_gemini_provider(config, mdl)
                return await provider.extract(
                    text,
                    semantic_hint=semantic_hint,
                    expense_categories=expense_categories,
                    correlation_id=correlation_id,
                )
            if pid == "deepseek":
                provider = self._cached_deepseek_provider(config, mdl)
                return await provider.extract(
                    text,
                    semantic_hint=semantic_hint,
                    expense_categories=expense_categories,
                    correlation_id=correlation_id,
                )
            from mesiri_ai.fakes import FakeExtractionProvider

            return await FakeExtractionProvider(fixtures.VALID_RECEIPT_EXTRACTION).extract(
                text,
                semantic_hint=semantic_hint,
                expense_categories=expense_categories,
                correlation_id=correlation_id,
            )

        try:
            return await _call_extract(provider_id, model)
        except MesiriError:
            if fallback_id:
                logger.warning(
                    "extraction primary provider %r failed, trying fallback %r",
                    provider_id,
                    fallback_id,
                )
                return await _call_extract(fallback_id, fallback_model)
            raise

    async def decompose(
        self, text: str, *, correlation_id: str | None = None
    ) -> DecompositionResult:
        """Split (never classify) text that already failed single-intent
        extraction (docs/execution/COMPOSITE_REQUEST_PLAN_LAYER.md §9).

        Reuses the "extraction" route's provider/model rather than adding a
        new routing capability -- same reasoning as generate_json below:
        it's the same underlying model doing a different job on the same
        text, and every org already has an extraction route configured.
        """
        config = await self._resolve_config()
        route = config["routing"].get("extraction", {"provider_id": "fake", "model": ""})
        provider_id = route["provider_id"]
        model = route["model"]
        fallback_id = route.get("fallback_provider_id")
        fallback_model = route.get("fallback_model") or ""

        async def _call_decompose(pid: str, mdl: str) -> DecompositionResult:
            if pid == "gemini":
                provider = self._cached_gemini_provider(config, mdl)
                return await provider.decompose(text, correlation_id=correlation_id)
            if pid == "deepseek":
                provider = self._cached_deepseek_provider(config, mdl)
                return await provider.decompose(text, correlation_id=correlation_id)
            # No fake/fabricated split: an unconfigured route degrades to
            # "not multi-intent" (today's single-message behaviour), never a
            # guessed segmentation. Unlike extract()'s fake fallback (which
            # exists so tests without real providers still exercise the
            # whole pipeline against a known fixture), there is no
            # equivalent safe fixture for an arbitrary multi-intent split.
            return DecompositionResult(provider="fake")

        try:
            return await _call_decompose(provider_id, model)
        except MesiriError:
            if fallback_id:
                logger.warning(
                    "decomposition primary provider %r failed, trying fallback %r",
                    provider_id,
                    fallback_id,
                )
                return await _call_decompose(fallback_id, fallback_model)
            raise

    async def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        correlation_id: str | None = None,
    ) -> str:
        """Free-form JSON generation for the interaction slow-path classifier
        (correction detection). Only GeminiProvider implements this today --
        DeepSeek's adapter doesn't -- so this reuses the "extraction" route's
        provider when it resolves to gemini, and otherwise falls back to
        building a Gemini provider directly whenever a Gemini key exists at
        all (e.g. extraction is routed to DeepSeek but Gemini is still
        configured). Raises if no Gemini-capable provider is configured;
        callers (interactions/handler.py's slow path) already treat any
        exception here as AMBIGUOUS rather than crashing the journey."""
        config = await self._resolve_config()
        route = config["routing"].get("extraction", {"provider_id": "fake", "model": ""})
        model = route["model"] if route["provider_id"] == "gemini" else self._settings.gemini.model
        gemini_key = config["secrets"].get("gemini", {}).get("api_key")
        if not gemini_key:
            raise MesiriError.configuration(
                "No Gemini-capable provider configured for JSON generation", code="CONFIG_MISSING"
            )
        provider = self._cached_gemini_provider(config, model)
        return await provider.generate_json(
            system_prompt, user_prompt, correlation_id=correlation_id
        )

    async def analyze_image(
        self,
        image: bytes,
        *,
        mime_type: str | None = None,
        hint: str | None = None,
        correlation_id: str | None = None,
    ) -> VisionResult:
        """Analyze image contents with automatic fallback."""
        config = await self._resolve_config()
        route = config["routing"].get("vision", {"provider_id": "fake", "model": ""})
        provider_id = route["provider_id"]
        model = route["model"]
        fallback_id = route.get("fallback_provider_id")
        fallback_model = route.get("fallback_model") or ""

        async def _call_vision(pid: str, mdl: str) -> VisionResult:
            if pid == "gemini":
                provider = self._cached_gemini_provider(config, mdl)
                return await provider.analyze_image(
                    image, mime_type=mime_type, hint=hint, correlation_id=correlation_id
                )
            from mesiri_ai.fakes import FakeVisionProvider

            return await FakeVisionProvider(fixtures.VALID_RECEIPT_VISION).analyze_image(
                image, mime_type=mime_type, hint=hint, correlation_id=correlation_id
            )

        try:
            return await _call_vision(provider_id, model)
        except MesiriError:
            if fallback_id:
                logger.warning(
                    "vision primary provider %r failed, trying fallback %r",
                    provider_id,
                    fallback_id,
                )
                return await _call_vision(fallback_id, fallback_model)
            raise

    async def translate_to_english(
        self,
        text: str,
        *,
        correlation_id: str | None = None,
    ) -> TranslationResult:
        """Translate text to English with automatic fallback."""
        config = await self._resolve_config()
        route = config["routing"].get("translation", {"provider_id": "fake", "model": ""})
        provider_id = route["provider_id"]
        model = route["model"]
        fallback_id = route.get("fallback_provider_id")
        fallback_model = route.get("fallback_model") or ""

        async def _call_translate(pid: str, mdl: str) -> TranslationResult:
            if pid == "gemini":
                provider = self._cached_gemini_provider(config, mdl)
                return await provider.translate_to_english(text, correlation_id=correlation_id)
            if pid == "deepseek":
                provider = self._cached_deepseek_provider(config, mdl)
                return await provider.translate_to_english(text, correlation_id=correlation_id)
            from mesiri_ai.fakes import FakeTranslationProvider

            return await FakeTranslationProvider().translate_to_english(
                text, correlation_id=correlation_id
            )

        try:
            return await _call_translate(provider_id, model)
        except MesiriError:
            if fallback_id:
                logger.warning(
                    "translation primary provider %r failed, trying fallback %r",
                    provider_id,
                    fallback_id,
                )
                return await _call_translate(fallback_id, fallback_model)
            raise
