"""Request 67: "send me today's report" with entries saved gets the draft PDF
(the existing draft renderer), not a dead end."""

from __future__ import annotations

import datetime
from types import SimpleNamespace
from typing import Any

import pytest

from runtime.agent.query_entry import DPR_RETRY_REPLY, QueryEntry
from workflows.dpr_request.nodes import generate_dpr_request_reply

TODAY = datetime.date(2026, 10, 20)
SITE = SimpleNamespace(id="s1", name="Green Villa", project_id="p1")
ACTOR = SimpleNamespace(organization_id="org", projects=[SimpleNamespace(id="p1")], sites=[SITE])


class _Storage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put_object(self, key: str, data: bytes, content_type: str = "") -> None:
        self.objects[key] = data

    async def head_object(self, key: str) -> None:
        return None


class _Query:
    def __init__(self, lines: list[str], *, boom: bool = False) -> None:
        self.lines, self.boom, self.draft_calls, self.find_calls = lines, boom, 0, 0

    async def draft_pdf(self, **kw: Any) -> tuple[list[str], bytes | None]:
        self.draft_calls += 1
        if self.boom:
            raise RuntimeError("renderer down")
        self.asked = kw
        return self.lines, b"%PDF" if self.lines else None

    async def find_report(self, **kw: Any) -> dict[str, Any]:
        self.find_calls += 1
        return {"status": "not_generated"}


def _ready(status: str) -> SimpleNamespace:
    fields = {"dpr_day": "", "dpr_status": status, "dpr_site_name": "Green Villa", "dpr_preview": "x"}
    return SimpleNamespace(event=SimpleNamespace(project_id=None, site_id=None, fields=fields))


@pytest.fixture(autouse=True)
def _today(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("runtime.agent.query_entry.project_today", lambda zone: TODAY)


@pytest.mark.parametrize("status", ["not_generated", "preview", "pending_confirmation", "waiting"])
async def test_today_with_entries_sends_the_draft_pdf_once(status):
    storage, query = _Storage(), _Query(["• Labour: 16 workers"])
    entry = QueryEntry(None, None, ACTOR, dpr_request_query=query, object_storage=storage)
    ready = _ready(status)
    assert await entry._past_day_draft(ready, timezone="Asia/Kolkata") is None
    fields = ready.event.fields
    assert query.draft_calls == 1 and query.asked["report_date"] == TODAY
    assert fields["dpr_status"] == "ready" and fields["dpr_confirmed"] is False
    assert storage.objects[fields["dpr_object_key"]] == b"%PDF"
    text = generate_dpr_request_reply({"collected_fields": fields})["pending_prompt"]
    assert text.startswith("Today's DPR") and "attached" in text


async def test_today_with_nothing_logged_says_so_in_the_new_words():
    entry = QueryEntry(None, None, ACTOR, dpr_request_query=_Query([]), object_storage=_Storage())
    ready = _ready("not_generated")
    assert await entry._past_day_draft(ready, timezone="Asia/Kolkata") is None
    text = generate_dpr_request_reply({"collected_fields": ready.event.fields})["pending_prompt"]
    assert text == "Nothing's been logged for today yet, so there's no report. Send me today's update and I'll make it."


async def test_a_report_that_already_exists_is_not_made_again():
    query = _Query(["• Labour: 16 workers"])
    entry = QueryEntry(None, None, ACTOR, dpr_request_query=query, object_storage=_Storage())
    ready = _ready("ready")
    assert await entry._past_day_draft(ready, timezone="Asia/Kolkata") is None
    assert query.draft_calls == 0 and ready.event.fields["dpr_status"] == "ready"


async def test_a_failed_draft_gets_the_retry_later_words(caplog):
    entry = QueryEntry(None, None, ACTOR, dpr_request_query=_Query(["x"], boom=True), object_storage=_Storage())
    say = await entry._past_day_draft(_ready("not_generated"), timezone="Asia/Kolkata")
    assert say.text == DPR_RETRY_REPLY == "Couldn't make today's report just now, try again in a few minutes."
    assert "Traceback" not in say.text
    assert any("past_draft_failed" in r.message for r in caplog.records)


def test_the_new_texts_are_localised():
    from runtime.reply_language import localize_fixed_reply

    for text in (DPR_RETRY_REPLY, generate_dpr_request_reply({"collected_fields": {}})["pending_prompt"]):
        for lang, script in (("malayalam", "native"), ("hindi", "native")):
            assert localize_fixed_reply(text, lang, script) != text, (lang, text)
