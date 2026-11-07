"""SA-37: announcements -- a message from the Mesiri team to the people of every company, from the control panel.

An announcement is a title, a WhatsApp message and up to four pictures. Sending it queues one ``notifications``
row per person (``rule_key = 'announcement'``, ``subject_id = '<announcement>:<user>'``), so the WhatsApp sender's
own rules decide each delivery: an opt-out stops it, quiet hours hold it, and outside the 24-hour window it waits
for the person's next message (``waiting_window``, at most ``hold_days``) or goes as the approved template. Nothing
here talks to WhatsApp.

Who gets it: active people with a WhatsApp number in active and trial companies, narrowed by company, role or
person. Sending again reaches only people not already queued that day (the notifications dedup key).

Mounted by both apps (backend http/app.py and the assistant's runtime/lifecycle.py), platform admins only. Every
send is in the admin audit log.
"""

from __future__ import annotations

import base64
import binascii
import datetime as dt
import json
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.domains.shared.auth import require_platform_admin
from mesiri.infrastructure.objectstorage.dependency import get_object_storage
from mesiri.infrastructure.postgres.dependency import get_db_conn
from mesiri_contracts.common.storage import ObjectStoragePort

router = APIRouter(prefix="/admin/announcements", tags=["admin"])

RULE_KEY = "announcement"
#: Meta template for people outside the 24-hour window, once approved (docs/ops/whatsapp-templates.md).
TEMPLATE = "mesiri_product_update"
MAX_IMAGES = 4
MAX_IMAGE_BYTES = 5 * 1024 * 1024
IMAGE_TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
#: Role groups the page offers; a list of role names works too.
ROLE_GROUPS = {
    "office": ("ADMIN", "OWNER", "PROJECT_MANAGER", "FINANCE"),
    "site": ("SITE_ENGINEER", "SUPERVISOR", "FOREMAN", "USER"),
}


class AnnouncementIn(BaseModel):
    title: str = Field(min_length=1, max_length=60)
    message: str = Field(min_length=1, max_length=3500)
    hold_days: int = Field(default=7, ge=0, le=14)


class AnnouncementPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=60)
    message: str | None = Field(default=None, min_length=1, max_length=3500)
    hold_days: int | None = Field(default=None, ge=0, le=14)


class Audience(BaseModel):
    """Who: every company (``organization_ids`` empty), some companies, some roles, or some people."""

    organization_ids: list[uuid.UUID] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)
    user_ids: list[uuid.UUID] = Field(default_factory=list)


class ImageIn(BaseModel):
    content_type: str
    data_base64: str


def _roles(audience: Audience) -> list[str]:
    out: list[str] = []
    for role in audience.roles:
        out.extend(ROLE_GROUPS.get(role.lower(), (role.upper(),)))
    return sorted(set(out))


_PEOPLE = """
    SELECT u.id AS user_id, u.organization_id, o.name AS company, o.status AS company_status, upper(u.role) AS role,
           EXISTS (
               SELECT 1 FROM inbound_messages m
                WHERE m.received_at > now() - interval '24 hours'
                  AND regexp_replace(m.sender_wa_id, '\\D', '', 'g') = regexp_replace(u.whatsapp_number, '\\D', '', 'g')
           ) AS in_window
      FROM users u
      JOIN organizations o ON o.id = u.organization_id
     WHERE u.status = 'active'
       AND COALESCE(btrim(u.whatsapp_number), '') <> ''
       AND o.status IN ('active', 'trial')
       AND (CAST(:orgs AS uuid[]) IS NULL OR u.organization_id = ANY(CAST(:orgs AS uuid[])))
       AND (CAST(:roles AS text[]) IS NULL OR upper(u.role) = ANY(CAST(:roles AS text[])))
       AND (CAST(:users AS uuid[]) IS NULL OR u.id = ANY(CAST(:users AS uuid[])))
     ORDER BY o.name, u.id
"""


async def _people(conn: AsyncConnection, audience: Audience) -> list[dict[str, Any]]:
    roles = _roles(audience)
    rows = await conn.execute(text(_PEOPLE), {
        "orgs": [str(o) for o in audience.organization_ids] or None,
        "roles": roles or None,
        "users": [str(u) for u in audience.user_ids] or None,
    })
    return [dict(r._mapping) for r in rows]


def _reach(people: list[dict[str, Any]]) -> dict[str, Any]:
    companies: dict[str, dict[str, Any]] = {}
    for p in people:
        c = companies.setdefault(str(p["organization_id"]), {
            "organization_id": str(p["organization_id"]), "name": p["company"], "status": p["company_status"],
            "people": 0, "in_window": 0})
        c["people"] += 1
        c["in_window"] += int(bool(p["in_window"]))
    return {
        "people": len(people),
        "in_window": sum(1 for p in people if p["in_window"]),
        "companies": sorted(companies.values(), key=lambda c: (-c["people"], c["name"])),
    }


