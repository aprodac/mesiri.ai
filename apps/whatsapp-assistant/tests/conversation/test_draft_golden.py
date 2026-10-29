"""Request 136 (D): the golden conversations of the draft pipeline, scripted and live.

Two runs over the same cases (``draft_golden.yaml``), as for the materials and site sets:

- CI (scripted): each case's ``calls`` go through the real journey with the draft
  pipeline on, and the card must be exactly what the case says: the site (or the
  question), the kinds of lines, their words, the template sentence above it, and
  every site decided by ``draft_site.resolve``.
- live (``pytest -m live``, needs GEMINI_API_KEY): the real model reads each message.
  The deploy runs it before production (``.github/workflows/deploy.yml``, job
  ``live-gate``) and stops on a failed case. Each case gets one retry: a case that
  fails twice in a row is a failure, a single miss is printed as flaky.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import os
from pathlib import Path
from typing import Any

import pytest

from mesiri_ai.fakes import FakeToolCallingProvider

pytest.importorskip("langgraph", reason="needs the `workflow` extra (LangGraph)")

from tests.replay.test_agent_replay import _make_world  # noqa: E402
from tests.replay.test_draft_per_message_p3 import _SteelCatalog  # noqa: E402

from context import seed  # noqa: E402
from runtime.agent import draft as dr  # noqa: E402
from runtime.agent import draft_site, history, runner, work_site  # noqa: E402
from runtime.agent.draft_store import MemoryDraftStore  # noqa: E402
from runtime.agent.prompt import Turn  # noqa: E402

PATH = Path(__file__).with_name("draft_golden.yaml")
CASES = [
    json.loads(line.strip()[2:])
    for line in PATH.read_text(encoding="utf-8").splitlines()
    if line.strip().startswith("- {")
]
VILLA, SITE_B = "Green Villa, Kakkanad", "Site B"
_SITE_KEY = {VILLA: seed.SITE_A1, SITE_B: seed.SITE_A2}
_TEMPLATES = (runner._CARD_CHECK, runner._CARD_ASKS, runner._CARD_BOTH)


async def villa_world():  # noqa: ANN201
    """The TEST company as on WhatsApp: two sites, the draft pipeline on, database ids."""
    world = await _make_world(site_keys=(seed.SITE_A1, seed.SITE_A2))
    world.draft_v2, world.drafts = True, MemoryDraftStore()
    world.catalog = _SteelCatalog()
    project, site = type(world.actor.projects[0]), type(world.actor.sites[0])
    project_id = await world.deps.bridge.canonical_project_id(seed.PROJ_ALPHA)
    names = {"Site A1": VILLA, "Site A2": SITE_B}
    world.actor = dataclasses.replace(
        world.actor,
        projects=[project(id=project_id, name="Project Alpha")],
        sites=[
            site(id=world.site_ids[s.id], name=names.get(s.name, s.name), project_id=project_id)
            for s in world.actor.sites
        ],
    )
    world.project_id = project_id
    world.report = _report_entry(world)
    world.day_facts = _History(next(s.id for s in world.actor.sites if s.name == VILLA))
    from tests.unit.request104_fakes import ENGINEER, FakeActions

    world.actions = FakeActions(people=[ENGINEER])
    return world


class _History:
    """Request 143 (D): the sites' history for the check layer: a case's ``history``
    ({"tiling|ground floor": 88}) is Green Villa's saved percents; no labour history."""

    def __init__(self, villa_id: Any) -> None:
        self.villa_id = str(villa_id)
        self.percents: dict[str, tuple[float, str]] = {}

    async def site_history(self, *, organization_id, site_id, day):  # noqa: ANN001, ANN201
        from runtime.day_facts import SiteHistory

        return SiteHistory(percents=self.percents if str(site_id) == self.villa_id else {})

    async def work(self, **_):  # noqa: ANN003, ANN201
        return []

    async def latest_update(self, activity_id):  # noqa: ANN001, ANN201
        return None


class _GreenVillaDay:
    """Day Facts for the golden world: Green Villa has a day's entries, Site B none."""

    def __init__(self, villa_id: Any) -> None:
        self.villa_id = str(villa_id)

    async def site_day(self, *, organization_id, project_id, site_id, day):  # noqa: ANN001, ANN201
        from runtime.day_facts import SiteDay

        villa = str(site_id) == self.villa_id
        payload = (
            {"site_name": VILLA, "activity_count": 1, "activities": [{"work_type": "tiling", "quantities": []}],
             "labour": {"headcount": 8}}
            if villa
            else {}
        )
        return SiteDay(str(organization_id), str(project_id), str(site_id), day, payload=payload)


class _Renderer:
    async def render_pdf(self, html: str) -> bytes:
        return b"%PDF-golden"


