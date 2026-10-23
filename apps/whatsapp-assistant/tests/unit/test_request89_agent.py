"""Request 89 (22 Oct re-test): a past day's report counted from the saved
entries and sent as a draft PDF, the reply language decided in code, natural
lines above a Save card."""

from __future__ import annotations

import datetime
from types import SimpleNamespace
from typing import Any

import pytest

from mesiri_ai.fakes import FakeToolCallingProvider
from runtime.agent import reply_text as rt
from runtime.agent import runner as r
from runtime.agent.prompt import AgentContext, reply_language, reply_letters_rule
from runtime.agent.query_entry import QueryEntry, _one_name_per_trade
from runtime.agent.tools import ScopeLookup, to_candidate
from runtime.dpr_request_query import for_document, only_kept

# -- 1. one rule for a past day's report ---------------------------------------

YESTERDAY = datetime.date(2026, 10, 21)


class _Storage:
    def __init__(self, existing: set[str] | None = None) -> None:
        self.objects: dict[str, bytes] = {}
        self.existing = existing or set()

    async def put_object(self, key: str, data: bytes, content_type: str = "") -> None:
        self.objects[key] = data

    async def head_object(self, key: str) -> None:
        if key not in self.existing and key not in self.objects:
            raise FileNotFoundError(key)


class _Query:
    def __init__(self, lines: list[str], *, project: dict | None = None, pdf: bytes | None = b"%PDF-draft") -> None:
        self.lines, self.pdf, self.project = lines, pdf, project or {"status": "not_generated"}
        self.asked: dict[str, Any] = {}
        self.project_asked: dict[str, Any] = {}

    async def draft_pdf(self, **kw: Any) -> tuple[list[str], bytes | None]:
        self.asked = kw
        return self.lines, self.pdf if self.lines else None

    async def find_report(self, **kw: Any) -> dict[str, Any]:
        self.project_asked = kw
        return self.project


SITE = SimpleNamespace(id="s1", name="Green Villa", project_id="p1")
ACTOR = SimpleNamespace(organization_id="org", projects=[SimpleNamespace(id="p1")], sites=[SITE])


def _ready(status: str, *, said: str = "yesterday", day: str = "21 Oct 2026") -> SimpleNamespace:
    event = SimpleNamespace(
        project_id=None,
        site_id=None,
        fields={"dpr_day": day, "dpr_status": status, "report_date": said, "dpr_site_name": "Green Villa", "dpr_update_count": 0},
    )
    return SimpleNamespace(event=event)


@pytest.fixture
def at_ist(monkeypatch: pytest.MonkeyPatch) -> list[str | None]:
    """Today in the project's zone is 22 Oct; records which zone was asked."""
    zones: list[str | None] = []

    def today(zone: str | None) -> datetime.date:
        zones.append(zone)
        return datetime.date(2026, 10, 22)

    monkeypatch.setattr("runtime.agent.query_entry.project_today", today)
    return zones


async def test_an_unconfirmed_past_day_with_entries_is_sent_as_a_draft_pdf(at_ist):
    storage, query = _Storage(), _Query(["• Labour: 16 workers", "• Materials: Cement, M sand"])
    entry = QueryEntry(None, None, ACTOR, dpr_request_query=query, object_storage=storage)
    ready = _ready("pending_confirmation")
    assert await entry._past_day_draft(ready, timezone="Asia/Kolkata") is None  # the workflow's "attached" line follows
    fields = ready.event.fields
    assert fields["dpr_status"] == "ready" and fields["dpr_confirmed"] is False
    assert fields["dpr_code"] == "Draft-20261021"
    assert storage.objects[fields["dpr_object_key"]] == b"%PDF-draft"
    # the day is the project's: the zone was asked for, and yesterday is the 21st
    assert at_ist == ["Asia/Kolkata"]
    assert query.asked["report_date"] == YESTERDAY and query.asked["site_id"] == "s1"


async def test_both_phrasings_take_the_same_path_and_get_the_same_answer(at_ist):
    answers = []
    for said, wording in (("yesterday", "send yesterday's report"), ("innale", "innale report ayakku")):
        candidate = to_candidate("request_dpr", {"date": said}, ScopeLookup())
        assert candidate.fields["report_date"] == "yesterday", wording
        entry = QueryEntry(None, None, ACTOR, dpr_request_query=_Query(["• Labour: 16 workers"]), object_storage=_Storage())
        ready = _ready("pending_confirmation", said=candidate.fields["report_date"])
        await entry._past_day_draft(ready, timezone="Asia/Kolkata")
        answers.append({k: v for k, v in ready.event.fields.items() if k != "dpr_object_key"})
    assert answers[0] == answers[1] and answers[0]["dpr_status"] == "ready"


