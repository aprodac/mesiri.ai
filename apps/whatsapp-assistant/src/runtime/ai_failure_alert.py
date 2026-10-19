"""Tell the team when AI provider calls keep failing.

Fed by mesiri_ai.core.failures (every provider call that ends in failure).
The rule -- any 401/402/403 at once, otherwise 5 failures in 10 minutes, and
never more than one alert an hour -- is `FailureAlertPolicy`.

Where the alert goes: always a WARNING in the log. The team WhatsApp group
gets it too only when `MESIRI_AI_ALERT_TEAM_GROUP` is set to 1: the WA-14
hourly alarm has no live channel yet (it is a line in the nightly review),
so which chat should hear about this is the owner's call, not a default.

The policy is kept per process, so the web app and the worker can each
alert once an hour.
"""

from __future__ import annotations

import logging
import os
import time

from mesiri_ai.core import failures
from mesiri_ai.core.failures import FailureAlertPolicy, ProviderFailure
from runtime.team_notify import TeamNotifier

_log = logging.getLogger("mesiri.ai_failure_alert")

_TEAM_GROUP_ENV = "MESIRI_AI_ALERT_TEAM_GROUP"


class AIFailureAlerter:
    def __init__(
        self,
        notifier: TeamNotifier | None = None,
        *,
        policy: FailureAlertPolicy | None = None,
        clock=time.monotonic,
    ) -> None:
        self._notifier = notifier
        self._policy = policy or FailureAlertPolicy()
        self._clock = clock

    async def on_failure(self, failure: ProviderFailure) -> None:
        text = self._policy.record(failure, now=self._clock())
        if text is None:
            return
        _log.warning("ai.alert %s", text)
        if self._notifier is not None and os.environ.get(_TEAM_GROUP_ENV, "").strip() in {
            "1",
            "true",
            "yes",
        }:
            await self._notifier.post(f"⚠️ {text}")


def install_ai_failure_alerts(notifier: TeamNotifier | None = None) -> AIFailureAlerter:
    alerter = AIFailureAlerter(notifier)
    failures.set_failure_sink(alerter.on_failure)
    return alerter
