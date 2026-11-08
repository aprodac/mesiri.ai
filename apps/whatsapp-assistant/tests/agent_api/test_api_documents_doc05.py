"""DOC-05 / DR-08 (8 Nov 2026): "send me the latest S-101" and "first floor slab level?" on WhatsApp.

The model finds the document through the dashboard's own route and calls `send_document`; the code fetches the file
through the API (its role check) and sends it. Guards: an out-of-date revision is never sent; a document the person
may not see (404) is never sent; nothing is prepared for Save; a failed send is not called sent.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, Response
from tests.agent_api.replaykit import _real_tools
from tests.agent_api.standin import ACTOR

from agent_api import documents
from agent_api.agent import ApiAgent
from agent_api.client import ApiClient
from agent_api.links import PAGES
from agent_api.tools import ALLOWED, build_tools
from mesiri.domains.shared.auth import get_current_user
from mesiri_ai.fakes import FakeToolCallingProvider

PROJECT = str(uuid.uuid4())
CURRENT, OLD, HIDDEN = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())


def _app(read: list) -> FastAPI:
    app = FastAPI()

    @app.get("/projects/{project_id}/documents/find")
    async def find(project_id: str, q: str, jwt: dict = Depends(get_current_user)):
        read.append(("find", q))
        return {"documents": [{"id": CURRENT, "number": "S-101", "title": "Column layout", "revision": "C"}],
                "folders": {"drawing": 3}}

    @app.get("/documents/{doc_id}/file")
    async def file(doc_id: str, jwt: dict = Depends(get_current_user)):
        read.append(("file", doc_id))
        if doc_id == HIDDEN:
            return Response(status_code=404)
        status = "current" if doc_id == CURRENT else "superseded"
        return Response(content=b"%PDF-1.4 drawing", media_type="application/pdf", headers={
            "Content-Disposition": 'attachment; filename="S-101 rev C.pdf"', "X-Document-Status": status,
            "X-Document-Revision": "C" if status == "current" else "B", "X-Document-Number": "S-101",
            "X-Document-Title": "Column layout"})

    @app.get("/projects/{project_id}/drawing-facts")
    async def facts(project_id: str, q: str | None = None, jwt: dict = Depends(get_current_user)):
        read.append(("facts", q))
        return {"levels": [{"text": "+400 LVL", "value": 400, "drawing": "A-201 Sections", "revision": "C"}],
                "rooms": [], "checks": [], "floors": ["First floor"], "drawings": []}

    return app


class _Sender:
    def __init__(self, ok: bool = True) -> None:
        self.sent: list[tuple] = []
        self.ok = ok

    async def __call__(self, wa_id, data, *, filename, caption=None, mime_type="application/pdf", shows=None):
        self.sent.append((wa_id, data, filename, caption, mime_type))
        return self.ok


async def _client(read: list) -> ApiClient:
    return ApiClient(ACTOR, app=_app(read))


def test_the_tools_are_the_dashboards_routes_and_read_only() -> None:
    tools = _real_tools()
    assert (tools["find_documents"].method, tools["find_documents"].path) == \
        ("GET", "/projects/{project_id}/documents/find")
    assert (tools["drawing_facts"].method, tools["drawing_facts"].path) == ("GET", "/projects/{project_id}/drawing-facts")
    assert not tools["find_documents"].is_write and not tools["drawing_facts"].is_write
    assert PAGES["documents"][0] == "/planning/documents?project={project_id}"


async def test_send_me_the_latest_s101_sends_the_current_file() -> None:
    read: list = []
    app = _app(read)
    sender = _Sender()
    client = ApiClient(ACTOR, app=app)
    tools = build_tools(app.openapi(), tuple(a for a in ALLOWED if a.name == "find_documents"))
    script = [[("find_documents", {"project_id": PROJECT, "q": "S-101"})],
              [(documents.SEND_DOCUMENT, {"document_id": CURRENT})], "S-101 Column layout rev C sent."]
    try:
        turn = await ApiAgent(FakeToolCallingProvider(script), tools).run(
            client, "S-101 latest drawing ayakku", actions={documents.SEND_DOCUMENT: (
                documents.TOOL, lambda a: documents.send(client, sender, "919800000000", a))})
    finally:
        await client.close()
    assert read == [("find", "S-101"), ("file", CURRENT)] and turn.pending == []
    assert sender.sent == [("919800000000", b"%PDF-1.4 drawing", "S-101 rev C.pdf", "S-101 Column layout rev C",
                            "application/pdf")]


async def test_an_old_revision_or_a_hidden_document_is_never_sent() -> None:
    read: list = []
    client = ApiClient(ACTOR, app=_app(read))
    sender = _Sender()
    try:
        old = await documents.send(client, sender, "91", {"document_id": OLD})
        hidden = await documents.send(client, sender, "91", {"document_id": HIDDEN})
        made_up = await documents.send(client, sender, "91", {"document_id": "S-101"})
    finally:
        await client.close()
    assert "out of date" in old["status"] and "no such document" in hidden["status"]
    assert "not a document id" in made_up["status"] and sender.sent == []


async def test_a_failed_send_is_not_called_sent() -> None:
    client = ApiClient(ACTOR, app=_app([]))
    try:
        out = await documents.send(client, _Sender(ok=False), "91", {"document_id": CURRENT})
    finally:
        await client.close()
    assert out["status"].startswith("not sent")


async def test_slab_level_only_reads_the_drawing_facts() -> None:
    read: list = []
    app = _app(read)
    client = ApiClient(ACTOR, app=app)
    tools = build_tools(app.openapi(), tuple(a for a in ALLOWED if a.name == "drawing_facts"))
    try:
        turn = await ApiAgent(FakeToolCallingProvider([[("drawing_facts", {"project_id": PROJECT, "q": "first floor"})],
                                                       "First floor: +400 LVL (A-201 rev C)."]), tools).run(
            client, "first floor slab level?")
    finally:
        await client.close()
    assert read == [("facts", "first floor")] and turn.pending == []


def test_the_sop_rules_for_documents() -> None:
    sop = " ".join((Path(__file__).resolve().parents[2] / "src/agent_api/SOP.md").read_text(encoding="utf-8").split())
    assert "18. Project documents." in sop and "19. What the drawings say" in sop
    assert "never send an older revision" in sop and "never claim a file went" in sop
    assert "never converted to another unit" in sop and "never a guess or a typical value" in sop
