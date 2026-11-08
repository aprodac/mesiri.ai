"""A subcontractor on Mesiri's WhatsApp (NXT-16, option B; approved by Alan 8 Nov 2026). Plan: subcontractors-plan.md S6.

v3 as for staff (one model + an SOP + API routes as tools), with a different, short list: only the ``/partner`` routes,
called with the contact's own token (signed apart: every staff route refuses it). What they send needs no Save card:
the API records it as waiting for the company (a bill for the check, work for the engineer), so it is sent at once and
the reply says it waits. Reached only for a number that is not a staff member (message_journey's unregistered branch).
"""

from __future__ import annotations

import logging
import re
from typing import Any

from agent_api.agent import ApiAgent, confirm
from agent_api.client import ApiClient
from agent_api.tools import Allowed, build_tools

_log = logging.getLogger("mesiri.partner")

PARTNER_ALLOWED: tuple[Allowed, ...] = (
    Allowed("my_statement", "GET", "/partner/statement",
            "What is pending for this subcontractor with the company: payable now, retention held, advance still to "
            "recover, bills waiting for the company's check, and each work order's progress."),
    Allowed("my_work_orders", "GET", "/partner/work-orders",
            "Their work orders: each line (id, work, unit, agreed quantity and rate, done, billed, left) and their bills "
            "with status and what was held or deducted."),
    Allowed("report_work_done", "POST", "/partner/work-done",
            "Report work they finished: work_order_id and line_id (from my_work_orders), quantity, done_on when not "
            "today, notes. It waits for the site engineer before it counts."),
    Allowed("send_bill", "POST", "/partner/bills",
            "Send their bill on a work order: work_order_id, lines [{line_id, quantity, rate only when it differs from "
            "the agreed}], amount when they said the bill's total, their_bill_no. It waits for the company's check; the "
            "answer says what the check found."),
)

PARTNER_SOP = """You are Mesiri, the assistant of a construction company, talking on WhatsApp with one of its \
subcontractors (an outside team that works for the company at agreed rates). You only know their own work orders, \
bills, payments and balance, through the tools; you know nothing else about the company and never guess.

Rules:
- Answer in their language (Malayalam, Manglish, Tamil, Hindi or English, as they wrote). Short, plain, with numbers.
- "How much is pending / when will I get paid / balance": my_statement. Say payable now first, then what waits for the \
company's check, retention held (released after the work is complete) and advance still to recover.
- Work they finished ("40 m³ concreting done on Block A"): find the line with my_work_orders, then report_work_done. \
Say it is sent and waits for the site engineer to confirm.
- Their bill ("bill 15,200 for 40 m³"): find the work order and lines with my_work_orders, then send_bill. Say it is \
sent, waits for the company's check, and what the check found (from the answer), never that it is approved or paid.
- When the work order or the line is unclear, ask once with the choices (work order ref and line).
- Never promise a payment date, never talk about other subcontractors, rates of others, or the company's money.
- Anything else (a dispute, a new job): say you will pass it to the company, and that their site engineer or the office \
will call."""


async def _contact(database: Any, wa_id: str) -> dict | None:
    from mesiri.domains.partner.router import contact_by_phone

    async with database.transaction() as conn:
        return await contact_by_phone(conn, wa_id)


class PartnerWhatsApp:
    """Answers a message from a subcontractor's contact; ``None`` when the number is not one (the caller carries on)."""

    def __init__(self, *, provider: Any, database: Any, app: Any | None = None) -> None:
        from agent_api.app import build_api_app

        self._database = database
        self._app = app if app is not None else build_api_app(database)
        self._agent = ApiAgent(provider, build_tools(self._app.openapi(), PARTNER_ALLOWED), sop=PARTNER_SOP,
                               capability="api_agent")

    async def reply(self, message: Any) -> str | None:
        from mesiri.domains.partner.router import partner_token

        wa_id = str(getattr(message.sender, "wa_id", "") or "")
        contact = await _contact(self._database, wa_id)
        if contact is None:
            return None
        text = (getattr(message, "text", None) or "").strip()
        if not text:
            return (f"Hello {contact['name']}, this is {contact['company_name']}'s Mesiri. Please type your message: "
                    "your balance, work done, or your bill with its quantities.")
        client = ApiClient(app=self._app, token=partner_token(contact["id"], contact["organization_id"], contact["vendor_id"]))
        try:
            turn = await self._agent.run(client, text, sender_name=f"{contact['name']} of {contact['vendor_name']}",
                                         language=contact.get("language"))
            reply = turn.reply.strip()
            if turn.pending:  # sent at once: the API keeps it waiting for the company
                results = await confirm(client, turn.pending)
                reply = _with_results(reply, results)
            return reply or "Sorry, I could not read that. Please write it again."
        finally:
            await client.close()


def _with_results(reply: str, results: list[Any]) -> str:
    """The model's words, without any Save talk, and one line per thing sent, from the API's own answer."""
    reply = re.sub(r"(?i)[^.\n]*\b(tap|press)\s+save\b[^.\n]*[.\n]?", "", reply).strip()
    lines = []
    for r in results:
        body = r.body if isinstance(r.body, dict) else {}
        if not r.ok:
            lines.append(f"⚠️ Not sent: {body.get('detail') or 'please try again'}")
        elif "ref" in body:
            check = "; ".join(body.get("check") or [])
            lines.append(f"✅ Bill {body['ref']} on {body.get('work_order')} sent (₹{body.get('amount')}): waits for the "
                         f"company's check{f' — {check}' if check else ''}.")
        else:
            lines.append(f"✅ Sent: {body.get('reported', '')} on {body.get('work_order', '')} — waits for the site engineer.")
    return "\n".join(x for x in [reply, *lines] if x)
