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
from runtime.agent import draft_site, runner, work_site  # noqa: E402
from runtime.agent.draft_store import MemoryDraftStore  # noqa: E402

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
    return world


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
    if case.get("saved"):
        await _saved_at(world, case["saved"])
    for turn in case.get("before", []):
        await world.say(provider_for(turn), turn["message"])
    result = await world.say(provider_for(case), case["message"])
    return world, result


def mismatch(case: dict[str, Any], world: Any, result: Any, items: list[dr.DraftItem]) -> str | None:
    """Why the turn is wrong for ``case``, or None when it is exactly right."""
    if result.outcome != "ok" or result.reply is None:
        return f"outcome {result.outcome}"
    text = result.reply.text
    decisions = list(world.last_gateway.decisions)
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
        assert case.get("read") or (case["site"] and case["kinds"]), case["id"]


def _scripted(turn: dict[str, Any]) -> FakeToolCallingProvider:
    # The model's own words are deliberately wrong ("Site B tap cheyyu"): they must never show.
    return FakeToolCallingProvider([[tuple(c) for c in turn["calls"]], "Site B tap cheyyu. Saved!"])


@pytest.mark.parametrize("case", CASES, ids=[f"case{c['id']}" for c in CASES])
async def test_the_draft_pipeline_makes_exactly_the_expected_card(case):
    world, result = await run_case(case, _scripted)
    why = mismatch(case, world, result, await _items(world))
    assert why is None, why
    if not case.get("read"):
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
