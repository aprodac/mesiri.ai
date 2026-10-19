"""Timeout + bounded-retry execution helper for provider calls (M3).

Wraps a single provider coroutine with a deadline and a bounded number of
retries on *retryable* mapped errors, records latency, and returns the raw
result. Non-retryable errors (e.g. malformed output) are raised immediately.

Retries are intentionally simple (fixed small backoff) — this is a foundation,
not a full resilience policy.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

from mesiri_contracts.common.errors import ErrorCode, MesiriError

from .errors import map_provider_error
from .failures import ProviderFailure, report_failure

T = TypeVar("T")


async def call_with_resilience(
    fn: Callable[[], Awaitable[T]],
    *,
    provider: str,
    operation: str,
    timeout_seconds: float,
    max_retries: int = 2,
    correlation_id: str | None = None,
    backoff_seconds: float = 0.1,
) -> tuple[T, float]:
    """Execute ``fn`` with a timeout and bounded retries.

    Returns ``(result, latency_ms)``. Raises the mapped :class:`MesiriError`
    when all attempts fail or a non-retryable error occurs.
    """
    attempts = max_retries + 1
    last_error: MesiriError | None = None
    start = time.perf_counter()

    for attempt in range(attempts):
        try:
            result = await asyncio.wait_for(fn(), timeout=timeout_seconds)
            latency_ms = round((time.perf_counter() - start) * 1000, 2)
            return result, latency_ms
        except Exception as exc:  # noqa: BLE001 — normalized below
            err = map_provider_error(provider, exc, correlation_id=correlation_id)
            last_error = err
            if not err.retryable or attempt == attempts - 1:
                # A malformed answer is the model's, not an outage: it must
                # not count toward "the AI account is down".
                if err.error_code != ErrorCode.PROVIDER_MALFORMED_OUTPUT.value:
                    report_failure(
                        ProviderFailure(
                            provider=provider,
                            operation=operation,
                            error_code=err.error_code,
                            status_code=err.details.get("status_code"),
                            correlation_id=correlation_id,
                        )
                    )
                raise err from exc
            await asyncio.sleep(backoff_seconds * (attempt + 1))

    # Unreachable, but keeps type-checkers satisfied.
    raise last_error  # type: ignore[misc]
