"""V1 audit, Sites (docs/qa/v1-audit/02-sites.md): one scenario per SIT row, each
following the row's Repro, plus the property that no waiting message is lost.

The sender is the audit's Site Engineer: Project A (Site A, Tower 1) and
Project B (Site A, Site B)."""

from __future__ import annotations

import datetime as dt
import random
import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from tests.unit.test_material_entry import MESSAGE, ORG, USR, _Context, _Understanding

from backend.ports import ProjectSummary, SiteSummary
from context.active_context import RedisActiveContextStore
from mesiri.infrastructure.redis.client import FakeRedis
from mesiri_contracts.assistant.candidates import Candidate
from mesiri_contracts.assistant.enums import InputModality, SemanticType
from mesiri_contracts.assistant.normalized_message import NormalizedMessage, SenderInfo
from runtime.agent import site_match
from runtime.agent import work_site as ws
from runtime.agent.entry_base import Ready, Say
from runtime.agent.save_button import TO_SAVE_HEADER, with_save_buttons
from runtime.agent.site_entry import SiteEntry
from runtime.agent.tools import ScopeLookup
from runtime.today_context import build_stock_line, build_today_line

P_A, P_B = ProjectSummary("pa", "Project A"), ProjectSummary("pb", "Project B")
A_SITE_A = SiteSummary("a1", "Site A", "pa")
A_TOWER = SiteSummary("a2", "Tower 1", "pa")
B_SITE_A = SiteSummary("b1", "Site A", "pb")
B_SITE_B = SiteSummary("b2", "Site B", "pb")
ALL = [A_SITE_A, A_TOWER, B_SITE_A, B_SITE_B]


