"""Request 142: closing an issue no longer loops (live 29 Oct, Green Villa mixer).

"Mixer shari aayi" listed the open mixer issues, with the same report twice and titles
cut off; tapping one sent its (cut) title back for the model to match again, which
listed them again, and "all of them" was not understood. Now a row names its issues
by id: the tap makes the "Close: ..." line of the card, with Save. The model is not
asked to match a title a second time.
"""

from __future__ import annotations

import datetime as dt

import pytest

pytest.importorskip("langgraph", reason="needs the `workflow` extra (LangGraph)")

from tests.replay.test_agent_replay import _make_world  # noqa: E402
from tests.replay.test_request104_c_close_issues import _placed  # noqa: E402, F401
from tests.unit.request104_fakes import FakeActions, FakeDispatcher  # noqa: E402

from context import seed  # noqa: E402
from mesiri_ai.fakes import FakeToolCallingProvider  # noqa: E402
from runtime.agent import issue_match  # noqa: E402
from runtime.agent.draft_store import MemoryDraftStore  # noqa: E402


def _issue(n: int, narrative: str, issue_type: str, day: int):  # noqa: ANN202
    return {
        "id": f"{n:08x}-0000-4000-8000-000000000000",
        "site_id": "11111111-1111-4111-8111-000000000002",
        "issue_type": issue_type,
        "severity": "MEDIUM",
        "narrative": narrative,
        "status": "OPEN",
        "occurred_at": dt.datetime(2026, 10, day, 6, 0, tzinfo=dt.UTC),
    }


MIXER_A = _issue(1, "Mixer ippo work cheyyunnilla, concrete machine stopped", "EQUIPMENT_BREAKDOWN", 28)
MIXER_B = _issue(2, "Mixer ippo work cheyyunnilla, concrete machine stopped", "EQUIPMENT_BREAKDOWN", 28)
MIXER_C = _issue(3, "Mixer breakdown aayi", "EQUIPMENT_BREAKDOWN", 27)
MIXER_D = _issue(4, "Mixer machine repair venam, bearing noise", "EQUIPMENT_BREAKDOWN", 26)
CEMENT = _issue(5, "Cement running low", "MATERIAL_SHORTAGE", 25)


@pytest.fixture
async def world():
    world = await _make_world(site_keys=(seed.SITE_A1,))
    world.draft_v2 = True
    world.drafts = MemoryDraftStore()
    world.actions = FakeActions(dispatcher=FakeDispatcher())

    async def open_issues(scoped):  # noqa: ANN001, ANN202
        return [MIXER_A, MIXER_B, MIXER_C, MIXER_D, CEMENT]

    world.open_issues = open_issues
    return world


async def _ask(world, args):  # noqa: ANN001, ANN202
    provider = FakeToolCallingProvider([[("update_issue", {"action": "resolve", **args})], "Mixer fixed aayath ethaanu?"])
    return await world.say(provider, "Green Villa mixer shari aayi, ippo work cheyyunnund")


async def test_the_list_groups_the_same_report_and_keeps_every_title_within_the_limit(world):
    result = await _ask(world, {"about": ["mixer"]})
    rows = result.reply.list_rows

    assert all(len(r.title) <= 24 for r in rows)
    titles = [r.title for r in rows]
    assert len(set(titles)) == len(titles)  # no two rows read alike
    mixer_rows = [r for r in rows if r.id.startswith("agc:grp:")]
    assert len(mixer_rows) == 4  # three distinct mixer reports (+ the all-of-them row)
    duplicates = next(r for r in rows if "2 same reports" in r.description)
    assert duplicates.id.count(",") == 1  # one row closes both
    assert rows[-1].title == issue_match.SOMETHING_ELSE


async def test_a_tap_on_a_row_makes_the_close_card_without_asking_again(world):
    result = await _ask(world, {"about": ["mixer"]})
    row = next(r for r in result.reply.list_rows if r.title.startswith("Mixer breakdown"))

    card = await world.gateway("tap").pick_issues(row.id)

    assert "Close: Mixer breakdown aayi" in card.text
    assert [b.title for b in card.buttons] == ["✅ Save", "❌ Cancel"]
    assert "Which issue" not in card.text


async def test_the_duplicate_row_closes_both_reports_in_one_line(world):
    result = await _ask(world, {"about": ["mixer"]})
    row = next(r for r in result.reply.list_rows if "2 same reports" in r.description)

    card = await world.gateway("tap").pick_issues(row.id)

    assert card.text.count("Close:") == 1 and "×2" in card.text
    draft = await world.drafts.open_for(world.actor.organization_id, world.actor.user_id)
    stored = [a for a in world.actions.store.rows.values()] if hasattr(world.actions.store, "rows") else []
    assert draft is not None and len(draft.items) == 1
    assert not stored or len(stored[0].payload["issues"]) == 2


async def test_all_of_them_is_one_row_and_a_spoken_all(world):
    result = await _ask(world, {"about": ["mixer"]})
    every = next(r for r in result.reply.list_rows if r.title.startswith("All "))
    card = await world.gateway("tap").pick_issues(every.id)
    assert card.text.count("Close:") == 3  # three distinct reports, the duplicate pair as one line

    # ...and said in words: "ellam mixer issues-um close cheyyu" -> all_matching
    world.drafts = MemoryDraftStore()
    spoken = await _ask(world, {"about": ["mixer"], "all_matching": True})
    assert spoken.reply.list_rows is None
    assert spoken.reply.text.count("Close:") == 3
    assert "Cement" not in spoken.reply.text


async def test_something_else_asks_for_words_instead_of_ten_english_options(world):
    reply = await world.gateway("tap").pick_issues(f"{issue_match.TAP_PREFIX}{issue_match.ELSE}")
    assert reply.text == issue_match.ELSE_TEXT and reply.list_rows is None


async def test_a_stale_tap_names_nothing_and_adds_nothing_to_the_card(world):
    reply = await world.gateway("tap").pick_issues("agc:grp:deadbeef")

    assert reply.list_rows, "the open issues are offered again, never guessed"
    assert (await world.drafts.open_for(world.actor.organization_id, world.actor.user_id)) is None


def test_tap_ids_round_trip():
    assert issue_match.parse_tap(issue_match.tap_id(["0000000a", "0000000b"])) == ["0000000a", "0000000b"]
    assert issue_match.parse_tap("agc:else") == []
    assert issue_match.parse_tap("agc:grp:nothex") is None and issue_match.parse_tap("agd:save:x") is None


async def test_a_tap_never_asks_the_project_the_row_already_names(world, monkeypatch):
    """Live 29 Oct (screenshots): a sender on several projects tapped "Innu bhayankara
    mazha..." and was asked "Which project is this for?", then again after answering. The
    model's call had the site from the chat; the tap has only the issue ids. A tap now
    uses the issues' own site and project and never settles a project."""
    from runtime.agent import action_entry
    from runtime.agent.entry_base import choose

    result = await _ask(world, {"about": ["mixer"]})
    row = next(r for r in result.reply.list_rows if r.title.startswith("Mixer breakdown"))

    async def unknown_project(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
        return choose("Which project is this for?", ["Project Alpha", "Hospital Project"], "project")

    monkeypatch.setattr(action_entry.ActionEntry, "settle", unknown_project)
    card = await world.gateway("tap").pick_issues(row.id)

    assert "Which project" not in card.text
    assert "Close: Mixer breakdown aayi" in card.text
    assert [b.title for b in card.buttons] == ["✅ Save", "❌ Cancel"]
