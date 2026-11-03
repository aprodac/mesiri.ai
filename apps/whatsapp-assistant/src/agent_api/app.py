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
    "mesiri.domains.timeline.router",
    "mesiri.domains.workforce.router",
    "mesiri.domains.progress.router",
    "mesiri.domains.expenses.router",
    "mesiri.domains.finance.router",
    "mesiri.domains.dpr.router",
    "mesiri.domains.identity.preferences_router",  # WA-169: the reply language they chose
)


def build_api_app(database: Any) -> FastAPI:
    from mesiri.infrastructure.postgres.tenant import TenantResetMiddleware

    app = FastAPI(title="Mesiri API (agent)")
    app.add_middleware(TenantResetMiddleware)
    for module in API_ROUTERS:
        app.include_router(importlib.import_module(module).router)
    app.state.container = SimpleNamespace(material_db=database)
    return app
