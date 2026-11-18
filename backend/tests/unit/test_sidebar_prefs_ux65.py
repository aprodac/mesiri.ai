"""UX-65: a person's own sidebar (``users.sidebar``). Self only, like SS-27: the row is the token's user in the token's
company; it changes what their sidebar shows, never what they may open."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from mesiri.domains.identity import preferences_router as me

ORG, USER = uuid.uuid4(), uuid.uuid4()
CTX = SimpleNamespace(user_id=USER, organization_id=ORG, role="PROJECT_MANAGER")


class Conn:
    def __init__(self, *, sidebar: object = None, rows: int = 1) -> None:
        self.sidebar, self.rows = sidebar, rows
        self.statements: list = []

    async def execute(self, statement):  # noqa: ANN001, ANN201
        compiled = statement.compile()
        if statement.is_select and "organization_settings" in str(compiled):
            return SimpleNamespace(first=lambda: None)
        self.statements.append(statement)
        if statement.is_select:
            row = SimpleNamespace(reply_language=None, voice_transcript=None, start_mode="free", guide_seen={},
                                  created_at=None, sidebar=self.sidebar)
            return SimpleNamespace(first=lambda: row)
        if "sidebar" in compiled.params:
            self.sidebar = compiled.params["sidebar"]
        return SimpleNamespace(rowcount=self.rows)


def _where(statement) -> set:  # noqa: ANN001
    return {v for k, v in statement.compile().params.items() if k.startswith(("id", "organization_id"))}


def test_a_sidebar_is_pages_and_known_sections_only() -> None:
    body = me.SidebarPrefs(pins=["/cost/green-red", "/tasks?view=overdue", "/cost/green-red"], order=["site", "tasks", "site"],
                           hidden=["plan"])
    assert body.pins == ["/cost/green-red", "/tasks?view=overdue"]  # a page pinned twice is kept once, first place
    assert body.order == ["site", "tasks"]
    for bad in ({"pins": ["https://evil.example"]}, {"pins": ["/today?project=1"]}, {"pins": ["cost"]},
                {"order": ["settings"]}, {"hidden": ["daily"]}, {"pins": [f"/p{i}" for i in range(me.SIDEBAR_PINS_MAX + 1)]}):
        with pytest.raises(ValidationError):
            me.SidebarPrefs(**bad)


@pytest.mark.parametrize(("stored", "expected"), [
    (None, None),                                   # never changed: the role's default
    ("null", None),
    ([], None),
    ({}, me.SidebarPrefs()),                        # changed to nothing pinned: kept as such
    ({"pins": ["/boq", 3, "bad", "/boq"], "order": ["money", "nope"], "hidden": "site"},
     me.SidebarPrefs(pins=["/boq"], order=["money"])),
])
def test_clean_sidebar(stored: object, expected: me.SidebarPrefs | None) -> None:
    assert me.clean_sidebar(stored) == expected


async def test_get_returns_the_callers_own_sidebar() -> None:
    conn = Conn(sidebar={"pins": ["/materials/requests"], "order": ["site"], "hidden": ["plan"]})
    out = await me.get_preferences(CTX, conn)
    assert out.sidebar == me.SidebarPrefs(pins=["/materials/requests"], order=["site"], hidden=["plan"])
    assert _where(conn.statements[0]) == {USER, ORG}


async def test_get_with_none_set_is_the_role_default() -> None:
    assert (await me.get_preferences(CTX, Conn())).sidebar is None


async def test_put_writes_only_the_callers_row() -> None:
    conn = Conn()
    body = me.SidebarPrefs(pins=["/site/approvals", "/cost/green-red"], order=["site", "money"], hidden=["plan"])
    out = await me.set_sidebar(body, CTX, conn)
    assert out.sidebar == body
    assert conn.sidebar == {"pins": ["/site/approvals", "/cost/green-red"], "order": ["site", "money"], "hidden": ["plan"]}
    assert _where(conn.statements[0]) == {USER, ORG}


async def test_delete_goes_back_to_the_role_default() -> None:
    conn = Conn(sidebar={"pins": ["/boq"]})
    out = await me.reset_sidebar(CTX, conn)
    assert out.sidebar is None
    assert _where(conn.statements[0]) == {USER, ORG}


@pytest.mark.parametrize("call", ["put", "delete"])
async def test_a_missing_user_is_404(call: str) -> None:
    conn = Conn(rows=0)
    with pytest.raises(HTTPException) as err:
        if call == "put":
            await me.set_sidebar(me.SidebarPrefs(), CTX, conn)
        else:
            await me.reset_sidebar(CTX, conn)
    assert err.value.status_code == 404
