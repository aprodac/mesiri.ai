"""Set the company or a client's logo by sending it on WhatsApp (WA-13).

Owner's decision (19 Oct): a photo whose caption says it is a logo is set
straight away, for both kinds:

    "logo" / "our logo" / "company logo"             -> the company logo (BE-20)
    "client logo for Riverside" / "Riverside logo"   -> that project's client
      (any caption with "client" or "customer", or     logo (BE-33)
       naming one of the sender's projects)

Only the company's admin (owner) can change logos, the same rule as the web
(the dashboard's branding page and PUT /projects/{id}/client-logo). The file
rules are BE-20's (PNG / JPEG / WebP, 700 KB); a bigger WhatsApp photo is
shrunk first. Photos without "logo" in the caption are untouched here, so the
daily setup question (SS-14) still collects letterhead photos for the team.
"""

from __future__ import annotations

import io
import logging
import re
import uuid
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa

from channel.replies import ReplySpec
from mesiri.application.organizations.branding_admin import remove_file, set_logo_key
from mesiri.domains.organizations import branding
from mesiri_contracts.assistant.enums import InputModality

_log = logging.getLogger(__name__)

_CLIENT_WORDS = frozenset({"client", "clients", "customer", "customers"})
_LOGO_MAX_SIDE = 800

ONLY_OWNER = "Only your company's owner can change logos. Ask them to send it."
WHICH_PROJECT = (
    "Which project is this client logo for? Send it again with the project's name, "
    "e.g. *client logo for {example}*."
)
NOT_AN_IMAGE = "I couldn't use that as a logo. Please send it as a photo (PNG or JPG)."
COMPANY_SAVED = "✅ Your company logo is saved. It shows on your daily reports from now on."
CLIENT_SAVED = "✅ Client logo saved for *{project}*. It shows on that project's daily reports."


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


@dataclass(frozen=True, slots=True)
class LogoTarget:
    kind: str  # "company" | "client"
    project_id: str | None = None
    project_name: str | None = None
    unclear: bool = False  # a client logo, but which project isn't clear


def read_caption(caption: str | None, projects: list[Any]) -> LogoTarget | None:
    """What a caption asks for, or None when it doesn't say "logo". Pure."""
    words = _words(caption or "")
    if "logo" not in words and "logos" not in words:
        return None
    said = set(words)
    named = [
        p
        for p in projects
        if (tokens := _words(str(getattr(p, "name", "") or ""))) and set(tokens) <= said
    ]
    client = bool(said & _CLIENT_WORDS)
    if not client and not named:
        return LogoTarget("company")
    if len(named) == 1:
        return LogoTarget("client", str(named[0].id), str(named[0].name))
    if client and not named and len(projects) == 1:
        return LogoTarget("client", str(projects[0].id), str(projects[0].name))
    return LogoTarget("client", unclear=True)


def logo_bytes(data: bytes, content_type: str | None) -> tuple[bytes, str]:
    """`data` as a usable logo (BE-20's rules): as it is when it fits, else
    shrunk to JPEG. Raises ValueError when it isn't an image."""
    try:
        branding.logo_extension(data, content_type or "")
        return data, content_type or "image/jpeg"
    except ValueError:
        pass
    try:
        from PIL import Image

        image = Image.open(io.BytesIO(data))
        image.thumbnail((_LOGO_MAX_SIDE, _LOGO_MAX_SIDE))
        out = io.BytesIO()
        image.convert("RGB").save(out, format="JPEG", quality=85)
    except Exception as exc:  # noqa: BLE001 -- not an image, or no Pillow
        raise ValueError("not a usable image") from exc
    shrunk = out.getvalue()
    branding.logo_extension(shrunk, "image/jpeg")  # still too big -> ValueError
    return shrunk, "image/jpeg"


class LogoFromWhatsApp:
    def __init__(self, *, db: Any, storage: Any) -> None:
        self._db = db
        self._storage = storage

    async def handle_media(self, message: Any, actor: Any) -> ReplySpec | None:
        """The reply when `message` is a logo photo, else None (not handled)."""
        if message.modality not in (InputModality.IMAGE, InputModality.DOCUMENT):
            return None
        if message.media is None or not message.media.object_key:
            return None
        projects = list(getattr(actor, "projects", None) or [])
        target = read_caption(message.text, projects)
        if target is None or not actor.organization_id:
            return None
        if str(actor.role or "").upper() != "ADMIN":
            return ReplySpec(text=ONLY_OWNER)
        if target.unclear:
            example = str(projects[0].name) if projects else "Riverside Tower"
            return ReplySpec(text=WHICH_PROJECT.format(example=example))

        stored = await self._storage.get_object(message.media.object_key)
        try:
            data, content_type = logo_bytes(
                stored.data, stored.content_type or message.media.mime_type
            )
            extension = branding.logo_extension(data, content_type)
        except ValueError:
            return ReplySpec(text=NOT_AN_IMAGE)

        org_id = uuid.UUID(str(actor.organization_id))
        user_id = _uuid_or_none(actor.user_id)
        if target.kind == "company":
            key = branding.company_logo_key(org_id, extension)
            await self._storage.put_object(key, data, content_type=content_type)
            async with self._db.transaction() as conn:
                old = await set_logo_key(conn, org_id, key, updated_by=user_id)
            if old:
                await remove_file(self._storage, old)
            _log.info("logo_from_whatsapp.company_set org=%s", org_id)
            return ReplySpec(text=COMPANY_SAVED)

        project_id = uuid.UUID(str(target.project_id))
        key = branding.client_logo_key(org_id, project_id, extension)
        await self._storage.put_object(key, data, content_type=content_type)
        async with self._db.transaction() as conn:
            old = (
                await conn.execute(
                    sa.text(
                        "SELECT client_logo_object_key FROM projects "
                        "WHERE id = :p AND organization_id = :o FOR UPDATE"
                    ),
                    {"p": project_id, "o": org_id},
                )
            ).scalar_one_or_none()
            await conn.execute(
                sa.text(
                    "UPDATE projects SET client_logo_object_key = :k "
                    "WHERE id = :p AND organization_id = :o"
                ),
                {"k": key, "p": project_id, "o": org_id},
            )
        if old and old != key and branding.owns_key(org_id, old):
            await remove_file(self._storage, old)
        _log.info("logo_from_whatsapp.client_set org=%s project=%s", org_id, project_id)
        return ReplySpec(text=CLIENT_SAVED.format(project=target.project_name))


def _uuid_or_none(value: object) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None
