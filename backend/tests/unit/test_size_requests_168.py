"""WA-168: size requests. An answer sets the size for the company, then saves every held line as the person who
reported it (one line failing never blocks the others), and tells them; only an admin or project manager answers."""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from mesiri.domains.materials import router as materials_router
from mesiri.domains.materials import size_requests

ORG, ADMIN, ENGINEER, OTHER = (uuid.uuid4() for _ in range(4))
MATERIAL, LOAD = uuid.uuid4(), uuid.uuid4()


def _ctx(role: str, user: uuid.UUID = ADMIN) -> SimpleNamespace:
    return SimpleNamespace(role=role, organization_id=ORG, user_id=user)


def _line(user: uuid.UUID, summary: str) -> dict:
    return size_requests.held_line("/materials/inflows", {"material_id": str(MATERIAL), "unit_id": str(LOAD),
                                   "quantity": 1, "project_id": str(uuid.uuid4()), "occurred_date": "2026-11-03"},
                                   summary, f"k-{summary}", user, "SITE_ENGINEER")


class _Nested:
    """A connection whose savepoints do nothing (the fakes never touch it)."""

    def begin_nested(self) -> _Nested:
        return self

    async def __aenter__(self):  # noqa: ANN204
        return self

    async def __aexit__(self, *exc):  # noqa: ANN002, ANN204
        return False

    async def execute(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201
        return SimpleNamespace(rowcount=0)


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> dict:
    state: dict = {"request": {
        "id": uuid.uuid4(), "material_id": MATERIAL, "from_unit_id": LOAD, "material": "M sand", "unit_name": "Loads",
        "stock_unit_name": "Bags", "status": "open",
        "held_lines": [_line(ENGINEER, "1 load msand"), _line(OTHER, "2 load msand")]},
        "sizes": [], "saved_as": [], "closed": None, "told": []}

    async def get_request(conn, org, rid, lock=False):  # noqa: ANN001, ANN202
        return state["request"] if org == ORG else None

    async def close_request(conn, rid, status, user, size, outcome):  # noqa: ANN001, ANN202
        state["closed"] = (status, size, outcome)

    async def set_conversion(material_id, body, auth_context, conn):  # noqa: ANN001, ANN202
        state["sizes"].append((material_id, body.from_unit_id, body.one_unit_equals))

    async def create_inflow(body, key, auth_context, conn):  # noqa: ANN001, ANN202
        if auth_context.user_id == OTHER:
            raise HTTPException(status_code=403, detail="Not authorized for this site")
        state["saved_as"].append((auth_context.user_id, key))
        return {"id": "r", "converted": "1 Loads = 60 bags"}

    class Auth:
        def __init__(self, conn: object) -> None: ...

        async def resolve_from_jwt(self, user_id, org_id, role):  # noqa: ANN001, ANN202
            return _ctx(role, user_id)

    class Notices:
        def __init__(self, conn: object) -> None: ...

        async def claim(self, **kwargs):  # noqa: ANN003, ANN202
            state["told"].append(kwargs)
            return uuid.uuid4()

    from mesiri.authorization import service
    from mesiri.infrastructure.postgres.repositories import notifications

    monkeypatch.setattr(size_requests, "get_request", get_request)
    monkeypatch.setattr(size_requests, "close_request", close_request)
    monkeypatch.setattr(materials_router, "set_unit_conversion", set_conversion)
    monkeypatch.setattr(materials_router, "create_inflow", create_inflow)
    monkeypatch.setattr(service, "AuthorizationService", Auth)
    monkeypatch.setattr(notifications, "PostgresNotificationRepository", Notices)
    return state


async def _answer(role: str, size: str = "60") -> dict:
    return await materials_router.answer_size_request(
        uuid.uuid4(), materials_router.SizeAnswer(one_unit_equals=Decimal(size)), auth_context=_ctx(role), conn=_Nested())


async def test_an_answer_sets_the_size_then_saves_each_line_as_its_reporter(world: dict) -> None:
    answer = await _answer("ADMIN")
    assert world["sizes"] == [(MATERIAL, LOAD, Decimal("60"))]
    assert world["saved_as"] == [(ENGINEER, "k-1 load msand")]  # as the person who reported it, same key
    assert [line["saved"] for line in answer["lines"]] == [True, False]  # one refused line never blocks the other
    assert answer["lines"][1]["reason"] == "Not authorized for this site"
    assert world["closed"][0] == "answered" and "1 of 2 waiting lines saved" in answer["message"]
    assert [t["recipient_user_id"] for t in world["told"]] == [ENGINEER]
    assert "1 load msand" in world["told"][0]["payload"]["message"]


async def test_guard_only_an_admin_or_project_manager_answers_or_dismisses(world: dict) -> None:
    for call in (_answer("SITE_ENGINEER"),
                 materials_router.dismiss_size_request(uuid.uuid4(), auth_context=_ctx("SITE_ENGINEER"), conn=_Nested()),
                 materials_router.delete_unit_conversion(MATERIAL, LOAD, auth_context=_ctx("SITE_ENGINEER"),
                                                         conn=_Nested())):
        with pytest.raises(HTTPException) as err:
            await call
        assert err.value.status_code == 403
    assert world["sizes"] == [] and world["closed"] is None


async def test_guard_an_answered_request_is_not_answered_twice(world: dict) -> None:
    world["request"]["status"] = "answered"
    with pytest.raises(HTTPException) as err:
        await _answer("PROJECT_MANAGER")
    assert err.value.status_code == 409 and world["sizes"] == []


def test_only_a_receipt_or_a_use_can_wait_for_a_size() -> None:
    assert _line(ENGINEER, "x")["path"] == "/materials/inflows"
    with pytest.raises(ValueError):
        size_requests.held_line("/expenses", {}, "x", None, ENGINEER, "ADMIN")


def test_the_chain_reaches_0500_with_no_fork() -> None:
    from pathlib import Path

    versions = Path(__file__).resolve().parents[2] / "migrations" / "versions"
    text = (versions / "0500_material_size_requests.py").read_text()
    assert 'down_revision = "0499"' in text and "ENABLE ROW LEVEL SECURITY" in text and "tenant_isolation" in text
    assert sum('down_revision = "0499"' in p.read_text() for p in versions.glob("*.py")) == 1