async def _get(conn: AsyncConnection, announcement_id: uuid.UUID, *, lock: bool = False) -> dict[str, Any]:
    sql = "SELECT * FROM announcements WHERE id = :id" + (" FOR UPDATE" if lock else "")
    row = (await conn.execute(text(sql), {"id": announcement_id})).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Announcement not found")
    return dict(row._mapping)


async def _deliveries(conn: AsyncConnection, ids: list[uuid.UUID]) -> dict[str, dict[str, int]]:
    """Per announcement: how many queued rows are sent, waiting, skipped (by reason)."""
    if not ids:
        return {}
    rows = await conn.execute(text(
        """
        SELECT split_part(subject_id, ':', 1) AS announcement_id,
               CASE WHEN status = 'skipped' THEN 'skipped:' || COALESCE(skip_reason, '?') ELSE status END AS state,
               count(*) AS n
          FROM notifications
         WHERE rule_key = :rule AND split_part(subject_id, ':', 1) = ANY(:ids)
         GROUP BY 1, 2
        """), {"rule": RULE_KEY, "ids": [str(i) for i in ids]})
    out: dict[str, dict[str, int]] = {}
    for r in rows:
        out.setdefault(r.announcement_id, {})[r.state] = int(r.n)
    return out


def _view(row: dict[str, Any], deliveries: dict[str, int]) -> dict[str, Any]:
    return {
        "id": str(row["id"]), "title": row["title"], "message": row["message"],
        "images": len(row["image_keys"] or []), "hold_days": row["hold_days"],
        "created_at": row["created_at"].isoformat(), "updated_at": row["updated_at"].isoformat(),
        "sends": row["sends"] or [], "deliveries": deliveries,
    }


@router.get("")
async def list_announcements(_admin: dict = Depends(require_platform_admin),
                             conn: AsyncConnection = Depends(get_db_conn)):
    rows = [dict(r._mapping) for r in await conn.execute(
        text("SELECT * FROM announcements ORDER BY created_at DESC LIMIT 100"))]
    deliveries = await _deliveries(conn, [r["id"] for r in rows])
    return {"items": [_view(r, deliveries.get(str(r["id"]), {})) for r in rows]}


@router.post("", status_code=201)
async def create_announcement(body: AnnouncementIn, admin: dict = Depends(require_platform_admin),
                              conn: AsyncConnection = Depends(get_db_conn)):
    row = (await conn.execute(text(
        "INSERT INTO announcements (title, message, hold_days, created_by) VALUES (:t, :m, :h, :by) RETURNING *"),
        {"t": body.title.strip(), "m": body.message.strip(), "h": body.hold_days, "by": _admin_id(admin)})).first()
    return _view(dict(row._mapping), {})  # type: ignore[union-attr]


@router.patch("/{announcement_id}")
async def update_announcement(announcement_id: uuid.UUID, body: AnnouncementPatch,
                              _admin: dict = Depends(require_platform_admin),
                              conn: AsyncConnection = Depends(get_db_conn)):
    """Edit the words or the hold. People already queued keep what was queued for them."""
    await _get(conn, announcement_id, lock=True)
    changes = {k: (v.strip() if isinstance(v, str) else v) for k, v in body.model_dump(exclude_none=True).items()}
    if changes:
        sets = ", ".join(f"{k} = :{k}" for k in changes)
        await conn.execute(text(f"UPDATE announcements SET {sets}, updated_at = now() WHERE id = :id"),  # noqa: S608
                           {**changes, "id": announcement_id})
    row = await _get(conn, announcement_id)
    return _view(row, (await _deliveries(conn, [announcement_id])).get(str(announcement_id), {}))


@router.post("/{announcement_id}/images", status_code=201)
async def add_image(announcement_id: uuid.UUID, body: ImageIn, _admin: dict = Depends(require_platform_admin),
                    conn: AsyncConnection = Depends(get_db_conn),
                    storage: ObjectStoragePort = Depends(get_object_storage)):
    """A picture sent with the message (a screenshot): PNG, JPEG or WebP, at most 5 MB, at most four."""
    row = await _get(conn, announcement_id, lock=True)
    keys = list(row["image_keys"] or [])
    if len(keys) >= MAX_IMAGES:
        raise HTTPException(status_code=422, detail=f"At most {MAX_IMAGES} pictures.")
    ext = IMAGE_TYPES.get(body.content_type.lower())
    if ext is None:
        raise HTTPException(status_code=422, detail="A picture is PNG, JPEG or WebP.")
    try:
        data = base64.b64decode(body.data_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=422, detail="The picture could not be read.") from exc
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=422, detail="A picture is at most 5 MB.")
    key = f"announcements/{announcement_id}/{uuid.uuid4().hex}.{ext}"
    await storage.put_object(key, data, content_type=body.content_type.lower())
    keys.append(key)
    await conn.execute(text("UPDATE announcements SET image_keys = CAST(:k AS jsonb), updated_at = now() WHERE id = :id"),
                       {"k": json.dumps(keys), "id": announcement_id})
    return {"images": len(keys)}


