"""Company letterhead and branding requests, for any given company (SA-09).

One implementation for two callers:

- the dashboard's own `/company/branding*` routes (domains/organizations/
  router.py), where a company admin edits their letterhead;
- the superadmin's control panel (both admin routers), where the Mesiri team
  fills it in from the photos the owner sent on WhatsApp (SS-14).

The rules stay in domains/organizations/branding.py (fields, logo files,
per-company keys) and domains/organizations/setup_questions.py (what a
branding request is). This module only does the I/O around them. Every
function takes the caller's connection and never commits.

A branding request is `{id, status: open|done, created_at, sent_by_user_id,
files: [{object_key, content_type, received_at}], done_at, owner_notified}`.
The team marks it done here; the assistant tells the owner on their next
message and sets `owner_notified` itself. Nothing here sends WhatsApp
messages.
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa

from mesiri.domains.organizations import branding, setup_questions
from mesiri.domains.organizations import settings as org_settings
from mesiri.infrastructure.postgres.repositories.organization_settings import (
    PostgresOrganizationSettingsRepository,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection

    from mesiri_contracts.common.storage import ObjectStoragePort, StoredObject

_log = logging.getLogger(__name__)

LOGO_LINK_SECONDS = 900

# The company's own contact details, printed on the letterhead. They live on
# `organizations` (the dashboard edits them through PATCH /company).
CONTACT_FIELDS: tuple[str, ...] = ("address", "phone", "email")
_CONTACT_MAX = 300


class BrandingAdminError(ValueError):
    """Something that can't be done; `status_code` is what a route answers
    (404 no such company / request / file, 409 already done, 422 bad input)."""

    def __init__(self, message: str, *, status_code: int = 422) -> None:
        super().__init__(message)
        self.status_code = status_code


# ---------------------------------------------------------------------------
# Letterhead (moved from domains/organizations/router.py, behaviour unchanged)
# ---------------------------------------------------------------------------
async def branding_view(
    conn: AsyncConnection, storage: ObjectStoragePort, org_id: uuid.UUID
) -> dict[str, Any] | None:
    """The company's letterhead: account details, branding fields and a
    short-lived logo link. None when there is no such company."""
    org = (
        (
            await conn.execute(
                sa.text("SELECT name, address, phone, email FROM organizations WHERE id = :id"),
                {"id": org_id},
            )
        )
        .mappings()
        .first()
    )
    if org is None:
        return None
    stored = await PostgresOrganizationSettingsRepository(conn).get(org_id, org_settings.BRANDING)
    values = branding.branding_values(stored)
    logo_key = values.pop("logo_object_key")
    has_logo = branding.owns_key(org_id, logo_key)
    logo_url = None
    if has_logo:
        url = await storage.generate_presigned_url(logo_key, expires_in_seconds=LOGO_LINK_SECONDS)
        # With storage not configured (the fake adapter) there is no
        # downloadable link; the page still loads, just without the image.
        logo_url = url if url.startswith(("http://", "https://")) else None
    return {
        "company_name": org["name"],
        "address": org["address"],
        "phone": org["phone"],
        "email": org["email"],
        "has_logo": has_logo,
        "logo_url": logo_url,
        **values,
    }


async def update_branding_text(
    conn: AsyncConnection, org_id: uuid.UUID, update: object, *, updated_by: uuid.UUID | None
) -> dict[str, str | None]:
    """Change any of the branding text fields; fields left out stay as they
    are. Returns the validated changes. Raises ValueError for a bad value."""
    changes = branding.validate_text_fields(update)
    repo = PostgresOrganizationSettingsRepository(conn)
    current = branding.branding_values(await repo.get(org_id, org_settings.BRANDING))
    await repo.set(org_id, org_settings.BRANDING, {**current, **changes}, updated_by=updated_by)
    return changes


async def set_logo_key(
    conn: AsyncConnection, org_id: uuid.UUID, key: str | None, *, updated_by: uuid.UUID | None
) -> str | None:
    """Store `key` as the company logo; returns the key it replaced when that
    file is the company's own and now unused (the caller deletes it after
    commit)."""
    repo = PostgresOrganizationSettingsRepository(conn)
    current = branding.branding_values(await repo.get(org_id, org_settings.BRANDING))
    old = current.get("logo_object_key")
    await repo.set(
        org_id,
        org_settings.BRANDING,
        {**current, "logo_object_key": key},
        updated_by=updated_by,
    )
    return old if branding.owns_key(org_id, old) and old != key else None


async def replace_logo(
    conn: AsyncConnection,
    storage: ObjectStoragePort,
    org_id: uuid.UUID,
    *,
    data_base64: str,
    content_type: str,
    updated_by: uuid.UUID | None,
) -> str | None:
    """Upload a new logo (PNG, JPEG or WebP, up to 700 KB) and make it the
    company's; returns the old key to delete after commit. Raises ValueError
    when the file isn't a usable logo."""
    data, extension, content_type = branding.decode_upload(data_base64, content_type)
    key = branding.company_logo_key(org_id, extension)
    await storage.put_object(key, data, content_type=content_type)
    return await set_logo_key(conn, org_id, key, updated_by=updated_by)


