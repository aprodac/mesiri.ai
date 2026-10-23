"""Request 90 (23 Oct re-test): every write is a card item (no card, no write),
"undo that" reaches only the latest card, "today" is the project's day, and a
report answers in the language of the message."""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from channel.replies import ListRow, ReplySpec
from interactions.saved_summary import QUESTION_PREFIX
from mesiri_ai.fakes import FakeToolCallingProvider
from mesiri_contracts.assistant.planner_decision import WorkflowKey
from runtime.agent import cards as c
from runtime.agent import project_day as pd
from runtime.agent import runner as r
from runtime.agent import save_button as sb
from runtime.agent import toolbox as tb
from runtime.agent.gateway import StepResult
from runtime.agent.journey_gateway import NOTHING_TO_UNDO, undo_from_card
from runtime.agent.prompt import AgentContext
from runtime.agent.tools import ScopeLookup
from runtime.today_context import build_today_line

# -- helpers -------------------------------------------------------------------


class _Redis:
    def __init__(self) -> None:
        self.data: dict[str, Any] = {}

    def namespaced(self, *parts: str) -> str:
        return ":".join(parts)

    async def set_json(self, key: str, value: Any, *, ttl_seconds: int | None = None) -> None:
        self.data[key] = value

    async def get_json(self, key: str) -> Any | None:
        return self.data.get(key)

    async def delete(self, *keys: str) -> None:
        for key in keys:
            self.data.pop(key, None)


ACTOR = SimpleNamespace(organization_id="org-1", user_id="user-1")


def _item(summary: str, fact_type: str = "labour_report") -> c.CardItem:
    return c.CardItem("save_labour", {}, fact_type, str(uuid.uuid4()), summary)


class _Withdrawer:
    def __init__(self) -> None:
        self.calls: list[list] = []

    async def __call__(self, facts: list) -> Any:
        self.calls.append(list(facts))
        return SimpleNamespace(done=list(facts), refused=[], already=0)


def _handled(fact_type_action: str = "RECORD_SITE_ISSUE", *, draft: bool = True, question: bool = False) -> Any:
    from mesiri_contracts.assistant.draft_action import DraftActionType

    action = getattr(DraftActionType, fact_type_action)
    fields = {"narrative": QUESTION_PREFIX + "x"} if question else {}
    confirmed = SimpleNamespace(draft_action=SimpleNamespace(action_type=action, fields=fields))
    return SimpleNamespace(
        saved_draft=draft,
        execution_result=SimpleNamespace(material_row_id=str(uuid.uuid4())),
        result=SimpleNamespace(confirmed_action=confirmed),
    )


# -- 2. undo: only the latest card ----------------------------------------------


async def test_undo_after_a_saved_labour_card_removes_the_labour_only():
    store = c.CardStore(_Redis())
    labour = _item("3 workers (3 mason)")
    await store.put(ACTOR, c.new_card(c.SAVED, [labour]))
    withdraw = _Withdrawer()
    step = await undo_from_card(store, ACTOR, withdraw, [])
    assert withdraw.calls == [[labour.fact]]
    assert (step.status, step.text) == ("undone", "Removed: 3 workers (3 mason) (today)")
    assert await store.get(ACTOR) is None


@pytest.mark.parametrize("state", [None, c.LEGACY])
async def test_undo_with_no_saved_card_says_nothing_to_undo(state):
    store = c.CardStore(_Redis())
    if state is not None:
        await store.put(ACTOR, c.new_card(state, []))
    withdraw = _Withdrawer()
    step = await undo_from_card(store, ACTOR, withdraw, [])
    assert (step.status, step.text) == ("info", NOTHING_TO_UNDO)
    assert withdraw.calls == []  # never "the latest record of any type"


async def test_a_card_that_cannot_be_withdrawn_does_not_fall_back_to_another_record():
    store = c.CardStore(_Redis())
    await store.put(ACTOR, c.new_card(c.SAVED, [_item("3 workers (3 mason)")]))

    async def none(_facts: list) -> None:
        return None

    step = await undo_from_card(store, ACTOR, none, [])
    assert (step.status, step.text) == ("info", NOTHING_TO_UNDO)


async def test_the_toolbox_has_no_latest_record_fallback():
    class Bare:
        undo_calls = 0

        async def undo_latest_draft(self) -> StepResult:
            Bare.undo_calls += 1
            return StepResult("undone", text="Done. I've removed the issue.")

    box = tb.AgentToolbox(gateway=Bare(), scope=ScopeLookup(), user_text="undo that")
    out = await box.handle("undo_last", {})
    assert Bare.undo_calls == 0 and out.content["status"] == "info"


