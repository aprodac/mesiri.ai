"""SS-65: the shared sample story runs on any API client, without the assistant's code, and never raises.

A fake client answers every call, so the test reads what the story asks the API for: the subcontractor the guided
demo's subcontract chapter needs, Green Villa left without an estimate (its BOQ chapter uploads one), and the same
story twice for the same day.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import re
import uuid
from dataclasses import dataclass
from typing import Any

from mesiri.application.organizations import sample_story

MATERIALS = ("cement", "m sand", "p sand", "aggregate 20mm", "solid blocks", "steel", "binding wire")


@dataclass
class _Res:
    status: int
    body: Any

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


class _FakeApi:
    def __init__(self, fail: str | None = None) -> None:
        self.calls: list[tuple[str, str, dict | None]] = []
        self.fail = fail

    async def call(self, method: str, path: str, *, json: dict | None = None, params: dict | None = None,
                   idempotency_key: str | None = None) -> _Res:
        self.calls.append((method, path, json))
        if self.fail and self.fail in path:
            raise RuntimeError("the API is down")
        if method == "GET" and path == "/materials":
            return _Res(200, {"items": [{"id": f"m-{n}", "name": n, "default_unit_id": f"u-{n}"} for n in MATERIALS]})
        if method == "GET":
            return _Res(200, {})
        return _Res(201, {"id": str(uuid.uuid4()), "lines": [{"id": str(uuid.uuid4())}]})


def _run(api: _FakeApi, today: dt.date = dt.date(2026, 11, 2)) -> tuple[dict[str, int], list[str]]:
    info = {"project_id": "p-green-villa", "site_ids": ["s-main", "s-annex"], "others": []}
    return asyncio.run(sample_story.seed(api, info, today=today))


def test_story_makes_the_subcontractor_the_chapters_need() -> None:
    api = _FakeApi()
    seeded, failed = _run(api)
    assert failed == []
    assert seeded["subcontractor"] == 1 and seeded["vendor"] == len(sample_story.DEMO_VENDORS)
    bodies = [b for m, p, b in api.calls if m == "POST" and p == "/finance/vendors" and (b or {}).get("kind") == "subcontractor"]
    assert [b["name"] for b in bodies] == ["Joy Tiling Works"]


def test_green_villa_is_left_without_an_estimate() -> None:
    api = _FakeApi()
    _run(api)
    boq = [p for _m, p, _b in api.calls if "/boq/" in p]
    assert boq and not any(p.startswith("/projects/p-green-villa/") for p in boq)


def test_same_day_same_story() -> None:
    ids = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

    def shape(api: _FakeApi) -> list[tuple[str, str, str]]:
        return [(m, ids.sub("<id>", p), ids.sub("<id>", repr(b))) for m, p, b in api.calls]

    first, second = _FakeApi(), _FakeApi()
    assert _run(first)[0] == _run(second)[0]
    assert shape(first) == shape(second)


def test_a_failing_route_is_counted_never_raised() -> None:
    seeded, failed = _run(_FakeApi(fail="/progress/issues"))
    assert seeded["worker"] == len(sample_story.DEMO_WORKERS)
    assert any(f.startswith("issue: RuntimeError") for f in failed)


def test_lake_view_gets_its_whole_estimate_and_its_contract() -> None:
    """Project bible section 8 item 3: Lake View's full estimate (learn/lake_view.py) goes in as its BOQ, every line,
    each tower's sections on its own site; the contract is the estimate's total with its terms (TDS, no advance)."""
    from mesiri.application.learn import lake_view

    api = _FakeApi()
    _, failed = _run(api)
    assert failed == []
    sections = [b for m, p, b in api.calls if m == "POST" and p.endswith("/boq/sections")]
    assert [s["name"] for s in sections] == [name for name, _t, _l in lake_view.ESTIMATE]
    assert [bool(s.get("site_id")) for s in sections] == [tower is not None for _n, tower, _l in lake_view.ESTIMATE]
    lines = [b for m, p, b in api.calls if m == "POST" and "/boq/sections/" in p and p.endswith("/lines")]
    assert [(b["work"], b["planned_quantity"], b["client_rate"]) for b in lines] == [
        (w, q, r) for _n, _t, rows in lake_view.ESTIMATE for w, _u, q, r, _lr, _mr in rows]
    contract = next(b for m, p, b in api.calls if m == "PUT" and p.endswith("/contract"))
    assert contract["contract_value"] == sum(b["planned_quantity"] * b["client_rate"] for b in lines)
    assert (contract["tds_pct"], contract.get("mobilisation_advance")) == (2, None)


def test_lake_view_lines_hold_all_the_work_the_story_counts_on_them() -> None:
    """Every work Lake View's sites record, in the seed's two weeks and the 62 days, has a line on its tower, and the
    line's planned quantity is more than all of it: a line never shows more done than its tower holds."""
    from mesiri.application.learn import lake_view, sample_plan

    for key, tower in (("tower_a", "Tower A"), ("tower_b", "Tower B")):
        planned = {w: q for w, _u, q, *_ in lake_view.lines_of(tower)}
        at = (sample_story.DEMO_SITES + sample_story.DEMO_SITES_2).index(tower)
        done: dict[str, float] = {}
        works = sample_story.DEMO_WORK[at]
        for work, _n, _u, days, _uses in works:  # each of the seed's stages, its quantity day by day
            done[work] = done.get(work, 0) + sum(days)
        for stage in sample_plan.STAGES[key]:
            done[stage.work] = done.get(stage.work, 0) + stage.per_day * stage.days
        for work, qty in done.items():
            assert work in planned, f"{tower}: no line for {work}"
            assert qty < planned[work], f"{tower}: {work} {qty} done against {planned[work]} planned"