async def test_the_workflow_says_attached_and_not_confirmed_for_the_draft(at_ist):
    from workflows.dpr_request.nodes import generate_dpr_request_reply

    entry = QueryEntry(None, None, ACTOR, dpr_request_query=_Query(["• Labour: 16 workers"]), object_storage=_Storage())
    ready = _ready("pending_confirmation")
    await entry._past_day_draft(ready, timezone="Asia/Kolkata")
    text = generate_dpr_request_reply({"collected_fields": ready.event.fields})["pending_prompt"]
    assert "attached" in text and "Not confirmed yet" in text and "0 updates" not in text


async def test_a_confirmed_project_pdf_for_the_day_is_sent_as_that(at_ist):
    project = {"status": "ready", "object_key": "dpr/p/1.pdf", "code": "DPR-20261021-543A", "confirmed": True}
    storage = _Storage({"dpr/p/1.pdf"})
    query = _Query(["• Labour: 16 workers"], project=project)
    entry = QueryEntry(None, None, ACTOR, dpr_request_query=query, object_storage=storage)
    ready = _ready("pending_confirmation")
    assert await entry._past_day_draft(ready, timezone="Asia/Kolkata") is None
    fields = ready.event.fields
    assert (fields["dpr_status"], fields["dpr_object_key"], fields["dpr_code"], fields["dpr_confirmed"]) == (
        "ready", "dpr/p/1.pdf", "DPR-20261021-543A", True
    )
    assert query.project_asked["site_id"] is None and storage.objects == {}  # no draft made


async def test_a_day_with_no_entries_says_there_is_none(at_ist):
    from workflows.dpr_request.nodes import generate_dpr_request_reply

    storage = _Storage()
    entry = QueryEntry(None, None, ACTOR, dpr_request_query=_Query([]), object_storage=storage)
    ready = _ready("pending_confirmation")
    assert await entry._past_day_draft(ready, timezone="Asia/Kolkata") is None
    text = generate_dpr_request_reply({"collected_fields": ready.event.fields})["pending_prompt"]
    assert text.startswith("There is no DPR for 21 Oct 2026") and "0 updates" not in text
    assert storage.objects == {}


async def test_a_draft_that_cannot_be_rendered_is_shown_as_text(at_ist):
    entry = QueryEntry(None, None, ACTOR, dpr_request_query=_Query(["• Labour: 16 workers"], pdf=None), object_storage=_Storage())
    say = await entry._past_day_draft(_ready("pending_confirmation"), timezone="Asia/Kolkata")
    assert say.status == "answer" and "isn't confirmed yet" in say.text and "• Labour: 16 workers" in say.text


async def test_today_and_a_ready_pdf_are_left_alone(at_ist):
    entry = QueryEntry(None, None, ACTOR, dpr_request_query=_Query(["• Labour: 16 workers"]), object_storage=_Storage())
    assert await entry._past_day_draft(_ready("pending_confirmation", day=""), timezone="Asia/Kolkata") is None
    ready = _ready("ready")
    assert await entry._past_day_draft(ready, timezone="Asia/Kolkata") is None
    assert ready.event.fields["dpr_status"] == "ready" and "dpr_object_key" not in ready.event.fields


def test_the_ist_day_boundary_is_the_projects_not_utc():
    """00:30 IST on the 22nd is still the 21st in UTC: yesterday is the 21st."""
    from zoneinfo import ZoneInfo

    from canonicalization.occurred_date import parse_stated_date

    ist = datetime.datetime(2026, 10, 22, 0, 30, tzinfo=ZoneInfo("Asia/Kolkata"))
    assert ist.astimezone(datetime.UTC).date() == YESTERDAY
    assert parse_stated_date("yesterday", today=ist.date()) == YESTERDAY


def test_the_document_leaves_out_what_was_cancelled():
    payload = {
        "activities": [{"work_type": "a", "review": "rejected"}, {"work_type": "b", "review": "confirmed"}],
        "issues": [{"issue_type": "x", "review": "rejected"}],
        "materials": [{"material_name": "Steel"}, {"material_name": "Cement"}],
        "activity_count": 2,
    }
    items = [{"section": "materials", "title": "Cement", "review": "confirmed"},
             {"section": "work", "review": "rejected"}]
    out = for_document(only_kept(payload, items))
    assert [a["work_type"] for a in out["activities"]] == ["b"] and out["issues"] == []
    assert [m["material_name"] for m in out["materials"]] == ["Cement"]


# -- 2. the reply language is decided in code ----------------------------------


