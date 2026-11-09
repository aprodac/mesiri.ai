"""WA-119: the API the agent calls, inside the process that handles the message.

WhatsApp messages are handled by the ARQ worker, which has no web app. This
builds one with exactly the dashboard routers the agent's tools use, on the
worker's own database pool (``get_db_conn`` reads ``app.state.container.material_db``),
so a tool call runs the dashboard's code, auth and company checks with no network hop.
"""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI

#: The routers behind ``tools.ALLOWED``. A tool whose route is not served here
#: fails ``build_tools`` (and the test), never a customer's message.
#: The same modules the live app (runtime/lifecycle.py) mounts for these paths:
#: /projects is the assistant's own ``projects.router`` there, not the backend's.
API_ROUTERS: tuple[str, ...] = (
    "projects.router",
    "mesiri.domains.materials.router",
    "mesiri.domains.procurement.router",  # PRC-22: material requests (what a site asks for)
    "mesiri.domains.procurement.orders_router",  # PRC-23: a saved delivery put on its purchase order
    "mesiri.domains.timeline.router",
    "mesiri.domains.workforce.router",
    "mesiri.domains.progress.router",
    "mesiri.domains.expenses.router",
    "mesiri.domains.finance.router",
    "mesiri.domains.vendors.router",  # WA-201: the vendor list, so a known vendor is never added twice
    "mesiri.domains.subcontracts.router",  # NXT-05..07: work orders, measurement, subcontract bills
    "mesiri.domains.partner.router",  # NXT-16: the subcontractor's own routes (partner tools only)
    "mesiri.domains.dpr.router",
    "mesiri.domains.equipment.router",  # NXT-11: machines, their day logs, hire check
    "mesiri.domains.schedule.router",  # ST-04: the project schedule (Gantt)
    "mesiri.domains.materials.plan_router",  # MP-04: the material plan (what to order and when)
    "mesiri.domains.places.router",  # LP-04: floors and rooms, what is left on a floor
    "mesiri.domains.documents.router",  # DOC-05, DR-08: find a document, what the drawings say
    "mesiri.domains.costing.router",  # CC-11: cost control (green / red, budget vs actual, labour on BOQ lines)
    "mesiri.domains.billing.router",  # NXT-03: RA bills, money received from clients, what they owe
    "mesiri.domains.admin.my_requests_router",  # request 230: the person's own requests
    "mesiri.domains.approvals.router",  # GM-01: what is waiting for this person's decision
    "mesiri.domains.identity.preferences_router",  # WA-169: the reply language they chose
)


def build_api_app(database: Any) -> FastAPI:
    from mesiri.infrastructure.postgres.tenant import TenantResetMiddleware

    app = FastAPI(title="Mesiri API (agent)")
    # [282]: the API app v3 actually calls (the worker builds its own); a bad value is a 422 here too.
    from mesiri.http import db_errors

    db_errors.install(app)
    app.add_middleware(TenantResetMiddleware)
    for module in API_ROUTERS:
        app.include_router(importlib.import_module(module).router)
    app.state.container = SimpleNamespace(material_db=database)
    return app
