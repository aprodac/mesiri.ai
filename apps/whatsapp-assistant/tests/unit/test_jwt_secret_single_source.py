"""BE-31: every route that checks a login uses the one configured secret.

A router with its own hardcoded copy ignores MESIRI_JWT_SECRET: setting the
secret in production then locks that router out while it stays forgeable with
the public default.
"""

from __future__ import annotations

from pathlib import Path

from mesiri.domains.identity import auth_service

_DEFAULT = "mesiri-temp-secret-key-change-in-production"
_REPO = Path(__file__).resolve().parents[4]


def test_only_auth_service_holds_the_fallback_secret():
    holders = [
        str(path.relative_to(_REPO))
        for root in ("apps/whatsapp-assistant/src", "backend/src")
        for path in (_REPO / root).rglob("*.py")
        if _DEFAULT in path.read_text(encoding="utf-8")
    ]
    assert holders == ["backend/src/mesiri/domains/identity/auth_service.py"]


def test_users_and_projects_routers_use_the_shared_secret():
    from projects import router as projects_router
    from users import router as users_router

    assert users_router.SECRET_KEY is auth_service.SECRET_KEY
    assert projects_router.SECRET_KEY is auth_service.SECRET_KEY