def _report_entry(world):  # noqa: ANN001, ANN202
    from context.resolver import ContextResolver
    from runtime.agent.report_entry import ReportEntry

    world.documents = []
    villa = next(s.id for s in world.actor.sites if s.name == VILLA)

    async def send_document(wa_id, data, *, filename, caption, shows=None):  # noqa: ANN001, ANN202
        world.documents.append(filename)
        return True

    return ReportEntry(
        ContextResolver(world.deps), None, world.actor, active_context=world.deps.active_context,
        day_facts=_GreenVillaDay(villa), send_document=send_document, renderer=_Renderer(),
    )


async def _saved_at(world, name: str) -> None:  # noqa: ANN001
    await work_site.remember_saved_site(
        world.deps.active_context,
        organization_id=seed.ORG_A,
        user_id=seed.USER_ENGINEER,
        project_id=world.project_id,
        site_id=world.site_ids[_SITE_KEY[name]],
        own_site_ids={s.id for s in world.actor.sites},
        timezone=None,
    )


async def run_case(case: dict[str, Any], provider_for) -> tuple[Any, Any]:  # noqa: ANN001
    """The case's conversation; ``provider_for(turn)`` gives the model of each turn."""
    world = await villa_world()
    from runtime.day_facts import work_key

    world.day_facts.percents = {
        work_key(*key.split("|")): (float(value), "") for key, value in (case.get("history") or {}).items()
    }
    if case.get("saved"):
        await _saved_at(world, case["saved"])
    _as_on_whatsapp(world)
    turns: list[Turn] = []
    for turn in case.get("before", []):
        before = await world.say(provider_for(turn), turn["message"], turns=history.for_model(tuple(turns)))
        turns.append(Turn(turn["message"], before.reply.text if before.reply else ""))
    result = await world.say(provider_for(case), case["message"], turns=history.for_model(tuple(turns)))
    return world, result


def _as_on_whatsapp(world) -> None:  # noqa: ANN001
    """The model's context as the journey gives it (``message_journey._card_line``):
    the open card, with its id for update_pending_card. Without it a correction
    ("alla, 6 mason aanu", case 7) reaches the model with no card to correct."""
    context = world.context

    def with_card(turns=(), **kw):  # noqa: ANN001, ANN003, ANN202
        return context(turns, card_line=world.card_line, **kw)

    world.card_line = None
    world.context = with_card
    say = world.say

    async def say_with_card(provider, text, **kw):  # noqa: ANN001, ANN003, ANN202
        world.card_line = dr.context_line(
            await world.drafts.open_for(world.actor.organization_id, world.actor.user_id)
        )
        return await say(provider, text, **kw)

    world.say = say_with_card


def mismatch(case: dict[str, Any], world: Any, result: Any, items: list[dr.DraftItem]) -> str | None:
    """Why the turn is wrong for ``case``, or None when it is exactly right."""
    if result.outcome != "ok" or result.reply is None:
        return f"outcome {result.outcome}"
    text = result.reply.text
    decisions = list(world.last_gateway.decisions)
    if case.get("report"):
        # Request 143: the PDF went, and the reply is the code's one line, never the model's.
        from runtime.agent.wording import day_words, say

        language = case["lang"] if case["lang"] != "en" else "english"
        today = dt.date.today()
        line = say("report.draft", language, at=f" · {VILLA}", **day_words(today, today, language))
        if not world.documents:
            return "no report PDF was sent"
        if text != line:
            return f"the reply is not the report's line: {text!r}"
        return None
    if case.get("read"):
        reads = [d for d in decisions if d["what"] == "read_site"]
        if not reads or any(d["by"] != draft_site.DECIDER for d in reads):
            return f"the read's site was not the resolver's: {decisions}"
        return "a card was shown for a question" if "📝" in text else None
    lines = [i for i in items if i.state != dr.UNREADABLE]
    kinds = sorted(i.kind for i in lines)
    if kinds != sorted(case["kinds"]):
        return f"lines {kinds} != {sorted(case['kinds'])} ({[i.line for i in items]})"
    # Every line this turn ADDED got its site from the resolver. A correction that edits a
    # line already on the card (update_pending_card) adds none: its site was decided then.
    added = [d for d in decisions if d["what"] == "item"]
    sites = [d for d in decisions if d["what"] == "site"]
    if len(sites) < len(added) or any(d["by"] != draft_site.DECIDER for d in sites):
        return f"a site was not decided by the resolver: {decisions}"
    if case["site"] == "ask":
        if not any(i.needs_site for i in lines):
            return f"expected the card to ask the site, got {[i.site for i in lines]}"
    elif {i.site for i in lines} != {case["site"]}:
        return f"site {sorted({i.site for i in lines})} != {case['site']}"
    if bool(case.get("waiting")) != any(i.state == dr.NEEDS_ANSWER for i in lines):
        return f"waiting {case.get('waiting', False)} != {[i.state for i in lines]}"
    card = "\n".join(i.line for i in lines)
    missing = [w for w in case.get("has", []) if w not in card]
    if missing:
        return f"the card lacks {missing}: {card!r}"
    first = text.split("\n\n", 1)[0]
    language = case["lang"] if case["lang"] != "en" else "english"
    allowed = {t[language] for t in _TEMPLATES} | {
        runner._CHOOSE[language].format(options=" or ".join(i.options))
        for i in lines
        if i.options
    }
    if first not in allowed:
        return f"the words above the card are not the template: {first!r}"
    if [d for d in decisions if d["what"] == "reply"] != [{"what": "reply", "by": runner.TEMPLATE}]:
        return f"the reply was not the template's: {decisions}"
    return None


