"""SA-16: Claude's read-only control-plane API -- the token gate and the
secret hiding. Runs against Postgres in
tests/integration/test_claude_ops_postgres.py."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from mesiri.domains.admin import claude_ops_router as ops

TOKEN = "t" * 40
BCRYPT = "$2b$12$abcdefghijklmnopqrstuvabcdefghijklmnopqrstuvwxyz12345"


@pytest.fixture(autouse=True)
def _fresh_settings():
    from mesiri.bootstrap.settings import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.parametrize("configured", [None, "", "short-token"])
async def test_api_is_off_without_a_long_enough_token(monkeypatch, configured) -> None:
    if configured is None:
        monkeypatch.delenv("MESIRI_CLAUDE_OPS_TOKEN", raising=False)
    else:
        monkeypatch.setenv("MESIRI_CLAUDE_OPS_TOKEN", configured)
    with pytest.raises(HTTPException) as off:
        await ops.require_claude_ops(f"Bearer {configured or TOKEN}")
    assert off.value.status_code == 404


@pytest.mark.parametrize("header", [None, "", "Bearer wrong", TOKEN, f"Basic {TOKEN}"])
async def test_wrong_or_missing_token_is_refused(monkeypatch, header) -> None:
    monkeypatch.setenv("MESIRI_CLAUDE_OPS_TOKEN", TOKEN)
    with pytest.raises(HTTPException) as refused:
        await ops.require_claude_ops(header)
    assert refused.value.status_code == 401


async def test_right_token_passes(monkeypatch) -> None:
    monkeypatch.setenv("MESIRI_CLAUDE_OPS_TOKEN", TOKEN)
    assert await ops.require_claude_ops(f"Bearer {TOKEN}") is None


@pytest.mark.parametrize(
    "sql",
    [
        "select * from ai_provider_secrets",
        "SELECT hashed_password FROM users",
        "select code_hash from login_codes",
        "select api_key from x",
    ],
)
def test_sql_naming_secrets_is_refused(sql: str) -> None:
    with pytest.raises(HTTPException) as refused:
        ops.check_no_secrets(sql)
    assert refused.value.status_code == 400


def test_innocent_sql_passes() -> None:
    ops.check_no_secrets("select * from users where note like '%password%'")


def test_secrets_are_hidden_by_column_key_and_hash_shape() -> None:
    assert ops.hide_secrets("x", "hashed_password") == ops.HIDDEN
    assert ops.hide_secrets(None, "api_key") is None
    assert ops.hide_secrets(f"(1,a,{BCRYPT},b)") == f"(1,a,{ops.HIDDEN},b)"
    assert ops.hide_secrets({"user": {"hashed_password": "h", "name": "Ravi"}}) == {
        "user": {"hashed_password": ops.HIDDEN, "name": "Ravi"}
    }
    assert ops.hide_secrets([BCRYPT]) == [ops.HIDDEN]
    argon = "$argon2id$v=19$m=65536,t=3,p=4$abcABC$defDEF"
    assert ops.hide_secrets(f"x {argon} y") == f"x {ops.HIDDEN} y"
    assert ops.hide_secrets("paid $20 and $2 more") == "paid $20 and $2 more"
