"""WA-209 (4 Nov, Adarsh, live): cement saved at 12:27 pm was answered as "innaale raavile" (yesterday morning), because
the model read every time in UTC; and a voice note heard as "30" instead of "5" was only seen on the list. Times the
model reads are now the company's own, it is told the time now, and a voice note's reply starts with what was heard.
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pytest
from tests.agent_api.standin import STAND_IN_TOOLS, two_receipts_model
from tests.agent_api.test_api_whatsapp_119 import CTX, Harness, _message

from agent_api import whatsapp as wa
from mesiri_contracts.assistant.enums import InputModality

IST = ZoneInfo("Asia/Kolkata")


@pytest.fixture(autouse=True)
def _stand_in_tools(monkeypatch):  # noqa: ANN001, ANN202 -- as test_api_whatsapp_119 does
    from agent_api import tools as tools_mod

    real = tools_mod.build_tools
    monkeypatch.setattr(wa, "build_tools", lambda openapi: real(
        openapi, tuple(a for a in tools_mod.ALLOWED if a.name in STAND_IN_TOOLS)))


@pytest.mark.parametrize(
    ("value", "clock"),
    [
        ("2026-11-05T06:57:00+00:00", "12:27"),  # the live case: 12:27 pm IST, not 06:57
        ("2026-11-05T06:57:00Z", "12:27"),
        ("2026-11-04T20:00:00+00:00", "01:30"),  # past midnight in India: the next day's clock
        ("2026-11-05T12:27:00+05:30", "12:27"),  # already in the company's time
        ("not a time", ""),
        (None, ""),
    ],
)
def test_an_api_time_is_the_companys_clock(value, clock) -> None:
    assert wa.local_clock(value, IST) == clock


def test_the_model_is_told_the_time_now_and_how_to_read_tool_times() -> None:
    line = wa.now_line(dt.datetime(2026, 11, 5, 12, 29, tzinfo=IST), IST)
    assert "Thursday 05 Nov 2026, 12:29" in line and "UTC+05:30" in line
    assert "UTC (+00:00)" in line and "today / yesterday" in line


def test_the_heard_line_is_short_and_marked() -> None:
    assert wa.heard_line("10 chaakku,  pinne 20 chaakku cement vannu") == "🎤 _10 chaakku, pinne 20 chaakku cement vannu_\n\n"
    long = wa.heard_line("x " * 300)
    assert long.endswith("…_\n\n") and len(long) <= wa.HEARD_MAX + 10


async def test_a_voice_notes_reply_starts_with_what_was_heard() -> None:
    h = Harness(two_receipts_model(), transcript="50 bag cement, 50 TMT vannu")
    await h.service.handle(_message(None, modality=InputModality.VOICE), CTX)
    reply = h.sent[-1]
    assert reply.text.startswith("🎤 _50 bag cement, 50 TMT vannu_\n\n")
    assert "*Ready to save:*" in reply.text  # the list and its buttons are as before
    assert [b.title for b in reply.buttons] == ["Save", wa.EDIT_TITLE, "Cancel"]


async def test_a_typed_message_has_no_heard_line() -> None:
    h = Harness(two_receipts_model())
    await h.service.handle(_message(), CTX)
    assert not h.sent[-1].text.startswith("🎤")


async def test_todays_entries_read_in_the_companys_time(monkeypatch) -> None:
    class _Got:
        ok = True
        body = {"items": [{"occurred_at": "2026-11-05T06:57:00+00:00", "site_id": None,
                           "event_type": "material_receipt", "summary": "10 bags Cement"}]}  # fmt: skip

    class _Client:
        async def call(self, method, path, params=None):  # noqa: ANN001, ANN202
            return _Got()

    h = Harness(two_receipts_model())
    text = await h.service._today(CTX, _Client(), [])
    assert "- 12:27 material_receipt: 10 bags Cement" in text
    assert "06:57" not in text
    assert text.startswith("It is now ")