@pytest.mark.parametrize(
    "text, language",
    [
        ("used 10 bags cement for columns", "english"),
        ("crane breakdown, work stopped since morning", "english"),
        ("send yesterday's report", "english"),
        ("how many workers this week?", "english"),
        ("ground floor flooring theernnu", "manglish"),
        ("innale report ayakku", "manglish"),
        ("2 painter vannu", "manglish"),
        ("ഇന്ന് 5 പേർ വന്നു", "malayalam"),
        ("आज 5 मिस्त्री आए", "hindi"),
        ("ok", None),
        ("50 bags", None),
        ("👍", None),
    ],
)
def test_the_language_comes_from_the_message(text, language):
    assert reply_language(text) == language


def test_the_instruction_is_hard_and_says_which_language():
    assert "English only" in reply_letters_rule("used 10 bags cement for columns")
    assert "Manglish" in reply_letters_rule("ground floor flooring theernnu")
    assert "Malayalam script" in reply_letters_rule("ഇന്ന് 5 പേർ വന്നു")
    assert reply_letters_rule("👍") is None


@pytest.mark.parametrize(
    "reply",
    ["Okay. Nokki shariyenkil Save tap cheyyu.", "Okay. Shariyenkil Save tap cheyyu.", "Ayyo, pani nirthi."],
)
def test_manglish_for_an_english_message_is_a_mismatch(reply):
    assert r.script_problems(reply, "used 10 bags cement for columns")
    assert r.script_problems(reply, "crane breakdown, work stopped since morning")


def test_each_language_in_the_same_language_out_passes():
    assert not r.script_problems("Got it, 10 bags cement used for columns. Please check it and tap Save.", "used 10 bags cement for columns")
    assert not r.script_problems("Sheri, ground floor flooring theernnu. Nokki Save tap cheyyu.", "ground floor flooring theernnu")
    assert not r.script_problems("ശരി, 5 പേർ. ശരിയാണെങ്കിൽ Save അമർത്തുക.", "ഇന്ന് 5 പേർ വന്നു")
    assert r.script_problems("Got it, 5 people today. Please check it and tap Save.", "ഇന്ന് 5 പേർ വന്നു")  # English for Malayalam


CTX = AgentContext(
    user_name="Anil", role="SUPERVISOR", company="Acme", now=datetime.datetime(2026, 10, 22, 9, 30),
    projects=(("Project Alpha", None),), sites=(("Site A1", "Project Alpha"),),
)


class _Provider(FakeToolCallingProvider):
    """The first run is scripted (tool calls, then words); the runner's later
    no-tool tries answer from ``retries`` in turn (the fake would replay the script)."""

    def __init__(self, script: list, retries: list[str]) -> None:
        super().__init__(script)
        self.retries = list(retries)
        self.asked: list[str] = []

    async def run_tools(self, system_prompt, messages, tools, handler, **kw):  # noqa: ANN001, ANN201
        if self.calls == 0:
            return await super().run_tools(system_prompt, messages, tools, handler, **kw)
        from mesiri_ai.models import ToolRunResult

        self.calls += 1
        self.asked.append(messages[-1].text)
        return ToolRunResult(text=self.retries.pop(0), calls=[], steps=1, stop_reason="answered", model="fake")


async def _reply_for(user_text: str, script: list, retries: list[str], summary: str = "10 bags cement used (columns)", saved: str = "") -> tuple[str, FakeToolCallingProvider]:
    """Run the runner with a gateway that prepares one card line; ``script`` is the model's turns."""
    from runtime.agent.gateway import StepResult

    class Gateway:
        async def run(self, candidate, *, text):  # noqa: ANN001, ANN202
            return StepResult("saved", text=saved or summary, summary=summary)

    provider = _Provider(script, retries)
    result = await r.AgentRunner(provider).run(
        ctx=CTX, user_text=user_text, gateway=Gateway(), scope=ScopeLookup()
    )
    return result.reply.text, provider


CEMENT = [("save_material_usage", {"material": "cement", "quantity": 10, "unit": "bags", "purpose": "columns"})]


async def test_manglish_for_english_is_asked_again_once_then_corrected():
    text, provider = await _reply_for(
        "used 10 bags cement for columns",
        [CEMENT, "Okay. Nokki shariyenkil Save tap cheyyu."],
        ["Got it, 10 bags cement used for columns. Please check it and tap Save."],
    )
    assert text.startswith("Got it, 10 bags cement used for columns. Please check it and tap Save.")
    assert len(provider.asked) == 1 and "English only" in provider.asked[0]
    assert not rt.manglish_word_count(text, r._MANGLISH_WORDS)


async def test_when_the_second_try_is_wrong_too_the_code_line_in_english_goes_out():
    text, provider = await _reply_for(
        "used 10 bags cement for columns",
        [CEMENT, "Okay. Nokki shariyenkil Save tap cheyyu."],
        ["Sheri. Shariyenkil Save tap cheyyu."],
    )
    assert sum("was rejected" in a for a in provider.asked) == 1  # the language is asked again once, not more
    assert text.startswith("10 bags cement used (columns). Please check it and tap Save.")
    assert not rt.manglish_word_count(text, r._MANGLISH_WORDS)


