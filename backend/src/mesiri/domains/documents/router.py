"""REST API for the project documents and drawings register (DOC-01, DOC-05 find, DR-07, DR-08).

  GET    /projects/{project_id}/documents               current documents (folder, status, q, activity), folder
                                                        counts, expiring within 30 days
  POST   /projects/{project_id}/documents               upload one file (multipart, 25 MB); folder, number, title,
                                                        revision guessed from the file name and a drawing's title
                                                        block when not given; a drawing PDF's facts kept (DR-07)
  GET    /projects/{project_id}/documents/find?q=       the best current matches for "latest column drawing"
  GET    /projects/{project_id}/drawing-facts?q=        levels, floors, rooms and checks of the current drawings
  GET    /documents/{doc_id}                            one document, a short-lived link, its revisions
  GET    /documents/{doc_id}/file                       the file itself (download; WhatsApp sends it, DOC-05)
  PATCH  /documents/{doc_id}                            folder, number, title, revision, dates, links, restricted
  POST   /documents/{doc_id}/revisions                  a new revision (multipart); the old one is superseded
  DELETE /documents/{doc_id}                            archive (kept, hidden); never a hard delete
  POST   /documents/{doc_id}/track                      DR-10/11: the drawing's footings (Foundation / B3) and rooms
                                                        (Ground Floor / Kitchen) become places, so site's work lands
  GET    /projects/{project_id}/live-maps               DR-10/11: the live plans: each drawing page coloured by the
                                                        work at each footing and room, per trade, with photos; feed

Who (D-DOC1, approved 8 Nov 2026): everyone on the project sees drawings, approvals, test reports, handover and other
papers, and may upload; contract, BOQ / estimate, work orders and anything marked restricted are seen only by the
owner, admin, finance and project managers (``may_view_expenses``). Revising, archiving, restricting and editing are
for the owner, admin and project managers (and the uploader may correct the details of their own upload).
Plan: docs/plans/project-documents-plan.md.
"""

from __future__ import annotations

import asyncio
import datetime
import hashlib
import logging
import re
import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.authorization.context import AuthorizationContext
from mesiri.authorization.roles import may_view_expenses
from mesiri.domains.documents import live, naming, store
from mesiri.domains.projects.router import get_auth_context
from mesiri.domains.shared.media import signed_media_url
from mesiri.domains.shared.modules import require_module
from mesiri.infrastructure.objectstorage.dependency import get_object_storage
from mesiri.infrastructure.postgres.dependency import get_db_conn
from mesiri_contracts.common.storage import ObjectStoragePort

_log = logging.getLogger(__name__)
router = APIRouter(tags=["documents"], dependencies=[Depends(require_module("dpr"))])

#: D-DOC4: the biggest file kept. (Production nginx caps request bodies at 8 MB until raised: see the tracker.)
MAX_BYTES = 25 * 1024 * 1024
#: Drawing PDFs read for their title block and facts at once per process, and how long a read may take.
_reads = asyncio.Semaphore(2)
READ_SECONDS = 30
#: D-DOC1: who revises, archives, restricts and edits.
MANAGE_ROLES = frozenset({"ADMIN", "OWNER", "SUPER_ADMIN", "PROJECT_MANAGER"})


def may_manage(role: str | None) -> bool:
    return str(role or "").strip().upper() in MANAGE_ROLES


def _in_scope(auth: AuthorizationContext, project_id: uuid.UUID) -> None:
    if not auth.project_scope.grants_all_org_projects and project_id not in auth.project_scope.project_ids:
        raise HTTPException(status_code=403, detail="Not authorized for this project")


async def _project(conn: AsyncConnection, auth: AuthorizationContext, project_id: uuid.UUID) -> str:
    _in_scope(auth, project_id)
    name = await store.project_name(conn, auth.organization_id, project_id)
    if name is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return name


