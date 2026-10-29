"""Request 143, phase 2: "send me the report" is always a PDF from Day Facts, made
and sent by code, with one sentence of the code's in the sender's language.

Repro (live, 29 Oct): "innathe report ayakku" came back as "Today's report ready
aayittilla, ithu oru draft aanu..." with no content and no PDF.
"""

from __future__ import annotations

import datetime
from types import SimpleNamespace
from typing import Any

import pytest

from runtime.agent import report_entry as re_mod
from runtime.agent import runner as r
from runtime.agent.entry_base import Say, Scoped
from runtime.agent.report_entry import ReportEntry
from runtime.agent.tools import ScopeLookup, to_candidate
from runtime.agent.wording import LANGUAGES, LINES, day_words, language_of, say
from runtime.day_facts import DayFacts, SiteDay, for_document, only_kept

TODAY = datetime.date(2026, 10, 29)
YESTERDAY = datetime.date(2026, 10, 28)

GREEN = SimpleNamespace(id="s1", name="Green Villa", project_id="p1")
SITE_B = SimpleNamespace(id="s2", name="Site B", project_id="p1")

DAY_PAYLOAD = {
    "site_name": "Green Villa",
    "activities": [
        {"work_type": "tiling", "narrative": "Ground floor tiling 40%", "quantities": []},
        {"work_type": "plastering", "narrative": "Plastering 150 sqft",
         "quantities": [{"quantity": "150", "unit": "sqft"}]},
    ],
    "activity_count": 2,
    "labour": {"headcount": 11, "trades": [{"trade": "mason", "headcount": 4}, {"trade": "helper", "headcount": 7}]},
    "materials": [{"material_name": "Cement"}],
    "issues": [{"issue_type": "EQUIPMENT_BREAKDOWN", "status": "OPEN"}],
    "open_issue_count": 1,
}


def _day(site_id: str, payload: dict | None) -> SiteDay:
    return SiteDay("org", "p1", site_id, TODAY, payload=dict(payload or {}))


class _Facts:
    """Day Facts with the day each site holds; records what was read."""

    def __init__(self, days: dict[str, dict | None]) -> None:
        self.days, self.read = days, []

    async def site_day(self, *, organization_id: Any, project_id: Any, site_id: Any, day: Any) -> SiteDay:
        self.read.append((site_id, day))
        return _day(site_id, self.days.get(site_id))


class _Stored:
    """find_report: a confirmed PDF for the scopes in ``ready``."""

    def __init__(self, ready: dict[str | None, dict] | None = None) -> None:
        self.ready = ready or {}

    async def find_report(self, *, site_id: Any, **_: Any) -> dict[str, Any]:
        return self.ready.get(site_id, {"status": "not_generated", "object_key": None, "code": None})


class _Storage:
    def __init__(self, keys: dict[str, bytes] | None = None) -> None:
        self.keys = keys or {}

    async def head_object(self, key: str) -> None:
        if key not in self.keys:
            raise FileNotFoundError(key)

    async def get_object(self, key: str) -> Any:
        return SimpleNamespace(data=self.keys[key])


class _Renderer:
    def __init__(self, fail: bool = False) -> None:
        self.html: list[str] = []
        self.fail = fail

    async def render_pdf(self, html: str) -> bytes:
        if self.fail:
            raise RuntimeError("chromium gone")
        self.html.append(html)
        return b"%PDF-draft"


class _Entry(ReportEntry):
    """The entry with its scope settled by the test (no context resolver)."""


def _entry(
    facts: _Facts,
    *,
    sites=(GREEN,),
    site_id: str | None = "s1",
    stored: _Stored | None = None,
    storage: _Storage | None = None,
    renderer: _Renderer | None = None,
    send_ok: bool = True,
) -> tuple[ReportEntry, list[tuple[str, bytes]]]:
    sent: list[tuple[str, bytes]] = []

    async def send_document(wa_id: str, data: bytes, *, filename: str, caption: Any) -> bool:
        sent.append((filename, data))
        return send_ok

    actor = SimpleNamespace(organization_id="org", sites=list(sites), projects=[SimpleNamespace(id="p1")])
    entry = _Entry(
        context_resolver=None,
        org_settings_query=None,
        actor=actor,
        day_facts=facts,
        dpr_request_query=stored or _Stored(),
        object_storage=storage or _Storage(),
        send_document=send_document,
        renderer=renderer or _Renderer(),
    )

    async def settle(*_: Any, **__: Any) -> Scoped:
        return Scoped(SimpleNamespace(timezone="Asia/Kolkata"), "org", "p1", site_id, "p1", site_id)

    entry.settle = settle  # type: ignore[method-assign]
    return entry, sent