async def remove_file(storage: ObjectStoragePort, key: str) -> None:
    """Delete a file no longer used. Runs after the response, once the new
    key is committed; a failure only leaves an unused file behind."""
    try:
        await storage.delete_object(key)
    except Exception:  # noqa: BLE001
        _log.warning("branding.old_logo_delete_failed key=%s", key, exc_info=True)


def validate_contact(update: object) -> dict[str, str | None]:
    """The address / phone / email fields present in `update`, trimmed (empty
    clears). Pure. Raises BrandingAdminError for anything else."""
    if not isinstance(update, dict):
        raise BrandingAdminError("Expected an object")
    changes: dict[str, str | None] = {}
    for field in CONTACT_FIELDS:
        if field not in update:
            continue
        value = update[field]
        if value is not None and not isinstance(value, str):
            raise BrandingAdminError(f"{field} must be text")
        text = " ".join((value or "").split()) or None
        if text is not None and len(text) > _CONTACT_MAX:
            raise BrandingAdminError(f"{field} is longer than {_CONTACT_MAX} characters")
        changes[field] = text
    return changes


async def update_contact(
    conn: AsyncConnection, org_id: uuid.UUID, changes: dict[str, str | None]
) -> None:
    """Save validated contact fields on the company (only CONTACT_FIELDS)."""
    fields = [f for f in CONTACT_FIELDS if f in changes]
    if not fields:
        return
    await conn.execute(
        sa.text(
            "UPDATE organizations SET "
            + ", ".join(f"{f} = :{f}" for f in fields)
            + ", updated_at = now() WHERE id = :id"
        ),
        {"id": org_id, **{f: changes[f] for f in fields}},
    )


# The company's own details, edited from the control panel's company page
# (SA-03). Timezone is deliberately not here: each project copies it when it
# is created (`reporting_timezone`), so changing it on the company would not
# move any report time.
DETAIL_FIELDS: tuple[str, ...] = ("name", "primary_contact")
_COMPANY_NAME_MAX = 120  # create_company's limit


def validate_details(update: object) -> dict[str, str | None]:
    """The name / primary contact present in `update`, spaces collapsed.
    A name can't be emptied; a primary contact can. Pure. Raises
    BrandingAdminError for anything else."""
    if not isinstance(update, dict):
        raise BrandingAdminError("Expected an object")
    changes: dict[str, str | None] = {}
    for field in DETAIL_FIELDS:
        if field not in update:
            continue
        value = update[field]
        if value is not None and not isinstance(value, str):
            raise BrandingAdminError(f"{field} must be text")
        text = " ".join((value or "").split()) or None
        limit = _COMPANY_NAME_MAX if field == "name" else _CONTACT_MAX
        if field == "name" and text is None:
            raise BrandingAdminError("The company name can't be empty")
        if text is not None and len(text) > limit:
            raise BrandingAdminError(f"{field} is longer than {limit} characters")
        changes[field] = text
    return changes


async def update_details(
    conn: AsyncConnection, org_id: uuid.UUID, changes: dict[str, str | None]
) -> dict[str, dict[str, str | None]]:
    """Save validated details; returns {field: {"before", "after"}} for the
    fields that actually changed (for the audit log). Raises
    BrandingAdminError(404) when the company doesn't exist."""
    current = (
        await conn.execute(
            sa.text("SELECT name, primary_contact FROM organizations WHERE id = :id"),
            {"id": org_id},
        )
    ).mappings().first()
    if current is None:
        raise BrandingAdminError("Organization not found", status_code=404)
    changed = {
        field: {"before": current[field], "after": value}
        for field, value in changes.items()
        if field in DETAIL_FIELDS and current[field] != value
    }
    if changed:
        await conn.execute(
            sa.text(
                "UPDATE organizations SET "
                + ", ".join(f"{f} = :{f}" for f in changed)
                + ", updated_at = now() WHERE id = :id"
            ),
            {"id": org_id, **{f: changes[f] for f in changed}},
        )
    return changed


# ---------------------------------------------------------------------------
# Branding requests (SS-14's photos, worked by the Mesiri team)
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class BrandingRequestItem:
    organization_id: uuid.UUID
    organization_name: str
    id: str
    status: str
    created_at: str | None
    done_at: str | None
    owner_notified: bool
    file_count: int
    files: tuple[dict[str, Any], ...]


