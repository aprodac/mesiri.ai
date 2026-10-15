"""What each AI provider call used, reported for cost tracking (BE-25).

Every adapter calls `report(...)` once per successful provider response with
the tokens (or audio seconds) the provider says it used. Where the report
goes is the app's choice: it installs a sink with `set_usage_sink`, and the
backend turns each report into a priced, company-tagged row. No sink -- tests,
scripts -- and reports are dropped.

Kept free of persistence on purpose (see tests/test_architecture_boundaries):
this module only describes usage and hands it on.

`report` never raises and never waits on the sink, so cost tracking can't
slow down or break the reply the call was made for.
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import logging
import struct
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass, field, replace
from typing import Any

_log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ProviderUsage:
    provider: str
    operation: str
    model: str | None
    correlation_id: str | None = None
    latency_ms: float | None = None
    # Prompt tokens, all modalities, including the cached and audio ones.
    input_tokens: int | None = None
    # Of input_tokens: served from the provider's cache (cheaper).
    cached_input_tokens: int | None = None
    # Of input_tokens: audio (Gemini prices audio input higher).
    audio_input_tokens: int | None = None
    # Completion tokens including any thinking/reasoning tokens (billed as output).
    output_tokens: int | None = None
    # Audio length, for providers that bill by time (Sarvam).
    audio_seconds: float | None = None
    # Who/what this was for, from the surrounding `usage_scope`.
    organization_id: str | None = None
    purpose: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class _Scope:
    organization_id: str | None = None
    purpose: str | None = None


_NO_SCOPE = _Scope()
_scope: contextvars.ContextVar[_Scope | None] = contextvars.ContextVar(
    "mesiri_ai_usage_scope", default=None
)

UsageSink = Callable[[ProviderUsage], Awaitable[None] | None]
_sink: UsageSink | None = None
# Keeps fire-and-forget sink tasks alive until they finish.
_pending: set[asyncio.Task[None]] = set()


def set_usage_sink(sink: UsageSink | None) -> None:
    """Install (or, with None, remove) where usage reports go."""
    global _sink
    _sink = sink


@contextlib.contextmanager
def usage_scope(
    *, organization_id: str | None = None, purpose: str | None = None
) -> Iterator[None]:
    """Tag every AI call made inside the block with a company and/or purpose,
    for calls the backend can't attribute from their correlation id (a
    scheduled job, a dashboard upload)."""
    current = _scope.get() or _NO_SCOPE
    token = _scope.set(
        _Scope(
            organization_id=organization_id or current.organization_id,
            purpose=purpose or current.purpose,
        )
    )
    try:
        yield
    finally:
        _scope.reset(token)


def report(usage: ProviderUsage) -> None:
    """Hand one call's usage to the sink. Never raises, never blocks."""
    sink = _sink
    if sink is None:
        return
    scope = _scope.get() or _NO_SCOPE
    usage = replace(
        usage,
        organization_id=usage.organization_id or scope.organization_id,
        purpose=usage.purpose or scope.purpose,
    )
    try:
        result = sink(usage)
        if asyncio.iscoroutine(result):
            task = asyncio.get_running_loop().create_task(result)
            _pending.add(task)
            task.add_done_callback(_finished)
    except Exception:  # noqa: BLE001
        _log.exception("ai.usage_report_failed provider=%s", usage.provider)


def _finished(task: asyncio.Task[None]) -> None:
    _pending.discard(task)
    if not task.cancelled() and task.exception() is not None:
        _log.error("ai.usage_sink_failed", exc_info=task.exception())


async def drain() -> None:
    """Wait for reports still being written (tests, shutdown)."""
    while _pending:
        await asyncio.gather(*list(_pending), return_exceptions=True)


# ---------------------------------------------------------------------------
# Reading usage out of each provider's response
# ---------------------------------------------------------------------------


def _int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _get(obj: Any, name: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def gemini_usage(response: Any) -> dict[str, int | None]:
    """Token counts from a google-genai GenerateContentResponse's
    `usage_metadata`. Thinking tokens are billed as output, so they are added
    to output_tokens."""
    meta = _get(response, "usage_metadata")
    if meta is None:
        return {}
    output = (_int(_get(meta, "candidates_token_count")) or 0) + (
        _int(_get(meta, "thoughts_token_count")) or 0
    )
    audio = 0
    for detail in _get(meta, "prompt_tokens_details") or []:
        modality = str(_get(detail, "modality") or "").upper()
        if modality.endswith("AUDIO"):
            audio += _int(_get(detail, "token_count")) or 0
    return {
        "input_tokens": _int(_get(meta, "prompt_token_count")),
        "cached_input_tokens": _int(_get(meta, "cached_content_token_count")),
        "audio_input_tokens": audio or None,
        "output_tokens": output,
    }


def openai_style_usage(response: Any) -> dict[str, int | None]:
    """Token counts from an OpenAI-compatible chat completion's `usage`
    (DeepSeek adds prompt_cache_hit_tokens). Reasoning tokens are already
    inside completion_tokens."""
    usage = _get(response, "usage")
    if not usage:
        return {}
    cached = _get(usage, "prompt_cache_hit_tokens")
    if cached is None:
        cached = _get(_get(usage, "prompt_tokens_details") or {}, "cached_tokens")
    return {
        "input_tokens": _int(_get(usage, "prompt_tokens")),
        "cached_input_tokens": _int(cached),
        "output_tokens": _int(_get(usage, "completion_tokens")),
    }


def ogg_duration_seconds(audio: bytes) -> float | None:
    """Length of an Ogg (Opus/Vorbis) file, from the granule position of its
    last page. WhatsApp voice notes are Ogg/Opus, which counts granules at
    48 kHz; Vorbis uses the stream's own rate from its header. None when it
    isn't an Ogg file we can read."""
    if not audio.startswith(b"OggS"):
        return None
    last = audio.rfind(b"OggS")
    if last < 0 or len(audio) < last + 14:
        return None
    granule = struct.unpack_from("<q", audio, last + 6)[0]
    if granule <= 0:
        return None
    rate = 48000
    pre_skip = 0
    head = audio.find(b"OpusHead")
    if head >= 0 and len(audio) >= head + 12:
        pre_skip = struct.unpack_from("<H", audio, head + 10)[0]
    else:
        vorbis = audio.find(b"\x01vorbis")
        if vorbis >= 0 and len(audio) >= vorbis + 16:
            rate = struct.unpack_from("<I", audio, vorbis + 12)[0] or 48000
    return max(granule - pre_skip, 0) / rate
