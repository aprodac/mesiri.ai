"""SS-66: the sandbox status is known (never read as suspended) and never operational, so nothing that runs on its
own reaches a person's learning company; the sandbox router refuses a sandbox token and a platform admin."""

from __future__ import annotations

import asyncio
import datetime as dt
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from mesiri.domains.learn import sandbox_router
from mesiri.domains.organizations import lifecycle

NOW = dt.datetime(2026, 11, 17, tzinfo=dt.UTC)


def test_sandbox_is_its_own_status_and_not_operational() -> None:
    assert lifecycle.effective_status("sandbox", None, NOW) == lifecycle.SANDBOX
    assert not lifecycle.is_operational("sandbox", None, NOW)
    assert "'sandbox'" not in lifecycle.operational_sql("o")
    assert "sandbox" in lifecycle.SIGNUP_SOURCES


@pytest.mark.parametrize("payload", [{"sub": "x", "org": "y", "sandbox": "z"}, {"sub": "00000000-0000-0000-0000-000000000001", "org": ""}])
def test_router_refuses_a_sandbox_token_and_a_platform_admin(payload) -> None:  # noqa: ANN001
    with pytest.raises(HTTPException) as err:
        asyncio.run(sandbox_router._person(SimpleNamespace(), payload))
    assert err.value.status_code == 403


def test_the_database_refusal_becomes_a_plain_reason() -> None:
    from mesiri.http.db_errors import invalid_value_detail

    message = ('(sqlalchemy.dialects.postgresql.asyncpg.Error) <class \'asyncpg.exceptions.CheckViolationError\'>: '
               "MESIRI_SANDBOX: People in the sample company can't have a WhatsApp number, so nothing in it reaches a real phone.")
    assert invalid_value_detail(message) == (
        "People in the sample company can't have a WhatsApp number, so nothing in it reaches a real phone.")


def test_a_sample_company_may_message_mesiri_but_is_never_operational() -> None:
    """UX-26: Tell Mesiri in a sample company. Its person may send a message; nothing that runs by itself reaches it."""
    assert lifecycle.may_message("sandbox", None, NOW) is True
    assert lifecycle.is_operational("sandbox", None, NOW) is False
    # The guards: the rule for a message is otherwise exactly is_operational.
    assert lifecycle.may_message("active", None, NOW) is True
    for status in ("expired", "suspended", "pending", None):
        assert lifecycle.may_message(status, None, NOW) is False
    assert lifecycle.may_message("trial", NOW - dt.timedelta(days=1), NOW) is False