# -- 1. no card, no write --------------------------------------------------------


def test_an_issue_is_a_card_item():
    kind, facts = sb.card_plan([_handled("RECORD_SITE_ISSUE")])
    assert kind == "card" and len(facts) == 1 and facts[0][0] == "site_issue"


def test_a_question_next_to_a_write_does_not_push_the_card_out():
    question = ReplySpec(
        text="Which site?",
        buttons=(ListRow("a", "Site A"), ListRow("b", "Site B")),
    )
    text_only = sb.question_as_text(question)
    assert not text_only.buttons and not text_only.list_rows
    assert "• Site A" in text_only.text and "1." not in text_only.text  # a typed number must not pick Save


def test_more_entries_than_one_card_holds_are_blocked_not_left_as_drafts():
    kind, facts = sb.card_plan([_handled("RECORD_SITE_ISSUE") for _ in range(sb.MAX_ITEMS + 1)])
    assert kind == "blocked" and len(facts) == sb.MAX_ITEMS + 1
    assert str(sb.MAX_ITEMS) in sb.NOT_SHOWN


def test_a_record_the_review_log_does_not_cover_is_flagged_not_silent():
    from mesiri_contracts.assistant.draft_action import DraftActionType

    other = next(a for a in DraftActionType if a not in sb.FACT_TYPE_BY_ACTION)
    handled = _handled("RECORD_SITE_ISSUE")
    handled.result.confirmed_action.draft_action.action_type = other
    kind, _ = sb.card_plan([handled])
    assert kind == "legacy"


def test_an_engineer_question_is_no_entry_and_needs_no_card():
    assert sb.card_plan([_handled(question=True)]) == ("none", [])


# -- 3. the project's day --------------------------------------------------------

IST = "Asia/Kolkata"


def _utc(y: int, m: int, d: int, h: int, mi: int) -> dt.datetime:
    return dt.datetime(y, m, d, h, mi, tzinfo=dt.UTC)


@pytest.mark.parametrize(
    "utc_moment, today, week_start",
    [
        # 00:30 IST on Fri 23 Oct is still 22 Oct in UTC.
        (_utc(2026, 10, 22, 19, 0), dt.date(2026, 10, 23), dt.date(2026, 10, 19)),
        # 23:30 IST on Thu 22 Oct is 18:00 UTC the same day.
        (_utc(2026, 10, 22, 18, 0), dt.date(2026, 10, 22), dt.date(2026, 10, 19)),
        # 00:30 IST on Mon 26 Oct starts a new week while UTC is still Sunday.
        (_utc(2026, 10, 25, 19, 0), dt.date(2026, 10, 26), dt.date(2026, 10, 26)),
        # 23:30 IST on Sun 25 Oct is still last week.
        (_utc(2026, 10, 25, 18, 0), dt.date(2026, 10, 25), dt.date(2026, 10, 19)),
    ],
)
def test_the_day_boundaries_are_the_projects_not_utcs(utc_moment, today, week_start):
    for zone in (IST, "UTC", None, "", "Not/AZone"):  # an untouched or unknown zone is India
        assert pd.project_today(zone, utc_moment) == today
        assert pd.week_start(zone, utc_moment) == week_start
        assert pd.project_yesterday(zone, utc_moment) == today - dt.timedelta(days=1)


def test_another_projects_zone_is_respected():
    moment = _utc(2026, 10, 22, 19, 0)
    assert pd.project_today("Asia/Dubai", moment) == dt.date(2026, 10, 22)
    assert pd.project_today("Asia/Dubai", _utc(2026, 10, 22, 20, 30)) == dt.date(2026, 10, 23)


class _Frozen:
    """Stands in for the ``datetime`` module inside occurred_date, so the old
    ``today_for`` the lookups end in sees a fixed moment."""

    def __init__(self, moment: dt.datetime) -> None:
        class _DT(dt.datetime):
            @classmethod
            def now(cls, tz=None):  # noqa: ANN001, ANN206
                return moment.astimezone(tz) if tz else moment

        self.date, self.timedelta, self.datetime, self.UTC = dt.date, dt.timedelta, _DT, dt.UTC


class _Service:
    def __init__(self) -> None:
        self.asked: list[tuple[dt.date, dt.date]] = []

    async def summarize_attendance(self, **kw: Any) -> dict[str, Any]:
        self.asked.append((kw["start_date"], kw["end_date"]))
        return {"headcount": 0, "rows": []}

    async def search(self, **kw: Any) -> dict[str, Any]:
        self.asked.append((kw["start_date"], kw["end_date"]))
        return {"activities": []}


