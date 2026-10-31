"""Request 174: the v2 materials eval set, as a kit the CI test and the live run share.

``run_case`` sends one message through ``V2Runner`` in the real journey (World) and ``judge``
says whether the card is exactly right. A *wrong save* is a card line that should not be
there, or a line with wrong figures: the gate allows none.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from tests.replay.test_agent_replay import _Catalog, _make_world
from tests.replay.test_draft_per_message_p1 import open_items

from agent_v2.runner import V2Runner
from context import seed
from mesiri_ai.fakes import FakeToolCallingProvider
from runtime.agent import draft as dr
from runtime.agent.draft_store import MemoryDraftStore
from runtime.agent.runner import AgentRunner

EVALS = Path(__file__).resolve().parents[2] / "src" / "agent_v2" / "skills" / "materials" / "evals.yaml"
GOLDEN = Path(__file__).resolve().parents[1] / "conversation" / "materials_golden.yaml"
KIND = {
    "record_material_receipt": dr.KIND_MATERIAL_IN,
    "record_material_usage": dr.KIND_MATERIAL_OUT,
}
#: What a line of each kind is judged on (request 178: transfers have a quantity too).
QUANTITY_KINDS = (dr.KIND_MATERIAL_IN, dr.KIND_MATERIAL_OUT, dr.KIND_TRANSFER_MATERIAL)
MATERIAL_ACTIONS = frozenset(KIND)


def _load(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line.strip()[2:])
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("- {")
    ]


def load_evals() -> list[dict[str, Any]]:
    return _load(EVALS)


def golden_as_evals() -> list[dict[str, Any]]:
    """The 25 cases of tests/conversation/materials_golden.yaml in the v2 case format. A case
    with anything but material lines in it (labour, an issue, an order, an engineer question)
    is one v2 must hand back whole."""
    out = []
    for case in _load(GOLDEN):
        actions = [e["action"] for e in case.get("expect", [])]
        new: dict[str, Any] = {"id": 1000 + case["id"], "lang": case["lang"], "message": case["message"], "calls": []}
        if case.get("ask"):
            new.update(ask=True, expect=[])
        elif case.get("query"):
            new.update(query=True, expect=[])
        elif case.get("chat") or case.get("card") or any(a not in MATERIAL_ACTIONS for a in actions):
            new.update(handback=True, expect=[])
        else:
            new["expect"] = [
                {"kind": KIND[e["action"]], "material": e["material"], "quantity": e["quantity"]}
                for e in case["expect"]
            ]
        out.append(new)
    return out


def _name(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _line_matches(expected: dict[str, Any], item: dr.DraftItem) -> bool:
    if item.kind != expected["kind"]:
        return False
    if _name(item.args.get("material")) not in {_name(m) for m in expected["material"]}:
        return False
    key = "counted" if expected["kind"] == dr.KIND_STOCK_COUNT else "quantity"
    # Request 178: the unit stays as said ("load" is not turned into cum); the rate is on the line.
    if "unit" in expected and _name(item.args.get("unit")) != _name(expected["unit"]):
        return False
    if "unit_cost" in expected and float(item.args.get("unit_cost") or 0) != float(expected["unit_cost"]):
        return False
    if "to_site" in expected and _name(item.args.get("to_site")) != _name(expected["to_site"]):
        return False
    try:
        return float(item.args.get(key)) == float(expected[key])
    except (TypeError, ValueError):
        return False


@dataclass(slots=True)
class Verdict:
    right: bool
    wrong_save: bool
    why: str = ""
    handed_back: bool = False
    ms: float = 0.0


class _Books:
    """The books show 176 bags of cement, as at Paraclette on 31 Oct (a count needs them)."""

    async def query(self, **kwargs: Any) -> list[dict]:
        return [{"current_stock": 176, "unit": "bag", "material_name": "Cement", "received": 176, "used": 0}]


class Recording:
    """Wraps a provider and records the v2 tool calls (their names and arguments)."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def run_tools(self, system_prompt, messages, tools, handler, **kw):  # noqa: ANN001, ANN003
        async def record(name: str, args: dict[str, Any]):
            self.calls.append((name, dict(args)))
            return await handler(name, args)

        return await self.inner.run_tools(system_prompt, messages, tools, record, **kw)


