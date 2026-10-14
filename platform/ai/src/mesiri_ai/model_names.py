"""Retired AI model names and what replaces them (BE-29).

Providers retire model names: DeepSeek's `deepseek-chat` / `deepseek-reasoner`
stopped resolving on 24 Jul 2026 (requests now fail) -- the current name is
`deepseek-flash` (DeepSeek-V4.1-Flash) -- and Google lists `gemini-2.0-flash`
for shutdown from 1 Jun 2026 and no longer prices it; `gemini-2.5-flash` is
current. A model name can come from the env (`MESIRI_*__MODEL`), the control
panel's routing table (`ai_active_routes`) or a code default, so the
resolver maps every one of them through `current_model_name` rather than
trusting each source to have been updated.

Checked against the providers' price pages on 14 Oct 2026. When a provider
retires another name, add it here.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

RETIRED_MODELS: dict[str, str] = {
    "deepseek-chat": "deepseek-flash",
    "deepseek-reasoner": "deepseek-flash",
    "deepseek-v4-flash": "deepseek-flash",
    "gemini-2.0-flash": "gemini-2.5-flash",
    "gemini-2.0-flash-001": "gemini-2.5-flash",
    "gemini-2.0-flash-lite": "gemini-2.5-flash-lite",
    "gemini-2.0-flash-lite-001": "gemini-2.5-flash-lite",
}

_warned: set[str] = set()


def current_model_name(model: str | None) -> str | None:
    """The name to send to the provider: `model`, or its replacement if the
    provider has retired it (logged once per name, so the stale setting gets
    noticed and fixed at its source)."""
    if not model:
        return model
    replacement = RETIRED_MODELS.get(model.strip())
    if replacement is None:
        return model
    if model not in _warned:
        _warned.add(model)
        logger.warning(
            "ai.model_retired configured=%s using=%s -- update the setting or routing table",
            model,
            replacement,
        )
    return replacement
