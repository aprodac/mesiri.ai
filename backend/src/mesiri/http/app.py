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

    # Register Routers
    import logging

    _log = logging.getLogger("mesiri.http")

    try:
        from mesiri.domains.identity.router import router as identity_router

        app.include_router(identity_router)
    except Exception as exc:  # noqa: BLE001 — surface every router failure, not just ImportError
        _log.exception("identity router not loaded: %s", exc)

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
        from mesiri.domains.admin.costs_router import router as costs_admin_router

        app.include_router(costs_admin_router)
    except Exception as exc:  # noqa: BLE001
        _log.exception("costs admin router not loaded: %s", exc)

    try:
        from mesiri.domains.admin.database_router import router as database_admin_router

        app.include_router(database_admin_router)
    except Exception as exc:  # noqa: BLE001
        _log.exception("database admin router not loaded: %s", exc)

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
        from mesiri.domains.workforce.router import router as workforce_router

        app.include_router(workforce_router)
    except Exception as exc:  # noqa: BLE001
        _log.exception("workforce router not loaded: %s", exc)

    try:
        from mesiri.domains.progress.router import router as progress_router

        app.include_router(progress_router)
    except Exception as exc:  # noqa: BLE001
        _log.exception("progress router not loaded: %s", exc)

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

