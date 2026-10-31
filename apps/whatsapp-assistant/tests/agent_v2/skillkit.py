"""Request 185: the module skills' eval sets (skills/<module>/evals.yaml), as a kit the CI test
and the live run share. Same shape as the materials kit (evalkit.py): one message goes through
V2Runner in the real journey World; the open lines and the tool calls are judged.

A *wrong save* is a line that must not be there (a kind the case does not expect, or a write
tool in ``must_not_call``) or a line with wrong figures. The gate allows none.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tests.agent_v2.evalkit import Recording
from tests.agent_v2.replaykit import new_world
from tests.replay.test_draft_per_message_p1 import open_items

from agent_v2.runner import V2Runner
from agent_v2.skills import DIR, MODULES
from mesiri_ai.fakes import FakeToolCallingProvider
from runtime.agent import draft as dr
from runtime.agent.runner import AgentRunner

WRITE_NAMES = frozenset(
    {"save_labour", "save_work_done", "correct_work_quantity", "report_issue", "update_issue", "save_expense",
     "draft_receipt", "draft_usage", "draft_stock_count", "transfer"}
)


def load(module: str) -> list[dict[str, Any]]:
    path: Path = DIR / module / "evals.yaml"
    return [
        json.loads(line.strip()[2:])
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("- {")
    ]


def all_cases() -> list[tuple[str, dict[str, Any]]]:
    return [(module, case) for module in MODULES for case in load(module)]


@dataclass(slots=True)
class Verdict:
    right: bool
    wrong_save: bool
    why: str = ""


def _workers(args: dict[str, Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for w in args.get("workers") or []:
        trade = str(w.get("trade") or "").casefold()
        out[trade] = out.get(trade, 0) + int(w.get("headcount") or 0)
    return out


def _matches(want: dict[str, Any], item: dr.DraftItem) -> bool:
    if item.kind != want["kind"]:
        return False
    for key, value in want.items():
        if key == "kind":
            continue
        if key == "workers":
            if _workers(item.args) != {k.casefold(): v for k, v in value.items()}:
                return False
        elif key == "total":
            if sum(_workers(item.args).values()) != value:
                return False
        else:
            got = item.args.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                try:
                    if float(got) != float(value):
                        return False
                except (TypeError, ValueError):
                    return False
            elif str(got or "").casefold() != str(value).casefold():
                return False
    return True


def judge(case: dict[str, Any], items: list[dr.DraftItem], names: list[str]) -> Verdict:
    lines = [i for i in items if i.state != dr.UNREADABLE]
    bad = [n for n in case.get("must_not_call", []) if n in names]
    if bad:
        return Verdict(False, any(n in WRITE_NAMES for n in bad), f"called {bad}, which this message must not trigger")
    missing_calls = [n for n in case.get("must_call", []) if n not in names]
    left = list(lines)
    missing = []
    for want in case.get("expect", []):
        hit = next((i for i in left if _matches(want, i)), None)
        if hit is None:
            missing.append(want)
        else:
            left.remove(hit)
    if left:
        return Verdict(False, True, f"extra or wrong lines: {[(i.kind, i.args) for i in left]}")
    if missing:
        return Verdict(False, False, f"missing lines {missing}")
    if missing_calls:
        return Verdict(False, False, f"missing calls {missing_calls}")
    return Verdict(True, False)


async def _given(world: Any, case: dict[str, Any]) -> None:
    for calls in case.get("given", []):
        setup = V2Runner(FakeToolCallingProvider([[tuple(c) for c in calls], "ok"]), AgentRunner(FakeToolCallingProvider(["x"])))
        await setup.run(
            ctx=world.context(), user_text="setup", gateway=world.gateway("setup"), scope=world.scope(),
            correlation_id="cor_setup",
        )


async def run_case(case: dict[str, Any], provider: Any) -> tuple[Verdict, Any]:
    world = await new_world()
    await _given(world, case)
    card = await world.drafts.open_for(world.actor.organization_id, world.actor.user_id)
    recording = Recording(provider)
    runner = V2Runner(recording, AgentRunner(FakeToolCallingProvider(["(today's agent)"])))
    result = await runner.run(
        ctx=world.context(card_line=dr.context_line(card)), user_text=case["message"],
        gateway=world.gateway(case["message"]), scope=world.scope(), correlation_id="cor_skill_eval",
    )
    names = [name for name, _ in recording.calls]
    return judge(case, await open_items(world), names), result


def scripted(case: dict[str, Any]) -> FakeToolCallingProvider:
    """The good run of a case, as a scripted model."""
    calls = [(name, args) for name, args in case["calls"]]
    return FakeToolCallingProvider([calls, "Check it and tap Save."] if calls else ["I don't have that, sorry."])