async def _doc(conn: AsyncConnection, auth: AuthorizationContext, doc_id: uuid.UUID) -> dict[str, Any]:
    doc = await store.one(conn, auth.organization_id, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    _in_scope(auth, doc["project_id"])
    if store.is_restricted(doc) and not may_view_expenses(auth.role):
        # Never say it exists to someone who may not see it.
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


def _out(value: Any) -> Any:
    if isinstance(value, datetime.date | datetime.datetime):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dict):
        return {k: _out(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_out(v) for v in value]
    return value


def _row(doc: dict[str, Any]) -> dict[str, Any]:
    out = _out({k: v for k, v in doc.items() if k != "object_key"})
    out["restricted_by_folder"] = doc.get("folder") in naming.RESTRICTED_FOLDERS
    return out


async def _read(upload: UploadFile) -> tuple[bytes, str, str]:
    name = (upload.filename or "document").replace("\\", "/").rsplit("/", 1)[-1].strip() or "document"
    kind = naming.content_type(name)
    if kind is None:
        raise HTTPException(status_code=415, detail="That kind of file is not kept. Send a PDF, a photo (JPG, PNG, "
                                                    "HEIC), Word, Excel or DWG.")
    data = bytearray()
    while chunk := await upload.read(1024 * 1024):
        data.extend(chunk)
        if len(data) > MAX_BYTES:
            raise HTTPException(status_code=413, detail="The file is over 25 MB")
    if not data:
        raise HTTPException(status_code=422, detail="The file is empty")
    if kind == "application/pdf" and not bytes(data[:1024]).lstrip().startswith(b"%PDF"):
        raise HTTPException(status_code=422, detail="That file is not a PDF")
    return bytes(data), name, kind


async def _read_drawing(data: bytes) -> dict[str, Any] | None:
    """The drawing reader's result for a PDF (title block of page 1, facts), or None (not readable, too slow, busy)."""
    from mesiri.domains.drawings.read import read_pdf

    if _reads.locked():
        return None
    async with _reads:
        try:
            return await asyncio.wait_for(asyncio.to_thread(read_pdf, data), timeout=READ_SECONDS)
        except Exception:  # noqa: BLE001 -- a file that cannot be read is still kept
            _log.info("documents.pdf_not_read", exc_info=True)
            return None


def _facts(read: dict[str, Any]) -> dict[str, Any]:
    """DR-07: what is kept of a read (the drafts are rebuilt on the Drawing check page when needed)."""
    keep = ("pages", "project", "client", "architect", "units", "levels", "floors", "fixtures", "checks", "structure")
    sheets = [{k: s.get(k) for k in ("page", "title", "kind", "level", "discipline", "number", "revision", "scale",
                                      "date", "rooms", "levels", "fixtures", "width", "height")}
              for s in read.get("sheets") or []]
    return {**{k: read.get(k) for k in keep}, "sheets": sheets}


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = " ".join(value.split())
    return value or None


def _date(value: str | None, what: str) -> datetime.date | None:
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"{what} is not a date (YYYY-MM-DD)") from exc


def object_key(org: uuid.UUID, owner: str, doc_id: uuid.UUID, name: str) -> str:
    """Where a kept file is stored: ``owner`` is the project id, or ``vendors/<id>`` for a supplier's papers (PRC-52)."""
    safe = re.sub(r"[^A-Za-z0-9._ -]+", "_", name)[:120] or "document"
    return f"documents/{org}/{owner}/{doc_id}/{safe}"


async def _save_file(object_storage: ObjectStoragePort, org: uuid.UUID, project_id: uuid.UUID, doc_id: uuid.UUID,
                     name: str, data: bytes, kind: str) -> str:
    key = object_key(org, str(project_id), doc_id, name)
    await object_storage.put_object(key, data, content_type=kind)
    return key


