"""The production container is wired: context resolver, workflow runtime,
interaction handler with its execution dispatcher, object storage, and the
control panel's simulator (ARCH-06: the classic pipeline tests that lived here
went with the pipeline)."""

from __future__ import annotations

import httpx

from context.resolver import ContextResolver
from interactions import InteractionHandler
from runtime.dependencies import Settings, build_container
from workflows import WorkflowRuntime


async def test_build_container_wires_context_resolver():
    settings = Settings(
        verify_token="test-verify-token",
        app_secret="test-app-secret",
        access_token="test-access-token",
    )
    async with httpx.AsyncClient(timeout=30.0) as http_client:
        container = build_container(settings, http_client)

    assert container.context_resolver is not None
    assert isinstance(container.context_resolver, ContextResolver)
    # ARCH-06: the control panel's test message runs the real handler.
    assert container.simulate_handler is not None
    assert container.workflow_runtime is not None
    assert isinstance(container.workflow_runtime, WorkflowRuntime)
    assert container.interaction_handler is not None
    assert isinstance(container.interaction_handler, InteractionHandler)
    # M8: the interaction handler must be wired with an execution dispatcher,
    # not left running M7-only (which would silently skip domain execution).
    assert container.interaction_handler._dispatcher is not None
    assert container.material_db is not None
    # object_storage was built locally in build_container (used for
    # build_pipeline/WhatsAppReceiver) but never attached to the returned
    # AppContainer -- backend/src/mesiri/infrastructure/objectstorage/
    # dependency.py's get_object_storage() falls back to
    # `request.app.state.container.object_storage` for the real production
    # app (runtime/lifecycle.py), so a missing field here meant every
    # expense-attachment/receipt fetch 500'd with AttributeError, in
    # production, for every user, always.
    assert container.object_storage is not None
