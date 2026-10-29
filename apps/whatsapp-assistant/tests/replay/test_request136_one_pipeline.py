# ruff: noqa: F811
"""Request 136: ONE pipeline for site updates on draft_v2 (Ilan, 28 Oct: "sorted, not patched").

Root causes it closes (code facts of 28 Oct):

1. The site resolver of [132] (``draft_site.resolve``) was never called; the "Ee update
   ethu site-inte aanu?" question came from the entry's old path. Now ``draft_flow.add``
   calls the resolver for every line and hands the entry the site it decided.
2. "Green Villa" did not name "Green Villa, Kakkanad" (whole name only). Now a site is
   named by its full name or its head (the part before the comma).
3. The model's sentence above the card could contradict it ("Site B tap cheyyu" while the
   buttons ask). Now the words above a draft card are the code's (``card_sentence``).
4. "innu enthokke cheythu?" read another site (the context layer's default) and no
   materials. Now a day read takes the resolver's site (else every site) and lists the
   day's materials as the DPR counts them.
5. Scripted tests passed while the resolver was dead code. Now every draft turn records
   who decided the site, the lines and the reply (``gateway.decisions``, the
   "draft_decisions" trace stage), and the tests below fail if the site came from
   anything else or the words above a card were not the template's.

The model is scripted; everything after it is the real journey (the D phase of the plan
runs the same conversations against the live model).
"""

from __future__ import annotations

import dataclasses
import datetime as dt
from types import SimpleNamespace

import pytest
from tests.replay.test_draft_per_message_p1 import open_items, titles
from tests.replay.test_draft_per_message_p3 import (  # noqa: F401  (fixtures)
    CEMENT,
    MASONS,
    _clock,
    _remember,
    at,
    tap,
    two,
)

from context import seed
from mesiri_ai.fakes import FakeToolCallingProvider
from runtime.agent import draft as dr
from runtime.agent import draft_site, runner, site_match
from runtime.agent.draft_flow import ITEM_FROM_TOOL
from runtime.agent.entry_base import ALL_SITES
from workflows.activity_query.nodes import generate_activity_search_reply

PUTTY = ("save_work_done", {"narrative": "ground floor wall putty 200 sqft", "work_type": "putty",
                            "location": "ground floor", "quantities": [{"work_type": "putty", "quantity": 200,
                                                                        "unit": "sqft"}]})
TILING = ("save_work_done", {"narrative": "tiling 70%", "work_type": "tiling", "progress_percent": 70})
VILLA, SITE_B = "Green Villa, Kakkanad", "Site B"


def _renamed(world, names: dict[str, str]):  # noqa: ANN001, ANN202
    sites = [dataclasses.replace(s, name=names.get(s.name, s.name)) for s in world.actor.sites]
    world.actor = dataclasses.replace(world.actor, sites=sites)
    return world


@pytest.fixture
async def villa(two):  # noqa: ANN001, ANN201
    """The TEST company's two sites as on WhatsApp: "Green Villa, Kakkanad" and "Site B"."""
    return _renamed(two, {"Site A1": VILLA, "Site A2": SITE_B})


def _site_decisions(world) -> list[dict]:  # noqa: ANN001
    return [d for d in world.last_gateway.decisions if d["what"] == "site"]


def _reply_decisions(world) -> list[dict]:  # noqa: ANN001
    return [d for d in world.last_gateway.decisions if d["what"] == "reply"]


def _first_paragraph(text: str) -> str:
    return text.split("\n\n", 1)[0]


# -- 2. the shared matcher: a site is named by its full name or its head -------------------


def _sites(*names: str) -> list[SimpleNamespace]:
    return [SimpleNamespace(id=f"s{i}", name=n, project_id="p") for i, n in enumerate(names)]


