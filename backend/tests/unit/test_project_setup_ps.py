"""PS / QA-04 (20 Nov 2026): what a project is set up with, tested where the rules live.

- 2.1 duplicate sites: "villa 1" was saved beside "Villa 1" on production (both routers only checked "not empty").
- PS-05 the project's kind and size: a known type, an area above zero, whole floors.
- PS-01..04 contract terms: payment days, contract type, delay penalty and its cap, escalation.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from mesiri.application.projects.site_names import (
    already_a_site,
    existing_site_named,
    same_site_name,
)
from mesiri.application.projects.size import ProjectSize, size_of, size_values
from mesiri.domains.billing.contracts import TERM_FIELDS
from mesiri.domains.billing.router import ContractIn

ORG = uuid.uuid4()
PROJECT = uuid.uuid4()


class Sites:
    """Answers the one read of a project's sites."""

    def __init__(self, rows: list[tuple[uuid.UUID, str]]) -> None:
        self.rows = rows
        self.params: dict[str, Any] = {}

    async def execute(self, statement: Any, params: Any = None) -> Any:  # noqa: ANN401
        self.params = dict(statement.compile().params)
        return SimpleNamespace(fetchall=lambda: [SimpleNamespace(id=i, name=n) for i, n in self.rows])


# -- 2.1 duplicate sites ------------------------------------------------------------------------------------------

@pytest.mark.parametrize("typed", ["villa 1", "VILLA 1", "  Villa   1 ", "Ｖｉｌｌａ 1"])
async def test_the_reported_case_and_its_spellings_are_one_site(typed: str) -> None:
    conn = Sites([(uuid.uuid4(), "Villa 1")])
    assert await existing_site_named(conn, ORG, PROJECT, typed) == "Villa 1"
    assert conn.params == {"org": ORG, "p": PROJECT}  # only this project's sites are read
    assert already_a_site("Villa 1") == "Villa 1 is already a site of this project"


async def test_renaming_a_site_to_its_own_name_is_not_a_clash() -> None:
    own = uuid.uuid4()
    conn = Sites([(own, "Villa 1"), (uuid.uuid4(), "Villa 2")])
    assert await existing_site_named(conn, ORG, PROJECT, "villa 1", other_than=own) is None
    assert await existing_site_named(conn, ORG, PROJECT, "Villa 2", other_than=own) == "Villa 2"


async def test_guard_new_names_and_numbers_are_not_clashes() -> None:
    conn = Sites([(uuid.uuid4(), "Villa 1")])
    for name in ("Villa 2", "Villa 10", "Villa 1A", ""):
        assert await existing_site_named(conn, ORG, PROJECT, name) is None
    assert same_site_name("Villa 1") != same_site_name("Villa 11")


# -- PS-05 the project's kind and size -----------------------------------------------------------------------------

def test_size_is_checked_and_written_only_when_sent() -> None:
    body = ProjectSize(projectType=" Villa ", builtUpAreaSqft=12800, floors=2)
    assert size_values(body, sent_only=False) == {"project_type": "villa", "built_up_area_sqft": 12800, "floors": 2,
                                                   "overhead_pct": None}
    assert size_values(ProjectSize(), sent_only=True) == {}  # an edit that does not mention size keeps it
    assert size_values(ProjectSize(floors=None), sent_only=True) == {"floors": None}  # sent empty: cleared
    assert ProjectSize(projectType="").projectType is None


@pytest.mark.parametrize("bad", [{"projectType": "castle"}, {"builtUpAreaSqft": 0}, {"floors": 0}, {"floors": 2.5}])
def test_a_wrong_size_is_refused(bad: dict) -> None:
    with pytest.raises(ValidationError):
        ProjectSize(**bad)


def test_size_reads_a_stored_row() -> None:
    assert size_of(SimpleNamespace(project_type="villa", built_up_area_sqft=Decimal("12800.00"), floors=2,
                                   overhead_pct=Decimal("8.00"))) == {
        "project_type": "villa", "built_up_area_sqft": 12800.0, "floors": 2, "overhead_pct": 8.0}
    assert size_of(SimpleNamespace()) == {"project_type": None, "built_up_area_sqft": None, "floors": None,
                                          "overhead_pct": None}


# -- PS-01..04 contract terms --------------------------------------------------------------------------------------