@router.get("/projects/{project_id}/documents")
async def list_documents(project_id: uuid.UUID, folder: str | None = None,
                         status: str = Query(default="current", pattern="^(current|superseded|archived|all)$"),
                         q: str | None = Query(default=None, max_length=120),
                         work_package_id: uuid.UUID | None = None,
                         auth: AuthorizationContext = Depends(get_auth_context),
                         conn: AsyncConnection = Depends(get_db_conn)):
    name = await _project(conn, auth, project_id)
    see = may_view_expenses(auth.role)
    if folder and folder not in naming.FOLDERS:
        raise HTTPException(status_code=422, detail=f"folder is one of {', '.join(naming.FOLDERS)}")
    rows = await store.listing(conn, auth.organization_id, project_id, see_restricted=see, folder=folder,
                               status=status, q=q, work_package_id=work_package_id)
    return {"project": {"id": str(project_id), "name": name}, "documents": [_row(r) for r in rows],
            "counts": await store.counts(conn, auth.organization_id, project_id, see_restricted=see),
            "expiring": _out(await store.expiring(conn, auth.organization_id, project_id, see_restricted=see)),
            "can_manage": may_manage(auth.role), "sees_restricted": see, "folders": list(naming.FOLDERS)}


@router.post("/projects/{project_id}/documents", status_code=201)
async def upload_document(project_id: uuid.UUID, file: UploadFile = File(...),
                          folder: str | None = Form(default=None), number: str | None = Form(default=None),
                          title: str | None = Form(default=None), revision: str | None = Form(default=None),
                          discipline: str | None = Form(default=None), valid_until: str | None = Form(default=None),
                          restricted: bool = Form(default=False), work_package_id: uuid.UUID | None = Form(default=None),
                          auth: AuthorizationContext = Depends(get_auth_context),
                          conn: AsyncConnection = Depends(get_db_conn),
                          object_storage: ObjectStoragePort = Depends(get_object_storage)):
    """Keep one file. What is not given is guessed (``guessed`` lists those fields so the page can show them for a
    check). A file already kept in this project is refused (409, with the one kept). A drawing whose number is
    already current becomes its new revision (owner, admin, PM only); the old one is marked superseded."""
    await _project(conn, auth, project_id)
    return await _keep(conn, auth, object_storage, project_id, file, supersede=None, given={
        "folder": folder, "number": number, "title": title, "revision": revision, "discipline": discipline,
        "valid_until": valid_until, "restricted": restricted, "work_package_id": work_package_id})


