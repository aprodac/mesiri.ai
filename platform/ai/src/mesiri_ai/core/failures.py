"""Provider call failures, reported so the team hears about a broken AI account.

Every adapter call that ends in failure (after its own retries) is handed to
`report_failure`. Where it goes is the app's choice: it installs a sink with
`set_failure_sink`. No sink -- tests, scripts -- and reports are dropped.

`FailureAlertPolicy` is the "when is this worth waking someone" rule, kept
pure (no clock of its own, no I/O) so it can be tested exactly:

- any 401/402/403 alerts at once -- a key or an unpaid account stays broken
  until a person acts, every call fails until then (the 19 Oct DeepSeek
  account that was set up but never recharged);
- otherwise `threshold` failures inside `window_seconds` alert;
- either way, at most one alert per `cooldown_seconds`.

`report_failure` never raises and never waits on the sink, same contract as
mesiri_ai.usage.report, so alerting can't slow down or break a reply.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from .errors import AUTH_OR_QUOTA_STATUSES

_log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ProviderFailure:
    provider: str
    operation: str
    error_code: str
    status_code: int | None = None
    correlation_id: str | None = None

    @property
    def needs_a_person(self) -> bool:
        return self.status_code in AUTH_OR_QUOTA_STATUSES


class FailureAlertPolicy:
    def __init__(
        self,
        *,
        threshold: int = 5,
        window_seconds: float = 600.0,
        cooldown_seconds: float = 3600.0,
    ) -> None:
        self._threshold = threshold
        self._window = window_seconds
        self._cooldown = cooldown_seconds
        self._recent: deque[float] = deque()
        self._last_alert: float | None = None

    def record(self, failure: ProviderFailure, *, now: float) -> str | None:
        """Note one failure. Returns the alert text when one should be sent
        now, else None."""
        self._recent.append(now)
        while self._recent and now - self._recent[0] > self._window:
            self._recent.popleft()

        if self._last_alert is not None and now - self._last_alert < self._cooldown:
            return None

        if failure.needs_a_person:
            reason = (
                f"{failure.provider} answered HTTP {failure.status_code} "
                "(key invalid, no credit, or no access) -- every call to it will keep failing "
                "until the account is fixed"
            )
        elif len(self._recent) >= self._threshold:
            reason = (
                f"{len(self._recent)} AI calls failed in the last "
                f"{int(self._window // 60)} minutes (latest: {failure.provider} "
                f"{failure.operation}, {failure.error_code})"
            )
        else:
            return None

        self._last_alert = now
        return (
            f"AI provider problem: {reason}. Messages are being retried and the other "
            "provider is used where one is configured."
        )


FailureSink = Callable[[ProviderFailure], Awaitable[None] | None]
_sink: FailureSink | None = None
_pending: set[asyncio.Task[None]] = set()


def set_failure_sink(sink: FailureSink | None) -> None:
    """Install (or, with None, remove) where failure reports go."""
    global _sink
    _sink = sink


def report_failure(failure: ProviderFailure) -> None:
    """Hand one failed call to the sink. Never raises, never blocks."""
    sink = _sink
    if sink is None:
        return
    try:
        result = sink(failure)
        if asyncio.iscoroutine(result):
            task = asyncio.get_running_loop().create_task(result)
            _pending.add(task)
            task.add_done_callback(_finished)
    except Exception:  # noqa: BLE001
        _log.exception("ai.failure_report_failed provider=%s", failure.provider)


def _finished(task: asyncio.Task[None]) -> None:
    _pending.discard(task)
    if not task.cancelled() and task.exception() is not None:
        _log.error("ai.failure_sink_failed", exc_info=task.exception())


async def drain() -> None:
    """Wait for reports still being handled (tests, shutdown)."""
    while _pending:
        await asyncio.gather(*list(_pending), return_exceptions=True)
