"""PRC-52: a supplier's own papers -- GST certificate, PAN, cancelled cheque, agreement, ISO / BIS, other.

They belong to the company, not a project, so they are kept in ``vendor_documents`` (migration 0545), not in the
project documents register (whose rows and access are per project). Everything else is the register's: the upload
checks (``documents.router._read``: kinds of file, 25 MB, a PDF is a PDF), the storage key pattern
(``documents.router.object_key``) and the short-lived link (``signed_media_url``).

One current paper per kind ("other" may have several): a new upload of the kind supersedes the old one, which stays as
history; archiving hides a paper and brings back the one it replaced. Status per kind: ``valid``, ``expiring`` (within
``EXPIRING_DAYS``), ``expired``, ``missing`` (a required kind with no paper), or ``none`` (optional, not on file).
Required: the GST certificate and PAN of a supplier registered for GST (it has a GSTIN on record); a shop with no
GSTIN has neither to give, so nothing is "missing" for it. The PAN of a registered supplier is read from its GSTIN
(characters 3-12), shown beside the paper, never asked again.

Who (D-DOC1, as the supplier page): GST certificate, ISO / BIS and other papers are seen by anyone who sees the
supplier; PAN, cheque and agreement only by the owner, admin, finance and project managers (``may_view_expenses``),
who also add and archive papers.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

KINDS: dict[str, str] = {"gst": "GST certificate", "pan": "PAN", "cheque": "Cancelled cheque",
                         "agreement": "Agreement", "iso_bis": "ISO / BIS certificate", "other": "Other"}
RESTRICTED_KINDS = frozenset({"pan", "cheque", "agreement"})
REQUIRED_WITH_GSTIN = ("gst", "pan")
#: A paper expiring within this many days is flagged (and shows on Today).
EXPIRING_DAYS = 15

_COLS = ("id", "vendor_id", "kind", "number", "valid_until", "status", "supersedes_id", "object_key", "file_name",
         "content_type", "size_bytes", "notes", "uploaded_by", "created_at")
_SELECT = ", ".join(f"d.{c}" for c in _COLS) + ", u.full_name AS uploaded_by_name"


def pan_from_gstin(gstin: str | None) -> str | None:
    g = (gstin or "").strip().upper()
    return g[2:12] if len(g) == 15 else None


def status_of(doc: dict | None, required: bool, today: datetime.date) -> tuple[str, int | None]:
    """(status, days left) of a kind's current paper."""
    if doc is None:
        return ("missing" if required else "none"), None
    until = doc.get("valid_until")
    if until is None:
        return "valid", None
    left = (until - today).days
    if left < 0:
        return "expired", left
    return ("expiring" if left <= EXPIRING_DAYS else "valid"), left


def _out(doc: dict) -> dict[str, Any]:
    return {"id": str(doc["id"]), "kind": doc["kind"], "number": doc["number"],
            "valid_until": doc["valid_until"].isoformat() if doc["valid_until"] else None, "status": doc["status"],
            "file_name": doc["file_name"], "content_type": doc["content_type"], "size_bytes": doc["size_bytes"],
            "notes": doc["notes"], "uploaded_by_name": doc.get("uploaded_by_name"),
            "created_at": doc["created_at"].isoformat()}


async def fetch(conn: AsyncConnection, org: uuid.UUID, vendor_id: uuid.UUID) -> list[dict]:
    """Every paper of the supplier (current, superseded, archived), newest first."""
    rows = (await conn.execute(text(
        f"SELECT {_SELECT} FROM vendor_documents d LEFT JOIN users u ON u.id = d.uploaded_by "
        "WHERE d.organization_id = :org AND d.vendor_id = :v ORDER BY d.created_at DESC"),
        {"org": org, "v": vendor_id})).mappings().all()
    return [dict(r) for r in rows]


async def one(conn: AsyncConnection, org: uuid.UUID, vendor_id: uuid.UUID, doc_id: uuid.UUID) -> dict | None:
    row = (await conn.execute(text(
        f"SELECT {_SELECT} FROM vendor_documents d LEFT JOIN users u ON u.id = d.uploaded_by "
        "WHERE d.organization_id = :org AND d.vendor_id = :v AND d.id = :id"),
        {"org": org, "v": vendor_id, "id": doc_id})).mappings().first()
    return dict(row) if row else None


