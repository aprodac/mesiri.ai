"""The company letterhead printed on a DPR (BE-19).

Gathers what BE-20/BE-33 store -- the company record, its `branding` setting
and the project's client logo -- into one value the template renders. Logos
are embedded as data URIs so the headless browser never has to fetch
anything over the network.

A letterhead never stops a DPR: a missing or unreadable logo, or no branding
at all, falls back to the plain header.
"""

from __future__ import annotations

import base64
import logging
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

_IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/webp"})
_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")


@dataclass(frozen=True, slots=True)
class Letterhead:
    company_name: str
    address: str = ""
    contact: str = ""  # phone · email
    gstin: str = ""
    brand_color: str | None = None
    signatory_name: str = ""
    signatory_designation: str = ""
    logo_data_uri: str | None = None
    client_name: str = ""
    client_logo_data_uri: str | None = None


async def _data_uri(object_storage: Any, organization_id: Any, key: object) -> str | None:
    from mesiri.domains.organizations import branding

    if not branding.owns_key(organization_id, key):
        return None
    try:
        stored = await object_storage.get_object(key)
    except Exception:  # noqa: BLE001 -- a lost logo must not stop the report
        logger.warning("dpr_letterhead.logo_unreadable key=%s", key, exc_info=True)
        return None
    if stored.content_type not in _IMAGE_TYPES or not stored.data:
        return None
    return f"data:{stored.content_type};base64,{base64.b64encode(stored.data).decode()}"


async def _letterhead_row(conn: Any, daily_report_id: Any, branding_key: str) -> Any:
    # A savepoint where the connection offers one: callers may hand over the
    # transaction that is about to send the DPR, and a failed lookup here must
    # not leave that transaction unusable.
    begin_nested = getattr(conn, "begin_nested", None)
    if begin_nested is None:
        return await _fetch(conn, daily_report_id, branding_key)
    async with begin_nested():
        return await _fetch(conn, daily_report_id, branding_key)


async def _fetch(conn: Any, daily_report_id: Any, branding_key: str) -> Any:
    from sqlalchemy import text

    return (
        (
            await conn.execute(
                text(
                    "SELECT o.id AS organization_id, o.name, o.address, o.phone, o.email, "
                    "       p.client, p.client_logo_object_key, s.value AS branding "
                    "FROM daily_reports dr "
                    "JOIN organizations o ON o.id = dr.organization_id "
                    "LEFT JOIN projects p ON p.id = dr.project_id "
                    "LEFT JOIN organization_settings s "
                    "  ON s.organization_id = o.id AND s.key = :key "
                    "WHERE dr.id = :id"
                ),
                {"id": daily_report_id, "key": branding_key},
            )
        )
        .mappings()
        .first()
    )


async def load_letterhead(
    conn: Any, object_storage: Any, daily_report_id: Any
) -> Letterhead | None:
    """The letterhead for one DPR, or None when it can't be loaded (no such
    report, or any error -- the DPR is then sent with the plain header)."""
    from mesiri.domains.organizations import branding
    from mesiri.domains.organizations import settings as org_settings

    try:
        row = await _letterhead_row(conn, daily_report_id, org_settings.BRANDING)
    except Exception:  # noqa: BLE001 -- the DPR goes out with the plain header
        logger.warning("dpr_letterhead.load_failed report=%s", daily_report_id, exc_info=True)
        return None
    if row is None:
        return None
    org_id = row["organization_id"]
    values = branding.branding_values(row["branding"])
    color = values.get("brand_color")
    return Letterhead(
        company_name=str(values.get("letterhead_name") or row["name"] or ""),
        address=row["address"] or "",
        contact=" · ".join(v for v in (row["phone"], row["email"]) if v),
        gstin=str(values.get("gstin") or ""),
        brand_color=color if isinstance(color, str) and _COLOR.match(color) else None,
        signatory_name=str(values.get("signatory_name") or ""),
        signatory_designation=str(values.get("signatory_designation") or ""),
        logo_data_uri=await _data_uri(object_storage, org_id, values.get("logo_object_key")),
        client_name=row["client"] or "",
        client_logo_data_uri=await _data_uri(object_storage, org_id, row["client_logo_object_key"]),
    )
