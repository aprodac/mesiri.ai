"""WA-119: calls the app's API as the person who sent the message.

Every call carries a bearer token for that person, made by the backend's own
``create_access_token`` and valid for a few minutes, so the API applies the
same login, role, project/site access and company checks it applies to the
dashboard. The token never leaves this process when ``app`` is given (calls
go through ``httpx.ASGITransport`` into the same FastAPI app, no network).
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import httpx

#: Long enough for one turn plus the person's confirmation round trip on the
#: same client; a new client (new token) is made per turn.
TOKEN_MINUTES = 5


@dataclass(frozen=True)
class Actor:
    """Who the calls are made as. ``role`` is the user's role as the login stores it."""

    user_id: str
    organization_id: str
    role: str
    name: str = ""


@dataclass(frozen=True)
class ApiResponse:
    status: int
    body: Any

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


def token_for(actor: Actor, minutes: int = TOKEN_MINUTES) -> str:
    """The same token the login issues (sub / org / role / name), short-lived."""
    from mesiri.domains.identity.auth_service import create_access_token

    return create_access_token(
        {"sub": actor.user_id, "org": actor.organization_id, "role": actor.role, "name": actor.name},
        expires_delta=timedelta(minutes=minutes),
    )


class ApiClient:
    """One person's API session for one turn. ``app`` = in process; else ``base_url`` over HTTP."""

    def __init__(self, actor: Actor | None = None, *, app: Any | None = None, base_url: str | None = None,
                 token: str | None = None, timeout_seconds: float = 15.0) -> None:
        """``actor``: calls are made as that person with a short-lived token made here.
        ``token``: a login token the person already has (the chat script logs in)."""
        if app is None and not base_url:
            raise ValueError("ApiClient needs the app or a base_url")
        if (actor is None) == (token is None):
            raise ValueError("ApiClient needs exactly one of actor or token")
        #: [265]: the sender's role as the login stores it ("ADMIN", ...); None with a login token.
        self.role: str | None = actor.role if actor is not None else None
        #: WEB-68: who is asking (the accounts they hold); None with a login token.
        self.user_id: str | None = actor.user_id if actor is not None else None
        transport = httpx.ASGITransport(app=app) if app is not None else None
        bearer = token if token is not None else token_for(actor)  # type: ignore[arg-type]
        self._http = httpx.AsyncClient(
            transport=transport,
            base_url=base_url or "http://mesiri.internal",
            headers={"Authorization": f"Bearer {bearer}"},
            timeout=timeout_seconds,
        )

    async def call(self, method: str, path: str, *, params: dict[str, Any] | None = None,
                   json: dict[str, Any] | None = None, idempotency_key: str | None = None) -> ApiResponse:
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
        # Its own task = its own copy of the context: the company the API binds for the
        # request (bind_tenant in get_auth_context) never leaks back into the caller.
        response = await asyncio.create_task(
            self._http.request(method, path, params=params or None, json=json, headers=headers)
        )
        try:
            body: Any = response.json()
        except ValueError:
            body = response.text
        return ApiResponse(response.status_code, body)

    async def close(self) -> None:
        await self._http.aclose()


def new_idempotency_key() -> str:
    return f"api-agent-{uuid.uuid4()}"
