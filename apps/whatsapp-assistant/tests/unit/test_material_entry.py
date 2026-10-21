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
            context_organization_id=ORG,
            context_user_id=USR,
            context_project_id=project_id,
            context_site_id=site_id,
        )
        self.ok = ok

    async def resolve(self, message: Any, understanding: Any) -> Result:
        return Result.ok(self.ctx) if self.ok else Result.err(ValueError("no context"))


class _Catalog:
    def __init__(self, materials: list[dict], *, per: float | None = None) -> None:
        self.materials = materials
        self.per = per
        self.created: list[tuple] = []

    async def find_materials(self, *, organization_id: str, name: str) -> list[dict]:
        exact = [m for m in self.materials if m["name"].lower() == name.lower()]
        return exact or [m for m in self.materials if name.lower() in m["name"].lower()]

    async def resolve_unit(self, text: str) -> dict | None:
        return UNITS.get(text.lower().rstrip("s") + "s") or UNITS.get(text.lower())

    async def get_unit(self, unit_id: str) -> dict | None:
        return next((u for u in UNITS.values() if u["id"] == unit_id), None)

    async def find_conversion(self, **kwargs: Any) -> float | None:
        return self.per

    async def list_active_materials(self, *, organization_id: str) -> list[dict]:
        return self.materials

    async def create_material(self, *, organization_id: str, name: str, unit_id: str, created_by: str) -> dict:
        self.created.append((name, unit_id, created_by))
        return {"id": "77777777-7777-4777-8777-777777777777", "name": name, "default_unit_id": unit_id, "is_active": True}


class _Stock:
    def __init__(self) -> None:
        self.asked: dict = {}

    async def query(self, **kwargs: Any) -> list[dict]:
        self.asked = kwargs
        return [{"current_stock": 120.0}]


class _Modules:
    """The org settings the entry reads: modules, and who may add materials."""

    def __init__(self, enabled: list[str], *, create_roles: list[str] | None = None) -> None:
        self.enabled = enabled
        self.create_roles = create_roles or []

    async def enabled_modules(self, *, organization_id: str) -> list[str]:
        return self.enabled

    async def get(self, *, organization_id: str, key: str) -> Any:
        return self.create_roles


def _actor(*sites: str, role: str = "SITE_ENGINEER") -> Any:
    return SimpleNamespace(
        role=role, user_id=USR, projects=[], sites=[SimpleNamespace(id=s, name=s, project_id=PRJ) for s in sites]
    )


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


async def test_a_name_with_several_matches_is_a_question_with_the_options():
    said = await _prepare(_entry(catalog=_Catalog([{**CEMENT, "name": "Cement Paint"}, {**CEMENT, "id": "c2", "name": "Cement PPC"}])))
    assert isinstance(said, Say) and said.status == "choose"
    assert "Options: Cement Paint, Cement PPC" in said.text
    assert said.options == ("Cement Paint", "Cement PPC")  # shown as buttons by the code


async def test_an_unknown_name_lists_the_catalogue_when_they_may_not_add_one():
    catalog = _Catalog([SAND])
    said = await _prepare(_entry(catalog=catalog, modules=_Modules(["materials"], create_roles=[])))
    assert said.status == "choose"
    assert "Options: Sand" in said.text and "admin on the dashboard" in said.text


async def test_an_unknown_name_asks_to_add_it_when_they_may():
    entry = _entry(catalog=_Catalog([SAND]), modules=_Modules(["materials"], create_roles=["SITE_ENGINEER"]))
    said = await _prepare(entry, material_name="Fevicol", unit="bags")
    assert said.status == "choose" and "add it as a new material" in said.text
    assert said.text.count("new_material") == 1
    assert said.options == ("Yes, add it", "No")


async def test_after_a_yes_the_new_material_is_added_and_saved():
    catalog = _Catalog([SAND])
    entry = _entry(catalog=catalog, modules=_Modules(["materials"], create_roles=["SITE_ENGINEER"]))
    ready = await _prepare(entry, material_name="Fevicol", unit="bags", new_material=True)
    assert isinstance(ready, Ready)
    assert catalog.created == [("Fevicol", "u-bag", USR)]
    assert "new_material" not in ready.event.fields
    assert ready.event.fields["material_name"] == "Fevicol"


async def test_a_new_material_is_never_added_without_the_right():
    catalog = _Catalog([SAND])
    entry = _entry(catalog=catalog, modules=_Modules(["materials"], create_roles=[]))
    said = await _prepare(entry, material_name="Fevicol", new_material=True)
    assert said.status == "choose" and catalog.created == []


async def test_a_new_material_in_an_unknown_unit_asks_for_the_unit():
    entry = _entry(catalog=_Catalog([SAND]), modules=_Modules(["materials"], create_roles=["SITE_ENGINEER"]))
    said = await _prepare(entry, material_name="Fevicol", unit="tins", new_material=True)
    assert said.status == "choose" and "which unit" in said.text


async def test_no_project_is_a_question_with_their_projects():
    actor = _actor(SITE)
    actor.projects = [SimpleNamespace(name="Green Villa"), SimpleNamespace(name="Lake View")]
    said = await _prepare(_entry(context=_Context(project_id=None, site_id=None), actor=actor))
    assert said.status == "choose" and "Options: Green Villa, Lake View" in said.text


async def test_two_sites_is_a_question_with_the_sites():
    said = await _prepare(_entry(context=_Context(site_id=None), actor=_actor("Kakkanad", "Edappally")))
    assert said.status == "choose" and "Options: Kakkanad, Edappally" in said.text


async def test_a_failed_context_asks_for_the_project_with_buttons():
    """Live 22 Oct: the classic route answered a plain "Yes" with "Sorry, I
    couldn't make out that message"."""
    actor = _actor(SITE)
    actor.projects = [SimpleNamespace(name="Hospital Project"), SimpleNamespace(name="Mithilash")]
    said = await _prepare(_entry(context=_Context(ok=False), actor=actor))
    assert said.status == "choose" and said.options == ("Hospital Project", "Mithilash")


async def test_a_project_with_one_site_gets_that_site():
    ready = await _prepare(_entry(context=_Context(site_id=None), actor=_actor(SITE)))
    assert str(ready.event.site_id) == SITE
