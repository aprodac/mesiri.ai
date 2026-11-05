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

#: Tries of a message while the AI is down (a blip, a provider error): then "could not process".
MAX_ATTEMPTS = 3
#: [221] (3 and 5 Nov: "Your message is kept" was dropped after the third try, about an hour in): while the AI budget
#: is used up the message really is kept, tried again for about 18 hours (``budget_defer_seconds``). This is
#: worker.WorkerSettings.max_tries; every other failure still stops at MAX_ATTEMPTS (``reply_for_attempt``).
BUDGET_MAX_ATTEMPTS = 12
#: The longest wait between two tries while the budget is used up.
BUDGET_DEFER_MAX_SECONDS = 2 * 3600

#: The pause before the one immediate second try, so a provider blip never
#: reaches the sender (request 57, A5); only if that also fails is "I'll
#: process this in a few minutes" said.
QUICK_RETRY_PAUSE_SECONDS = 1.5

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
#: WA-143: the AI account's spending budget is used up: the message is kept for longer (below), and
#: the sender is told plainly, not "a few minutes".
BUDGET_REPLY = ("Got it 👍 Mesiri's AI is paused for a short while (the team has been told). "
                "Your message is kept and I'll do it as soon as it's back.")
#: Seconds a retry waits per attempt when the budget is used up (20 min, then 40 min): time for a
#: person to raise the cap, instead of three tries inside three minutes.
BUDGET_RETRY_DEFER_STEP_SECONDS = 20 * 60
GAVE_UP_REPLY = (
    "Sorry, I couldn't process that message — nothing was saved. "
    "Please send it again in a little while."
)
RESEND_REPLY = "I can't process messages right now — nothing was saved. Please send it again in a few minutes."


class AIUnavailableError(Exception):
    """Every AI provider failed for this message; the job should be retried.

    ``budget_exhausted``: the provider's spending budget is used up (WA-143): retried later."""

    def __init__(self, *args: object, budget_exhausted: bool = False) -> None:
        super().__init__(*args)
        self.budget_exhausted = budget_exhausted


def is_budget_error(error: BaseException | None) -> bool:
    """WA-143: the AI account's spending budget is used up (``mesiri_ai.core.errors``)."""
    details = getattr(error, "details", None)
    return isinstance(details, dict) and bool(details.get("budget_exhausted"))


class FallBackToClassic(Exception):
    """The v3 agent failed for a reason that is not a provider outage (a bug in it or in a tool):
    the journey answers this message with the classic agent instead (request 204; v2 until WA-134)."""


def is_ai_outage(understanding: UnderstandingResult) -> bool:
    """True when understanding is unusable *because a provider call failed*
    (rather than because the message made no sense)."""
    if understanding.overall_confidence is not ConfidenceLevel.UNUSABLE:
        return False
    return any(
        not execution.succeeded and execution.error_code in _OUTAGE_CODES
        for execution in understanding.provider_executions
    )


def reply_for_attempt(attempt: int | None, *, budget: bool = False) -> tuple[str, bool]:
    """(text, retry): what to tell the sender on this attempt, and whether the
    message will be retried (so the journey should raise). ``budget``: the AI account's
    spending budget is used up (WA-143): the queued line says so."""
    if attempt is None:
        return RESEND_REPLY, False
    if attempt >= (BUDGET_MAX_ATTEMPTS if budget else MAX_ATTEMPTS):
        return GAVE_UP_REPLY, False
    # Told once, on the first try; later tries stay quiet until they succeed.
    return ((BUDGET_REPLY if budget else QUEUED_REPLY) if attempt == 1 else ""), True


def budget_defer_seconds(attempt: int) -> int:
    """[221]: the wait before the next try while the AI budget is used up: 20 min, 40 min, ... then every 2 hours."""
    return min(BUDGET_RETRY_DEFER_STEP_SECONDS * max(attempt, 1), BUDGET_DEFER_MAX_SECONDS)


def is_provider_failure(error: BaseException) -> bool:
    """False only when ``error`` carries an error code that is NOT a provider outage (a
    validation / "no usable output" error): that call answered, so retrying it later would
    give the same nothing. Any other error is treated as an outage, as before (request 184)."""
    code = getattr(error, "error_code", None)
    return not code or str(code) in _OUTAGE_CODES


def is_outage_error(error: BaseException) -> bool:
    """True only for a real provider outage (quota, auth, timeout, provider error). Unlike
    ``is_provider_failure`` an error with no code is NOT one: a bug in a tool or in the agent
    must fall back to another engine, not be queued and retried three times (request 204)."""
    if isinstance(error, TimeoutError):
        return True
    return str(getattr(error, "error_code", "") or "") in _OUTAGE_CODES
