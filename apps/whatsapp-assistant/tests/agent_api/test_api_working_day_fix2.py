"""Fix 2: before the company's working day starts, the model is told "today" is the day that just ended, and the date
it is given ("Today is ...") is that working day, so an update sent at 00:05 is dated the day it describes."""

from __future__ import annotations

import datetime as dt
from typing import Any
from zoneinfo import ZoneInfo

from tests.agent_api.standin import ACTOR, stand_in_api, stand_in_tools

from agent_api.agent import ApiAgent
from agent_api.client import ApiClient
from agent_api.whatsapp import now_line
from mesiri_ai.fakes import FakeToolCallingProvider

IST = ZoneInfo("Asia/Kolkata")


def test_after_midnight_the_model_is_told_the_working_day() -> None:
    line = now_line(dt.datetime(2026, 11, 8, 0, 5, tzinfo=IST), IST, dt.date(2026, 11, 7), "04:00")
    assert "The working day is still Saturday 07 Nov" in line and "entries are dated 2026-11-07" in line


def test_guard_in_the_day_nothing_is_added() -> None:
    line = now_line(dt.datetime(2026, 11, 8, 10, 0, tzinfo=IST), IST, dt.date(2026, 11, 8), "04:00")
    assert "working day" not in line


class Recording(FakeToolCallingProvider):
    systems: list[str] = []

    async def run_tools(self, system: str, *args: Any, **kwargs: Any) -> Any:
        self.systems.append(system)
        return await super().run_tools(system, *args, **kwargs)


async def test_the_date_the_model_is_given_is_the_working_day() -> None:
    model = Recording(["ok"])
    app = stand_in_api([])
    client = ApiClient(ACTOR, app=app)
    try:  # a day that starts at 11:59: before noon it is "still yesterday"
        await ApiAgent(model, stand_in_tools(app)).run(client, "innu 4 mason", day_starts_at="11:59")
    finally:
        await client.close()
    now = dt.datetime.now(IST)
    expected = now.date() - dt.timedelta(days=1) if now.time() < dt.time(11, 59) else now.date()
    assert f"Today is {expected.isoformat()}" in model.systems[-1]