@router.get("/{announcement_id}/images/{index}")
async def get_image(announcement_id: uuid.UUID, index: int, _admin: dict = Depends(require_platform_admin),
                    conn: AsyncConnection = Depends(get_db_conn),
                    storage: ObjectStoragePort = Depends(get_object_storage)):
    keys = (await _get(conn, announcement_id))["image_keys"] or []
    if not 0 <= index < len(keys):
        raise HTTPException(status_code=404, detail="No such picture")
    stored = await storage.get_object(keys[index])
    return Response(content=stored.data, media_type=getattr(stored, "content_type", None) or "image/png")


@router.delete("/{announcement_id}/images/{index}", status_code=204)
async def remove_image(announcement_id: uuid.UUID, index: int, _admin: dict = Depends(require_platform_admin),
                       conn: AsyncConnection = Depends(get_db_conn)):
    """Takes the picture off the announcement (people already queued keep theirs)."""
    keys = list((await _get(conn, announcement_id, lock=True))["image_keys"] or [])
    if not 0 <= index < len(keys):
        raise HTTPException(status_code=404, detail="No such picture")
    keys.pop(index)
    await conn.execute(text("UPDATE announcements SET image_keys = CAST(:k AS jsonb), updated_at = now() WHERE id = :id"),
                       {"k": json.dumps(keys), "id": announcement_id})


@router.post("/audience")
async def audience(body: Audience, _admin: dict = Depends(require_platform_admin),
                   conn: AsyncConnection = Depends(get_db_conn)):
    """Who an announcement would reach: people per company, and how many messaged Mesiri in the last 24 hours
    (they get it at once; the others when they next message, or by the template once it is approved)."""
    return _reach(await _people(conn, body))


@router.post("/{announcement_id}/send")
async def send_announcement(announcement_id: uuid.UUID, body: Audience,
                            admin: dict = Depends(require_platform_admin),
                            conn: AsyncConnection = Depends(get_db_conn)):
    """Queue it for everyone in the audience. The WhatsApp worker sends within a minute (inside the 24-hour
    window), holds it until their next message (outside it), and skips opted-out numbers."""
    from mesiri.application.audit.record import record_admin_action
    from mesiri.domains.audit.actions import ANNOUNCEMENT_SENT, actor_from_admin

    row = await _get(conn, announcement_id, lock=True)
    people = await _people(conn, body)
    if not people:
        raise HTTPException(status_code=422, detail="Nobody to send to: no one with a WhatsApp number matches.")
    today = dt.date.today()
    payload = {
        "message": row["message"],
        "images": list(row["image_keys"] or []),
        "hold_until_window": row["hold_days"] > 0,
        "hold_days": row["hold_days"],
        "template": {"name": TEMPLATE, "body_params": [row["title"]]},
    }
    queued = 0
    for person in people:
        result = await conn.execute(text(
            """
            INSERT INTO notifications (id, organization_id, rule_key, subject_id, occurred_on, recipient_user_id,
                                       payload)
            VALUES (:id, :org, :rule, :subject, :day, :user, CAST(:payload AS jsonb))
            ON CONFLICT ON CONSTRAINT uq_notifications_dedup DO NOTHING
            RETURNING id
            """), {"id": uuid.uuid4(), "org": person["organization_id"], "rule": RULE_KEY,
                   "subject": f"{announcement_id}:{person['user_id']}", "day": today,
                   "user": person["user_id"], "payload": json.dumps(payload)})
        queued += int(result.first() is not None)
    reach = _reach(people)
    send = {"at": dt.datetime.now(dt.UTC).isoformat(), "by": admin.get("name") or admin.get("sub"),
            "organization_ids": [str(o) for o in body.organization_ids], "roles": body.roles,
            "user_ids": [str(u) for u in body.user_ids], "people": reach["people"], "queued": queued}
    await conn.execute(text(
        "UPDATE announcements SET sends = sends || CAST(:s AS jsonb), updated_at = now() WHERE id = :id"),
        {"s": json.dumps([send]), "id": announcement_id})
    await record_admin_action(
        conn, actor=actor_from_admin(admin), action=ANNOUNCEMENT_SENT, target_type="announcement",
        target_id=announcement_id, summary=f"Announcement \"{row['title']}\" queued for {queued} people",
        details={"companies": len(reach["companies"]), "people": reach["people"], "queued": queued,
                 "in_window": reach["in_window"], "roles": body.roles})
    return {"queued": queued, "already": reach["people"] - queued, **reach}


def _admin_id(admin: dict) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(admin.get("sub")))
    except ValueError:
        return None