async def _keep(conn: AsyncConnection, auth: AuthorizationContext, object_storage: ObjectStoragePort,
                project_id: uuid.UUID, file: UploadFile, *, supersede: dict[str, Any] | None,
                given: dict[str, Any], guess: bool = True) -> dict[str, Any]:
    """``guess`` False (PRC-52 delivery certificates): what is not given stays empty -- nothing read from the file or
    its name, so a certificate never takes another document's number and becomes its revision."""
    org = auth.organization_id
    data, name, kind = await _read(file)
    sha = hashlib.sha256(data).hexdigest()
    dup = await store.same_file(conn, org, project_id, sha)
    if dup is not None:
        raise HTTPException(status_code=409, detail={"message": f"This file is already kept: {dup['title']}"
                                                                f"{' rev ' + dup['revision'] if dup['revision'] else ''}",
                                                     "document_id": str(dup["id"])})
    read = await _read_drawing(data) if kind == "application/pdf" and guess else None
    first = next((s for s in (read or {}).get("sheets") or [] if s.get("has_text")), None)
    hints = naming.guess(name, first) if guess else {}
    values: dict[str, Any] = {}
    guessed: list[str] = []
    for key in ("folder", "number", "title", "revision", "discipline"):
        value = _clean(given.get(key))
        if value is None and supersede is not None and key in ("folder", "number", "title", "discipline"):
            value = supersede.get(key)
        if value is None:
            value = hints.get(key)
            if value is not None:
                guessed.append(key)
        values[key] = value
    if values["folder"] not in naming.FOLDERS:
        raise HTTPException(status_code=422, detail=f"folder is one of {', '.join(naming.FOLDERS)}")
    if values["folder"] != "drawing":
        values["discipline"] = None
    elif values["discipline"] not in naming.DISCIPLINES:
        values["discipline"] = "other"
    values["title"] = (values["title"] or name)[:200]
    restricted = bool(given.get("restricted")) or (supersede or {}).get("restricted", False)
    if restricted and not may_manage(auth.role):
        raise HTTPException(status_code=403, detail="Only the owner, an admin or a project manager can restrict a "
                                                    "document")

    old = supersede or await store.current_by_number(conn, org, project_id, values["number"])
    if old is not None:
        if not may_manage(auth.role):
            raise HTTPException(status_code=403, detail=f"{values['number']} rev {old['revision'] or '-'} is current; "
                                                        "only the owner, an admin or a project manager can issue a "
                                                        "new revision")
        if supersede is None and (old.get("revision") or "") == (values["revision"] or ""):
            raise HTTPException(status_code=409, detail={
                "message": f"{values['number']} rev {old['revision'] or '-'} is already current. Give the new "
                           f"revision letter, or upload it as a new revision of that document.",
                "document_id": str(old["id"])})

    doc_id = uuid.uuid4()
    key = await _save_file(object_storage, org, project_id, doc_id, name, data, kind)
    facts = _facts(read) if read and values["folder"] == "drawing" and first is not None else None
    plan = ((facts or {}).get("structure") or {}).get("plan")
    if plan and plan.get("page"):
        # DR-10: the footing plan as a picture, so the live plan can colour each footing on the real drawing.
        try:
            from mesiri.domains.drawings.pdf_text import render_png

            png, width, height = await asyncio.wait_for(asyncio.to_thread(render_png, data, plan["page"]), 20)
            plan["image_key"] = f"documents/{org}/{project_id}/{doc_id}/plan-page-{plan['page']}.png"
            await object_storage.put_object(plan["image_key"], png, content_type="image/png")
            plan["image_width"], plan["image_height"] = width, height
        except Exception:  # noqa: BLE001 -- the drawing is still kept; only the picture is missing
            _log.info("documents.plan_image_failed", exc_info=True)
    if facts and live.floor_sheets(facts):
        # DR-11: the floor plans as pictures, so the live plans colour each room on the architect's drawing.
        await live.render_plans(data, facts, object_storage, f"documents/{org}/{project_id}/{doc_id}")
    await store.insert(conn, org, project_id, {
        "id": doc_id, **values, "status": "current", "supersedes_id": old["id"] if old else None,
        "valid_until": _date(given.get("valid_until"), "valid_until"), "restricted": restricted,
        "object_key": key, "file_name": name, "content_type": kind, "size_bytes": len(data), "sha256": sha,
        "pages": (read or {}).get("pages"), "facts": facts, "source": "web",
        "work_package_id": given.get("work_package_id"), "uploaded_by": auth.user_id,
        # PRC-52: a delivery certificate's supplier and GRN.
        "vendor_id": given.get("vendor_id"), "goods_receipt_id": given.get("goods_receipt_id"),
        "notes": _clean(given.get("notes")),
    })
    doc = await store.one(conn, org, doc_id)
    out = _row(doc or {})
    out["guessed"] = guessed
    out["superseded"] = {"id": str(old["id"]), "revision": old.get("revision")} if old else None
    out["checks"] = len((facts or {}).get("checks") or [])
    return out


