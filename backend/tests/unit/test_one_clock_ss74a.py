"""SS-74a: one "today" (domains/shared/clock.py, guided-demo-plan.md section 18.5).

A learning sample company lives on its own date, carried by its token; every real company lives on the real date,
with nothing read from the database for it. These tests hold: the clock's rules, the token binding it, the shared
``company_today`` asking it first, the sandbox token and its day 0 (a Saturday), and that no code reads the real date
past the clock (a scan of the backend and the assistant, like the dashboard's build check for ``new Date()``).
"""

from __future__ import annotations

import ast
import asyncio
import datetime as dt
import re
import uuid
from pathlib import Path

import jwt

from mesiri.application.dpr import project_day
from mesiri.application.learn import sandbox
from mesiri.domains.identity.auth_service import ALGORITHM, SECRET_KEY
from mesiri.domains.shared import auth, clock

GAME = dt.date(2026, 11, 21)
REPO = Path(__file__).resolve().parents[3]


def test_a_real_company_gets_the_real_date():
    with clock.scope(None):
        assert clock.today() == dt.date.today()
        assert clock.override() is None
        assert clock.now().date() == dt.datetime.now().date()


def test_a_sample_company_gets_its_own_date_with_the_real_time_of_day():
    with clock.scope(GAME):
        assert clock.today() == GAME
        moment = clock.now(dt.UTC)
        assert moment.date() == GAME and moment.tzinfo is dt.UTC
        assert abs(moment.time().hour - dt.datetime.now(dt.UTC).hour) <= 1
    assert clock.override() is None  # restored after the block


def test_only_a_sandbox_token_names_a_date():
    with clock.scope(None):
        clock.bind_from_token({"sub": "u", "org": "o", "sandbox": "real-org", "today": GAME.isoformat()})
        assert clock.today() == GAME
        # A real token clears it: a stale binding never carries into another request's token.
        clock.bind_from_token({"sub": "u", "org": "o"})
        assert clock.override() is None
        # A date without the sandbox claim is ignored; a malformed date is the real date.
        clock.bind_from_token({"today": GAME.isoformat()})
        assert clock.override() is None
        clock.bind_from_token({"sandbox": "x", "today": "not a date"})
        assert clock.override() is None


def test_get_current_user_binds_the_token_date():
    token = jwt.encode({"sub": str(uuid.uuid4()), "org": str(uuid.uuid4()), "role": "ADMIN", "sandbox": "real",
                        "today": GAME.isoformat(), "exp": dt.datetime.now(dt.UTC) + dt.timedelta(hours=1)},
                       SECRET_KEY, algorithm=ALGORITHM)

    async def run():
        with clock.scope(None):
            await auth.get_current_user(f"Bearer {token}")
            return clock.today()

    assert asyncio.run(run()) == GAME


def test_company_today_asks_the_clock_first():
    class NoDatabase:
        async def execute(self, *_a, **_k):
            raise AssertionError("a sample company's today must not be read from the database")

    async def run():
        with clock.scope(GAME):
            return await project_day.company_today(NoDatabase(), uuid.uuid4())

    assert asyncio.run(run()) == GAME


def test_a_sample_company_starts_on_a_saturday_and_its_token_carries_the_date():
    # On the contract's calendar (21 Nov 2026): the same Saturday whenever it is opened, the plan's day 62 the eve of
    # the contract's handover (31 Jul 2027).
    from mesiri.application.learn.green_villa import CONTRACT

    for offset in range(0, 400, 37):
        zero = sandbox.day_zero(dt.date(2026, 11, 2) + dt.timedelta(days=offset))
        assert zero == dt.date(2027, 5, 29) and zero.weekday() == 5
    last = zero + dt.timedelta(days=sandbox.HANDOVER_DAY)
    assert 0 <= (dt.date.fromisoformat(CONTRACT["handover_on"]) - last).days < 7
    token, _exp = sandbox.sandbox_token(user_id=uuid.uuid4(), org_id=uuid.uuid4(), role="ADMIN", name="Asha",
                                        real_org=uuid.uuid4(), now=dt.datetime.now(dt.UTC), today=GAME)
    claims = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    assert claims["today"] == GAME.isoformat() and claims["sandbox"]


_REAL_TODAY = re.compile(r"(?<![`\w.])(?:_?dt\.|datetime\.)?date\.today\(\)")
#: Where the real date is meant: the clock itself, and command-line scripts run outside any request.
_ALLOWED = ("domains/shared/clock.py", "/scripts/")


def test_no_code_reads_the_real_date_past_the_clock():
    found = []
    for root in (REPO / "backend" / "src" / "mesiri", REPO / "apps" / "whatsapp-assistant" / "src"):
        for path in root.rglob("*.py"):
            rel = path.as_posix()
            if any(a in rel for a in _ALLOWED):
                continue
            source = path.read_text(encoding="utf-8")
            if "date.today()" not in source:
                continue
            docs: set[int] = set()
            for node in ast.walk(ast.parse(source)):
                if isinstance(node, ast.Expr) and isinstance(getattr(node, "value", None), ast.Constant) \
                        and isinstance(node.value.value, str):
                    docs.update(range(node.lineno, node.end_lineno + 1))
            for n, line in enumerate(source.splitlines(), 1):
                code = line.split("#", 1)[0]
                if n not in docs and _REAL_TODAY.search(code):
                    found.append(f"{path.relative_to(REPO)}:{n}")
    assert not found, f"use clock.today() from mesiri.domains.shared.clock (SS-74a): {found}"
