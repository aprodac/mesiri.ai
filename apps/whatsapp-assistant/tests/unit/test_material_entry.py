"""ARCH-01: the agent's material saves without the classic pipeline.

Each branch either builds the workflow's event, says one line, or hands the
call back to the classic route (None) for the pickers it still owns.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from mesiri_contracts.assistant.candidates import Candidate
from mesiri_contracts.assistant.enums import SemanticType
from mesiri_contracts.assistant.planner_decision import WorkflowKey
from mesiri_contracts.common.result import Result
from runtime.agent.material_entry import MaterialEntry, Ready, Say

ORG = "11111111-1111-4111-8111-111111111111"
USR = "22222222-2222-4222-8222-222222222222"
PRJ = "33333333-3333-4333-8333-333333333333"
SITE = "44444444-4444-4444-8444-444444444444"
CEMENT = {"id": "55555555-5555-4555-8555-555555555555", "name": "Cement", "default_unit_id": "u-bag", "is_active": True}
SAND = {"id": "66666666-6666-4666-8666-666666666666", "name": "Sand", "default_unit_id": "u-cum", "is_active": True}
UNITS = {
    "bags": {"id": "u-bag", "code": "bag", "display_name": "Bags"},
    "cum": {"id": "u-cum", "code": "cum", "display_name": "Cubic Meters"},
}


class _Context:
    def __init__(self, *, project_id: str | None = PRJ, site_id: str | None = SITE, ok: bool = True) -> None:
        self.ctx = SimpleNamespace(
            organization_id=ORG,
            user_id=USR,
            project_id=project_id,
            site_id=site_id,
            conversation_id=None,
            permissions=[],
            timezone="Asia/Kolkata",
        )
        self.ok = ok

    async def resolve(self, message: Any, understanding: Any) -> Result:
        return Result.ok(self.ctx) if self.ok else Result.err(ValueError("no context"))


class _Catalog:
    def __init__(self, materials: list[dict], *, per: float | None = None) -> None:
        self.materials = materials
        self.per = per

    async def find_materials(self, *, organization_id: str, name: str) -> list[dict]:
        exact = [m for m in self.materials if m["name"].lower() == name.lower()]
        return exact or [m for m in self.materials if name.lower() in m["name"].lower()]

    async def resolve_unit(self, text: str) -> dict | None:
        return UNITS.get(text.lower().rstrip("s") + "s") or UNITS.get(text.lower())

    async def get_unit(self, unit_id: str) -> dict | None:
        return next((u for u in UNITS.values() if u["id"] == unit_id), None)

    async def find_conversion(self, **kwargs: Any) -> float | None:
        return self.per


class _Stock:
    def __init__(self) -> None:
        self.asked: dict = {}

    async def query(self, **kwargs: Any) -> list[dict]:
        self.asked = kwargs
        return [{"current_stock": 120.0}]


class _Modules:
    def __init__(self, enabled: list[str]) -> None:
        self.enabled = enabled

    async def enabled_modules(self, *, organization_id: str) -> list[str]:
        return self.enabled


def _actor(*sites: str, role: str = "SITE_ENGINEER") -> Any:
    return SimpleNamespace(role=role, sites=[SimpleNamespace(id=s, name=s, project_id=PRJ) for s in sites])


def _entry(*, catalog: _Catalog | None = None, context: _Context | None = None, modules=None, actor=None, stock=None):
    return MaterialEntry(
        context_resolver=context or _Context(),
        catalog_query=catalog or _Catalog([CEMENT, SAND]),
        inventory_query=stock,
        org_settings_query=modules,
        actor=actor or _actor(SITE),
    )


def _candidate(**fields: Any) -> Candidate:
    base = {"material_name": "cement", "quantity": 50, "unit": "bags", "direction": "received"}
    return Candidate(semantic_type=SemanticType.MATERIAL_UPDATE, fields={**base, **fields})


MESSAGE = SimpleNamespace(correlation_id="cor_1", message_id="wamid.1")


async def _prepare(entry: MaterialEntry, **fields: Any):
    return await entry.prepare(MESSAGE, None, _candidate(**fields))


async def test_a_known_material_in_its_stock_unit_is_ready_to_save():
    ready = await _prepare(_entry(), supplier="Sharma Traders")
    assert isinstance(ready, Ready)
    assert ready.decision.workflow_key is WorkflowKey.MATERIAL_RECEIPT
    fields = ready.event.fields
    assert (fields["material_id"], fields["material_name"], fields["unit_id"]) == (CEMENT["id"], "Cement", "u-bag")
    assert fields["supplier"] == "Sharma Traders"
    assert fields["occurred_date_source"] == "inferred_at_confirmation"
    assert (str(ready.event.project_id), str(ready.event.site_id)) == (PRJ, SITE)


async def test_a_convertible_unit_is_converted_and_what_was_said_is_kept():
    ready = await _prepare(_entry(catalog=_Catalog([CEMENT, SAND], per=28)), material_name="Sand", quantity=40)
    assert isinstance(ready, Ready)
    fields = ready.event.fields
    assert (fields["quantity"], fields["unit"]) == (pytest.approx(1.4286, abs=1e-3), "cum")
    assert (fields["reported_quantity"], fields["reported_unit"]) == (40.0, "bags")


async def test_a_unit_with_no_conversion_asks_for_the_amount():
    said = await _prepare(_entry(), material_name="Sand", quantity=40)
    assert isinstance(said, Say)
    assert said.text.startswith("Not saved yet: Sand is counted in Cubic Meters here")
    assert "How much is that in Cubic Meters?" in said.text  # a site engineer is not asked for the rule


async def test_usage_carries_the_stock_of_that_material_by_id():
    stock = _Stock()
    ready = await _prepare(_entry(stock=stock), direction="used", work_item="slab")
    assert ready.event.fields["available_stock"] == 120.0
    assert stock.asked["material_id"] == CEMENT["id"] and stock.asked["material_name"] is None


@pytest.mark.parametrize("quantity", [0, -5, "lots"])
async def test_a_quantity_that_is_not_above_zero_is_never_saved(quantity):
    said = await _prepare(_entry(), quantity=quantity)
    assert isinstance(said, Say) and said.status == "error"


async def test_a_switched_off_module_says_so():
    said = await _prepare(_entry(modules=_Modules(["labour"])))
    assert isinstance(said, Say) and "switched on" in said.text


@pytest.mark.parametrize(
    "entry",
    [
        _entry(catalog=_Catalog([{**CEMENT, "name": "Cement Paint"}])),  # not an exact name: the picker
        _entry(catalog=_Catalog([])),  # not in the catalogue: pick one / add it
        _entry(context=_Context(project_id=None, site_id=None)),  # which project?
        _entry(context=_Context(site_id=None), actor=_actor(SITE, "other-site")),  # which site?
        _entry(context=_Context(ok=False)),  # no context: the classic route says why
    ],
)
async def test_anything_needing_a_picker_takes_the_classic_route(entry):
    assert await _prepare(entry) is None


async def test_a_project_with_one_site_gets_that_site():
    ready = await _prepare(_entry(context=_Context(site_id=None), actor=_actor(SITE)))
    assert str(ready.event.site_id) == SITE
