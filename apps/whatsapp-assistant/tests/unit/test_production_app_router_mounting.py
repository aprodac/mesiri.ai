"""Every domain router the dashboard depends on must be mounted on the app
that actually runs in production.

This is not a hypothetical risk -- it has happened four times in
runtime/lifecycle.py's create_app(), each one silent until a real user hit
it: expenses, finance, and vendors routers were each built against
backend/src/mesiri/http/app.py (which infra/mesiri.service does not run) and
never added to this one, and every dashboard call for that domain 404'd in
production. Labour was the fourth (reported by Alan 2026-07-27 -- "Add
Worker" said not found, and a WhatsApp-confirmed attendance never showed up
on the dashboard, both because /labour/* simply wasn't reachable).

Each fix landed as a one-line addition with no test to catch a fifth
occurrence. This is that test. It doesn't need a live database: router
mounting in create_app() is synchronous route registration, not a network
call -- the actual DB connections only happen in the ASGI lifespan, which
this never starts.

Inspecting `app.routes` directly does NOT work as a check here: this
FastAPI version defers included routers into a lazy `_IncludedRouter`
wrapper that only resolves at request-dispatch or schema-generation time, so
a mounted router can look absent from `app.routes` while working correctly.
Forcing `app.openapi()` is what actually resolves everything, and is also
the more honest check -- it's the same resolution path a real request goes
through.
"""

from __future__ import annotations

from runtime.dependencies import Settings
from runtime.lifecycle import create_app


def _production_app_paths() -> set[str]:
    settings = Settings(verify_token="x", app_secret="x", access_token="x")
    app = create_app(settings=settings)
    return set(app.openapi()["paths"].keys())


def test_labour_workforce_routes_are_mounted():
    """The exact gap Alan hit: POST /labour/workers ("Add Worker") and every
    other /labour/* dashboard call."""
    paths = _production_app_paths()
    for expected in (
        "/labour/workers",
        "/labour/workers/{worker_id}",
        "/labour/attendance",
        "/labour/attendance/{report_id}",
        "/labour/attendance/attachments",
        "/labour/settings",
        "/labour/reports/statement",
        "/labour/workers/statistics",
        "/labour/workers/{worker_id}/statistics",
    ):
        assert expected in paths, f"{expected} not mounted on the production app"


def test_every_previously_fixed_router_gap_stays_fixed():
    """Regression guard for the three earlier occurrences of this exact bug
    class, so this test would have caught each of them."""
    paths = _production_app_paths()
    for expected in ("/expenses", "/finance/accounts", "/finance/vendors"):
        assert expected in paths, f"{expected} not mounted -- same bug class as labour's"


def test_progress_routes_are_mounted():
    """Daily Reporting's router (mesiri.domains.progress.router) was added to
    both create_app() locations in the same change, precisely to avoid
    becoming the fifth occurrence of this bug class."""
    paths = _production_app_paths()
    for expected in (
        "/progress/activities",
        "/progress/activities/{activity_id}",
        "/progress/issues",
        "/progress/issues/{issue_id}",
    ):
        assert expected in paths, f"{expected} not mounted on the production app"


def test_dpr_routes_are_mounted():
    """The fifth occurrence, actually found: mesiri.domains.dpr.router was
    built entirely against backend/src/mesiri/http/app.py (which
    infra/mesiri.service does not run) and never added here -- every DPR
    dashboard call, including the DPR revision and project-level roll-up
    endpoints, 404'd in production. Found and fixed while wiring the
    automations router below."""
    paths = _production_app_paths()
    for expected in (
        "/dpr/daily-reports",
        "/dpr/daily-reports/{report_id}",
        "/dpr/daily-reports/{report_id}/approve",
        "/dpr/daily-reports/{report_id}/publish",
        "/dpr/daily-reports/{report_id}/revise",
        "/dpr/daily-reports/{report_id}/pdf",
    ):
        assert expected in paths, f"{expected} not mounted on the production app"


def test_automations_routes_are_mounted():
    """New this feature -- mounted in both create_app() locations from the
    start, precisely to avoid becoming the sixth occurrence."""
    paths = _production_app_paths()
    for expected in ("/automations", "/automations/{automation_id}", "/automations/{automation_id}/runs"):
        assert expected in paths, f"{expected} not mounted on the production app"


def test_a_domain_router_failing_to_import_does_not_crash_the_whole_app():
    """Each router is mounted inside its own try/except (see
    runtime/lifecycle.py) precisely so one broken domain can't take the
    entire assistant down. create_app() succeeding at all, even if some
    future router regresses, is itself worth pinning."""
    settings = Settings(verify_token="x", app_secret="x", access_token="x")
    app = create_app(settings=settings)
    assert app is not None


def test_site_whatsapp_group_route_is_mounted():
    """WA-87: the site page's WhatsApp group button."""
    assert "/projects/{project_id}/sites/{site_id}/whatsapp-group" in _production_app_paths()


def test_goods_received_rates_and_boq_routes_are_mounted():
    """Occurrences seven and eight, found 7 Nov 2026 while adding Rates (PRC-14): Procurement > GRN (PRC-29) and
    the BOQ (CC-02) were mounted only in backend/src/mesiri/http/app.py, so both pages 404'd in production."""
    paths = _production_app_paths()
    for expected in (
        "/procurement/grns",
        "/procurement/rates",
        "/procurement/rates/{material_id}",
        "/projects/{project_id}/boq",
    ):
        assert expected in paths, f"{expected} not mounted on the production app"


# Backend-app routers that production serves with its own modules (same paths), so not mounted from mesiri here.
_REPLACED_IN_PRODUCTION = {
    "mesiri.domains.admin.router",  # admin.router (control panel)
    "mesiri.domains.identity.router",  # auth.router (/auth/me, login)
    "mesiri.domains.projects.router",  # this app's projects routes
    "mesiri.domains.users.router",  # this app's users routes
    "mesiri.domains.escalations.router",  # not used by the dashboard
}


def test_every_router_the_backend_app_mounts_is_mounted_here_too():
    """The class, not the next instance: each earlier test named the paths of the router just fixed, so a new
    router added to backend/src/mesiri/http/app.py alone still slipped through. Read from both files' source."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[4]
    module = re.compile(r"mesiri\.domains\.[a-z_.]*router[a-z_]*")
    backend = set(module.findall((root / "backend/src/mesiri/http/app.py").read_text(encoding="utf-8")))
    here = set(module.findall((root / "apps/whatsapp-assistant/src/runtime/lifecycle.py").read_text(encoding="utf-8")))
    missing = backend - here - _REPLACED_IN_PRODUCTION
    assert not missing, f"Mounted in backend/http/app.py but not in runtime/lifecycle.py (404 in production): {sorted(missing)}"