def _ask(text: str, date: str | None = None) -> tuple[SimpleNamespace, Any]:
    candidate = to_candidate("request_dpr", {"date": date} if date else {}, ScopeLookup())
    message = SimpleNamespace(text=text, correlation_id="c1", sender=SimpleNamespace(wa_id="91"))
    return message, candidate


async def _run(entry: ReportEntry, text: str, date: str | None = None) -> Say:
    message, candidate = _ask(text, date)
    return await entry.prepare(message, None, candidate)


@pytest.fixture(autouse=True)
def _today(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(re_mod, "project_today", lambda zone: TODAY)


# -- the repro: always a PDF, with the day in it -------------------------------


async def test_innathe_report_ayakku_sends_the_days_pdf_with_its_content():
    facts, renderer = _Facts({"s1": DAY_PAYLOAD}), _Renderer()
    entry, sent = _entry(facts, renderer=renderer)
    message, candidate = _ask("innathe report ayakku")
    said = await entry.prepare(message, None, candidate)
    assert isinstance(said, Say) and said.status == "answer" and said.documents == 1
    assert said.text == "Innathe draft report · Green Villa ithaa, ithuvare save cheythathil ninnu. Confirm aayittilla."
    assert "ready aayittilla" not in said.text
    (filename, data), = sent
    assert data == b"%PDF-draft" and filename == "Draft-DPR-Green-Villa-20261029.pdf"
    html = renderer.html[0]
    for shown in ("Tiling", "Plastering", "150", "Cement"):
        assert shown in html, shown
    assert facts.read == [("s1", TODAY)]  # the project's today, read once


async def test_an_english_ask_gets_the_english_line():
    entry, sent = _entry(_Facts({"s1": DAY_PAYLOAD}))
    said = await _run(entry, "send me today's report")
    assert said.text.startswith("Here is the draft report for today · Green Villa") and len(sent) == 1


async def test_a_confirmed_day_sends_the_stored_dpr_not_a_draft():
    stored = _Stored({"s1": {"status": "ready", "object_key": "dpr/1.pdf", "code": "DPR-20261028-AB12", "confirmed": True}})
    facts = _Facts({"s1": DAY_PAYLOAD})
    entry, sent = _entry(facts, stored=stored, storage=_Storage({"dpr/1.pdf": b"%PDF-final"}))
    message, candidate = _ask("innale report ayakku", "yesterday")
    said = await entry.prepare(message, None, candidate)
    assert sent == [("DPR-20261028-AB12.pdf", b"%PDF-final")]
    assert said.text == "28 Oct-inte DPR · Green Villa ithaa."
    assert facts.read == []  # a signed-off day is not re-read


async def test_an_unconfirmed_stored_pdf_is_not_sent_the_days_facts_are():
    stored = _Stored({"s1": {"status": "ready", "object_key": "dpr/old.pdf", "code": "DPR-X", "confirmed": False}})
    entry, sent = _entry(_Facts({"s1": DAY_PAYLOAD}), stored=stored, storage=_Storage({"dpr/old.pdf": b"stale"}))
    await _run(entry, "report")
    assert sent and sent[0][1] == b"%PDF-draft"


async def test_the_projects_confirmed_dpr_stands_for_a_site_with_none_of_its_own():
    stored = _Stored({None: {"status": "ready", "object_key": "dpr/p.pdf", "code": "DPR-P", "confirmed": True}})
    entry, sent = _entry(_Facts({"s1": DAY_PAYLOAD}), stored=stored, storage=_Storage({"dpr/p.pdf": b"%PDF-p"}))
    await _run(entry, "report")
    assert sent == [("DPR-P.pdf", b"%PDF-p")]


async def test_a_day_with_nothing_saved_says_so_and_sends_nothing():
    entry, sent = _entry(_Facts({"s1": {}}))
    message, candidate = _ask("innale report ayakku", "yesterday")
    said = await entry.prepare(message, None, candidate)
    assert sent == [] and said.documents == 0
    assert said.text == "28 Oct-nu · Green Villa onnum save cheythittilla, athukondu report illa."


async def test_cancelled_entries_are_not_in_the_report():
    payload = {"activities": [{"work_type": "tiling", "review": "rejected"}], "activity_count": 1}
    items = [{"section": "work", "review": "rejected"}]
    entry, sent = _entry(_Facts({"s1": only_kept(payload, items)}))
    said = await _run(entry, "report")
    assert sent == [] and said.text.startswith("Nothing is saved today")


# -- which site ----------------------------------------------------------------


async def test_several_sites_and_none_named_is_one_pdf_per_site_with_entries():
    facts = _Facts({"s1": DAY_PAYLOAD, "s2": {**DAY_PAYLOAD, "site_name": "Site B"}})
    entry, sent = _entry(facts, sites=(GREEN, SITE_B), site_id=None)
    said = await _run(entry, "innathe report")
    assert [f for f, _ in sent] == ["Draft-DPR-Green-Villa-20261029.pdf", "Draft-DPR-Site-B-20261029.pdf"]
    assert said.documents == 2 and "Green Villa, Site B" in said.text


async def test_several_sites_skip_the_ones_with_nothing():
    entry, sent = _entry(_Facts({"s1": {}, "s2": DAY_PAYLOAD}), sites=(GREEN, SITE_B), site_id=None)
    said = await _run(entry, "report")
    assert [f for f, _ in sent] == ["Draft-DPR-Site-B-20261029.pdf"] and "· Site B" in said.text


async def test_a_named_site_is_only_that_site():
    facts = _Facts({"s1": DAY_PAYLOAD, "s2": DAY_PAYLOAD})
    entry, sent = _entry(facts, sites=(GREEN, SITE_B), site_id="s2")
    await _run(entry, "Site B report")
    assert facts.read == [("s2", TODAY)] and len(sent) == 1


# -- failures are said, in their language --------------------------------------


async def test_an_unreadable_day_is_asked_about_not_answered_with_today():
    entry, sent = _entry(_Facts({"s1": DAY_PAYLOAD}))
    said = await _run(entry, "report for someday", "someday")
    assert sent == [] and said.text.startswith("Which day's report")


async def test_a_pdf_that_cannot_be_made_is_said_plainly():
    entry, sent = _entry(_Facts({"s1": DAY_PAYLOAD}), renderer=_Renderer(fail=True))
    said = await _run(entry, "innathe report ayakku")
    assert sent == [] and said.text == say("report.failed", "manglish")


async def test_a_send_that_fails_is_said_not_claimed():
    entry, _ = _entry(_Facts({"s1": DAY_PAYLOAD}), send_ok=False)
    said = await _run(entry, "send the report")
    assert said.text == say("report.not_sent", "english") and said.documents == 0


# -- the reply is the code's ---------------------------------------------------


def _toolbox(report: str, documents: int, *, entries: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        report_text=report, report_documents=documents, answers=[report], parked=None,
        user_text="innathe report ayakku", saved=[], gateway=SimpleNamespace(handled=[], draft_mode=False),
        decisions={},
    )


def test_a_report_only_turn_is_the_codes_line_whatever_the_model_wrote(monkeypatch):
    monkeypatch.setattr(r, "_entries", lambda tb: [])
    monkeypatch.setattr(r, "_open_draft", lambda tb: None)
    monkeypatch.setattr(r, "_decided", lambda *a: None)
    line = "Innathe draft report · Green Villa ithaa, ithuvare save cheythathil ninnu. Confirm aayittilla."
    spec = r._report_only(_toolbox(line, 1))
    assert spec is not None and spec.text == line


def test_under_a_card_the_report_is_one_line_in_the_senders_language():
    tb = _toolbox("x", 1)
    assert r._report_line(tb) == say("report.with_card", "manglish")
    tb = _toolbox("Innu · Green Villa onnum save cheythittilla, athukondu report illa.", 0)
    assert r._report_line(tb) == tb.report_text


# -- Day Facts -----------------------------------------------------------------


async def test_day_facts_reads_each_site_day_once_per_turn(monkeypatch):
    reads: list[Any] = []

    async def read(conn: Any, **kw: Any) -> SiteDay:
        reads.append(kw["site_id"])
        return _day(kw["site_id"], DAY_PAYLOAD)

    class _Db:
        def transaction(self):
            class _Tx:
                async def __aenter__(self):
                    return object()

                async def __aexit__(self, *a):
                    return False

            return _Tx()

    monkeypatch.setattr("runtime.day_facts.read_site_day", read)
    facts = DayFacts(_Db()).for_turn()
    for _ in range(3):
        day = await facts.site_day(organization_id="org", project_id="p1", site_id="s1", day=TODAY)
    assert reads == ["s1"] and day.lines[0].startswith("• Work: Tiling, Plastering 150 sq ft")
    facts.forget()
    await facts.site_day(organization_id="org", project_id="p1", site_id="s1", day=TODAY)
    assert reads == ["s1", "s1"]


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


def test_the_project_date_rule_is_the_backends_one():
    from mesiri.application.dpr.project_day import local_date_sql
    from runtime.day_facts import project_date_sql

    assert project_date_sql("pu.occurred_at", ":org") == local_date_sql("pu.occurred_at", ":org")
    assert "AT TIME ZONE" in local_date_sql("x", ":org") and "::date" not in local_date_sql("x", ":org")


# -- wording -------------------------------------------------------------------


def test_every_line_has_every_language():
    for key, lines in LINES.items():
        assert set(lines) == set(LANGUAGES), key


@pytest.mark.parametrize(
    ("language", "today", "other"),
    [
        ("english", ("today", "today"), ("28 Oct", "for 28 Oct")),
        ("manglish", ("Innathe", "Innu"), ("28 Oct-inte", "28 Oct-nu")),
        ("malayalam", ("ഇന്നത്തെ", "ഇന്ന്"), ("28 Oct-ലെ", "28 Oct-ന്")),
    ],
)
def test_day_words(language, today, other):
    assert tuple(day_words(TODAY, TODAY, language).values()) == today
    assert tuple(day_words(YESTERDAY, TODAY, language).values()) == other


@pytest.mark.parametrize(
    ("text", "usual", "language"),
    [
        ("innathe report ayakku", None, "manglish"),
        ("send me the report", None, "english"),
        ("ഇന്നത്തെ റിപ്പോർട്ട്", None, "malayalam"),
        ("ok", "manglish", "manglish"),
        ("20", "manglish", "manglish"),
        ("send me the report", "manglish", "english"),
    ],
)
def test_language_of_the_message_else_the_senders_usual(text, usual, language):
    assert language_of(text, usual) == language


# -- a draft card and the report in one message (the real journey) ---------------


async def test_a_card_and_the_report_in_one_message_is_the_card_and_one_line():
    pytest.importorskip("langgraph", reason="needs the `workflow` extra (LangGraph)")
    from tests.conversation.test_draft_golden import villa_world

    from mesiri_ai.fakes import FakeToolCallingProvider

    world = await villa_world()
    provider = FakeToolCallingProvider(
        [
            [
                ("save_labour", {"workers": [{"trade": "mason", "headcount": 5}], "site": "Green Villa"}),
                ("request_dpr", {}),
            ],
            "Report ready aayittilla, ithu oru draft aanu.",
        ]
    )
    result = await world.say(provider, "Green Villa 5 mason vannu, innathe report ayakku")
    text = result.reply.text
    assert world.documents  # the PDF went
    assert text.count(say("report.with_card", "manglish")) == 1
    assert "ready aayittilla" not in text and "5 mason" in text
