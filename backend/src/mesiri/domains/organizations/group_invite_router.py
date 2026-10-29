"""WA-87: redirect for the `mesiri_group_invite` WhatsApp template button.

Meta refuses a template button that links straight to chat.whatsapp.com (an
anti-abuse rule against templates routing people to other WhatsApp chats), so
the button points here instead and this redirects on to the real invite link.
No tenant or auth context — the code alone is the capability.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse

router = APIRouter(tags=["group-invite"])

# The segment after chat.whatsapp.com/ in a WhatsApp group invite link.
_GROUP_INVITE_CODE = re.compile(r"^[A-Za-z0-9_-]{10,32}$")


@router.get("/j/{code}")
async def whatsapp_group_invite(code: str) -> RedirectResponse:
    if not _GROUP_INVITE_CODE.fullmatch(code):
        raise HTTPException(status_code=404)
    return RedirectResponse(f"https://chat.whatsapp.com/{code}", status_code=302)