def test_the_head_of_a_site_name_names_it_inside_a_sentence():
    villa_, b = _sites(VILLA, SITE_B)
    assert site_match.mentioned_sites([villa_, b], "Green Villa ground floor wall putty 200 sqft") == [villa_]
    assert site_match.mentioned_sites([villa_, b], "Site B-il 4 mason") == [b]
    assert site_match.mentioned_sites([villa_, b], "4 mason vannu") == []


def test_two_sites_with_the_same_head_are_both_named_so_the_sender_chooses():
    kakkanad, aluva = _sites("Green Villa, Kakkanad", "Green Villa, Aluva")
    assert site_match.mentioned_sites([kakkanad, aluva], "Green Villa 4 mason") == [kakkanad, aluva]
    # the full name said is that one site only
    assert site_match.mentioned_sites([kakkanad, aluva], "Green Villa, Aluva 4 mason") == [aluva]


def test_a_generic_head_names_nothing():
    assert site_match.head_words("Site, Block A") == []
    assert site_match.head_words("Tower 1") == []  # no cut: the whole name only
    assert site_match.head_words(VILLA) == ["green", "villa"]


def test_the_resolver_order():
    actor = SimpleNamespace(sites=_sites(VILLA, SITE_B), projects=[])
    villa_, b = actor.sites
    assert draft_site.resolve(actor, "Green Villa 4 mason", saved_site_id="s1").site is villa_  # named > saved
    assert draft_site.resolve(actor, "4 mason", said="Green Villa").site is villa_  # the model's part name
    assert draft_site.resolve(actor, "4 mason", card_site_id="s1", saved_site_id="s0").kind == draft_site.CARD
    assert draft_site.resolve(actor, "4 mason", saved_site_id="s1").kind == draft_site.SAVED
    asked = draft_site.resolve(actor, "4 mason")
    assert asked.kind == draft_site.ASK and asked.options == (villa_, b)
    unknown = draft_site.resolve(actor, "Site Z 4 mason", said="Site Z")
    assert unknown.kind == draft_site.ASK and unknown.unknown == "Site Z" and len(unknown.options) == 2


# -- 1. the resolver decides every draft line's site ----------------------------------------


async def test_green_villa_named_by_its_head_is_the_lines_site_with_no_question(villa):
    """28 Oct: "Green Villa ground floor wall putty 200 sqft" asked "Ee update ethu site-inte aanu?"."""
    result = await villa.say(
        FakeToolCallingProvider([[PUTTY], "Site B tap cheyyu."]), "Green Villa ground floor wall putty 200 sqft"
    )
    (item,) = await open_items(villa)
    assert item.state == dr.OK and item.site == VILLA
    assert "📍" not in result.reply.text and "ethu site" not in result.reply.text
    assert f"*To save* · {VILLA}" in result.reply.text
    assert _site_decisions(villa) == [{"what": "site", "by": draft_site.DECIDER, "kind": draft_site.NAMED}]


async def test_the_model_naming_part_of_the_site_is_enough(villa):
    result = await villa.say(FakeToolCallingProvider([[at("Green Villa", MASONS)], "Okay."]), "4 mason")
    (item,) = await open_items(villa)
    assert item.state == dr.OK and item.site == VILLA
    assert "📍" not in result.reply.text


async def test_a_save_within_three_hours_preselects_its_site(villa):
    await _remember(villa, seed.SITE_A2)
    _clock(villa, dt.timedelta(hours=2, minutes=30))
    result = await villa.say(FakeToolCallingProvider([[CEMENT], "Okay."]), "100 bags cement vannu")
    (item,) = await open_items(villa)
    assert item.site == SITE_B and f"*To save* · {SITE_B}" in result.reply.text
    assert _site_decisions(villa)[0]["kind"] == draft_site.SAVED


async def test_after_three_hours_the_card_asks(villa):
    await _remember(villa, seed.SITE_A2)
    _clock(villa, dt.timedelta(hours=3, minutes=5))
    await villa.say(FakeToolCallingProvider([[CEMENT], "Okay."]), "100 bags cement vannu")
    (item,) = await open_items(villa)
    assert item.needs_site
    assert _site_decisions(villa)[0]["kind"] == draft_site.ASK