def judge(
    case: dict[str, Any], items: list[dr.DraftItem], *, handed_back: bool, asked: bool, queried: bool,
    v2_drafted: bool = False, not_built: bool = False,
) -> Verdict:
    lines = [i for i in items if i.state != dr.UNREADABLE]
    expected = case.get("expect", [])
    if case.get("handback"):
        # (today's agent runs after a hand-back, so the card may hold ITS lines: only v2's count)
        ok = handed_back and not v2_drafted
        return Verdict(ok, v2_drafted, "" if ok else f"expected a hand-back; v2 drafted={v2_drafted}", handed_back)
    if handed_back:
        return Verdict(False, False, "handed back a message that is v2's", True)
    left = list(lines)
    missing = []
    for want in expected:
        hit = next((i for i in left if _line_matches(want, i)), None)
        if hit is None:
            missing.append(want)
        else:
            left.remove(hit)
    if left:
        return Verdict(False, True, f"extra or wrong lines: {[(i.kind, i.args) for i in left]}")
    if missing:
        return Verdict(False, False, f"missing {missing}")
    if case.get("ask") and not asked:
        return Verdict(False, False, "expected a question")
    if case.get("query") and not queried:
        return Verdict(False, False, "expected a stock answer")
    if case.get("not_built") and not not_built:
        return Verdict(False, False, "expected the 'material requests are not in Mesiri yet' line")
    return Verdict(True, False)


async def _given(world: Any, case: dict[str, Any]) -> None:
    """The card the case starts from: each ``given`` entry is one earlier message whose lines are
    put on the card by a scripted v2 run (so the live model is judged on the NEW message only)."""
    for calls in case.get("given", []):
        setup = V2Runner(FakeToolCallingProvider([[tuple(c) for c in calls], "ok"]), AgentRunner(FakeToolCallingProvider(["x"])))
        await setup.run(
            ctx=world.context(), user_text="setup", gateway=world.gateway("setup"), scope=world.scope(),
            correlation_id="cor_setup",
        )


async def run_case(case: dict[str, Any], v2_provider: Any) -> tuple[Verdict, Any]:
    sites = (seed.SITE_A1, seed.SITE_A2) if case.get("two_sites") else (seed.SITE_A1,)
    world = await _make_world(site_keys=sites, usual_site=seed.SITE_A1 if case.get("two_sites") else None)
    world.draft_v2 = True
    world.drafts = MemoryDraftStore()
    world.catalog = _Catalog()
    world.inventory = _Books()
    world.actor = replace(world.actor, role="PROJECT_MANAGER")  # may adjust stock
    await _given(world, case)
    from runtime.agent import draft as draft_card

    card_line = draft_card.context_line(await world.drafts.open_for(world.actor.organization_id, world.actor.user_id))
    classic = FakeToolCallingProvider(["Handled by today's agent."])
    recording = Recording(v2_provider)
    runner = V2Runner(recording, AgentRunner(classic))
    gateway = world.gateway(case["message"])
    result = await runner.run(
        ctx=world.context(card_line=card_line), user_text=case["message"], gateway=gateway, scope=world.scope(),
        correlation_id="cor_eval",
    )
    names = [name for name, _ in recording.calls]
    verdict = judge(
        case,
        await open_items(world),
        handed_back=classic.calls > 0,
        asked=result.toolbox.parked is not None or "ask" in names,
        queried="stock_for" in names,
        v2_drafted=any(n in ("draft_receipt", "draft_usage", "draft_stock_count", "transfer", "change_line", "remove_line") for n in names),
        not_built="material_request_not_available" in names,
    )
    return verdict, result


async def run_classic_timing(case: dict[str, Any], provider: Any) -> float:
    """Request 178 (gate): seconds today's agent takes on the same message in the same world,
    so v2's reply time is compared with the real baseline, not a guess."""
    import time

    sites = (seed.SITE_A1, seed.SITE_A2) if case.get("two_sites") else (seed.SITE_A1,)
    world = await _make_world(site_keys=sites, usual_site=seed.SITE_A1 if case.get("two_sites") else None)
    world.draft_v2, world.drafts, world.catalog, world.inventory = True, MemoryDraftStore(), _Catalog(), _Books()
    world.actor = replace(world.actor, role="PROJECT_MANAGER")
    await _given(world, case)
    started = time.perf_counter()
    await AgentRunner(provider).run(
        ctx=world.context(), user_text=case["message"], gateway=world.gateway(case["message"]), scope=world.scope(),
        correlation_id="cor_classic_eval",
    )
    return time.perf_counter() - started