# -- 3. natural lines --------------------------------------------------------------


@pytest.mark.parametrize("bare", ["Okay.", "Ok.", "Okay, noted."])
async def test_a_flat_okay_never_goes_out_above_a_card(bare):
    text, _ = await _reply_for(
        "crane breakdown, work stopped since morning",
        [[("report_issue", {"issue_type": "EQUIPMENT", "narrative": "crane breakdown, work stopped"})], bare],
        [bare, bare],
        summary="Issue: crane breakdown, work stopped",
    )
    first = text.split("\n")[0]
    assert "crane breakdown, work stopped" in first.casefold()
    assert "tap Save" in first and not first.startswith(("Okay", "Ok."))


def test_the_natural_fallback_is_built_from_the_items_in_each_language():
    items = ["Crane breakdown, work stopped"]
    assert r.covering_sentence(items, "crane breakdown, work stopped since morning") == "Crane breakdown, work stopped. Please check it and tap Save."
    assert r.covering_sentence(items, "crane kedayi pani nirthi").endswith("Save tap cheyyu.")
    assert "അമർത്തുക" in r.covering_sentence(items, "ക്രെയിൻ കേടായി")
    for lang_text in ("hello there", "crane kedayi pani nirthi", "ക്രെയിൻ കേടായി", "क्रेन खराब"):
        line = r.covering_sentence(items, lang_text)
        assert not line.startswith(("Okay", "Ok.")) and "saved" not in line.casefold()


def test_stray_sentences_tied_to_nothing_go():
    grounds = ["undo that", "Removed: 20 workers (today)"]
    assert rt.without_stray_sentences("Nale nokkam. Sheri, pani maattiyittund.", grounds) == "Sheri, pani maattiyittund."
    grounds = ["10 bags cement used for columns", "10 bags cement used (columns)"]
    reply = "Sheri, 10 bags cement used for columns. Verenthenkilum ariyamo? Nokki shariyenkil Save tap cheyyu."
    assert rt.without_stray_sentences(reply, grounds) == "Sheri, 10 bags cement used for columns. Nokki shariyenkil Save tap cheyyu."
    steel = "Ethra steel venam ennu paranjal record cheyyam."
    assert rt.without_stray_sentences("Got it, steel needed. " + steel, ["steel needed"]) == "Got it, steel needed."


def test_a_human_touch_and_a_save_ask_are_kept_and_a_reply_is_never_emptied():
    grounds = ["crane breakdown, work stopped since morning"]
    reply = "Sorry to hear that. Crane breakdown, work stopped since morning. Check it and tap Save."
    assert rt.without_stray_sentences(reply, grounds) == reply
    assert rt.without_stray_sentences("Anything else? Let me know if you need me.", grounds) == "Anything else? Let me know if you need me."


async def test_a_stray_line_before_a_system_line_is_dropped():
    from runtime.agent.gateway import StepResult

    class Gateway:
        async def undo_card(self, targets):  # noqa: ANN001, ANN202
            return StepResult("undone", text="Removed: 20 workers (today)")

    provider = FakeToolCallingProvider([[("undo_last", {})], "Nale nokkam. Sheri, mattiyittund."])  # noqa: E501
    result = await r.AgentRunner(provider).run(ctx=CTX, user_text="undo that", gateway=Gateway(), scope=ScopeLookup())
    assert "Nale nokkam" not in result.reply.text


def test_trades_in_a_labour_answer_are_shown_once_each():
    results = {"trades": ["mason", "masons", "Masons", "bar_bending", "bar_bender", "helper"]}
    _one_name_per_trade(results)
    from trade_label import trade_label

    assert [trade_label(t) for t in results["trades"]] == ["Mason", "Bar bender", "Helper"]


def test_the_prompt_carries_six_examples_per_language_and_the_pattern():
    from runtime.agent.prompt import SYSTEM_PROMPT

    for header in ("English message -> English reply", "Manglish message -> Manglish reply", "Malayalam script message -> Malayalam script reply"):
        block = SYSTEM_PROMPT.split(header, 1)[1].split("\n  ", 1)[1].split("\nManglish message", 1)[0].split("\nMalayalam script message", 1)[0]
        assert block.count(" -> ") >= 6 or header.startswith("Malayalam") or header.startswith("Manglish")
    assert SYSTEM_PROMPT.count(" -> ") >= 18
    assert "No \\\nfiller" not in SYSTEM_PROMPT and "Nale nokkam" in SYSTEM_PROMPT  # named as what NOT to write