@router.get("/projects/{project_id}/documents/find")
async def find_documents(project_id: uuid.UUID, q: str = Query(min_length=1, max_length=200),
                         folder: str | None = None,
                         auth: AuthorizationContext = Depends(get_auth_context),
                         conn: AsyncConnection = Depends(get_db_conn)):
    """DOC-05: current revisions only, best first (at most 5), only what this person may see. ``documents`` empty:
    nothing fits; ``folders``: what the project has, to say so."""
    await _project(conn, auth, project_id)
    see = may_view_expenses(auth.role)
    rows = await store.listing(conn, auth.organization_id, project_id, see_restricted=see, folder=folder)
    scored = sorted(((naming.find_score(q, r), r) for r in rows), key=lambda x: -x[0])
    best = [r for s, r in scored if s > 0][:5]
    return {"documents": [{k: _row(r)[k] for k in ("id", "folder", "discipline", "number", "title", "revision",
                                                   "file_name", "created_at", "valid_until")} for r in best],
            "folders": await store.counts(conn, auth.organization_id, project_id, see_restricted=see)}


@router.get("/projects/{project_id}/drawing-facts")
async def drawing_facts(project_id: uuid.UUID, q: str | None = Query(default=None, max_length=200),
                        auth: AuthorizationContext = Depends(get_auth_context),
                        conn: AsyncConnection = Depends(get_db_conn)):
    """DR-08: what the current drawings say: levels (with the sheets they are on), floors, rooms with sizes and
    areas, fixture counts and the checks, each naming its drawing and revision. ``q`` narrows rooms and levels to
    the words ("first floor", "slab", "kitchen")."""
    await _project(conn, auth, project_id)
    drawings = await store.current_drawing_facts(conn, auth.organization_id, project_id)
    words = [w for w in re.split(r"[^a-z0-9]+", (q or "").lower()) if len(w) > 2]
    levels, rooms, checks = [], [], []
    for d in drawings:
        f = d["facts"] or {}
        source = {"document_id": str(d["id"]), "drawing": " ".join(x for x in (d["number"], d["title"]) if x),
                  "revision": d["revision"]}
        for s in f.get("sheets") or []:
            for lv in s.get("levels") or []:
                levels.append({**lv, "sheet": s.get("title"), "page": s.get("page"), **source})
            for r in s.get("rooms") or []:
                rooms.append({**r, "floor": s.get("level"), "sheet": s.get("title"), "page": s.get("page"), **source})
        for c in f.get("checks") or []:
            checks.append({**c, **source})

    def fits(item: dict[str, Any]) -> bool:
        if not words:
            return True
        hay = " ".join(str(v) for v in item.values()).lower()
        return any(w in hay for w in words)

    structures = [{**(d["facts"] or {}).get("structure"), "document_id": str(d["id"]),
                   "drawing": " ".join(x for x in (d["number"], d["title"]) if x), "revision": d["revision"]}
                  for d in drawings if (d["facts"] or {}).get("structure")]
    return {"drawings": [{"document_id": str(d["id"]), "number": d["number"], "title": d["title"],
                          "revision": d["revision"]} for d in drawings],
            # DR-09: a structural set's foundation quantities, footings, columns and slab schedules.
            "structure": [{k: s.get(k) for k in ("drawing", "revision", "document_id", "notes", "foundation",
                                                 "footings", "columns", "columns_kg_per_m", "slabs", "assumptions")}
                          for s in structures],
            "levels": [x for x in levels if fits(x)][:60], "rooms": [x for x in rooms if fits(x)][:80],
            "checks": checks[:30],
            "floors": sorted({f for d in drawings for f in (d["facts"] or {}).get("floors") or []})}


@router.get("/documents/{doc_id}")
async def get_document(doc_id: uuid.UUID, auth: AuthorizationContext = Depends(get_auth_context),
                       conn: AsyncConnection = Depends(get_db_conn),
                       object_storage: ObjectStoragePort = Depends(get_object_storage)):
    doc = await _doc(conn, auth, doc_id)
    out = _row(doc)
    out["url"] = await signed_media_url(object_storage, doc["object_key"])
    out["history"] = _out(await store.history(conn, auth.organization_id, doc))
    out["can_manage"] = may_manage(auth.role)
    if doc["has_facts"]:
        facts = await store.facts(conn, auth.organization_id, doc_id) or {}
        out["facts"] = {k: facts.get(k) for k in ("floors", "levels", "fixtures", "checks", "pages")}
        st = facts.get("structure") or {}
        out["facts"]["foundation"] = st.get("foundation")
        out["facts"]["live_plan"] = bool((st.get("plan") or {}).get("footings") or facts.get("plans"))
    return out


