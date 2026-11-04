"""A person's own requests to Mesiri and where each one is (request 230).

Reads the same request log as the platform admin list (requests_router, one shared fetch), keeps only the
caller's, and returns nothing technical. Mounted by both apps and by the assistant's agent API (tool my_requests).
"""

from __future__ import annotations

import re
import uuid
from typing import Any

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.domains.admin.requests_router import _all_items
from mesiri.domains.shared.auth import get_current_user
from mesiri.infrastructure.postgres.dependency import get_db_conn

# ---- "Can I see it?": a person's own requests (request 230) -------------------------------------------------
#: The bot stores *who* as "Name (role, company)" and the message ids (correlation ids) in asked_ref, so the
#: caller is matched through the assistant's message log: the request counts as theirs when one of those
#: messages came from their own WhatsApp number inside their own company. Nothing is matched on the name.
MINE_SQL = sa.text(
    "SELECT DISTINCT im.correlation_id FROM inbound_messages im "
    "JOIN users u ON u.organization_id = im.organization_id AND u.id = :uid "
    "WHERE im.organization_id = :org AND im.correlation_id = ANY(:cids) AND u.whatsapp_number IS NOT NULL "
    "AND regexp_replace(u.whatsapp_number, '\\D', '', 'g') = regexp_replace(im.sender_wa_id, '\\D', '', 'g')"
)
#: The stage the person sees: asked / building / live / dropped. A "broken" one is being fixed again.
MINE_STAGE = {
    "asked": "asked", "waiting": "asked", "building": "building", "broken": "building",
    "live": "live", "verified": "live", "dropped": "dropped",
}
_MINE_ORDER = {"asked": 0, "building": 0, "live": 1, "dropped": 2}


def _plain_title(title: Any) -> str:
    text = re.sub(r"^\s*\[[^\]]{1,40}\]\s*", "", str(title or ""))  # "[bot upgrade] ..." is the team's label
    return re.sub(r"\s+", " ", text).strip()[:200] or "A request"


def my_list(items: list[dict[str, Any]], mine_cids: set[str]) -> list[dict[str, Any]]:
    """Only the requests with one of the caller's messages, once each, open first then live then dropped."""
    best: dict[str, dict[str, Any]] = {}
    for item in items:
        refs = {r.strip() for r in str(item.get("asked_ref") or "").split(",") if r.strip()}
        if not (refs & mine_cids):
            continue
        row = {
            "title": _plain_title(item.get("title")),
            "stage": MINE_STAGE.get(item.get("stage"), "asked"),
            "live_at": item.get("live_at") if MINE_STAGE.get(item.get("stage")) == "live" else None,
            "created_at": item.get("created_at"),
        }
        key = row["title"].casefold()  # the same complaint sent twice is one line
        kept = best.get(key)
        if kept is None or (_MINE_ORDER[row["stage"]], str(row["created_at"])) > (_MINE_ORDER[kept["stage"]], str(kept["created_at"])):
            best[key] = row
    rows = sorted(best.values(), key=lambda r: str(r["created_at"] or ""), reverse=True)  # newest first
    return sorted(rows, key=lambda r: _MINE_ORDER[r["stage"]])


router = APIRouter(prefix="/me", tags=["me"])


@router.get("/requests")
async def my_requests(
    project: str = Query("mesiri", max_length=40, pattern=r"^[a-z0-9_-]+$"),
    conn: AsyncConnection = Depends(get_db_conn),
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """The requests this person asked Mesiri for and where each one is: title, stage, live date, asked date."""
    try:
        uid, org = uuid.UUID(str(user.get("sub"))), uuid.UUID(str(user.get("org")))
    except ValueError:
        return {"items": []}  # a platform admin has no company; they use /admin/requests
    items = [i for i in await _all_items(project) if i.get("asked_by") and i.get("asked_ref")]
    cids = sorted({r.strip() for i in items for r in str(i["asked_ref"]).split(",") if r.strip()})
    if not cids:
        return {"items": []}
    rows = (await conn.execute(MINE_SQL, {"uid": uid, "org": org, "cids": cids})).all()
    return {"items": my_list(items, {str(r.correlation_id) for r in rows})}