async def test_two_green_villas_ask_between_them(two):
    world = _renamed(two, {"Site A1": "Green Villa, Kakkanad", "Site A2": "Green Villa, Aluva"})
    result = await world.say(FakeToolCallingProvider([[MASONS], "Okay."]), "Green Villa 4 mason vannu")
    (item,) = await open_items(world)
    assert item.needs_site
    shown = " | ".join(titles(result.reply)) + " " + " | ".join(r.description or "" for r in result.reply.list_rows or ())
    assert "Kakkana" in shown and "Aluva" in shown  # (a button title holds 20 characters)
    assert item.options == ["Green Villa, Aluva", "Green Villa, Kakkanad"] or set(item.options) == {
        "Green Villa, Kakkanad", "Green Villa, Aluva"}


async def test_a_site_that_is_not_theirs_is_asked_never_moved_elsewhere(villa):
    await _remember(villa, seed.SITE_A2)  # a saved site must not stand in for a wrong name
    result = await villa.say(FakeToolCallingProvider([[at("Site Z", MASONS)], "Okay."]), "Site Z 4 mason")
    (item,) = await open_items(villa)
    assert item.needs_site
    assert "Site Z" in result.reply.text


async def test_the_resolver_is_what_runs(villa, monkeypatch):
    """Wiring proof: the turn's site comes from ``draft_site.resolve`` and nothing else
    (dead code passed every scripted test before)."""
    calls = []
    real = draft_site.resolve

    def spy(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        calls.append(args[1])
        return real(*args, **kwargs)

    monkeypatch.setattr(draft_site, "resolve", spy)
    await villa.say(FakeToolCallingProvider([[at("Site B", MASONS), CEMENT], "Okay."]), "Site B 4 mason, 100 bags cement")
    assert len(calls) == 2  # once per line
    assert [d["by"] for d in _site_decisions(villa)] == [draft_site.DECIDER] * 2
    assert [d for d in villa.last_gateway.decisions if d["what"] == "item"] == [
        {"what": "item", "by": ITEM_FROM_TOOL, "kind": "save_labour"},
        {"what": "item", "by": ITEM_FROM_TOOL, "kind": "save_material_receipt"},
    ]


# -- 3. the words above a draft card are the code's ------------------------------------------


@pytest.mark.parametrize(
    ("text", "language"),
    [("Green Villa 4 mason vannu", "manglish"), ("Green Villa 4 masons came today", "english")],
)
async def test_the_sentence_above_the_card_is_the_template_not_the_model(villa, text, language):
    result = await villa.say(FakeToolCallingProvider([[MASONS], "Site B tap cheyyu, ok aano?"]), text)
    assert "Site B tap" not in result.reply.text
    assert _first_paragraph(result.reply.text) == runner._CARD_CHECK[language]
    assert _reply_decisions(villa) == [{"what": "reply", "by": runner.TEMPLATE}]


async def test_a_card_waiting_on_its_site_says_to_answer_it(villa):
    result = await villa.say(FakeToolCallingProvider([[MASONS], "Saved!"]), "4 mason vannu")
    first = _first_paragraph(result.reply.text)
    assert "Saved" not in result.reply.text
    # never "Site B tap cheyyu" for a card that asks between Green Villa and Site B
    assert first == runner._CARD_ASKS["manglish"]
    assert _reply_decisions(villa) == [{"what": "reply", "by": runner.TEMPLATE}]


async def test_every_draft_turn_of_a_golden_conversation_is_resolver_and_template(villa):
    """The 4-part note, a steel-free version of the 27 Oct round (labour, work, cement,
    breakdown), then a line that names no site on the same card, then the save."""
    note = (
        "Green Villa innathe update: 5 mason 3 helper, ground floor tiling 40% aayi, "
        "30 bags cement use cheythu, mixer breakdown aayi pani 2 hour ninnu"
    )
    calls = [
        ("save_labour", {"workers": [{"trade": "mason", "headcount": 5}, {"trade": "helper", "headcount": 3}]}),
        ("save_work_done", {"narrative": "ground floor tiling 40%", "work_type": "tiling",
                            "location": "ground floor", "progress_percent": 40}),
        ("save_material_usage", {"material": "cement", "quantity": 30, "unit": "bags"}),
    ]
    first = await villa.say(FakeToolCallingProvider([calls, "Site B-il save cheythu."]), note)
    assert "Site B" not in first.reply.text
    items = [i for i in await open_items(villa) if i.state != dr.UNREADABLE]
    assert len(items) == 4 and {i.site for i in items} == {VILLA}  # the breakdown is a line too
    assert all(d["by"] == draft_site.DECIDER for d in _site_decisions(villa))
    assert _reply_decisions(villa) == [{"what": "reply", "by": runner.TEMPLATE}]
    second = await villa.say(FakeToolCallingProvider([[TILING], "Okay."]), "tiling 70% aayi")
    assert _site_decisions(villa) == [{"what": "site", "by": draft_site.DECIDER, "kind": draft_site.CARD}]
    assert _first_paragraph(second.reply.text) == runner._CARD_CHECK["manglish"]
    saved = await tap(villa, second.reply, "✅ Save")
    assert saved.text.startswith("✅ *Saved*")


# -- 4. readers: the resolver's site (else every site) and the day's materials ----------------


async def test_what_was_done_today_reads_the_site_saved_to_not_a_default(villa, monkeypatch):
    from runtime.agent.query_entry import QueryEntry

    seen = []
    real = QueryEntry.prepare

    async def spy(self, message, understanding, candidate):  # noqa: ANN001, ANN202
        seen.append(dict(candidate.fields))
        return await real(self, message, understanding, candidate)

    monkeypatch.setattr(QueryEntry, "prepare", spy)
    await _remember(villa, seed.SITE_A1)
    await villa.say(FakeToolCallingProvider([[("query_work_log", {"date_range": "today"})], "Okay."]),
                    "innu enthokke cheythu?")
    assert seen[-1].get("site_id") == villa.site_ids[seed.SITE_A1]
    reads = [d for d in villa.last_gateway.decisions if d["what"] == "read_site"]
    assert reads == [{"what": "read_site", "by": draft_site.DECIDER, "kind": draft_site.SAVED}]


async def test_what_was_done_today_with_no_site_known_reads_every_site(villa, monkeypatch):
    from runtime.agent.query_entry import QueryEntry

    seen = []
    real = QueryEntry.prepare

    async def spy(self, message, understanding, candidate):  # noqa: ANN001, ANN202
        seen.append(dict(candidate.fields))
        return await real(self, message, understanding, candidate)

    monkeypatch.setattr(QueryEntry, "prepare", spy)
    await villa.say(FakeToolCallingProvider([[("query_work_log", {"date_range": "today"})], "Okay."]),
                    "innu enthokke cheythu?")
    assert seen[-1].get(ALL_SITES) is True and not seen[-1].get("site_id")


def test_the_work_log_answer_lists_the_days_materials():
    state = {"collected_fields": {"activity_search_results": {
        "activities": [{"work_type": "tiling", "narrative": "Tiling: 70%", "status": "IN_PROGRESS"}],
        "activity_count": 1,
        "materials": [{"material": "cement", "unit": "bags", "received": 0.0, "used": 30.0}],
    }}}
    text = generate_activity_search_reply(state)["pending_prompt"]
    assert "Tiling" in text and "🧱 Materials" in text and "Cement: 30 bags used" in text


def test_materials_alone_are_not_nothing_logged():
    state = {"collected_fields": {"activity_search_results": {
        "materials": [{"material": "cement", "unit": "bags", "received": 100.0, "used": 0.0}],
    }}}
    text = generate_activity_search_reply(state)["pending_prompt"]
    assert "Nothing logged" not in text and "Cement: 100 bags received" in text