def describe(docs: list[dict], *, gstin: str | None, today: datetime.date, see_restricted: bool) -> dict[str, Any]:
    """Per kind the current paper(s), its status and history, what the supplier record already holds; and the worst
    status (``expired`` > ``missing`` > ``expiring`` > ``ok``) for the supplier list and Today."""
    kinds = []
    for kind, label in KINDS.items():
        if kind in RESTRICTED_KINDS and not see_restricted:
            continue
        mine = [d for d in docs if d["kind"] == kind]
        current = [d for d in mine if d["status"] == "current"]
        required = bool(gstin) and kind in REQUIRED_WITH_GSTIN
        status, left = status_of(current[0] if current else None, required, today)
        if kind == "other" and current:
            worst = [status_of(d, False, today) for d in current]
            status, left = min(worst, key=lambda s: ("expired", "expiring", "valid").index(s[0]))
        kinds.append({
            "kind": kind, "label": label, "restricted": kind in RESTRICTED_KINDS, "required": required,
            "status": status, "days_left": left,
            "on_record": (gstin if kind == "gst" else pan_from_gstin(gstin) if kind == "pan" else None),
            "current": [_out(d) for d in current],
            "history": [_out(d) for d in mine if d["status"] == "superseded"],
        })
    return {"kinds": kinds, "attention": attention(kinds)}


def attention(kinds: list[dict]) -> str:
    states = {k["status"] for k in kinds}
    for s in ("expired", "missing", "expiring"):
        if s in states:
            return s
    return "ok"


async def insert(conn: AsyncConnection, org: uuid.UUID, values: dict[str, Any]) -> None:
    if values.get("supersedes_id"):
        await conn.execute(text("UPDATE vendor_documents SET status = 'superseded', updated_at = now() "
                                "WHERE id = :old AND organization_id = :org"), {"old": values["supersedes_id"], "org": org})
    cols = ["organization_id", *values]
    await conn.execute(text(f"INSERT INTO vendor_documents ({', '.join(cols)}) VALUES ({', '.join(':' + c for c in cols)})"),
                       {"organization_id": org, **values})


async def archive(conn: AsyncConnection, org: uuid.UUID, doc: dict) -> None:
    """Kept and hidden (the file stays in storage); the paper it replaced becomes current again."""
    await conn.execute(text("UPDATE vendor_documents SET status = 'archived', updated_at = now() "
                            "WHERE id = :id AND organization_id = :org"), {"id": doc["id"], "org": org})
    if doc["status"] == "current" and doc.get("supersedes_id"):
        await conn.execute(text("UPDATE vendor_documents SET status = 'current', updated_at = now() WHERE id = :old "
                                "AND organization_id = :org AND status = 'superseded'"),
                           {"old": doc["supersedes_id"], "org": org})


async def attention_by_vendor(conn: AsyncConnection, org: uuid.UUID, today: datetime.date, *,
                              see_restricted: bool) -> list[dict]:
    """Suppliers whose papers need attention (expired, missing, expiring), for the supplier list and Today."""
    vendors = (await conn.execute(text("SELECT id, name, gstin FROM vendors WHERE organization_id = :org"),
                                  {"org": org})).mappings().all()
    docs = (await conn.execute(text(
        f"SELECT {_SELECT} FROM vendor_documents d LEFT JOIN users u ON u.id = d.uploaded_by "
        "WHERE d.organization_id = :org AND d.status = 'current'"), {"org": org})).mappings().all()
    by: dict[uuid.UUID, list[dict]] = {}
    for d in docs:
        by.setdefault(d["vendor_id"], []).append(dict(d))
    out = []
    for v in vendors:
        if not v["gstin"] and v["id"] not in by:
            continue  # nothing required, nothing on file
        kinds = describe(by.get(v["id"], []), gstin=v["gstin"], today=today, see_restricted=see_restricted)["kinds"]
        worst = attention(kinds)
        if worst != "ok":
            out.append({"vendor_id": str(v["id"]), "name": v["name"], "attention": worst,
                        "papers": [{"kind": k["kind"], "label": k["label"], "status": k["status"],
                                    "days_left": k["days_left"]} for k in kinds
                                   if k["status"] in ("expired", "missing", "expiring")]})
    order = {"expired": 0, "missing": 1, "expiring": 2}
    out.sort(key=lambda x: (order[x["attention"]], x["name"].lower()))
    return out