async def _items(world) -> list[dr.DraftItem]:  # noqa: ANN001
    draft = await world.drafts.open_for(world.actor.organization_id, world.actor.user_id)
    return draft.items if draft else []


def test_the_draft_golden_set_is_well_formed():
    assert len(CASES) >= 9 and len({c["id"] for c in CASES}) == len(CASES)
    for case in CASES:
        assert case["message"] and case["calls"] and case["lang"] in ("en", "manglish"), case["id"]
        assert case.get("read") or case.get("report") or (case["site"] and case["kinds"]), case["id"]


def _scripted(turn: dict[str, Any]) -> FakeToolCallingProvider:
    # The model's own words are deliberately wrong ("Site B tap cheyyu"): they must never show.
    return FakeToolCallingProvider([[tuple(c) for c in turn["calls"]], "Site B tap cheyyu. Saved!"])


@pytest.mark.parametrize("case", CASES, ids=[f"case{c['id']}" for c in CASES])
async def test_the_draft_pipeline_makes_exactly_the_expected_card(case):
    world, result = await run_case(case, _scripted)
    why = mismatch(case, world, result, await _items(world))
    assert why is None, why
    if not case.get("read") and not case.get("report"):
        assert "Site B tap" not in result.reply.text and "Saved!" not in result.reply.text


@pytest.mark.live
async def test_live_model_on_the_draft_golden_set():
    """The deploy gate (request 136, D): the real model, every case, one retry each."""
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        pytest.skip("GEMINI_API_KEY not set")
    from pydantic import SecretStr

    from mesiri.bootstrap.settings import GeminiSettings
    from mesiri_ai.adapters.gemini.adapter import GeminiProvider

    provider = GeminiProvider(
        GeminiSettings(api_key=SecretStr(key), model=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"))
    )
    failures = []
    for case in CASES:
        whys = []
        for _attempt in range(2):
            started = dt.datetime.now()
            world, result = await run_case(case, lambda _turn: provider)
            why = mismatch(case, world, result, await _items(world))
            seconds = (dt.datetime.now() - started).total_seconds()
            if why is None:
                break
            whys.append(why)
            print(f"    miss #{case['id']}: {why} reply={(result.reply.text if result.reply else '')[:200]!r}")
        verdict = "PASS" if why is None else "FAIL"
        flaky = " (flaky: passed on retry)" if why is None and whys else ""
        print(f"{verdict} #{case['id']} {case['message'][:60]!r} ({seconds:.1f}s){flaky}")
        if why is not None:
            failures.append(case["id"])
    print(f"DRAFT GOLDEN {len(CASES) - len(failures)}/{len(CASES)}")
    assert not failures, f"failed cases: {failures}"


async def test_a_correction_is_shown_the_open_card_and_correcting_it_passes():
    """Live gate #7 (29 Oct): "alla, 6 mason aanu" reached the model with no card in its
    context, so "which entry?" was a fair answer. The model is shown the open card as on
    WhatsApp, and update_pending_card on it makes the card the case wants."""
    case = next(c for c in CASES if c["id"] == 7)
    fix = {"workers": [{"trade": "mason", "headcount": 6}]}
    seen: list[str] = []

    class _Correcting(FakeToolCallingProvider):
        async def run_tools(self, system, messages, tools, handler, **kw):  # noqa: ANN001, ANN003, ANN201
            seen.append(messages[0].text)
            return await super().run_tools(system, messages, tools, handler, **kw)

    def provider_for(turn):  # noqa: ANN001, ANN202
        if turn is case:
            return _Correcting([[("update_pending_card", {"card_id": "x", "item_index": 1, "changes": fix})], "Sheri"])
        return _scripted(turn)

    world, result = await run_case(case, provider_for)
    assert "Their open card" in seen[-1] and "8 workers (5 mason, 3 helper)" in seen[-1]
    assert mismatch(case, world, result, await _items(world)) is None


async def test_a_figure_the_model_left_out_is_on_the_card():
    """Live gate #2 (29 Oct): the model's save_work_done had no quantities, and the card
    read "Wall putty, ground floor". The figure in their words is on the card."""
    case = next(c for c in CASES if c["id"] == 2)
    call = ("save_work_done", {"narrative": case["message"], "work_type": "wall putty", "location": "ground floor"})
    world, result = await run_case(case, lambda _turn: FakeToolCallingProvider([[call], "x"]))
    assert mismatch(case, world, result, await _items(world)) is None
