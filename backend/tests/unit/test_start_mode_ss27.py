"""SS-27: how Mesiri guides a person (``users.start_mode``, ``users.guide_seen``). Self only, like WA-169: the row
is the token's user in the token's company; an answer only changes guidance, never access."""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from mesiri.domains.identity import preferences_router as me

ORG, USER = uuid.uuid4(), uuid.uuid4()
CTX = SimpleNamespace(user_id=USER, organization_id=ORG, role="ADMIN")
NOW = dt.datetime(2026, 11, 15, 9, tzinfo=dt.UTC)


class Conn:
    def __init__(self, *, mode: str | None = None, seen: object = None, created: dt.datetime | None = None,
                 rows: int = 1, found: bool = True) -> None:
        self.mode, self.seen, self.created, self.rows, self.found = mode, seen, created, rows, found
        self.statements: list = []

    async def execute(self, statement):  # noqa: ANN001, ANN201
        compiled = statement.compile()
        if statement.is_select and "organization_settings" in str(compiled):
            return SimpleNamespace(first=lambda: None)
        self.statements.append(statement)
        if statement.is_select:
            row = SimpleNamespace(reply_language=None, voice_transcript=None, start_mode=self.mode,
                                  guide_seen=self.seen, created_at=self.created) if self.found else None
            return SimpleNamespace(first=lambda: row)
        params = compiled.params
        if "start_mode" in params:
            self.mode = params["start_mode"]
        if "guide_seen" in params:
            self.seen = params["guide_seen"]
        return SimpleNamespace(rowcount=self.rows)


def _where(statement) -> set:  # noqa: ANN001
    return {v for k, v in statement.compile().params.items() if k.startswith(("id", "organization_id"))}


@pytest.mark.parametrize(("stored", "age_days", "mode", "ask"), [
    ("switching", 400, "switching", False),   # an answer stands, however old the account
    ("free", 0, "free", False),
    (None, 0, "guided", True),                # a new person: guided, and asked
    (None, 14, "guided", True),
    (None, 15, "free", False),                # was using Mesiri before this existed: left alone, never asked
    ("expert", 0, "guided", True),            # an answer that no longer exists falls back (plan 6.7 rule 7)
])
def test_start_mode_for(stored: str | None, age_days: int, mode: str, ask: bool) -> None:
    assert me.start_mode_for(stored, NOW - dt.timedelta(days=age_days), NOW) == (mode, ask)


def test_a_naive_created_at_is_read_as_utc() -> None:
    assert me.start_mode_for(None, (NOW - dt.timedelta(days=30)).replace(tzinfo=None), NOW) == ("free", False)


async def test_get_reads_the_callers_own_row() -> None:
    conn = Conn(mode="bring_data", seen={"/today": 2, "bad path": 1, "/x": "1"}, created=dt.datetime.now(dt.UTC))
    out = await me.get_preferences(CTX, conn)
    assert (out.start_mode, out.ask_start_mode, out.guide_seen) == ("bring_data", False, {"/today": 2})
    assert _where(conn.statements[0]) == {USER, ORG}


async def test_get_asks_a_new_person() -> None:
    out = await me.get_preferences(CTX, Conn(created=dt.datetime.now(dt.UTC)))
    assert (out.start_mode, out.ask_start_mode, out.guide_seen) == ("guided", True, {})


async def test_get_with_no_row_never_asks() -> None:
    out = await me.get_preferences(CTX, Conn(found=False))
    assert out.ask_start_mode is False


async def test_set_start_mode_writes_the_callers_own_row() -> None:
    conn = Conn()
    out = await me.set_start_mode(me.StartModeIn(start_mode="free"), CTX, conn)
    assert (out.start_mode, out.ask_start_mode, conn.mode) == ("free", False, "free")
    assert _where(conn.statements[-1]) == {USER, ORG}


async def test_set_start_mode_with_no_row_is_a_404() -> None:
    with pytest.raises(HTTPException) as err:
        await me.set_start_mode(me.StartModeIn(start_mode="guided"), CTX, Conn(rows=0))
    assert err.value.status_code == 404


def test_an_unknown_start_mode_is_refused() -> None:
    with pytest.raises(ValidationError):
        me.StartModeIn(start_mode="expert")


def test_the_migration_and_the_code_list_the_same_modes() -> None:
    import importlib.util
    import pathlib

    path = pathlib.Path(__file__).parents[2] / "migrations" / "versions" / "0553_users_start_mode.py"
    spec = importlib.util.spec_from_file_location("m0553", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    assert module._VALUES == me.START_MODES


async def test_guide_seen_keeps_the_newest_version_per_page() -> None:
    conn = Conn(seen={"/today": 1, "/reports": 1})
    out = await me.mark_guide_seen(me.GuideSeenIn(page="/today", version=2), CTX, conn)
    assert out.guide_seen == {"/reports": 1, "/today": 2} and conn.seen == out.guide_seen
    assert all(_where(s) == {USER, ORG} for s in conn.statements)


async def test_guide_seen_drops_the_oldest_past_the_cap() -> None:
    conn = Conn(seen={f"/p{i}": 1 for i in range(me.GUIDE_SEEN_MAX)})
    out = await me.mark_guide_seen(me.GuideSeenIn(page="/new", version=1), CTX, conn)
    assert len(out.guide_seen) == me.GUIDE_SEEN_MAX and "/p0" not in out.guide_seen and "/new" in out.guide_seen


async def test_guide_seen_with_no_row_is_a_404() -> None:
    with pytest.raises(HTTPException) as err:
        await me.mark_guide_seen(me.GuideSeenIn(page="/today", version=1), CTX, Conn(found=False))
    assert err.value.status_code == 404


@pytest.mark.parametrize(("page", "version"), [("today", 1), ("/Today", 1), ("/a b", 1), ("/" + "x" * 90, 1),
                                               ("/today", 0), ("/today", 1001)])
def test_a_bad_guide_seen_is_refused(page: str, version: int) -> None:
    with pytest.raises(ValidationError):
        me.GuideSeenIn(page=page, version=version)


async def test_show_me_around_again_clears_every_page() -> None:
    conn = Conn(seen={"/today": 3})
    out = await me.reset_guide_seen(CTX, conn)
    assert out.guide_seen == {} and conn.seen == {}
    assert _where(conn.statements[-1]) == {USER, ORG}


async def test_get_gives_mesiris_number_to_every_role(monkeypatch) -> None:
    from mesiri.bootstrap.settings import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("MESIRI_WHATSAPP__DISPLAY_NUMBER", " +91 90000 12345 ")
    try:
        engineer = SimpleNamespace(user_id=USER, organization_id=ORG, role="SITE_ENGINEER")
        assert (await me.get_preferences(engineer, Conn())).whatsapp_number == "+91 90000 12345"
        monkeypatch.setenv("MESIRI_WHATSAPP__DISPLAY_NUMBER", "")
        get_settings.cache_clear()
        assert (await me.get_preferences(engineer, Conn())).whatsapp_number is None  # an empty setting hides it
        monkeypatch.delenv("MESIRI_WHATSAPP__DISPLAY_NUMBER")
        get_settings.cache_clear()
        assert (await me.get_preferences(engineer, Conn())).whatsapp_number == "+91 95443 76072"  # SS-20 default
    finally:
        get_settings.cache_clear()