def request_items(
    organization_id: uuid.UUID, organization_name: str, stored: object
) -> list[BrandingRequestItem]:
    """A company's stored requests as list items. Pure; anything malformed is
    skipped rather than failing the whole list."""
    if not isinstance(stored, list):
        return []
    items = []
    for raw in stored:
        if not isinstance(raw, dict) or not raw.get("id"):
            continue
        files = tuple(f for f in raw.get("files") or () if isinstance(f, dict))
        items.append(
            BrandingRequestItem(
                organization_id=organization_id,
                organization_name=organization_name,
                id=str(raw["id"]),
                status=str(raw.get("status") or setup_questions.OPEN),
                created_at=raw.get("created_at"),
                done_at=raw.get("done_at"),
                owner_notified=bool(raw.get("owner_notified")),
                file_count=len(files),
                files=files,
            )
        )
    return items


def sort_for_team(items: list[BrandingRequestItem]) -> list[BrandingRequestItem]:
    """Open requests first, oldest first (they've waited longest); then done
    ones, newest first."""
    open_items = sorted(
        (i for i in items if i.status == setup_questions.OPEN), key=lambda i: i.created_at or ""
    )
    done_items = sorted(
        (i for i in items if i.status != setup_questions.OPEN),
        key=lambda i: i.done_at or i.created_at or "",
        reverse=True,
    )
    return open_items + done_items


_ALL_REQUESTS = sa.text(
    "SELECT s.organization_id, o.name, s.value FROM organization_settings s "
    "JOIN organizations o ON o.id = s.organization_id WHERE s.key = :key"
)


async def list_branding_requests(conn: AsyncConnection) -> list[BrandingRequestItem]:
    """Every company's branding requests, open first."""
    rows = (
        (await conn.execute(_ALL_REQUESTS, {"key": org_settings.BRANDING_REQUESTS}))
        .mappings()
        .all()
    )
    items: list[BrandingRequestItem] = []
    for row in rows:
        items.extend(request_items(row["organization_id"], row["name"], row["value"]))
    return sort_for_team(items)


async def company_branding_requests(
    conn: AsyncConnection, org_id: uuid.UUID, org_name: str
) -> list[BrandingRequestItem]:
    stored = await PostgresOrganizationSettingsRepository(conn).get(
        org_id, org_settings.BRANDING_REQUESTS
    )
    return sort_for_team(request_items(org_id, org_name, stored))


def mark_done(requests: object, request_id: str, now: dt.datetime) -> list[dict[str, Any]]:
    """`requests` with that one marked done. Pure. Raises BrandingAdminError
    (404 no such request, 409 already done)."""
    items = [dict(r) for r in requests] if isinstance(requests, list) else []
    target = next((r for r in items if str(r.get("id")) == request_id), None)
    if target is None:
        raise BrandingAdminError("Branding request not found", status_code=404)
    if target.get("status") == setup_questions.DONE:
        raise BrandingAdminError("This request is already done", status_code=409)
    target["status"] = setup_questions.DONE
    target["done_at"] = now.isoformat()
    # The assistant announces it to the owner and sets this to True.
    target["owner_notified"] = False
    return items


_LOCK_REQUESTS = sa.text(
    "SELECT value FROM organization_settings WHERE organization_id = :org AND key = :key FOR UPDATE"
)


async def mark_request_done(
    conn: AsyncConnection,
    org_id: uuid.UUID,
    request_id: str,
    *,
    updated_by: uuid.UUID | None,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    """Mark one branding request done; returns it. The row is locked for
    the read-modify-write so two team members can't both mark it."""
    now = now or dt.datetime.now(dt.UTC)
    row = (
        await conn.execute(_LOCK_REQUESTS, {"org": org_id, "key": org_settings.BRANDING_REQUESTS})
    ).first()
    if row is None:
        raise BrandingAdminError("Branding request not found", status_code=404)
    requests = mark_done(row.value, request_id, now)
    await PostgresOrganizationSettingsRepository(conn).set(
        org_id, org_settings.BRANDING_REQUESTS, requests, updated_by=updated_by
    )
    return next(r for r in requests if str(r.get("id")) == request_id)


async def request_file(
    conn: AsyncConnection,
    storage: ObjectStoragePort,
    org_id: uuid.UUID,
    request_id: str,
    index: int,
) -> tuple[StoredObject, str | None]:
    """The `index`-th photo of one of this company's requests, and its
    content type. Looked up by position, so only the company's own files can
    be served. Raises BrandingAdminError(404) when the request, the file or
    the stored object is gone (the in-memory fake storage forgets on restart)."""
    stored = await PostgresOrganizationSettingsRepository(conn).get(
        org_id, org_settings.BRANDING_REQUESTS
    )
    request = next((i for i in request_items(org_id, "", stored) if i.id == request_id), None)
    if request is None or not 0 <= index < len(request.files):
        raise BrandingAdminError("File not found", status_code=404)
    file = request.files[index]
    key = file.get("object_key")
    if not key:
        raise BrandingAdminError("File not found", status_code=404)
    try:
        obj = await storage.get_object(key)
    except Exception as exc:  # noqa: BLE001 -- any adapter's "missing"
        raise BrandingAdminError("File no longer available", status_code=404) from exc
    return obj, file.get("content_type")
