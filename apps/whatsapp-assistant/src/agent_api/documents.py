"""DOC-05: "send me the latest S-101" -- the file itself in the chat.

The model finds the document with ``find_documents`` (an API route; current revisions only, only what this person
may see) and calls ``send_document`` with its id. The code fetches the file through the same API (the role check
is the API's) and sends it; it never sends a revision that is out of date, and says plainly when it could not send.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from mesiri_ai.models import ToolSpec

from .client import ApiClient

_log = logging.getLogger(__name__)

SEND_DOCUMENT = "send_document"
TOOL = ToolSpec(name=SEND_DOCUMENT, description=(
    "Send one project document (a drawing, permit, report) as a file in this chat: document_id from "
    "find_documents. Only after find_documents gave it; never for a document they did not ask for."),
    parameters={"type": "object", "required": ["document_id"],
                "properties": {"document_id": {"type": "string"}}})


async def send(client: ApiClient, send_document: Callable[..., Awaitable[Any]], wa_id: str,
               arguments: dict[str, Any]) -> dict[str, Any]:
    raw = str(arguments.get("document_id") or "").strip()
    try:
        doc_id = uuid.UUID(raw)
    except ValueError:
        return {"status": "not sent: that is not a document id from find_documents"}
    status, data, headers = await client.fetch_bytes(f"/documents/{doc_id}/file")
    if status == 404:
        return {"status": "not sent: no such document for this person (or they may not see it)"}
    if status != 200 or not data:
        return {"status": "not sent; tell them to ask again in a minute"}
    lower = {k.lower(): v for k, v in headers.items()}
    if lower.get("x-document-status") != "current":
        # Plan risk 1: sending a superseded drawing is worse than sending none.
        return {"status": "not sent: that revision is out of date. Call find_documents again for the current one."}
    name = _file_name(lower.get("content-disposition"), raw)
    shown = " ".join(x for x in (lower.get("x-document-number"), lower.get("x-document-title")) if x) or name
    revision = lower.get("x-document-revision") or ""
    caption = f"{shown}{' rev ' + revision if revision else ''}"
    try:
        sent = await send_document(wa_id, data, filename=name, caption=caption,
                                   mime_type=lower.get("content-type", "application/pdf").split(";")[0],
                                   shows=f"document {caption}")
    except Exception:  # noqa: BLE001 -- the model tells them it did not go
        _log.exception("agent_api.send_document_failed")
        sent = False
    if not sent:
        return {"status": "not sent; tell them to ask again in a minute"}
    return {"status": "sent to their WhatsApp", "sent": caption, "current": True}


def _file_name(disposition: str | None, fallback: str) -> str:
    if disposition and 'filename="' in disposition:
        return disposition.split('filename="', 1)[1].split('"', 1)[0] or fallback
    return f"{fallback}.pdf"