def _event(date_range: str | None = None) -> Any:
    return SimpleNamespace(fields={"date_range": date_range}, project_id=None, site_id=None)


@pytest.mark.parametrize("utc_moment, today", [(_utc(2026, 10, 22, 19, 0), dt.date(2026, 10, 23)), (_utc(2026, 10, 22, 18, 0), dt.date(2026, 10, 22))])
@pytest.mark.parametrize("org_zone", ["UTC", None, IST])
async def test_labour_count_and_summary_ask_for_the_projects_today(monkeypatch, utc_moment, today, org_zone):
    from canonicalization import occurred_date
    from runtime.inbound_journey import seeding

    monkeypatch.setattr(occurred_date, "datetime", _Frozen(utc_moment))
    actor = SimpleNamespace(organization_id="org-1")
    zone = pd.project_zone_name(org_zone)  # what query_entry hands every lookup
    labour, log = _Service(), _Service()
    decision = SimpleNamespace(workflow_key=WorkflowKey.LABOUR_QUERY)
    await seeding._seed_labour_query(_event(), decision, labour, actor, zone)
    await seeding._seed_activity_search(
        _event(), SimpleNamespace(workflow_key=WorkflowKey.ACTIVITY_QUERY), log, actor, zone
    )
    assert labour.asked == [(today, today)]
    assert log.asked == [(today, today)]
    # "this week" starts on the project's Monday
    week = _Service()
    await seeding._seed_labour_query(_event("this_week"), decision, week, actor, zone)
    assert week.asked == [(today - dt.timedelta(days=today.weekday()), today)]


async def test_the_today_so_far_line_asks_for_the_projects_day(monkeypatch):
    from canonicalization import occurred_date

    monkeypatch.setattr(occurred_date, "datetime", _Frozen(_utc(2026, 10, 22, 20, 33)))  # 02:03 IST, 23 Oct
    service = _Service()
    actor = SimpleNamespace(organization_id="org-1", full_name="Anil K", sites=[])
    await build_today_line(service, actor, timezone_name=pd.project_zone_name("UTC"))
    assert service.asked == [(dt.date(2026, 10, 23),) * 2]


def test_the_work_site_expires_at_the_projects_midnight():
    from runtime.agent.work_site import seconds_until_midnight

    # 02:03 IST (20:33 UTC): the default "UTC" org zone must not give a UTC midnight.
    assert seconds_until_midnight(_utc(2026, 10, 22, 20, 33), "UTC") == int(21 * 3600 + 57 * 60)


# -- small: a report answers in the message's language --------------------------

CTX = AgentContext(
    user_name="Anil", role="SUPERVISOR", company="Acme", now=dt.datetime(2026, 10, 23, 2, 3),
    projects=(("Project Alpha", None),), sites=(("Site A1", "Project Alpha"),),
)


class _Provider(FakeToolCallingProvider):
    """The first run is scripted; the runner's later no-tool tries answer from ``retries``."""

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


async def test_a_report_with_no_words_from_the_model_is_said_in_manglish():
    english = "The report for 22 Oct at Green Villa isn't confirmed yet. So far:\n• Labour: 2 workers"

    class Gateway:
        async def run(self, candidate, *, text):  # noqa: ANN001, ANN202
            return StepResult("answer", text=english)

    provider = _Provider(
        [[("request_dpr", {"date": "yesterday"})], ""], ["Innale report: 22 Oct-nu 2 per vannu, ippo draft aanu."]
    )
    result = await r.AgentRunner(provider).run(
        ctx=CTX, user_text="innale report ayakku", gateway=Gateway(), scope=ScopeLookup()
    )
    assert "isn't confirmed" not in result.reply.text
    assert "Innale report" in result.reply.text
    assert "Manglish" in provider.asked[0] and "isn't confirmed" in provider.asked[0]


async def test_an_english_message_keeps_the_english_answer():
    class Gateway:
        async def run(self, candidate, *, text):  # noqa: ANN001, ANN202
            return StepResult("answer", text="The report for 22 Oct isn't confirmed yet. So far: 2 workers.")

    provider = _Provider([[("request_dpr", {"date": "yesterday"})], ""], [])
    result = await r.AgentRunner(provider).run(
        ctx=CTX, user_text="send yesterday's report", gateway=Gateway(), scope=ScopeLookup()
    )
    assert "isn't confirmed yet" in result.reply.text
    assert provider.asked == []  # no language retry for an English message