@router.get("/documents/{doc_id}/file")
async def document_file(doc_id: uuid.UUID, auth: AuthorizationContext = Depends(get_auth_context),
                        conn: AsyncConnection = Depends(get_db_conn),
                        object_storage: ObjectStoragePort = Depends(get_object_storage)):
    """The stored file, for the same people who may see the document. ``X-Document-*`` headers name it, so a sender
    can say which revision went (and whether it is still current)."""
    from mesiri_contracts.common.errors import MesiriError

    doc = await _doc(conn, auth, doc_id)
    try:
        stored = await object_storage.get_object(doc["object_key"])
    except MesiriError as exc:
        raise HTTPException(status_code=404, detail="The file is missing from storage") from exc
    safe = re.sub(r'[^A-Za-z0-9._ -]+', "_", doc["file_name"])
    return Response(content=stored.data, media_type=doc["content_type"], headers={
        "Content-Disposition": f'attachment; filename="{safe}"', "Cache-Control": "private, no-store",
        "X-Document-Status": doc["status"], "X-Document-Revision": doc["revision"] or "",
        "X-Document-Number": doc["number"] or "", "X-Document-Title": re.sub(r"[^\x20-\x7e]", "", doc["title"])})


class DocumentChange(BaseModel):
    folder: str | None = None
    discipline: str | None = None
    number: str | None = Field(default=None, max_length=60)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    revision: str | None = Field(default=None, max_length=10)
    revision_date: datetime.date | None = None
    valid_until: datetime.date | None = None
    restricted: bool | None = None
    work_package_id: uuid.UUID | None = None
    notes: str | None = Field(default=None, max_length=1000)

    _c = field_validator("number", "title", "revision", "notes")(_clean)


@router.patch("/documents/{doc_id}")
async def change_document(doc_id: uuid.UUID, body: DocumentChange,
                          auth: AuthorizationContext = Depends(get_auth_context),
                          conn: AsyncConnection = Depends(get_db_conn)):
    doc = await _doc(conn, auth, doc_id)
    if not (may_manage(auth.role) or doc["uploaded_by"] == auth.user_id):
        raise HTTPException(status_code=403, detail="Only the owner, an admin, a project manager or the person who "
                                                    "uploaded it can change a document's details")
    values = body.model_dump(exclude_unset=True)
    if "restricted" in values and not may_manage(auth.role):
        raise HTTPException(status_code=403, detail="Only the owner, an admin or a project manager can restrict a "
                                                    "document")
    if "folder" in values and values["folder"] not in naming.FOLDERS:
        raise HTTPException(status_code=422, detail=f"folder is one of {', '.join(naming.FOLDERS)}")
    if "discipline" in values and values["discipline"] not in (*naming.DISCIPLINES, None):
        raise HTTPException(status_code=422, detail=f"discipline is one of {', '.join(naming.DISCIPLINES)}")
    if values.get("number") and doc["status"] == "current":
        other = await store.current_by_number(conn, auth.organization_id, doc["project_id"], values["number"])
        if other is not None and other["id"] != doc_id:
            raise HTTPException(status_code=409, detail=f"{values['number']} is already another current document")
    if "title" in values and not values["title"]:
        raise HTTPException(status_code=422, detail="A document needs a title")
    await store.update(conn, auth.organization_id, doc_id, values)
    return _row(await store.one(conn, auth.organization_id, doc_id) or {})


