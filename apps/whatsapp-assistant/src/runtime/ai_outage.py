"""When every AI provider is down, keep the message and say so honestly.

On 19 Oct the routed text provider's account was unpaid: every call failed,
understanding came back UNUSABLE, and the sender got the greeting menu for
what they had just written -- as if Mesiri hadn't understood them. A provider
outage is not "didn't understand". The journey now:

1. tells the sender it is being processed in a few minutes (in their own
   language where they write one -- see runtime/reply_language.py);
2. raises `AIUnavailableError`, which worker.py turns into an ARQ retry
   (deferred), so the same message is run again from the top once a provider
   answers. Nothing was saved the first time, so the retry cannot double-write;
3. on the last try says plainly that it could not be processed, instead of a
   third silence.

Outside the ARQ worker (the dev/test fallback, the admin "retry" action)
there is no retry to promise: the sender is asked to resend instead.
"""

from __future__ import annotations

import contextvars

from mesiri_ai.core.errors import AUTH_OR_QUOTA_ERROR_CODE
from mesiri_contracts.assistant.confidence import ConfidenceLevel
from mesiri_contracts.assistant.understanding_result import UnderstandingResult
from mesiri_contracts.common.errors import ErrorCode

#: Matches worker.WorkerSettings.max_tries (worker.py reads it from here).
MAX_ATTEMPTS = 3

#: Seconds an ARQ retry waits per attempt already made (60s, then 120s).
RETRY_DEFER_STEP_SECONDS = 60

#: Which ARQ attempt this journey is (1-based); None outside the worker.
retry_attempt: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "mesiri_ai_retry_attempt", default=None
)

_OUTAGE_CODES = frozenset(
    {
        ErrorCode.PROVIDER_ERROR.value,
        ErrorCode.PROVIDER_UNAVAILABLE.value,
        ErrorCode.PROVIDER_TIMEOUT.value,
        AUTH_OR_QUOTA_ERROR_CODE,
    }
)

QUEUED_REPLY = "Got it 👍 I'll process this in a few minutes."
GAVE_UP_REPLY = (
    "Sorry, I couldn't process that message — nothing was saved. "
    "Please send it again in a little while."
)
RESEND_REPLY = "I can't process messages right now — nothing was saved. Please send it again in a few minutes."


class AIUnavailableError(Exception):
    """Every AI provider failed for this message; the job should be retried."""


def is_ai_outage(understanding: UnderstandingResult) -> bool:
    """True when understanding is unusable *because a provider call failed*
    (rather than because the message made no sense)."""
    if understanding.overall_confidence is not ConfidenceLevel.UNUSABLE:
        return False
    return any(
        not execution.succeeded and execution.error_code in _OUTAGE_CODES
        for execution in understanding.provider_executions
    )


def reply_for_attempt(attempt: int | None) -> tuple[str, bool]:
    """(text, retry): what to tell the sender on this attempt, and whether the
    message will be retried (so the journey should raise)."""
    if attempt is None:
        return RESEND_REPLY, False
    if attempt >= MAX_ATTEMPTS:
        return GAVE_UP_REPLY, False
    # Told once, on the first try; later tries stay quiet until they succeed.
    return (QUEUED_REPLY if attempt == 1 else ""), True