def test_the_new_terms_are_stored_with_the_contract() -> None:
    for term in ("client_payment_days", "contract_type", "ld_pct_per_week", "ld_cap_pct", "escalation_applies",
                 "escalation_terms"):
        assert term in TERM_FIELDS
    body = ContractIn(client_payment_days=45, contract_type="item_rate", ld_pct_per_week=Decimal("0.5"),
                      ld_cap_pct=Decimal("5"), escalation_applies=True, escalation_terms="  Steel above 5% ")
    dumped = body.model_dump(exclude={"client_id", "new_client"})
    assert dumped["client_payment_days"] == 45 and dumped["escalation_terms"] == "Steel above 5%"


@pytest.mark.parametrize("bad", [{"client_payment_days": 400}, {"client_payment_days": -1}, {"contract_type": "turnkey"},
                                 {"ld_pct_per_week": Decimal("101")}])
def test_a_wrong_term_is_refused(bad: dict) -> None:
    with pytest.raises(ValidationError):
        ContractIn(**bad)


# -- PS phase 2: the BOQ's first entry ------------------------------------------------------------------------------

def _line(qty: str, client: str | None, **rates: str) -> dict:
    from mesiri.domains.progress.boq import line_amounts

    line = {"planned_quantity": Decimal(qty), "client_rate": Decimal(client) if client else None,
            **{k: Decimal(v) for k, v in rates.items()}}
    return {**line, **line_amounts(line)}


def test_machinery_is_part_of_the_budget_and_earns_on_its_own() -> None:
    from mesiri.domains.progress.boq import line_progress

    line = _line("26", "9800", labour_rate="1900", material_rate="5600", machinery_rate="400")
    assert line["budget_rate"] == Decimal("7900") and line["budget_cost"] == Decimal("205400.00")
    done = line_progress(line, Decimal("2"))
    assert done["earned_machinery"] == Decimal("800.00") and done["earned"] == Decimal("15800.00")
    # Guard: a line without machinery is priced as before.
    assert _line("26", "9800", labour_rate="1900", material_rate="5600")["budget_cost"] == Decimal("195000.00")


def test_one_unpriced_line_no_longer_hides_the_margin() -> None:
    from mesiri.domains.progress.boq import totals

    lines = [_line("450", "25", labour_rate="20"), _line("290", "1650")]  # tiling: no cost rate yet (QA-04 3.2)
    t = totals(lines)
    assert t["margin"] is None  # unchanged meaning: every line priced
    assert t["priced_lines"] == 1 and t["priced_margin"] == Decimal("2250.00")
    assert t["lines_without_budget_rate"] == 1


def test_overheads_come_off_the_margin_only_when_set() -> None:
    from mesiri.domains.progress.boq import with_overheads

    t = {"budget_cost": Decimal("6734500.00"), "margin": Decimal("1471550.00"), "priced_margin": Decimal("1471550.00")}
    out = with_overheads(t, Decimal("8"))
    assert out["overhead_cost"] == Decimal("538760.00") and out["margin_after_overheads"] == Decimal("932790.00")
    assert with_overheads(t, None)["overhead_cost"] is None  # never an assumed %


@pytest.mark.parametrize(("title", "project", "warn"), [
    (["GREEN VILLA, PUTHUR ROAD, THRISSUR: ESTIMATE (G+1 residence, 3,200 sq ft)", "Client: Dr. Anand Krishnan"],
     "Palm Grove Villas", True),  # QA-04 3.5: the reported case
    (["GREEN VILLA, PUTHUR ROAD, THRISSUR: ESTIMATE"], "Green Villa", False),
    (["PALM GROVE VILLAS: BOQ"], "Palm Grove Villas", False),
    (["ESTIMATE"], "Palm Grove Villas", False),  # guard: a title that names nothing
    ([], "Palm Grove Villas", False),
])
def test_a_file_that_names_another_project_is_caught(title: list[str], project: str, warn: bool) -> None:
    from mesiri.domains.progress.boq_import import names_another_project

    assert names_another_project(title, project) is warn


# -- PS phase 2b: sites, the approved budget, export ----------------------------------------------------------------

def _boq_with(lines: list[dict]) -> dict:
    from mesiri.domains.progress.boq import line_amounts, totals

    full = [{**ln, **line_amounts(ln)} for ln in lines]
    return {"sections": [{"name": "D. Plastering", "code": None, "lines": full, "totals": totals(full)}],
            "totals": totals(full)}


def _ln(code: str, work: str, qty: str, rate: str, cost: str) -> dict:
    return {"boq_code": code, "work": work, "unit": "sqm", "planned_quantity": Decimal(qty),
            "client_rate": Decimal(rate), "labour_rate": Decimal(cost), "is_provisional": False}


