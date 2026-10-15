"""BE-01 step 0: shadow mode answers from the copy and records differences."""

from __future__ import annotations

import pytest

from context import runtime
from context.main_table_repositories import MainExternalIdentityRepository, MainProjectRepository
from context.models import Project
from context.postgres_repositories import PostgresProjectRepository
from context.shadow import ShadowPort, identity_source


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def record(self, port, method, args, old, new) -> None:
        self.calls.append((port, method, args, old, new))


class _Answer:
    def __init__(self, value=None, error: Exception | None = None) -> None:
        self.value, self.error = value, error

    async def list_authorized_projects(self, **_kwargs):
        if self.error:
            raise self.error
        return self.value


_A = Project("ctx_proj_a", "ctx_org_1", "Alpha")
_B = Project("ctx_proj_b", "ctx_org_1", "Beta")


@pytest.mark.anyio
async def test_same_answer_in_any_order_records_nothing():
    rec = _Recorder()
    port = ShadowPort("projects", _Answer([_A, _B]), _Answer([_B, _A]), rec)

    assert await port.list_authorized_projects(organization_id="o", user_id="u") == [_A, _B]
    assert rec.calls == []


@pytest.mark.anyio
async def test_different_answer_returns_the_copy_and_is_recorded():
    rec = _Recorder()
    port = ShadowPort("projects", _Answer([_A]), _Answer([_A, _B]), rec)

    assert await port.list_authorized_projects(organization_id="o", user_id="u") == [_A]
    [(name, method, args, old, new)] = rec.calls
    assert (name, method) == ("projects", "list_authorized_projects")
    assert args == {"args": [], "organization_id": "o", "user_id": "u"}
    assert len(old) == 1 and len(new) == 2


@pytest.mark.anyio
async def test_main_table_failure_is_recorded_not_raised():
    rec = _Recorder()
    port = ShadowPort("projects", _Answer([_A]), _Answer(error=RuntimeError("boom")), rec)

    assert await port.list_authorized_projects(organization_id="o", user_id="u") == [_A]
    assert "boom" in rec.calls[0][4]["error"]


@pytest.mark.anyio
async def test_copy_failure_still_raises():
    port = ShadowPort(
        "projects", _Answer(error=RuntimeError("copy down")), _Answer([_A]), _Recorder()
    )

    with pytest.raises(RuntimeError, match="copy down"):
        await port.list_authorized_projects(organization_id="o", user_id="u")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, "main"),
        ("context", "context"),
        ("MAIN", "main"),
        ("shadow", "shadow"),
        ("x", "main"),
    ],
)
def test_identity_source_setting(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("MESIRI_IDENTITY_SOURCE", raising=False)
    else:
        monkeypatch.setenv("MESIRI_IDENTITY_SOURCE", value)
    assert identity_source() == expected


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("context", PostgresProjectRepository),
        ("main", MainProjectRepository),
        ("shadow", ShadowPort),
    ],
)
def test_resolver_is_wired_from_the_setting(monkeypatch, source, expected):
    monkeypatch.setenv("MESIRI_IDENTITY_SOURCE", source)

    resolver = runtime.build_context_resolver()

    assert isinstance(resolver._d.projects, expected)  # noqa: SLF001


def test_resolver_reads_the_main_tables_by_default(monkeypatch):
    """BE-01 step 1: with no setting, WhatsApp identity comes from the main tables."""
    monkeypatch.delenv("MESIRI_IDENTITY_SOURCE", raising=False)

    resolver = runtime.build_context_resolver()

    assert isinstance(resolver._d.projects, MainProjectRepository)  # noqa: SLF001
    assert isinstance(resolver._d.identities, MainExternalIdentityRepository)  # noqa: SLF001