@router.post("/documents/{doc_id}/revisions", status_code=201)
async def new_revision(doc_id: uuid.UUID, file: UploadFile = File(...), revision: str | None = Form(default=None),
                       title: str | None = Form(default=None),
                       auth: AuthorizationContext = Depends(get_auth_context),
                       conn: AsyncConnection = Depends(get_db_conn),
                       object_storage: ObjectStoragePort = Depends(get_object_storage)):
    doc = await _doc(conn, auth, doc_id)
    if not may_manage(auth.role):
        raise HTTPException(status_code=403, detail="Only the owner, an admin or a project manager can issue a new "
                                                    "revision")
    if doc["status"] != "current":
        raise HTTPException(status_code=409, detail="Only the current revision can be replaced")
    return await _keep(conn, auth, object_storage, doc["project_id"], file, supersede=doc, given={
        "revision": revision, "title": title, "folder": doc["folder"], "number": doc["number"],
        "discipline": doc["discipline"], "work_package_id": doc["work_package_id"],
        "valid_until": None, "restricted": doc["restricted"]})


@router.delete("/documents/{doc_id}")
async def archive_document(doc_id: uuid.UUID, auth: AuthorizationContext = Depends(get_auth_context),
                           conn: AsyncConnection = Depends(get_db_conn)):
    await _doc(conn, auth, doc_id)
    if not may_manage(auth.role):
        raise HTTPException(status_code=403, detail="Only the owner, an admin or a project manager can archive a "
                                                    "document")
    await store.archive(conn, auth.organization_id, doc_id)
    return {"id": str(doc_id), "status": "archived"}


@router.post("/documents/{doc_id}/track")
async def track_on_site(doc_id: uuid.UUID, auth: AuthorizationContext = Depends(get_auth_context),
                        conn: AsyncConnection = Depends(get_db_conn)):
    """The drawing's footings ("Foundation / B3") and rooms ("Ground Floor / Kitchen") become places, so site's
    WhatsApp updates land on them and the live plans colour them. Places already there are kept (running it again
    adds none). Who: those who set up places (the planning roles)."""
    doc = await _doc(conn, auth, doc_id)
    facts = await store.facts(conn, auth.organization_id, doc_id) if doc["has_facts"] else None
    if not facts or not ((facts.get("structure") or {}).get("plan") or {}).get("footings") and not facts.get("plans"):
        raise HTTPException(status_code=422, detail="This drawing has no footing plan or floor plan with rooms "
                                                    "Mesiri could read")
    if not may_view_expenses(auth.role):
        raise HTTPException(status_code=403, detail="Only the owner, an admin, finance or a project manager can set "
                                                    "up places")
    return await live.track(conn, auth.organization_id, doc["project_id"], facts, auth.user_id)


@router.get("/projects/{project_id}/live-maps")
async def live_maps(project_id: uuid.UUID, auth: AuthorizationContext = Depends(get_auth_context),
                    conn: AsyncConnection = Depends(get_db_conn),
                    object_storage: ObjectStoragePort = Depends(get_object_storage)):
    """DR-10 / DR-11: every live map of the project's current drawings (the foundation, then floor by floor): the
    page as a picture, a marker per footing or room (position as a share of the page, 0..1) with its state overall
    and per trade, its newest photos and whether it changed in the last 48 hours; trades with rooms done; and the
    newest updates (``feed``). ``untracked``: drawings with footings or rooms not yet places."""
    from sqlalchemy import text

    await _project(conn, auth, project_id)
    out = await live.maps(conn, auth.organization_id, project_id, object_storage)
    untracked = {m["document"]["id"]: m["document"] for m in out["maps"] if not m["tracked"]}
    pending = (await conn.execute(text(
        "SELECT id, number, title, revision FROM project_documents WHERE organization_id = :org AND project_id = :p "
        "AND status = 'current' AND (facts -> 'structure' -> 'plan' -> 'footings' IS NOT NULL OR facts -> 'plans' IS "
        "NOT NULL) ORDER BY created_at DESC"), {"org": auth.organization_id, "p": project_id})).mappings().all()
    return {**out, "can_track": may_view_expenses(auth.role),
            "untracked": [untracked[str(d["id"])] for d in pending if str(d["id"]) in untracked]}
