"""FastAPI application factory exposing liveness and readiness (M1).

Endpoints:
    GET /health/live   -> the process is running (never touches dependencies)
    GET /health/ready  -> can the process reach Postgres, Redis, object storage

A middleware binds the correlation id for every request: it honours an inbound
``X-Correlation-ID`` header (so a journey started upstream stays traceable) or
mints one, and echoes it back. Health responses carry no credentials — only
user-safe dependency states.

Serve with:  uvicorn --factory mesiri.http.app:create_app
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from mesiri_contracts.common.health import DependencyState
from mesiri_contracts.common.ids import new_correlation_id

from ..bootstrap.lifecycle import AppLifecycle
from ..observability import tracing

CORRELATION_HEADER = "X-Correlation-ID"


def create_app(lifecycle: AppLifecycle | None = None) -> FastAPI:
    lc = lifecycle or AppLifecycle.create()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await lc.startup()
        try:
            yield
        finally:
            await lc.shutdown()

    app = FastAPI(title="Mesiri Assistant", version="0.1.0", lifespan=lifespan)
    app.state.lifecycle = lc
    # [282]: a value the database cannot read is a 422, never a crash (every route).
    from . import db_errors

    db_errors.install(app)

    @app.middleware("http")
    async def correlation_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
        correlation_id = request.headers.get(CORRELATION_HEADER) or new_correlation_id()
        with tracing.correlation_scope(correlation_id=correlation_id):
            response = await call_next(request)
        response.headers[CORRELATION_HEADER] = correlation_id
        return response

    @app.get("/health")
    @app.get("/health/live")
    async def live() -> dict:
        return {"status": "alive", "service": lc.container.settings.service_name}

    @app.get("/health/ready")
    async def ready() -> JSONResponse:
        report = await lc.container.health_checker().readiness()
        status_code = 200 if report.state == DependencyState.HEALTHY else 503
        return JSONResponse(status_code=status_code, content=report.model_dump())

    # CORS Configuration
    from fastapi.middleware.cors import CORSMiddleware

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # BE-03: every request starts with no company bound (postgres/tenant.py).
    from mesiri.infrastructure.postgres.tenant import TenantResetMiddleware

    app.add_middleware(TenantResetMiddleware)

    # ADM-01: the company activity log, one recorder for every module's changes.
    from mesiri.http.activity import ActivityRecorder

    app.add_middleware(ActivityRecorder, source="web", fastapi_app=app)

    # Register Routers
    import logging

    _log = logging.getLogger("mesiri.http")

    try:
        from mesiri.domains.identity.router import router as identity_router

        app.include_router(identity_router)
    except Exception as exc:  # noqa: BLE001 — surface every router failure, not just ImportError
        _log.exception("identity router not loaded: %s", exc)

    try:
        from mesiri.domains.identity.preferences_router import router as me_router

        app.include_router(me_router)
    except Exception as exc:  # noqa: BLE001
        _log.exception("me (preferences) router not loaded: %s", exc)

    try:
        from mesiri.domains.admin.router import router as admin_router

        app.include_router(admin_router)
    except Exception as exc:  # noqa: BLE001
        _log.exception("admin router not loaded: %s", exc)

    try:
        from mesiri.domains.admin.providers_router import router as providers_router

        app.include_router(providers_router)
    except Exception as exc:  # noqa: BLE001
        _log.exception("providers router not loaded: %s", exc)

    try:
        from mesiri.domains.users.router import router as users_router

        app.include_router(users_router)
    except Exception as exc:  # noqa: BLE001
        _log.exception("users router not loaded: %s", exc)

    try:
        from mesiri.domains.projects.router import router as projects_router

        app.include_router(projects_router)
    except Exception as exc:  # noqa: BLE001
        _log.exception("projects router not loaded: %s", exc)

    try:
        from mesiri.domains.materials.router import router as materials_router

        app.include_router(materials_router)
    except Exception as exc:  # noqa: BLE001
        _log.exception("materials router not loaded: %s", exc)

    try:
        from mesiri.domains.materials.stock_levels_router import router as stock_levels_router

        app.include_router(stock_levels_router)
    except Exception as exc:  # noqa: BLE001
        _log.exception("stock levels router not loaded: %s", exc)

    try:
        from mesiri.domains.expenses.router import router as expenses_router

        app.include_router(expenses_router)
    except Exception as exc:  # noqa: BLE001
        _log.exception("expenses router not loaded: %s", exc)

    try:
        from mesiri.domains.timeline.router import router as timeline_router

        app.include_router(timeline_router)
    except Exception as exc:  # noqa: BLE001
        _log.exception("timeline router not loaded: %s", exc)

    try:
        from mesiri.domains.organizations.router import router as organizations_router

        app.include_router(organizations_router)
    except Exception as exc:  # noqa: BLE001
        _log.exception("organizations router not loaded: %s", exc)

    try:
        from mesiri.domains.admin.branding_router import router as branding_admin_router

        app.include_router(branding_admin_router)
    except Exception as exc:  # noqa: BLE001
        _log.exception("branding admin router not loaded: %s", exc)

    try:
        from mesiri.domains.admin.my_requests_router import router as me_requests_router
        from mesiri.domains.admin.requests_router import router as requests_admin_router

        app.include_router(requests_admin_router)
        app.include_router(me_requests_router)
    except Exception as exc:  # noqa: BLE001
        _log.exception("requests admin router not loaded: %s", exc)

    try:
        from mesiri.domains.admin.costs_router import router as costs_admin_router

        app.include_router(costs_admin_router)
    except Exception as exc:  # noqa: BLE001
        _log.exception("costs admin router not loaded: %s", exc)

    try:
        from mesiri.domains.admin.replies_router import router as replies_admin_router

        app.include_router(replies_admin_router)
    except Exception as exc:  # noqa: BLE001
        _log.exception("replies admin router not loaded: %s", exc)

    try:
        from mesiri.domains.admin.announcements_router import router as announcements_admin_router

        app.include_router(announcements_admin_router)
    except Exception as exc:  # noqa: BLE001
        _log.exception("announcements admin router not loaded: %s", exc)

    try:
        from mesiri.domains.admin.overview_router import router as overview_admin_router

        app.include_router(overview_admin_router)
    except Exception as exc:  # noqa: BLE001
        _log.exception("overview admin router not loaded: %s", exc)

    try:
        from mesiri.domains.admin.database_router import router as database_admin_router

        app.include_router(database_admin_router)
    except Exception as exc:  # noqa: BLE001
        _log.exception("database admin router not loaded: %s", exc)

    try:
        from mesiri.domains.admin.claude_ops_router import router as claude_ops_router

        app.include_router(claude_ops_router)
    except Exception as exc:  # noqa: BLE001
        _log.exception("claude-ops router not loaded: %s", exc)

    try:
        from mesiri.domains.finance.router import router as finance_router

        app.include_router(finance_router)
    except Exception as exc:  # noqa: BLE001
        _log.exception("finance router not loaded: %s", exc)

    try:
        from mesiri.domains.vendors.router import router as vendors_router

        app.include_router(vendors_router)
    except Exception as exc:  # noqa: BLE001
        _log.exception("vendors router not loaded: %s", exc)

    try:
        from mesiri.domains.subcontracts.router import router as subcontracts_router

        app.include_router(subcontracts_router)
    except Exception as exc:  # noqa: BLE001
        _log.exception("subcontracts router not loaded: %s", exc)

    try:
        from mesiri.domains.partner.router import router as partner_router

        app.include_router(partner_router)
    except Exception as exc:  # noqa: BLE001
        _log.exception("partner router not loaded: %s", exc)

    try:
        from mesiri.domains.workforce.router import router as workforce_router

        app.include_router(workforce_router)
    except Exception as exc:  # noqa: BLE001
        _log.exception("workforce router not loaded: %s", exc)

    try:
        from mesiri.domains.procurement.router import router as procurement_requests_router

        app.include_router(procurement_requests_router)
    except Exception as exc:  # noqa: BLE001
        _log.exception("procurement requests router not loaded: %s", exc)

    try:
        from mesiri.domains.procurement.orders_router import router as purchase_orders_router

        app.include_router(purchase_orders_router)
    except Exception as exc:  # noqa: BLE001
        _log.exception("purchase orders router not loaded: %s", exc)

    try:
        from mesiri.domains.equipment.router import router as equipment_router

        app.include_router(equipment_router)
    except Exception as exc:  # noqa: BLE001
        _log.exception("equipment router not loaded: %s", exc)

    try:
        from mesiri.domains.costing.router import router as costing_router

        app.include_router(costing_router)
    except Exception as exc:  # noqa: BLE001
        _log.exception("cost control router not loaded: %s", exc)

    try:
        from mesiri.domains.finance.tally_router import router as tally_router

        app.include_router(tally_router)
    except Exception as exc:  # noqa: BLE001
        _log.exception("tally export router not loaded: %s", exc)

    try:
        from mesiri.domains.accounts.router import router as accounts_router

        app.include_router(accounts_router)
    except Exception as exc:  # noqa: BLE001
        _log.exception("accounts router not loaded: %s", exc)

    try:
        from mesiri.domains.tasks.router import router as tasks_router

        app.include_router(tasks_router)
    except Exception as exc:  # noqa: BLE001
        _log.exception("tasks router not loaded: %s", exc)

    try:
        from mesiri.domains.workforce.pay_router import router as labour_pay_router

        app.include_router(labour_pay_router)
    except Exception as exc:  # noqa: BLE001
        _log.exception("labour pay router not loaded: %s", exc)

    try:
        from mesiri.domains.approvals.router import router as approvals_router

        app.include_router(approvals_router)
    except Exception as exc:  # noqa: BLE001
        _log.exception("approvals router not loaded: %s", exc)

    try:
        from mesiri.domains.reports.period.router import router as period_report_router

        app.include_router(period_report_router)
    except Exception as exc:  # noqa: BLE001
        _log.exception("period report router not loaded: %s", exc)

    try:
        from mesiri.domains.audit.activity_router import router as activity_router

        app.include_router(activity_router)
    except Exception as exc:  # noqa: BLE001
        _log.exception("activity router not loaded: %s", exc)

    try:
        from mesiri.domains.users.handover_router import router as handover_router

        app.include_router(handover_router)
    except Exception as exc:  # noqa: BLE001
        _log.exception("handover router not loaded: %s", exc)

    try:
        from mesiri.domains.procurement.grn_router import router as goods_receipts_router

        app.include_router(goods_receipts_router)
    except Exception as exc:  # noqa: BLE001
        _log.exception("goods receipts router not loaded: %s", exc)

    try:
        from mesiri.domains.procurement.rates_router import router as rates_router

        app.include_router(rates_router)
    except Exception as exc:  # noqa: BLE001
        _log.exception("rates router not loaded: %s", exc)

    try:
        from mesiri.domains.procurement.rfqs_router import router as rfqs_router

        app.include_router(rfqs_router)
    except Exception as exc:  # noqa: BLE001
        _log.exception("quotations router not loaded: %s", exc)

    try:
        from mesiri.domains.procurement.returns_router import router as returns_router

        app.include_router(returns_router)
    except Exception as exc:  # noqa: BLE001
        _log.exception("returns router not loaded: %s", exc)

    try:
        from mesiri.domains.progress.router import router as progress_router

        app.include_router(progress_router)
    except Exception as exc:  # noqa: BLE001
        _log.exception("progress router not loaded: %s", exc)

    try:
        from mesiri.domains.progress.boq_router import router as boq_router

        app.include_router(boq_router)
    except Exception as exc:  # noqa: BLE001
        _log.exception("boq router not loaded: %s", exc)

    try:
        from mesiri.domains.drawings.router import router as drawings_router

        app.include_router(drawings_router)
    except Exception as exc:  # noqa: BLE001
        _log.exception("drawings router not loaded: %s", exc)

    try:
        from mesiri.domains.places.router import router as places_router

        app.include_router(places_router)
    except Exception as exc:  # noqa: BLE001
        _log.exception("places router not loaded: %s", exc)

    try:
        from mesiri.domains.documents.router import router as documents_router

        app.include_router(documents_router)
    except Exception as exc:  # noqa: BLE001
        _log.exception("documents router not loaded: %s", exc)

    try:
        from mesiri.domains.billing.router import router as billing_router

        app.include_router(billing_router)
    except Exception as exc:  # noqa: BLE001
        _log.exception("billing router not loaded: %s", exc)

    try:
        from mesiri.domains.client_view.router import router as client_view_router

        app.include_router(client_view_router)
    except Exception as exc:  # noqa: BLE001
        _log.exception("client view router not loaded: %s", exc)

    try:
        from mesiri.domains.materials.plan_router import router as material_plan_router

        app.include_router(material_plan_router)
    except Exception as exc:  # noqa: BLE001
        _log.exception("material plan router not loaded: %s", exc)

    try:
        from mesiri.domains.schedule.router import router as schedule_router

        app.include_router(schedule_router)
    except Exception as exc:  # noqa: BLE001
        _log.exception("schedule router not loaded: %s", exc)

    try:
        from mesiri.domains.dpr.router import router as dpr_router

        app.include_router(dpr_router)
    except Exception as exc:  # noqa: BLE001
        _log.exception("dpr router not loaded: %s", exc)

    try:
        from mesiri.domains.escalations.router import router as escalations_router

        app.include_router(escalations_router)
    except Exception as exc:  # noqa: BLE001
        _log.exception("escalations router not loaded: %s", exc)

    try:
        from mesiri.domains.automations.router import router as automations_router

        app.include_router(automations_router)
    except Exception as exc:  # noqa: BLE001
        _log.exception("automations router not loaded: %s", exc)

    return app

