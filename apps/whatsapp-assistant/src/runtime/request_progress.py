"""TM-69: the person who asked hears that they were understood, and where their request is (asked 3 Nov 2026).

"From the user's side, they should feel understood: the problem I faced is being fixed." Between "passed to the team"
and "it works now" the person heard nothing, sometimes for hours, and nothing at all when a fix got stuck. The team
bot now tells them, through this route, at three moments:

- ``understood``: when the fix is planned. The bot's own line, in their language, says back THEIR problem and what it
  cost them ("the 2 drums of primer you received at Green Villa weren't saved, so its stock is 40 L short"), then the
  fixed words: the team is fixing it now and will message them here when it works.
- ``again``: a fix that came back not right (a "Still wrong" tap, a failed live or real-use check): what the team
  found this time, in the same way. Never a question back: the team finds out and tells them.
- ``slow``: once, when it isn't live after a couple of hours or is waiting for an owner: fixed words, honest, with the
  same reference.

Same locks as the preview route (``previews.check_caller`` / ``checked_request``): off unless ``MESIRI_PREVIEWS=on``,
the bot's token only, the recipient read from the request's own message, v3 companies, the 24-hour window, each
stage once per request (``again`` once per round). The bot's line is checked here: one or two sentences, no links,
no phone numbers, no @mentions. Each message is traced as ``request_progress`` on the request, which is how Mesiri
remembers the request is open (``open_requests``) when the person brings it up again.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Literal

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from runtime import previews

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/teammate-api", tags=["teammate"])

#: The journey trace stage of a progress message (read back by ``open_requests``).
STAGE = "request_progress"
MAX_LINE = 280
_LINK = re.compile(r"https?://|www\.|\.(?:com|in|ai|app|io)\b", re.I)
_PHONE = re.compile(r"\d[\d\s-]{6,}\d")
_WORDING = {"understood": "progress.fixing", "again": "progress.fixing", "slow": "progress.slow"}


class ProgressRequest(BaseModel):
    correlation_id: str = Field(pattern=previews._CID.pattern)
    stage: Literal["understood", "again", "slow"]
    #: In the person's language: their problem said back (understood) or what was found this time (again).
    line: str = Field(default="", max_length=MAX_LINE)
    request_ref: str = Field(default="", max_length=12)
    #: The fix round for ``again`` (2, 3): each round is told once.
    round: int = Field(default=1, ge=1, le=5)


def checked_line(stage: str, line: str) -> str:
    """The bot's line as it may reach a customer, or HTTP 400. Required for understood / again; optional for slow."""
    text = " ".join(str(line or "").split())
    if not text:
        if stage == "slow":
            return ""
        raise HTTPException(status_code=400, detail="line is required: their problem in their words")
    if _LINK.search(text) or _PHONE.search(text) or "@" in text:
        raise HTTPException(status_code=400, detail="no links, phone numbers or @mentions in the line")
    if text.count(".") + text.count("?") + text.count("!") > 4:
        raise HTTPException(status_code=400, detail="one or two sentences")
    return text


def compose(stage: str, line: str, ref: str, language: str) -> str:
    """The message: the bot's line, then the fixed words in their language, then the reference."""
    from runtime.agent.wording import say

    parts = []
    if stage == "again":
        parts.append(say("progress.again_head", language))
    if line:
        parts.append(line)
    parts.append(say(_WORDING[stage], language, ref=ref or ""))
    return "\n\n".join(p.strip() for p in parts if p.strip()).strip()


@router.post("/progress")
async def send_progress(body: ProgressRequest, request: Request, authorization: str | None = Header(default=None)) -> dict:
    previews.check_caller(authorization)
    line = checked_line(body.stage, body.line)
    container = request.app.state.container
    once = f"progress:{body.correlation_id}:{body.stage}" + (f":{body.round}" if body.stage == "again" else "")
    row = await previews.checked_request(container, body.correlation_id, once_key=once)
    from runtime.agent.wording import language_of

    language = language_of(str(row.get("body_text") or "")) or "english"
    text = compose(body.stage, line, body.request_ref, language)
    sent = await container.whatsapp_sender.send_text(str(row["sender_wa_id"]), text)
    try:
        await container.trace_logger.log_stage(
            correlation_id=body.correlation_id, stage=STAGE,
            stage_payload={"stage": body.stage, "line": line, "ref": body.request_ref, "round": body.round, "sent": bool(sent)},
            duration_ms=0, succeeded=bool(sent))
    except Exception:  # noqa: BLE001 -- the message already went
        _log.warning("progress.trace_failed correlation_id=%s", body.correlation_id, exc_info=True)
    _log.info("progress.sent correlation_id=%s stage=%s ok=%s", body.correlation_id, body.stage, sent)
    return {"sent": bool(sent)}


# ---------- remembered: the person's open requests, for the v3 turn ----------

#: How far back an open request is remembered (release notes are dropped after 7 days too).
OPEN_DAYS = 7


async def open_requests(db: Any, sender_wa_id: str, *, live: set[str] | None = None, limit: int = 3) -> list[dict[str, Any]]:
    """The person's requests the team is fixing: the latest progress message per request in the last ``OPEN_DAYS``,
    minus those a release note has named (``live``: their correlation ids, from ``release_notes``). One indexed read."""
    import sqlalchemy as sa

    if live is None:
        from runtime.release_notes import live_correlation_ids

        live = live_correlation_ids()
    async with db.transaction() as conn:
        rows = (await conn.execute(sa.text(
            "SELECT DISTINCT ON (jt.correlation_id) jt.correlation_id, jt.created_at, "
            "jt.stage_payload::jsonb->>'stage' AS stage, jt.stage_payload::jsonb->>'line' AS line, "
            "jt.stage_payload::jsonb->>'ref' AS ref "
            "FROM journey_traces jt JOIN inbound_messages im ON im.correlation_id = jt.correlation_id "
            "WHERE im.sender_wa_id = :wa AND jt.stage = :stage AND jt.created_at > now() - make_interval(days => :days) "
            "ORDER BY jt.correlation_id, jt.created_at DESC"),
            {"wa": sender_wa_id, "stage": STAGE, "days": OPEN_DAYS})).mappings().all()
    out = [dict(r) for r in rows if str(r["correlation_id"]) not in live]
    out.sort(key=lambda r: r["created_at"], reverse=True)
    return out[:limit]


_STAGE_WORDS = {"understood": "being fixed", "again": "being fixed again (the first fix wasn't right)",
                "slow": "taking longer than usual; the person was told"}


def context_block(requests: list[dict[str, Any]]) -> str:
    """The lines the v3 model reads (SOP rule "Open requests"). Empty when there are none."""
    if not requests:
        return ""
    lines = ["OPEN REQUESTS (this person told us about these; the team is on them, not live yet):"]
    for r in requests:
        when = r["created_at"].strftime("%d %b %H:%M") if hasattr(r.get("created_at"), "strftime") else ""
        lines.append(f"- {r.get('ref') or ''} {_STAGE_WORDS.get(str(r.get('stage')), 'being fixed')}"
                     f"{f' (since {when} UTC)' if when else ''}: {str(r.get('line') or '').strip()[:240]}")
    return "\n".join(lines)
