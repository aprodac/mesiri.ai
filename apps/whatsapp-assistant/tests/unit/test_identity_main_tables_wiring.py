"""BE-01: the production resolver reads identity and scope from the main tables only."""

from __future__ import annotations

from context import runtime
from context.main_table_repositories import (
    MainExternalIdentityRepository,
    MainIdentityBridgeRepository,
    MainMembershipRepository,
    MainProjectRepository,
    MainSiteRepository,
)


def test_resolver_reads_the_main_tables(monkeypatch):
    # The old switch is gone: whatever it is set to, the main tables answer.
    monkeypatch.setenv("MESIRI_IDENTITY_SOURCE", "context")

    deps = runtime.build_context_resolver()._d  # noqa: SLF001

    assert isinstance(deps.identities, MainExternalIdentityRepository)
    assert isinstance(deps.memberships, MainMembershipRepository)
    assert isinstance(deps.projects, MainProjectRepository)
    assert isinstance(deps.sites, MainSiteRepository)
    assert isinstance(deps.bridge, MainIdentityBridgeRepository)
