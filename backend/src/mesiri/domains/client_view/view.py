"""What a client sees of their project (CV-02). Read only; built from what the dashboard already keeps.

Everything leaves through the ``_keep`` allow-lists below: a field is shown only when it is named here. Never on
this page: rates (client or budget), costs, budgets, suppliers, subcontractors, labour, people's names or numbers,
the company's money accounts, anything still in draft.

- **Company:** the letterhead name (or the company name), phone, brand colour and logo.
- **Project:** name, stage, start, contract finish, forecast finish, overall progress.
- **Schedule:** the milestones (all activities when the schedule has no milestones), planned and actual.
- **Photos:** from site reports the company approved or sent (``APPROVED`` / ``PUBLISHED``), on the day of the report:
  nothing a supervisor sent that the engineer has not looked at.
- **Bills:** submitted and certified RA bills (gross, retention, advance recovery, GST, TDS, net, certified), what
  was received against each and what is left; drafts and cancelled bills never.
- **Payments:** confirmed receipts (date, amount, kind, the bill), not the account the money went into.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from mesiri.application.dpr.project_day import company_today, local_date_sql
from mesiri.domains.billing import bills as bill_store
from mesiri.domains.billing import contracts, receivables
from mesiri.domains.billing.receipts import list_receipts
from mesiri.domains.schedule import store as schedule_store
from mesiri.domains.shared.media import signed_media_url
from mesiri_contracts.common.storage import ObjectStoragePort

PHOTO_LIMIT = 40
SCHEDULE_LIMIT = 60

COMPANY_FIELDS = ("name", "phone", "brand_color", "logo_url")
PROJECT_FIELDS = ("name", "stage", "start_date", "contract_finish", "forecast_finish", "slip_days", "progress",
                  "contract_value", "client_name")
SCHEDULE_FIELDS = ("name", "milestone", "start", "end", "actual_start", "actual_end", "done", "progress", "state",
                   "forecast_end")
PHOTO_FIELDS = ("url", "caption", "date", "work")
BILL_FIELDS = ("ref", "bill_date", "period_to", "status", "gross", "retention", "advance_recovery", "gst", "tds", "net",
               "certified_amount", "certified_on", "received", "left")
PAYMENT_FIELDS = ("received_on", "amount", "kind", "bill_ref")
TOTAL_FIELDS = ("billed", "received", "due", "advance_received")


def _keep(row: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {f: row.get(f) for f in fields}


async def _company(conn: AsyncConnection, storage: ObjectStoragePort, org: uuid.UUID) -> dict[str, Any]:
    from mesiri.application.organizations.branding_admin import branding_view

    view = await branding_view(conn, storage, org) or {}
    return _keep({"name": view.get("letterhead_name") or view.get("company_name"), "phone": view.get("phone"),
                  "brand_color": view.get("brand_color"), "logo_url": view.get("logo_url")}, COMPANY_FIELDS)


async def approved_photos(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID, *,
                          date_from: datetime.date | None = None, date_to: datetime.date | None = None,
                          limit: int = PHOTO_LIMIT) -> list[dict[str, Any]]:
    """Photos of site work from days whose site report was confirmed (approved or sent), newest first: the one rule
    for "a photo that may leave the company". The client view reads it, and so does the period report (PRC-19,
    D-R6), with a date range. Rows carry the stored key; signing a link is the caller's."""
    day = local_date_sql("pa.created_at", ":org")
    between = (f" AND {day} >= :f" if date_from else "") + (f" AND {day} <= :t" if date_to else "")
    rows = (await conn.execute(text(f"""
        SELECT pa.media_object_key, pa.caption, a.work_type, a.site_id, {day} AS day
          FROM progress_attachments pa
          JOIN activities a ON a.id = pa.parent_id
         WHERE pa.parent_type = 'ACTIVITY'
           AND a.organization_id = :org AND a.project_id = :p AND a.deleted_at IS NULL
           AND (pa.mime_type ILIKE 'image/%'
                OR (pa.mime_type IS NULL AND pa.attachment_type ILIKE ANY (ARRAY['%photo%', '%image%'])))
           AND EXISTS (
               SELECT 1 FROM daily_reports dr
                WHERE dr.organization_id = :org AND dr.project_id = a.project_id AND dr.site_id = a.site_id
                  AND dr.level::text = 'SITE' AND dr.status::text IN ('APPROVED', 'PUBLISHED')
                  AND dr.report_date = {day}){between}
         ORDER BY pa.created_at DESC, pa.id
         LIMIT :n"""), {"org": org, "p": project_id, "n": limit,  # noqa: S608 (SQL from code)
                       **({"f": date_from} if date_from else {}), **({"t": date_to} if date_to else {})})).mappings().all()
    return [dict(r) for r in rows]


