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

from mesiri_contracts.common.errors import MesiriError

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


def _db_error_in(exc: BaseException) -> DBAPIError | None:
    """The DBAPIError behind ``exc``. `get_db_conn`'s transaction re-raises every
    database error as MesiriError[POSTGRES_UNAVAILABLE] (database.py), so a bad
    value arrives wrapped; found by following the cause chain."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        if isinstance(current, DBAPIError):
            return current
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return None


def install(app: FastAPI) -> None:
    @app.exception_handler(DBAPIError)
    @app.exception_handler(MesiriError)
    async def _db_value_error(request: Request, exc: Exception) -> JSONResponse:
        # Only these messages are a caller's bad value (22P02, or asyncpg's own
        # check of an argument). Anything else is re-raised untouched, so a real
        # failure is the same 500, logged and reported exactly as before.
        db_error = _db_error_in(exc)
        detail = invalid_value_detail(str(db_error.orig)) if db_error is not None else None
        if detail is None:
            raise exc
        _log.info("db_errors.invalid_value path=%s detail=%s", request.url.path, detail)
        return JSONResponse(status_code=422, content={"detail": detail})
