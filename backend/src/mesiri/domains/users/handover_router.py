"""REST API for handing over a person's open work (ADM-03). Owner and admins (``may_hand_over_work``).

  POST /users/{user_id}/handover    {to_user_id, preview}: what moves (and what stays, and why); without preview, moves it
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.authorization.context import AuthorizationContext
from mesiri.authorization.roles import may_hand_over_work
from mesiri.domains.projects.router import get_auth_context
from mesiri.domains.users import handover
from mesiri.http.activity import mark_saved_nothing
from mesiri.infrastructure.postgres.dependency import get_db_conn

router = APIRouter(prefix="/users", tags=["users"])


class HandoverIn(BaseModel):
    to_user_id: uuid.UUID
    preview: bool = False


@router.post("/{user_id}/handover")
async def hand_over_work(user_id: uuid.UUID, body: HandoverIn, response: Response, auth: AuthorizationContext = Depends(get_auth_context),
                         conn: AsyncConnection = Depends(get_db_conn)) -> dict[str, Any]:
    """Give a person's open tasks and schedule activities to someone else (who reaches those projects)."""
    if not may_hand_over_work(auth.role):
        raise HTTPException(status_code=403, detail="Only the owner or an admin hands over someone's work.")
    if body.preview:
        result = await handover.plan(conn, auth.organization_id, user_id, body.to_user_id)
        result.pop("_ids")
        result["moved"] = None
        mark_saved_nothing(response)  # ADM-01: a preview is not a change
        return result
    return await handover.hand_over(conn, auth, user_id, body.to_user_id)
