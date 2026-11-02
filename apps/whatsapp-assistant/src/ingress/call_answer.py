"""WA-118 step 2 part B: checks a question from the call spike before the assistant reads it.

The route sits behind the public webhook host, so nothing here trusts the network: the body is
signed with the app secret under its own prefix (a Meta webhook signature can never pass), it
must be fresh, and the number must be on the allow-list in this app's settings.
"""

from __future__ import annotations

import json
import time

from ingress.verification import WebhookVerificationError, verify_request_signature

SIGNED_PREFIX = b"call-answer:"
MAX_AGE_SECONDS = 30
#: In the allow-list: every number. The assistant's own checks still decide who gets an answer.
EVERYONE = "*"


class CallAnswerRefused(Exception):
    pass


def read_call_question(body: bytes, signature: str | None, *, app_secret: str, allowed: str,
                       now: float | None = None) -> tuple[str, str]:
    """``(wa_id, text)`` of a question that passes every check."""
    try:
        verify_request_signature(payload=SIGNED_PREFIX + body, signature_header=signature, app_secret=app_secret)
    except WebhookVerificationError as exc:
        raise CallAnswerRefused("bad signature") from exc
    try:
        question = json.loads(body)
        wa_id, text, at = str(question["wa_id"]), str(question["text"]).strip(), float(question["at"])
    except (ValueError, KeyError, TypeError) as exc:
        raise CallAnswerRefused("bad question") from exc
    if abs((time.time() if now is None else now) - at) > MAX_AGE_SECONDS:
        raise CallAnswerRefused("stale")
    listed = {n.strip().lstrip("+") for n in allowed.split(",") if n.strip()}
    if EVERYONE not in listed and wa_id not in listed:
        raise CallAnswerRefused("not allowed")
    if not text:
        raise CallAnswerRefused("nothing said")
    return wa_id, text
