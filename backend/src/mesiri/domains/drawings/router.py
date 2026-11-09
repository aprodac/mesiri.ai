"""REST API for the drawing reader (DR-04).

  POST /drawings/read     body: the drawing PDF itself (Content-Type: application/pdf), up to 50 MB

Returns the set's sheets (title block, kind, floor), levels, rooms with sizes and areas, fixture counts, and the
checks (things to ask the architect). Nothing is stored: the result goes back to the person who uploaded the set
(D-DR1). Who: the roles that plan (owner, admin, finance, project manager), as the other Planning pages.
Plan: docs/plans/drawing-reader-plan.md.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request

from mesiri.authorization.context import AuthorizationContext
from mesiri.authorization.roles import may_view_expenses
from mesiri.domains.drawings import pdf_text
from mesiri.domains.drawings.read import read_pdf
from mesiri.domains.projects.router import get_auth_context
from mesiri.domains.shared.modules import require_module
from mesiri.http.activity import saves_nothing

router = APIRouter(prefix="/drawings", tags=["drawings"], dependencies=[Depends(require_module("dpr"))])

#: The biggest drawing PDF read (a large architectural set is 20-40 MB).
MAX_BYTES = 50 * 1024 * 1024
#: Seconds a read may take (a 9-sheet set takes 0.3 s); a file that takes longer is refused, not waited on.
TIME_LIMIT = 45
#: Reads at once per server process, so a few big files never take every worker.
_reads = asyncio.Semaphore(2)


@router.post("/read")
@saves_nothing  # ADM-01: changes nothing, so not in the activity log
async def read_drawing(request: Request, auth: AuthorizationContext = Depends(get_auth_context)):
    if not may_view_expenses(auth.role):
        raise HTTPException(status_code=403, detail="The drawing check is for the people who plan the project")
    if int(request.headers.get("content-length") or 0) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="The PDF is over 50 MB")
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > MAX_BYTES:
            raise HTTPException(status_code=413, detail="The PDF is over 50 MB")
    if not data.startswith(b"%PDF"):
        raise HTTPException(status_code=422, detail="That file is not a PDF. Send the drawing as a PDF (from CAD, "
                                                    "not a photo).")
    if _reads.locked():
        raise HTTPException(status_code=429, detail="Other drawings are being read right now: try again in a minute")
    async with _reads:
        try:
            result = await asyncio.wait_for(asyncio.to_thread(read_pdf, bytes(data)), timeout=TIME_LIMIT)
        except pdf_text.NotAPdf as exc:
            raise HTTPException(status_code=422, detail=f"The PDF could not be read: {exc}") from exc
        except TimeoutError as exc:
            raise HTTPException(status_code=422, detail="This PDF takes too long to read. Send the sheets in smaller "
                                                        "sets.") from exc
    result["file_name"] = request.headers.get("x-file-name")
    return result
