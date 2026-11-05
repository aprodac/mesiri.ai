"""Control panel → AI providers (5 Nov 2026): every Gemini model that can answer Mesiri is selectable, read live from
Google; Gemini 3.5 Flash is the default."""

from __future__ import annotations

from mesiri.domains.admin.providers_router import (
    DEFAULT_GEMINI_MODEL,
    KNOWN_GEMINI_MODELS,
    gemini_models_for_mesiri,
)

GEN = ["generateContent", "countTokens"]


def test_only_models_that_answer_text_voice_and_photos_are_offered() -> None:
    listing = [
        {"name": "models/gemini-3.5-flash", "supportedGenerationMethods": GEN},
        {"name": "models/gemini-3.6-flash", "supportedGenerationMethods": GEN},
        {"name": "models/gemini-2.5-flash-lite", "supportedGenerationMethods": GEN},
        {"name": "models/gemini-embedding-001", "supportedGenerationMethods": ["embedContent"]},
        {"name": "models/gemini-2.5-flash-preview-tts", "supportedGenerationMethods": GEN},
        {"name": "models/gemini-2.5-flash-image", "supportedGenerationMethods": GEN},
        {"name": "models/gemini-live-2.5-flash", "supportedGenerationMethods": GEN},
        {"name": "models/imagen-4.0", "supportedGenerationMethods": ["predict"]},
        {"name": "models/gemma-3-27b-it", "supportedGenerationMethods": GEN},
    ]
    assert gemini_models_for_mesiri(listing) == ["gemini-3.6-flash", "gemini-3.5-flash", "gemini-2.5-flash-lite"]


def test_the_default_is_gemini_3_5_flash_and_in_the_built_in_list() -> None:
    assert DEFAULT_GEMINI_MODEL == "gemini-3.5-flash" and DEFAULT_GEMINI_MODEL in KNOWN_GEMINI_MODELS
    assert gemini_models_for_mesiri([]) == []  # nothing read: the route falls back to the built-in list
