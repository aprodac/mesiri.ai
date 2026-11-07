"""A value the database cannot read is the caller's mistake, never a crash.

7 Nov 2026 ([282]): the assistant asked `GET /progress/issues?status=open`.
`site_issues.status` is a Postgres enum (`OPEN`, ...), so Postgres refused the
text, the route crashed, and the person read "The tool failed". More than
twenty routes pass a free-text filter (status, category, role, ...) or an id
straight to SQL, so the fix is here, once, for every route: Postgres error
22P02 ("invalid input value for enum ...", "invalid input syntax for type
uuid ...") becomes a 422 that names the field's bad value and, for an enum
written in the wrong case, the value that was meant. The dashboard and the
assistant read the same answer; the assistant can correct its call at once.

Installed on both apps that serve the API (backend `mesiri.http.app` and the
assistant's `runtime.lifecycle`, which is what production runs).
"""

from __future__ import annotations

import logging
import re

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError

_log = logging.getLogger("mesiri.http.db_errors")

_ENUM = re.compile(r'invalid input value for enum (?P<type>\w+): "(?P<value>[^"]*)"')
_SYNTAX = re.compile(r'invalid input syntax for type (?P<type>\w+): "(?P<value>[^"]*)"')
#: asyncpg refuses some values before Postgres sees them (no SQLSTATE then).
_ARGUMENT = re.compile(r"invalid input for query argument \$\d+: '(?P<value>[^']*)' \(invalid (?P<type>\w+)")


def invalid_value_detail(message: str) -> str | None:
    """The 422 detail for a bad-value message (Postgres 22P02 or asyncpg's argument check), or None when it is not one we can explain."""
    if m := _ENUM.search(message):
        value, kind = m["value"], m["type"]
        hint = f" Did you mean '{value.upper()}'?" if value != value.upper() else ""
        return f"'{value}' is not a valid {kind} value (values are upper case).{hint}"
    if m := _SYNTAX.search(message) or _ARGUMENT.search(message):
        value, kind = m["value"], m["type"]
        if kind.lower() == "uuid":
            return f"'{value}' is not a valid id. Use an id exactly as it was given."
        return f"'{value}' is not a valid {kind}."
    return None


def install(app: FastAPI) -> None:
    @app.exception_handler(DBAPIError)
    async def _db_value_error(request: Request, exc: DBAPIError) -> JSONResponse:
        # Only these messages are a caller's bad value (22P02, or asyncpg's own
        # check of an argument); anything else stays a 500 with its trace.
        detail = invalid_value_detail(str(exc.orig))
        if detail is None:
            # Not a bad value: a real failure. Keep it a 500 and keep the trace.
            _log.exception("db error on %s %s", request.method, request.url.path, exc_info=exc)
            return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})
        _log.info("db_errors.invalid_value path=%s detail=%s", request.url.path, detail)
        return JSONResponse(status_code=422, content={"detail": detail})