async def _photos(conn: AsyncConnection, storage: ObjectStoragePort, org: uuid.UUID,
                  project_id: uuid.UUID) -> list[dict[str, Any]]:
    out = []
    for r in await approved_photos(conn, org, project_id):
        url = await signed_media_url(storage, r["media_object_key"])
        if url:
            out.append(_keep({"url": url, "caption": r["caption"], "date": r["day"], "work": r["work_type"]},
                             PHOTO_FIELDS))
    return out


async def _money(conn: AsyncConnection, org: uuid.UUID, project_id: uuid.UUID,
                 today: datetime.date) -> dict[str, Any]:
    bills = [b for b in await bill_store.list_bills(conn, org, {project_id})
             if b["status"] in receivables.OWED_STATUSES]
    receipts = await list_receipts(conn, org, {project_id}, confirmed_only=True)
    settled = receivables.settle(
        [{"id": b["id"], "number": b["number"], "project_id": b["project_id"], "bill_date": b["bill_date"],
          "net": Decimal(b["net"] or 0), "status": b["status"]} for b in bills], receipts, today)
    by_id = {b["id"]: b for b in settled["bills"]}
    out_bills = []
    for b in sorted(bills, key=lambda b: b["number"], reverse=True):
        s = by_id.get(b["id"], {})
        out_bills.append(_keep({**b, "received": s.get("received"), "left": s.get("left")}, BILL_FIELDS))
    billed = sum((Decimal(b["net"] or 0) for b in bills), Decimal(0))
    received = sum((Decimal(r["amount"]) for r in receipts if r["kind"] != "advance"), Decimal(0))
    totals = {"billed": billed, "received": received,
              "due": sum((s["left"] for s in settled["bills"]), Decimal(0)),
              "advance_received": settled["advance_received"].get(project_id, Decimal(0))}
    return {"bills": out_bills, "payments": [_keep(r, PAYMENT_FIELDS) for r in receipts],
            "totals": _keep(totals, TOTAL_FIELDS)}


async def build(conn: AsyncConnection, storage: ObjectStoragePort, org: uuid.UUID,
                project_id: uuid.UUID) -> dict[str, Any] | None:
    """The client's page for one project, or None when the project is gone."""
    today = await company_today(conn, org)
    schedule = await schedule_store.load(conn, org, project_id, today)
    proj = schedule["project"]
    if proj is None:
        return None
    contract = await contracts.get_contract(conn, org, project_id) or {}
    summary = schedule["summary"]
    activities = schedule["activities"]
    milestones = [a for a in activities if a["milestone"]]
    project = _keep({
        "name": proj["name"], "stage": proj.get("stage"), "start_date": proj.get("start_date"),
        "contract_finish": summary["contract_finish"], "forecast_finish": summary["forecast_finish"],
        "slip_days": summary["slip_days"], "progress": summary["progress"],
        "contract_value": contract.get("contract_value"),
        "client_name": contract.get("client_name") or proj.get("client"),
    }, PROJECT_FIELDS)
    return {
        "company": await _company(conn, storage, org),
        "project": project,
        "today": today,
        "schedule": [_keep(a, SCHEDULE_FIELDS) for a in (milestones or activities)[:SCHEDULE_LIMIT]],
        "schedule_kind": "milestones" if milestones else "activities",
        "photos": await _photos(conn, storage, org, project_id),
        **await _money(conn, org, project_id, today),
    }