def test_changes_are_read_against_the_approved_budget() -> None:
    from mesiri.domains.progress.boq_extras import compare_with_baseline, line_key

    approved = _boq_with([_ln("4.1", "Plastering", "1450", "420", "330"), _ln("4.2", "External plastering", "780", "520", "410")])
    baseline = {"id": "b1", "name": "Budget v1", "locked_at": None, "totals": approved["totals"],
                "lines": [{"key": line_key(ln), "planned_quantity": ln["planned_quantity"], "client_rate": ln["client_rate"],
                           "budget_rate": ln["budget_rate"], "budget_cost": ln["budget_cost"],
                           "contract_value": ln["contract_value"]} for ln in approved["sections"][0]["lines"]]}
    now = _boq_with([_ln("4.1", "Plastering", "1600", "420", "330"), _ln("4.3", "Ceiling plastering", "380", "460", "370")])
    out = compare_with_baseline(now, baseline)
    assert (out["lines_changed"], out["lines_added"], out["lines_removed"]) == (1, 1, 1)
    first = now["sections"][0]["lines"][0]
    assert first["baseline"]["planned_quantity"] == Decimal("1450")  # what was approved stays readable
    assert now["sections"][0]["lines"][1]["baseline"] is None  # added since
    assert compare_with_baseline(now, None) is None  # guard: nothing approved, nothing compared


def test_work_done_is_counted_per_site() -> None:
    from mesiri.domains.progress.boq_extras import done_by_line_site

    line, v1, v2 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    work = [{"line_id": line, "site_id": v1, "quantity": Decimal("40")},
            {"line_id": line, "site_id": v1, "quantity": Decimal("20")},
            {"line_id": line, "site_id": v2, "quantity": Decimal("15")},
            {"line_id": line, "site_id": v2, "quantity": None}]  # another unit: left out, as for the line
    assert done_by_line_site(work) == {(line, v1): Decimal("60"), (line, v2): Decimal("15")}


class _Sites:
    def __init__(self, ids: set) -> None:
        self.ids, self.inserted = ids, []

    async def execute(self, statement: Any, params: Any = None) -> Any:  # noqa: ANN401
        sql = str(statement)
        if sql.startswith("SELECT id FROM sites"):
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [i for i in params["ids"] if i in self.ids]))
        if sql.startswith("INSERT"):
            self.inserted.append(params)
        return SimpleNamespace()


async def test_a_split_must_add_up_to_the_line() -> None:
    from fastapi import HTTPException

    from mesiri.domains.progress.boq_extras import set_line_sites

    v1, v2 = uuid.uuid4(), uuid.uuid4()
    conn = _Sites({v1, v2})
    with pytest.raises(HTTPException) as exc:
        await set_line_sites(conn, ORG, PROJECT, uuid.uuid4(), Decimal("1450"),
                             [{"site_id": v1, "quantity": Decimal("700")}, {"site_id": v2, "quantity": Decimal("700")}])
    assert exc.value.detail == "The sites add up to 1400, the line is 1450: they must match"
    await set_line_sites(conn, ORG, PROJECT, uuid.uuid4(), Decimal("1450"),
                         [{"site_id": v1, "quantity": Decimal("725")}, {"site_id": v2, "quantity": Decimal("725")}])
    assert len(conn.inserted) == 2
    with pytest.raises(HTTPException):  # a site of another project
        await set_line_sites(conn, ORG, PROJECT, uuid.uuid4(), Decimal("10"), [{"site_id": uuid.uuid4(), "quantity": 10}])


def test_the_export_reads_back_through_the_import() -> None:
    from mesiri.domains.progress.boq_extras import export_xlsx
    from mesiri.domains.progress.boq_import import read_sheet

    boq = _boq_with([_ln("4.1", "Plastering", "1450", "420", "330"), _ln("4.2", "External plastering", "780", "520", "410")])
    sheet = read_sheet(export_xlsx(boq, "Palm Grove Villas", "Dr. Meera Nair", Decimal("18"), with_costs=True))
    lines = [r for r in sheet.rows if not r.heading and r.unit]
    assert [(r.code, r.work, float(r.quantity), float(r.rates["client_rate"]), float(r.rates["labour_rate"]))
            for r in lines] == [("4.1", "Plastering", 1450, 420, 330), ("4.2", "External plastering", 780, 520, 410)]
    assert sheet.title and "Palm Grove Villas" in sheet.title[0]
