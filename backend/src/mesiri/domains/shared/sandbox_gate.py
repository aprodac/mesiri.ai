"""SS-66d: nothing a person does in their learning sandbox may reach a real phone.

A sandbox (application/learn/sandbox.py) has no phone numbers, is never operational (so no scheduled job, report or
reminder reaches it), and its people can't hold a WhatsApp number (migration 0557's trigger). This module is the last
line for what is left: a send started *while handling a sandbox request* (a material request approved, a document
sent from Tell Mesiri, an invite). The request's token says it is a sandbox (the ``sandbox`` claim); this middleware
marks the request, and the one WhatsApp sender (channel/whatsapp/outbound.py ``WhatsAppSender._send``) drops anything
sent while the mark is on. Tasks started from the request inherit the mark (contextvars are copied into them).
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import Any

import jwt

from mesiri.domains.identity.auth_service import ALGORITHM, SECRET_KEY

_log = logging.getLogger(__name__)

_in_sandbox: ContextVar[bool] = ContextVar("mesiri_in_sandbox", default=False)


def sending_blocked() -> bool:
    """True while handling a request made with a sandbox token."""
    return _in_sandbox.get()


def _claims(authorization: str | None) -> dict[str, Any]:
    if not authorization or not authorization.startswith("Bearer "):
        return {}
    try:
        return jwt.decode(authorization[7:], SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return {}


def is_sandbox_token(authorization: str | None) -> bool:
    return bool(_claims(authorization).get("sandbox"))


async def sandbox_gate_middleware(request: Any, call_next: Any) -> Any:
    # SS-74a: the same token gives the sample company's own date (domains/shared/clock.py) to the whole request.
    from mesiri.domains.shared import clock

    claims = _claims(request.headers.get("authorization"))
    token = _in_sandbox.set(bool(claims.get("sandbox")))
    try:
        with clock.scope(None):
            clock.bind_from_token(claims)
            return await call_next(request)
    finally:
        _in_sandbox.reset(token)


def note_blocked(to: str, kind: str) -> None:
    _log.info("sandbox_gate.send_blocked kind=%s to=%s", kind, (to or "")[-4:])
