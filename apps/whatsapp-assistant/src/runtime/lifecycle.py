"""Application lifecycle and FastAPI bootstrap for the WhatsApp assistant."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress

import httpx
from fastapi import FastAPI

from ingress.webhook import router as webhook_router
from runtime.automation_runner import runner_enabled, runner_loop
from runtime.dependencies import Settings, build_container

logger = logging.getLogger(__name__)


def configure_logging() -> None:
    """Configure process-wide logging defaults."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


async def worker_status(container) -> str:
    """"alive", "down" or "off" (no queue: dev/test), for the uptime monitor (INF-08).

    The worker runs every WhatsApp message, so a dead worker is an outage even
    while the web process answers. Same ARQ health-check key the control panel
    reads (admin/queue_router.py); a status word only, no counts.
    """
    from runtime.queue import HEALTH_CHECK_KEY

    if container is None or container.message_enqueuer is None:
        return "off"
    try:
        raw = await asyncio.wait_for(container.redis_client.get_raw(HEALTH_CHECK_KEY), 2.0)
    except Exception:  # noqa: BLE001 — /health itself must still answer
        return "down"
    return "alive" if raw is not None else "down"


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI application for the WhatsApp assistant."""
    configure_logging()
    from runtime.error_reporting import init_error_reporting

    init_error_reporting("app")
    app_settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Initialize and tear down shared runtime dependencies."""
        async with httpx.AsyncClient(timeout=30.0) as http_client:
            app.state.container = build_container(app_settings, http_client)
            # BE-31: logins signed with the public fallback secret can be
            # forged by anyone. Production refuses to boot on it (its .env was
            # confirmed to set MESIRI_JWT_SECRET, 19 Oct); elsewhere it is logged.
            import os

            from mesiri.domains.identity.auth_service import check_jwt_secret, jwt_secret_is_default

            check_jwt_secret(os.environ.get("MESIRI_ENVIRONMENT"))
            if jwt_secret_is_default():
                import logging

                logging.getLogger("mesiri.startup").error(
                    "MESIRI_JWT_SECRET is not set: logins are signed with the public "
                    "default secret and can be forged. Set it in /opt/mesiri/.env."
                )
            # Connect the Redis client (no-op for FakeRedis; real connection
            # for RedisClient when MESIRI_REDIS__HOST is configured).
            await app.state.container.redis_client.connect()
            # M8: connect the Material execution transaction owner.
            await app.state.container.material_db.connect()
            # SA-11: errors from here on go to the super admins on WhatsApp.
            from runtime.ops_alerts import install_ops_alerts

            install_ops_alerts(app.state.container.ops_alerts, "app")
            # Durable ingress queue (see runtime/queue.py): None against
            # FakeRedis, in which case WhatsAppReceiver already fell back to
            # asyncio.create_task at construction time and there is nothing
            # to connect here.
            if app.state.container.message_enqueuer is not None:
                await app.state.container.message_enqueuer.connect()

            # User-defined automations ("every day at 5pm send me the DPR"):
            # advisory-lock-elected (runtime/automation_runner.py's
            # _ADVISORY_LOCK_KEY), one tick at a time. Reuses material_db
            # rather than opening a second connection pool.
            automation_task = None
            if runner_enabled():
                automation_task = asyncio.create_task(
                    runner_loop(
                        db=app.state.container.material_db,
                        summary_writer=app.state.container.dpr_summary_writer,
                        card_renderer=app.state.container.receipt_renderer,
                    )
                )
            else:
                logger.info("Automation runner disabled by configuration")

            logger.info("WhatsApp assistant runtime initialized")
            try:
                yield
            finally:
                if automation_task is not None:
                    automation_task.cancel()
                    # Swallow the CancelledError the task raises on shutdown;
                    # it's the expected way the loop stops, not an error.
                    with suppress(asyncio.CancelledError):
                        await automation_task
                await app.state.container.material_db.disconnect()
                if app.state.container.message_enqueuer is not None:
                    await app.state.container.message_enqueuer.disconnect()
                await app.state.container.redis_client.disconnect()
                # Only closes anything if a render actually happened (the
                # headless browser launches lazily on first use) -- a no-op
                # otherwise.
                await app.state.container.receipt_renderer.close()

    app = FastAPI(title="Mesiri WhatsApp Assistant", lifespan=lifespan)

    @app.get("/health", tags=["ops"])
    async def health() -> dict:
        # build carries the running commit. Without it there is no way to
        # tell a fix that did not work from a fix that never shipped, which
        # cost days of chasing a bug that had already been fixed.
        #
        # media_storage is here for the same reason. With the fake adapter
        # selected, every photo is written to memory and every URL comes back
        # as memory://, which the dashboard renders as "Photo unavailable" --
        # a symptom that looks like a broken feature and is actually a
        # missing environment variable. The provider name only; never a
        # credential.
        from runtime.build_info import build_sha, media_storage_provider

        return {
            "status": "ok",
            "build": build_sha(),
            "media_storage": media_storage_provider(),
            "worker": await worker_status(getattr(app.state, "container", None)),
        }

    # Alias matching the documented liveness-probe convention
    # (README.md / backend/src/mesiri/http/app.py) -- infra/mesiri.service's
    # deploy health check hits this exact path.
    @app.get("/health/live", tags=["ops"])
    async def health_live() -> dict:
        return {"status": "ok"}

    app.include_router(webhook_router, prefix="/webhook")

    # SS-08: an expired trial company's dashboard is read-only. Registered
    # before CORS so CORS wraps it and the 403 still reaches the browser.
    from mesiri.domains.shared.trial_guard import trial_guard_middleware

    app.middleware("http")(trial_guard_middleware)

    # CORS for Control Plane dashboard
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

    # Admin / Control Plane routes
    try:
        from admin.router import router as admin_router

        app.include_router(admin_router)
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning("Admin router not loaded: %s", exc)

    # WhatsApp assistant log viewer (platform-admin only)
    try:
        from admin.logs_router import router as logs_router

        app.include_router(logs_router)
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning("Logs router not loaded: %s", exc)

    # Durable ingress queue / worker health (platform-admin only)
    try:
        from admin.queue_router import router as queue_router

        app.include_router(queue_router)
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning("Queue router not loaded: %s", exc)

    # Latency/performance viewer (platform-admin only)
    try:
        from admin.perf_router import router as perf_router

        app.include_router(perf_router)
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning("Perf router not loaded: %s", exc)

    # Assistant review export for the scheduled reviewer (platform-admin only)
    try:
        from admin.review_router import router as review_router

        app.include_router(review_router)
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning("Review router not loaded: %s", exc)

    # System graph — assistant pipeline visualization (platform-admin only)
    try:
        from admin.system_graph_router import router as system_graph_router

        app.include_router(system_graph_router)
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning("System graph router not loaded: %s", exc)

    # AI Providers visibility (platform-admin only)
    try:
        from mesiri.domains.admin.providers_router import router as providers_router

        app.include_router(providers_router)
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning("Providers router not loaded: %s", exc)

    # Platform-admin account management (platform-admin only)
    try:
        from admin.platform_users_router import router as platform_users_router

        app.include_router(platform_users_router)
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning("Platform users router not loaded: %s", exc)

    # Platform-wide settings: trial length, signup switch (SS-10)
    try:
        from admin.platform_settings_router import router as platform_settings_router

        app.include_router(platform_settings_router)
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning("Platform settings router not loaded: %s", exc)

    # Branding requests and a company's letterhead for the control panel
    # (SA-09); the backend's router, mounted here like /company.
    try:
        from mesiri.domains.admin.branding_router import router as branding_admin_router

        app.include_router(branding_admin_router)
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning("Branding admin router not loaded: %s", exc)

    # What Mesiri costs to run, per company, day and message, for the control
    # panel (SA-05); the backend's router, mounted here like branding.
    try:
        from mesiri.domains.admin.costs_router import router as costs_admin_router

        app.include_router(costs_admin_router)
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning("Costs admin router not loaded: %s", exc)

    # Reply time and AI tokens per WhatsApp message (SA-17); like costs.
    try:
        from mesiri.domains.admin.replies_router import router as replies_admin_router

        app.include_router(replies_admin_router)
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning("Replies admin router not loaded: %s", exc)

    # The control panel's Database page (SA-15); the backend's router, like costs.
    try:
        from mesiri.domains.admin.database_router import router as database_admin_router

        app.include_router(database_admin_router)
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning("Database admin router not loaded: %s", exc)

    # Claude's read-only control-plane API (SA-16); off until MESIRI_CLAUDE_OPS_TOKEN is set.
    try:
        from mesiri.domains.admin.claude_ops_router import router as claude_ops_router

        app.include_router(claude_ops_router)
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning("Claude-ops router not loaded: %s", exc)

    # Auth routes (mobile app login/register)
    try:
        from auth.router import router as auth_router

        app.include_router(auth_router)
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning("Auth router not loaded: %s", exc)

    # SS-08: "Continue with Mesiri" from the dashboard after a trial.
    try:
        from trial.router import router as trial_router

        app.include_router(trial_router)
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning("Trial router not loaded: %s", exc)

    # WEB-36: Tell Mesiri from the dashboard (the same handler as WhatsApp).
    try:
        from web_assistant.router import router as web_assistant_router

        app.include_router(web_assistant_router)
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning("Web assistant router not loaded: %s", exc)

    # Users routes (tenant management)
    try:
        from users.router import router as users_router

        app.include_router(users_router)
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning("Users router not loaded: %s", exc)

    # Projects routes (tenant-scoped project management)
    try:
        from projects.router import router as projects_router

        app.include_router(projects_router)
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning("Projects router not loaded: %s", exc)

    # Materials routes (tenant-scoped materials log)
    try:
        from mesiri.domains.materials.router import router as materials_router

        app.include_router(materials_router)
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning("Materials router not loaded: %s", exc)

    # Timeline routes
    try:
        from mesiri.domains.timeline.router import router as timeline_router

        app.include_router(timeline_router)
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning("Timeline router not loaded: %s", exc)

    # Company / tenant settings routes (dashboard Company Details screen)
    try:
        from mesiri.domains.organizations.router import router as organizations_router

        app.include_router(organizations_router)
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning("Organizations router not loaded: %s", exc)

    # Expenses routes (dashboard Expenses/Receipts/Categories pages) -- was
    # never wired into this app, only into backend/src/mesiri/http/app.py,
    # which infra/mesiri.service does not actually run (ExecStart is
    # `main:app`, i.e. this create_app()). Every dashboard finance/expense
    # call 404'd in production until this was added.
    try:
        from mesiri.domains.expenses.router import router as expenses_router

        app.include_router(expenses_router)
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning("Expenses router not loaded: %s", exc)

    # Finance routes (dashboard Accounts/Petty Cash pages) -- same gap as
    # expenses above.
    try:
        from mesiri.domains.finance.router import router as finance_router

        app.include_router(finance_router)
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning("Finance router not loaded: %s", exc)

    # Vendors routes (dashboard Vendors & Payees page) -- same gap as
    # expenses above.
    try:
        from mesiri.domains.vendors.router import router as vendors_router

        app.include_router(vendors_router)
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning("Vendors router not loaded: %s", exc)

    # Labour/workforce routes (dashboard Worker Roster, Attendance Log,
    # Overview, Reports, Settings pages; POST /labour/workers add-worker) --
    # same gap as expenses/finance/vendors above: built against
    # backend/src/mesiri/http/app.py, never wired into the app that actually
    # runs. Every dashboard labour call -- including saving a new worker --
    # 404'd in production until this was added (reported by Alan 2026-07-27:
    # "Add Worker" said not found, and a WhatsApp-confirmed attendance never
    # appeared on the dashboard even though it was genuinely saved).
    try:
        from mesiri.domains.workforce.router import router as workforce_router

        app.include_router(workforce_router)
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning("Workforce router not loaded: %s", exc)

    # Progress/Daily Reporting routes (dashboard Field Reports/Activities
    # pages -- GET /progress/activities, GET /progress/activities/{id}).
    # Mounted here too, not just in backend/src/mesiri/http/app.py, per the
    # lesson immediately above this block: a router that only exists in that
    # file 404s in production, since this file builds the app that actually
    # runs.
    try:
        from mesiri.domains.progress.router import router as progress_router

        app.include_router(progress_router)
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning("Progress router not loaded: %s", exc)

    # DPR (Daily Progress Report) routes -- GET/POST /dpr/daily-reports,
    # .../approve, .../publish, .../revise, .../pdf. Same gap as every
    # router above this line: built against backend/src/mesiri/http/app.py
    # only, never wired into the app that actually runs, so the entire DPR
    # dashboard surface (including revision and the project-level roll-up)
    # has been 404ing in production. Found while wiring the automations
    # router below -- fixed here rather than left for the next feature to
    # rediscover the same trap.
    try:
        from mesiri.domains.dpr.router import router as dpr_router

        app.include_router(dpr_router)
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning("DPR router not loaded: %s", exc)

    # WEB-27: the site DPR as a live document (the PDF's own HTML).
    try:
        from dpr_preview.router import router as dpr_preview_router

        app.include_router(dpr_preview_router)
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning("DPR preview router not loaded: %s", exc)

    # Signed download links for media kept on this server's disk (INF-09,
    # object storage provider "local"). Answers 404 under any other provider.
    try:
        from mesiri.domains.shared.media_router import router as media_router

        app.include_router(media_router)
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning("Media router not loaded: %s", exc)

    # Automations -- user-defined recurring schedules (GET/POST
    # /automations, PATCH/DELETE /automations/{id}, GET
    # /automations/{id}/runs). Mounted here for the same reason as DPR
    # immediately above.
    try:
        from mesiri.domains.automations.router import router as automations_router

        app.include_router(automations_router)
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning("Automations router not loaded: %s", exc)

    return app
