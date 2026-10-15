"""Dashboard side of "continue after the trial" (SS-08).

`POST /company/trial/continue`: the owner asks to keep using Mesiri, from
the dashboard banner shown once the trial has ended (or before). Records
the same continue request WhatsApp's "CONTINUE" does and tells the Mesiri
team's WhatsApp group. Exempt from the read-only trial guard by path.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from mesiri.application.organizations.trial import record_continue_request
from mesiri.domains.shared.auth import require_admin
from runtime.team_notify import TeamNotifier

router = APIRouter(prefix="/company/trial", tags=["trial"])


class ContinueResponse(BaseModel):
    requested: bool
    already_requested: bool


@router.post("/continue", response_model=ContinueResponse)
async def continue_after_trial(
    request: Request, admin: dict = Depends(require_admin)
) -> ContinueResponse:
    org = admin.get("org")
    if not org:
        raise HTTPException(status_code=400, detail="No company on this login")
    database = request.app.state.container.material_db
    async with database.transaction() as conn:
        added = await record_continue_request(
            conn, uuid.UUID(str(org)), user_id=str(admin.get("sub") or ""), via="dashboard"
        )
    if added:
        await TeamNotifier().post(
            f"💰 A trial company wants to continue with Mesiri (from the dashboard, org {org}). "
            "Please call them and convert in the control panel."
        )
    return ContinueResponse(requested=True, already_requested=not added)
