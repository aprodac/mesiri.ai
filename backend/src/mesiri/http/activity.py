"""The company activity log's one recorder (ADM-01): who changed what, when.

A pure ASGI layer on every app that serves the dashboard's API (the backend app, the production WhatsApp app, the
assistant's API app), so every module is covered, including ones added later, with no code in any of them. It
records a change when ALL of these hold:

- the method is POST, PUT, PATCH or DELETE and the reply is 2xx (a refused or failed request changed nothing);
- the request carries a company login (a token with ``org``): public routes (sign-in, signup, the WhatsApp webhook,
  a client's link) and platform admins (their own log is ``admin_audit_log``, BE-05) are not this log;
- the path is not on ``SKIPPED`` (sign-in and the like).

What it keeps: the person (id; their name and role at the time), web or WhatsApp, the route template and the
action in words (from the route's function name), the record (kind from the path, id from the path or the reply,
its ref or name from the reply), the path's ids, the status, when. Never the request body: amounts, phone numbers
and notes stay in their own tables (D-A1).

Writing the row happens after the reply is sent, in its own short transaction, and can never fail the request.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

import jwt
from sqlalchemy import text

from mesiri.domains.identity.auth_service import ALGORITHM, SECRET_KEY

logger = logging.getLogger(__name__)

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

WRITES = frozenset({"POST", "PUT", "PATCH", "DELETE"})
#: Path prefixes that are not a person changing the company's records.
SKIPPED = ("/auth", "/login", "/signup", "/webhook", "/client/", "/media/", "/admin", "/claude-ops", "/health",
           "/activity")
#: The reply is read for its record id and ref only when it is this small.
MAX_BODY = 256 * 1024
_WORDS = {"ra": "RA", "dpr": "DPR", "boq": "BOQ", "po": "PO", "grn": "GRN", "gst": "GST", "tds": "TDS", "wo": "WO",
          "upi": "UPI", "pdf": "PDF", "id": "ID"}
#: A route function's first word that is HTTP talk, not what the person did.
_VERBS = {"put": "save", "upsert": "save", "post": "add", "patch": "change"}
_PARAM = re.compile(r"\{([^}:]+)(?::[^}]*)?\}")
#: A reply carrying this header saved nothing (a preview): not a change, not logged.
SAVED_NOTHING_HEADER = "x-mesiri-saved-nothing"


def saves_nothing(endpoint):  # noqa: ANN001, ANN201 -- a decorator for route functions
    """Mark a POST route that never changes anything (an import preview, a check, a reader): never logged."""
    endpoint.saves_nothing = True
    return endpoint


def mark_saved_nothing(response) -> None:  # noqa: ANN001 -- a starlette Response
    """Say on this reply that the request saved nothing (``preview``): the recorder skips it."""
    response.headers[SAVED_NOTHING_HEADER] = "1"


def action_words(endpoint_name: str | None, method: str, kind: str | None = None) -> str:
    """'submit_ra_bill' -> 'Submit RA bill'. A bare verb ('create', 'revoke') takes the record's kind: 'Create
    client link'."""
    words = [_WORDS.get(w, w) for w in (endpoint_name or "").strip("_").split("_") if w]
    if not words:
        words = [{"POST": "create", "PUT": "save", "PATCH": "change", "DELETE": "delete"}[method]]
    words[0] = _VERBS.get(words[0], words[0])
    if len(words) == 1 and kind:
        words += [_WORDS.get(w, w) for w in kind.split("_")]
    return " ".join([words[0][:1].upper() + words[0][1:], *words[1:]])


def _singular(segment: str) -> str:
    kind = segment.replace("-", "_")
    if kind.endswith("ies"):
        return kind[:-3] + "y"
    if kind.endswith("ses") or kind.endswith("xes"):
        return kind[:-2]
    return kind[:-1] if kind.endswith("s") and not kind.endswith("ss") else kind


def record_from(route: str, path_params: dict[str, Any], reply: Any) -> tuple[str | None, str | None, str | None]:
    """(kind, id, label) of the record a change was about.

    The reply's record when it is one of the path's ids (``POST /billing/ra-bills/{bill_id}/submit`` -> that bill);
    a new record when the reply names an id the path does not (``POST /projects/{project_id}/ra-bills`` -> the new
    ra_bill); otherwise the last id in the path. The kind is the path segment before an id, made singular."""
    parts = [p for p in route.split("/") if p]
    pairs = []  # (param name, kind)
    for i, part in enumerate(parts):
        m = _PARAM.fullmatch(part)
        if m and i > 0 and not _PARAM.fullmatch(parts[i - 1]):
            pairs.append((m.group(1), _singular(parts[i - 1])))
    reply_id, label = _reply_record(reply)
    if reply_id:
        for name, kind in pairs:
            if path_params.get(name) == reply_id:
                return kind, reply_id, label
        last_static = next((p for p in reversed(parts) if not _PARAM.fullmatch(p)), None)
        if last_static:
            return _singular(last_static), reply_id, label
    if pairs:
        name, kind = pairs[-1]
        return kind, path_params.get(name) or None, None
    return None, None, None


