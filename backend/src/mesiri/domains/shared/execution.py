"""WA-121: an API endpoint that records through the same save handler as WhatsApp.

The handlers (application/*/handlers.py ``execute``) validate and save in their own
transaction, with an idempotency check. These helpers give the endpoint the
handler's database, check the site belongs to the project, and turn the
handler's ExecutionResult into the HTTP answer.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.domains.shared.modules import database_for
from mesiri_contracts.application.results.execution_result import ExecutionResult, ExecutionStatus

_KEY_NAMESPACE = uuid.UUID("5b1e2f0c-6f3a-4c55-9d0e-1f8a7c2b9e41")


def idempotency_uuid(organization_id: uuid.UUID, client_key: str | None) -> str:
    """The key the save handler is given: a UUID (the handlers treat it as the
    WhatsApp workflow id and skip one that matches no workflow), derived from the
    client's ``Idempotency-Key`` *and the company*, so a retry is the same key and two
    companies' keys never meet in the shared idempotency table. No key: a fresh one."""
    if not client_key:
        return str(uuid.uuid4())
    return str(uuid.uuid5(_KEY_NAMESPACE, f"{organization_id}:{client_key}"))


def handler_database(request: Request) -> Any:
    database = database_for(request)
    if database is None:
        raise HTTPException(status_code=503, detail="Recording is not available here")
    return database


async def assert_site_in_project(
    conn: AsyncConnection, organization_id: uuid.UUID, project_id: uuid.UUID, site_id: uuid.UUID | None
) -> None:
    if site_id is None:
        return
    row = (
        await conn.execute(
            text("SELECT project_id FROM sites WHERE id = :site AND organization_id = :org"),
            {"site": site_id, "org": organization_id},
        )
    ).first()
    if row is None or row[0] != project_id:
        raise HTTPException(status_code=404, detail="Site not found in this project")


def execution_response(result: ExecutionResult) -> JSONResponse:
    """201 recorded, 200 the same Idempotency-Key again, 422 refused with the reasons."""
    if result.status == ExecutionStatus.REJECTED:
        return JSONResponse(status_code=422, content={"detail": result.rejection_reasons})
    replayed = result.status == ExecutionStatus.ALREADY_EXECUTED
    return JSONResponse(
        status_code=200 if replayed else 201,
        content={
            "status": "replayed" if replayed else "created",
            "id": result.material_row_id,
            **({"note": result.conflict_note} if result.conflict_note else {}),
        },
    )