def uid(short: str) -> str:
    """A real UUID for a short id: the entries build events that need them."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, short))


U_PROJECTS = [ProjectSummary(uid("pa"), "Project A"), ProjectSummary(uid("pb"), "Project B")]
U_ALL = [SiteSummary(uid(s.id), s.name, uid(s.project_id)) for s in ALL]
# 06:30 India time, 22 Oct.
MORNING = dt.datetime(2026, 10, 22, 1, 0, tzinfo=dt.UTC)


def at(hour: int, minute: int = 0, day: int = 22) -> dt.datetime:
    """``hour:minute`` India time on ``day`` Oct 2026."""
    return dt.datetime(2026, 10, day, hour, minute, tzinfo=dt.timezone(dt.timedelta(hours=5, minutes=30))).astimezone(
        dt.UTC
    )


def actor(*sites: Any, role: str = "SITE_ENGINEER") -> Any:
    return SimpleNamespace(
        organization_id=ORG,
        user_id=USR,
        full_name="Suresh Kumar",
        role=role,
        timezone="Asia/Kolkata",
        projects=[P_A, P_B],
        sites=list(sites or ALL),
    )


def message(text: str = "50 bags cement arrived", *, tap: str | None = None, n: int = 1, now: dt.datetime = MORNING):
    return NormalizedMessage(
        message_id=f"wamid.{n}",
        sender=SenderInfo(wa_id="919000000002", profile_name="Suresh"),
        timestamp=now,
        modality=InputModality.INTERACTIVE if tap else InputModality.TEXT,
        text=text,
        metadata={"interactive_reply_id": tap} if tap else {},
    )


def make(now: dt.datetime = MORNING, redis: FakeRedis | None = None):
    redis = redis or FakeRedis()
    clock = {"now": now}
    store = RedisActiveContextStore(redis, clock=lambda: clock["now"])
    work_site = ws.WorkSite(active_context=store, redis=redis, clock=lambda: clock["now"])
    return work_site, store, clock


# --- SIT-01 · a site name it can't match is never replaced by today's site ----


def _entry(sites: list[Any], *, today_site: str = "b2", store: Any = None) -> SiteEntry:
    # The context layer resolved today's site (Site B), whatever the message said.
    me = actor(*sites)
    me.projects = U_PROJECTS
    return SiteEntry(
        context_resolver=_Context(project_id=uid("pb"), site_id=uid(today_site)),
        org_settings_query=None,
        actor=me,
        active_context=store,
    )


async def _issue(entry: SiteEntry, **fields: Any):
    candidate = Candidate(semantic_type=SemanticType.SITE_ISSUE, fields={"issue_type": "WEATHER", **fields})
    return await entry.prepare(MESSAGE, _Understanding(candidate), candidate)


@pytest.mark.parametrize("said", ["Site Z", "Sight B", "Tower 9"])
async def test_sit01_a_site_it_cannot_match_is_asked_never_saved_to_todays_site(said):
    out = await _issue(_entry(U_ALL), site_name=said)
    assert isinstance(out, Say) and out.status == "choose"
    assert out.question == f'I don\'t have a site called "{said}". Which site is this for?'
    assert set(out.options) == {"Site A · Project A", "Tower 1", "Site A · Project B", "Site B"}


async def test_sit01_a_site_it_matches_is_used_not_todays():
    out = await _issue(_entry(U_ALL), site_name="tower 1")
    assert isinstance(out, Ready)
    assert str(out.event.site_id) == uid("a2")


# --- SIT-02 / SIT-03 / SIT-04 · nothing waiting is ever lost ---------------------


async def test_sit02_a_second_message_before_the_tap_keeps_the_first():
    work_site, store, _ = make()
    me = actor(A_SITE_A, B_SITE_B)
    first = await work_site.morning_question(message("50 bags cement arrived", n=1), me)
    second = await work_site.morning_question(message("12 masons today", n=2), me)
    assert first is not None and "holding" not in first.text
    assert second is not None and "holding 2 message(s)" in second.text

    reply, waiting = await work_site.handle_tap(message("Site B", tap="today_site:b2", n=3), me)

    assert [m.text for m in waiting] == ["50 bags cement arrived", "12 masons today"]  # in order
    assert "Now saving your 2 waiting message(s)" in reply.text
    active = await store.get_active_context(organization_id=ORG, user_id=USR)
    assert active.site_id == "b2"


async def test_sit02_the_same_message_delivered_twice_is_held_once():
    work_site, _, _ = make()
    me = actor(A_SITE_A, B_SITE_B)
    await work_site.morning_question(message("cement", n=1), me)
    await work_site.morning_question(message("cement", n=1), me)
    _, waiting = await work_site.handle_tap(message("Site B", tap="today_site:b2", n=2), me)
    assert len(waiting) == 1


async def test_sit03_typing_the_site_name_answers_the_question_and_runs_the_waiting_message():
    work_site, store, _ = make()
    me = actor(A_SITE_A, B_SITE_B)
    await work_site.morning_question(message("50 bags cement arrived", n=1), me)

    answered = await work_site.answer_by_name(message("Site B", n=2), me)

    assert answered is not None
    reply, waiting = answered
    assert reply.text.startswith("👍 Site B (Project B) for today.")
    assert [m.text for m in waiting] == ["50 bags cement arrived"]
    assert (await store.get_active_context(organization_id=ORG, user_id=USR)).site_id == "b2"
    # The question is closed: nothing waits any more.
    assert await work_site.answer_by_name(message("Site B", n=3), me) is None


async def test_sit03_a_name_shared_by_two_projects_is_not_a_guess():
    work_site, _, _ = make()
    me = actor(A_SITE_A, B_SITE_A, B_SITE_B)
    await work_site.morning_question(message("cement", n=1), me)
    assert await work_site.answer_by_name(message("Site A", n=2), me) is None  # asks again, keeps it


async def test_sit03_a_message_that_is_not_just_a_site_name_does_not_answer():
    work_site, _, _ = make()
    me = actor(A_SITE_A, B_SITE_B)
    await work_site.morning_question(message("cement", n=1), me)
    assert await work_site.answer_by_name(message("5 masons at Site B today please", n=2), me) is None


async def test_sit04_a_late_tap_still_runs_the_waiting_message():
    work_site, _, clock = make()
    me = actor(A_SITE_A, B_SITE_B)
    await work_site.morning_question(message("50 bags cement arrived", n=1), me)
    clock["now"] = at(11, 0)  # four hours later, same working day

    reply, waiting = await work_site.handle_tap(message("Site B", tap="today_site:b2", n=2), me)

    assert [m.text for m in waiting] == ["50 bags cement arrived"]
    assert "I no longer have" not in reply.text


async def test_sit04_a_message_from_an_earlier_day_is_named_never_dropped_silently():
    work_site, _, clock = make()
    me = actor(A_SITE_A, B_SITE_B)
    await work_site.morning_question(message("50 bags cement arrived", n=1), me)
    clock["now"] = at(9, 0, day=23)  # the next working day

    question = await work_site.morning_question(message("12 masons today", n=2), me)

    assert "were not saved" in question.text and "50 bags cement arrived" in question.text
    _, waiting = await work_site.handle_tap(message("Site B", tap="today_site:b2", n=3), me)
    assert [m.text for m in waiting] == ["12 masons today"]  # today's message is not tangled with it


async def test_sit04_a_tap_with_nothing_left_says_so():
    work_site, _, _ = make()
    me = actor(A_SITE_A, B_SITE_B)
    reply, waiting = await work_site.handle_tap(message("Site B", tap="today_site:b2"), me)
    assert waiting == [] and "send it again" in reply.text


@pytest.mark.parametrize("seed", range(25))
async def test_property_n_messages_while_the_question_is_open_are_n_entries_after_the_answer(seed):
    rng = random.Random(seed)
    n = rng.randint(1, ws.MAX_WAITING)
    work_site, _, _ = make()
    me = actor(A_SITE_A, B_SITE_B)
    sent = [f"entry {i}" for i in range(n)]
    for i, text in enumerate(sent):
        question = await work_site.morning_question(message(text, n=i), me)
        assert question is not None  # every one of them gets the (re-sent) question

    how = rng.choice(["tap", "typed"])
    if how == "tap":
        _, waiting = await work_site.handle_tap(message("Site B", tap="today_site:b2", n=99), me)
    else:
        answered = await work_site.answer_by_name(message(rng.choice(["Site B", "site b", "at Site B"]), n=99), me)
        assert answered is not None
        _, waiting = answered
    assert [m.text for m in waiting] == sent


async def test_property_past_the_limit_the_sender_is_told_to_wait_not_dropped():
    work_site, _, _ = make()
    me = actor(A_SITE_A, B_SITE_B)
    for i in range(ws.MAX_WAITING):
        await work_site.morning_question(message(f"m{i}", n=i), me)
    over = await work_site.morning_question(message("one too many", n=999), me)
    assert over is not None and "already holding" in over.text and not over.list_rows
    _, waiting = await work_site.handle_tap(message("Site B", tap="today_site:b2", n=1000), me)
    assert len(waiting) == ws.MAX_WAITING


# --- SIT-05 · one entry for another site does not move the day ----------------


async def test_sit05_one_entry_at_another_site_leaves_todays_site_alone():
    work_site, store, _ = make()
    me = actor(*U_ALL)
    await work_site.set_today(me, project_id=uid("pb"), site_id=uid("b2"))
    entry = _entry(U_ALL, store=store)
    ready = await _issue(entry, site_name="Tower 1")
    assert isinstance(ready, Ready) and str(ready.event.site_id) == uid("a2")

    await entry.remember(ready)

    active = await store.get_active_context(organization_id=ORG, user_id=USR)
    assert (active.project_id, active.site_id) == (uid("pb"), uid("b2"))  # the helpers still go to Site B


async def test_sit05_the_first_save_of_the_day_still_remembers_its_site():
    _, store, _ = make()
    entry = _entry(U_ALL, store=store)
    ready = await _issue(entry, site_name="Tower 1")
    await entry.remember(ready)
    assert (await store.get_active_context(organization_id=ORG, user_id=USR)).site_id == uid("a2")


# --- SIT-06 · same site name in two projects --------------------------------------


async def test_sit06_the_same_name_in_two_projects_shows_the_project_on_the_button():
    work_site, _, _ = make()
    question = await work_site.morning_question(message(), actor())
    titles = {r.id: r.title for r in question.list_rows}
    assert titles["today_site:a1"] == "Site A · Project A"
    assert titles["today_site:b1"] == "Site A · Project B"
    assert titles["today_site:b2"] == "Site B" and titles["today_site:a2"] == "Tower 1"


def test_sit06_the_label_can_be_typed_or_tapped_back_to_one_site():
    scope = ScopeLookup(
        projects=(("pa", "Project A"), ("pb", "Project B")),
        sites=tuple((s.id, s.name, s.project_id) for s in ALL),
    )
    assert scope.site_id("Site A") is None  # two projects: asks
    assert scope.site_id("Site A · Project B") == "b1"
    assert scope.site_id("site a", "pa") == "a1"


# --- SIT-07 · greet by local time ----------------------------------------------------


@pytest.mark.parametrize(
    ("when", "expected"),
    [
        (at(8), "Good morning"),
        (at(14), "Good afternoon"),
        (at(19), "Good evening"),
        (at(22), None),
        (at(2, day=23), None),
    ],
)
async def test_sit07_the_greeting_follows_the_project_clock(when, expected):
    work_site, _, _ = make(when)
    question = await work_site.morning_question(message(now=when), actor(A_SITE_A, B_SITE_B))
    first_line = question.text.split("\n")[0]
    if expected is None:
        assert first_line == "Where are you working today?"
    else:
        assert first_line.startswith(expected)


# --- SIT-08 · the reply language -------------------------------------------------------


async def test_sit08_the_question_and_the_confirmation_follow_the_message_language():
    work_site, _, _ = make()
    me = actor(A_SITE_A, B_SITE_B)
    question = await work_site.morning_question(message("innu 50 chakku cement vannu"), me)
    assert "Innu ethu site-il aanu work cheyyunnath?" in question.text
    assert question.list_button_label == "Site select cheyyuka"[:20]

    reply, waiting = await work_site.handle_tap(message("Site B", tap="today_site:b2", n=2), me)
    assert reply.text.startswith("👍 Innu Site B (Project B).")
    assert "Vere site-il aanengil" in reply.text and [m.text for m in waiting] == ["innu 50 chakku cement vannu"]


async def test_sit08_malayalam_script_and_english_keep_their_own_wording():
    work_site, _, _ = make()
    me = actor(A_SITE_A, B_SITE_B)
    question = await work_site.morning_question(message("ഇന്ന് 50 ചാക്ക് സിമന്റ് വന്നു"), me)
    assert "ഇന്ന് ഏത് സൈറ്റിലാണ്" in question.text
    other, _, _ = make()
    english = await other.morning_question(message("50 bags cement arrived"), me)
    assert "Where are you working today?" in english.text


# --- SIT-09 · more than ten sites ------------------------------------------------------


def many(n: int = 12, project: str = "pa") -> list[Any]:
    return [SiteSummary(f"s{i:02d}", f"Block {i:02d}", project) for i in range(1, n + 1)]


async def test_sit09_twelve_sites_give_nine_and_something_else_and_the_eleventh_can_be_typed():
    sites = many(12)
    work_site, store, _ = make()
    me = actor(*sites)
    question = await work_site.morning_question(message("cement came", n=1), me)

    assert len(question.list_rows) == 10
    assert question.list_rows[-1].title == site_match.SOMETHING_ELSE
    assert "Type the site name" in question.text
    assert not {r.id for r in question.list_rows} >= {f"today_site:{s.id}" for s in sites}

    tapped = await work_site.handle_tap(message("Something else", tap="today_site:else", n=2), me)
    assert "Type the site name" in tapped[0].text and tapped[1] == []  # the message keeps waiting

    answered = await work_site.answer_by_name(message("Block 11", n=3), me)  # not on the list
    assert answered is not None and [m.text for m in answered[1]] == ["cement came"]
    assert (await store.get_active_context(organization_id=ORG, user_id=USR)).site_id == "s11"


async def test_sit09_a_site_question_in_an_entry_also_shows_nine_and_something_else():
    sites = [SiteSummary(uid(s.id), s.name, uid("pa")) for s in many(12)]
    out = await _issue(_entry(sites), site_name="Block 99")
    assert isinstance(out, Say) and len(out.options) == 10 and out.options[-1] == site_match.SOMETHING_ELSE
    assert "type the site name" in out.text


def test_sit09_the_closest_names_come_first():
    names, cut = site_match.options(many(12), {"pa": "Project A"}, said="Block 11")
    assert cut and names[0] == "Block 11"


# --- SIT-10 · multi-site senders get the same context ----------------------------------


class _Search:
    def __init__(self) -> None:
        self.asked: dict[str, Any] = {}

    async def search(self, **kwargs: Any) -> list[Any]:
        self.asked = kwargs
        return []


class _Inventory:
    def __init__(self) -> None:
        self.asked: dict[str, Any] = {}

    async def query(self, **kwargs: Any) -> list[dict]:
        self.asked = kwargs
        return [{"material_name": "Cement", "current_stock": 120.0, "unit": "bags"}]


async def test_sit10_stock_and_today_lines_are_read_for_the_chosen_site():
    me = actor(A_SITE_A, B_SITE_B)
    stock, search = _Inventory(), _Search()

    assert await build_stock_line(stock, me) is None  # no chosen site: nothing guessed
    line = await build_stock_line(stock, me, site_id="b2")
    await build_today_line(search, me, timezone_name="Asia/Kolkata", site_id="b2")

    assert stock.asked["site_id"] == "b2" and "Site B" in (line or "")
    assert search.asked["site_id"] == "b2"


# --- SIT-11 · the text card names the site ---------------------------------------------


def test_sit11_the_to_save_header_names_the_site():
    from channel.replies import ReplySpec

    spec = ReplySpec(text="✅ Saved: 5 masons")
    facts = [("labour_report", __import__("uuid").uuid4())]
    named = with_save_buttons(spec, facts, site="Green Villa")
    plain = with_save_buttons(spec, facts)
    assert named.text.startswith("📝 To save · Green Villa:")
    assert plain.text.startswith(TO_SAVE_HEADER)


# --- SIT-12 · the tip names a site they have ------------------------------------------


async def test_sit12_the_switch_tip_only_names_their_sites():
    work_site, _, _ = make()
    me = actor(A_TOWER, B_SITE_B)  # no "Site A"
    await work_site.morning_question(message(), me)
    reply, _ = await work_site.handle_tap(message("Site B", tap="today_site:b2", n=2), me)
    assert 'like "now at Tower 1"' in reply.text and "Site A" not in reply.text


# --- SIT-13 · whole words only ---------------------------------------------------------


async def test_sit13_main_is_not_found_inside_maintenance():
    work_site, _, _ = make()
    main = SiteSummary("m1", "Main", "pa")
    me = actor(main, B_SITE_B)
    assert not ws.names_a_site(me, "maintenance work done")
    assert await work_site.morning_question(message("maintenance work done"), me) is not None
    assert ws.names_a_site(me, "cement at main gate")
    assert await work_site.morning_question(message("cement at main"), me) is None


def test_sit13_a_near_miss_is_never_a_match_only_a_hint_for_the_order():
    assert site_match.find_sites(ALL, "Sight B") == []
    assert site_match.similarity("Site B", "Sight B") > site_match.SIMILAR_AT_LEAST
    assert [s.id for s in site_match.find_sites(ALL, "tower")] == ["a2"]  # a whole word of the name


# --- SIT-14 · PMs and Finance are not asked every morning -------------------------------


@pytest.mark.parametrize("role", ["PROJECT_MANAGER", "FINANCE", "ADMIN", "OWNER"])
async def test_sit14_only_site_engineers_get_the_morning_question(role):
    work_site, _, _ = make()
    assert await work_site.morning_question(message(), actor(role=role)) is None
    assert await work_site.morning_question(message(), actor(role="SITE_ENGINEER")) is not None


# --- SIT-15 · the day turns over in the project's time zone -----------------------------


async def test_sit15_just_after_midnight_a_night_shift_is_not_asked_again():
    work_site, _, clock = make(at(21, 0))
    me = actor(A_SITE_A, B_SITE_B)
    await work_site.set_today(me, project_id="pb", site_id="b2")
    clock["now"] = at(0, 30, day=23)  # 00:30 India, 19:00 UTC the day before
    assert await work_site.morning_question(message("night shift done, 4 masons", now=clock["now"]), me) is None
    assert await work_site.today(me) == ("pb", "b2")


async def test_sit15_the_next_morning_asks_again():
    work_site, _, clock = make(at(21, 0))
    me = actor(A_SITE_A, B_SITE_B)
    await work_site.set_today(me, project_id="pb", site_id="b2")
    clock["now"] = at(6, 30, day=23)
    assert await work_site.morning_question(message("cement", now=clock["now"]), me) is not None


def test_sit15_the_working_day_uses_the_project_zone_not_utc():
    # 19:00 UTC on 22 Oct is already 00:30 on 23 Oct in India.
    assert ws.seconds_until_midnight(at(0, 30, day=23), "Asia/Kolkata") == 23 * 3600 + 30 * 60
    assert ws.seconds_until_midnight(at(0, 30, day=23), "Asia/Kolkata", grace_hours=4) == 27 * 3600 + 30 * 60