def _reply_record(reply: Any) -> tuple[str | None, str | None]:
    """The record a JSON reply describes: its own top level, or the one object it wraps ({"task": {...}})."""
    if not isinstance(reply, dict):
        return None, None
    candidates = [reply] + [v for v in reply.values() if isinstance(v, dict)][:1]
    for obj in candidates:
        rid = obj.get("id")
        if rid is None:
            continue
        label = next((str(obj[k]) for k in ("ref", "code", "number", "title", "name", "label") if obj.get(k)), None)
        return str(rid), label[:200] if label else None
    return None, None


def _claims(headers: dict[bytes, bytes]) -> dict[str, Any] | None:
    auth = headers.get(b"authorization", b"").decode("latin-1")
    if not auth.startswith("Bearer "):
        return None
    try:
        claims = jwt.decode(auth[7:], SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
    try:
        claims["org"] = uuid.UUID(str(claims.get("org") or ""))
        claims["sub"] = uuid.UUID(str(claims.get("sub") or "")) if claims.get("sub") else None
    except ValueError:
        return None
    return claims


async def _connection(app: Any, scope: Scope):  # noqa: ANN202 -- an async generator, as get_db_conn is
    """The same database connection the app's routes get (``get_db_conn``, or a test's override)."""
    from starlette.requests import Request

    from mesiri.infrastructure.postgres.dependency import get_db_conn

    provider = getattr(app, "dependency_overrides", {}).get(get_db_conn, get_db_conn)
    gen = provider(Request(scope)) if provider is get_db_conn else provider()
    return gen


async def write(conn: Any, row: dict[str, Any]) -> None:
    await conn.execute(text(
        "INSERT INTO activity_log (organization_id, actor_user_id, actor_name, actor_role, source, method, route, "
        "action, record_kind, record_id, record_label, path_ids, status_code, correlation_id) "
        "SELECT :org, :actor, (SELECT full_name FROM users WHERE id = :actor), :role, :source, :method, :route, "
        ":action, :kind, :rid, :label, CAST(:ids AS jsonb), :status, :cid"), row)


def _exc():  # noqa: ANN202
    import sys

    exc = sys.exc_info()[1]
    return (exc,)


class ActivityRecorder:
    """Wrap an app: after a successful change with a company login, write one ``activity_log`` row."""

    def __init__(self, app: ASGIApp, *, source: str = "web", fastapi_app: Any = None) -> None:
        self.app = app
        self.source = source
        self.fastapi_app = fastapi_app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        method = scope.get("method", "")
        path = scope.get("path", "")
        if scope.get("type") != "http" or method not in WRITES or path.startswith(SKIPPED):
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        claims = _claims(headers)
        if claims is None:
            await self.app(scope, receive, send)
            return

        status = 0
        chunks: list[bytes] = []
        size = 0
        is_json = False

        async def capture(message: Message) -> None:
            nonlocal status, size, is_json
            if message["type"] == "http.response.start":
                status = int(message.get("status", 0))
                reply_headers = dict(message.get("headers") or [])
                if reply_headers.get(SAVED_NOTHING_HEADER.encode()):
                    status = -1  # a preview: saved nothing
                content_type = reply_headers.get(b"content-type", b"")
                is_json = content_type.startswith(b"application/json")
            elif message["type"] == "http.response.body" and is_json and size <= MAX_BODY:
                body = message.get("body", b"")
                size += len(body)
                if size <= MAX_BODY:
                    chunks.append(body)
            await send(message)

        await self.app(scope, receive, capture)
        if not 200 <= status < 300:
            return
        try:
            await self._record(scope, claims, method, status, headers, b"".join(chunks) if size <= MAX_BODY else b"")
        except Exception:  # noqa: BLE001 -- the change is made; a missed log line must never fail it
            logger.warning("activity.not_recorded path=%s", path, exc_info=True)

    async def _record(self, scope: Scope, claims: dict[str, Any], method: str, status: int,
                      headers: dict[bytes, bytes], body: bytes) -> None:
        route_obj = scope.get("route")
        route = getattr(route_obj, "path", None) or scope.get("path", "")
        endpoint = scope.get("endpoint") or getattr(route_obj, "endpoint", None)
        if getattr(endpoint, "saves_nothing", False):
            return
        path_params = {k: str(v) for k, v in (scope.get("path_params") or {}).items()}
        try:
            reply = json.loads(body) if body else None
        except ValueError:
            reply = None
        kind, record_id, label = record_from(route, path_params, reply)
        row = {
            "org": claims["org"], "actor": claims.get("sub"), "role": claims.get("role"), "source": self.source,
            "method": method, "route": route, "action": action_words(getattr(endpoint, "__name__", None), method, kind),
            "kind": kind, "rid": record_id, "label": label, "ids": json.dumps(path_params), "status": status,
            "cid": headers.get(b"x-correlation-id", b"").decode("latin-1") or None,
        }
        gen = await _connection(self.fastapi_app, scope)
        conn = await gen.__anext__()
        try:
            await write(conn, row)
        except BaseException:
            await gen.athrow(*_exc())  # the transaction rolls back
            raise
        try:  # run the dependency to its end, so its transaction commits
            await gen.__anext__()
        except StopAsyncIteration:
            pass
