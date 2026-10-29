"""[103]: site transfers, opening stock, load -> cum, and long material lists."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from tests.unit.test_material_entry import (
    CEMENT,
    PRJ,
    SAND,
    SITE,
    UNITS,
    _Catalog,
    _entry,
    _prepare,
)

from interactions.saved_summary import summarise_draft
from mesiri_contracts.assistant.draft_action import DraftActionType
from mesiri_contracts.assistant.planner_decision import WorkflowKey
from runtime.agent import tools as T
from runtime.agent.material_entry import SOMETHING_ELSE, Ready, Say
from runtime.agent.tools import ScopeLookup, to_candidate
from runtime.save_first import over_stock_note
from workflows.material.nodes import build_draft, request_confirmation

ORG_ID = "11111111-1111-4111-8111-111111111111"
USER_ID = "22222222-2222-4222-8222-222222222222"
SITE_B = "88888888-8888-4888-8888-888888888888"
PRJ_2 = "99999999-9999-4999-8999-999999999999"


def _actor(role: str = "ADMIN", extra_sites: tuple[tuple[str, str, str], ...] = ()) -> Any:
    sites = [SimpleNamespace(id=SITE, name="Green Villa", project_id=PRJ)]
    sites += [SimpleNamespace(id=i, name=n, project_id=p) for i, n, p in extra_sites]
    projects = [SimpleNamespace(id=PRJ, name="Villas"), SimpleNamespace(id=PRJ_2, name="Towers")]
    return SimpleNamespace(role=role, user_id="u", projects=projects, sites=sites)


def _two_sites(role: str = "ADMIN") -> Any:
    return _actor(role, ((SITE_B, "Site B", PRJ),))


# -- the tools ------------------------------------------------------------------


def test_transfer_material_is_a_write_tool_with_the_other_site_required():
    spec = next(s for s in T.tool_specs() if s.name == T.TRANSFER_MATERIAL)
    assert T.TRANSFER_MATERIAL in T.WRITE_TOOLS and T.SAVE_OPENING_STOCK in T.WRITE_TOOLS
    assert {"material", "quantity", "unit", "to_site"} <= set(spec.parameters["required"])


def test_the_tools_become_material_candidates():
    scope = ScopeLookup()
    transfer = to_candidate(T.TRANSFER_MATERIAL, {"material": "Cement", "quantity": 10, "unit": "bags", "to_site": "Site B"}, scope)
    assert transfer.fields["direction"] == "transfer" and transfer.fields["to_site_name"] == "Site B"
    opening = to_candidate(T.SAVE_OPENING_STOCK, {"material": "Steel", "quantity": 500, "unit": "kg"}, scope)
    assert opening.fields["direction"] == "opening_stock"


# -- transfer ---------------------------------------------------------------------


async def _transfer(entry, **fields):
    return await _prepare(entry, direction="transfer", to_site_name="Site B", **fields)


async def test_a_transfer_is_ready_with_both_sites_and_never_a_usage():
    ready = await _transfer(_entry(actor=_two_sites()))
    assert isinstance(ready, Ready)
    assert ready.decision.workflow_key is WorkflowKey.MATERIAL_TRANSFER
    f = ready.event.fields
    assert (f["to_site_id"], f["to_project_id"], f["to_site_name"]) == (SITE_B, PRJ, "Site B")
    assert f["from_site_name"] == "Green Villa"
    assert str(ready.event.site_id) == SITE  # the sending site
    assert "work_item" not in f


async def test_the_site_is_matched_ignoring_case_and_spacing():
    ready = await _prepare(_entry(actor=_two_sites()), direction="transfer", to_site_name="  site b ")
    assert isinstance(ready, Ready) and ready.event.fields["to_site_id"] == SITE_B


async def test_an_unknown_site_is_a_list_of_their_sites_never_a_guess():
    said = await _prepare(_entry(actor=_two_sites()), direction="transfer", to_site_name="Moon base")
    assert isinstance(said, Say) and said.status == "choose"
    assert said.options == ("Site B",)  # not the sending site
    assert "to_site" in said.text


async def test_no_site_named_asks_which():
    said = await _prepare(_entry(actor=_two_sites()), direction="transfer")
    assert isinstance(said, Say) and said.status == "choose"


async def test_sending_to_the_same_site_is_refused_as_unknown():
    said = await _prepare(_entry(actor=_two_sites()), direction="transfer", to_site_name="Green Villa")
    assert isinstance(said, Say) and said.options == ("Site B",)


async def test_with_no_other_site_it_says_so():
    said = await _transfer(_entry(actor=_actor()))
    assert isinstance(said, Say) and said.status == "info" and "no other site" in said.text


async def test_two_sites_with_one_name_are_told_apart_by_project():
    actor = _actor("ADMIN", ((SITE_B, "Block A", PRJ), ("a" * 8 + "-aaaa-4aaa-8aaa-" + "a" * 12, "Block A", PRJ_2)))
    said = await _prepare(_entry(actor=actor), direction="transfer", to_site_name="Block A")
    assert isinstance(said, Say) and set(said.options) == {"Block A (Villas)", "Block A (Towers)"}
    ready = await _prepare(_entry(actor=actor), direction="transfer", to_site_name="Block A (Towers)")
    assert isinstance(ready, Ready) and ready.event.fields["to_project_id"] == PRJ_2


def test_the_card_line_for_a_transfer():
    draft = SimpleNamespace(
        action_type=DraftActionType.TRANSFER_MATERIAL,
        fields={"material_name": "cement", "quantity": 10, "unit": "bags", "from_site_name": "Green Villa", "to_site_name": "Site B"},
    )
    assert summarise_draft(draft) == "Transfer: Cement 10 bags · Green Villa → Site B"


def test_the_confirmation_text_of_a_transfer_names_both_sites():
    state = {
        "workflow_key": WorkflowKey.MATERIAL_TRANSFER.value,
        "collected_fields": {
            "material_name": "Cement", "quantity": 10, "unit": "bags",
            "from_site_name": "Green Villa", "to_site_name": "Site B", "to_site_id": SITE_B,
        },
        "correlation_id": "c", "workflow_instance_id": "w", "organization_id": ORG_ID, "user_id": USER_ID,
        "project_id": PRJ, "site_id": SITE,
    }
    state.update(build_draft(state))
    text = request_confirmation(state)["pending_prompt"]
    assert "Material Transfer" in text and "From: Green Villa" in text and "To: Site B" in text
    assert state["draft_action"].action_type is DraftActionType.TRANSFER_MATERIAL


# -- opening stock ----------------------------------------------------------------


async def test_opening_stock_is_a_receipt_with_its_own_reason():
    ready = await _prepare(_entry(actor=_two_sites()), direction="opening_stock", material_name="Cement", quantity=500)
    assert isinstance(ready, Ready)
    assert ready.decision.workflow_key is WorkflowKey.MATERIAL_RECEIPT
    f = ready.event.fields
    assert f["movement_reason"] == "OPENING_STOCK" and f["direction"] == "received"
    assert f["site_label"] == "Green Villa"


async def test_opening_stock_is_for_an_admin_or_project_manager():
    said = await _prepare(_entry(actor=_two_sites("SITE_ENGINEER")), direction="opening_stock")
    assert isinstance(said, Say) and "admin or project manager" in said.text


def test_the_card_line_for_opening_stock():
    draft = SimpleNamespace(
        action_type=DraftActionType.RECORD_MATERIAL_RECEIPT,
        fields={"material_name": "steel", "quantity": 500, "unit": "kg", "movement_reason": "OPENING_STOCK", "site_label": "Green Villa"},
    )
    assert summarise_draft(draft) == "Opening stock: Steel 500 kg (Green Villa)"


def test_over_stock_adds_the_opening_stock_hint_only_when_none_was_entered():
    plain = over_stock_note(DraftActionType.RECORD_MATERIAL_USAGE, 10, "kg", 5)
    assert "opening stock" not in plain
    hinted = over_stock_note(DraftActionType.RECORD_MATERIAL_USAGE, 10, "kg", 5, no_opening_stock=True, material="Steel")
    assert hinted.splitlines()[-1] == 'If there was stock before Mesiri, send "opening stock steel 500 kg".'


class _Stock:
    async def query(self, **kwargs: Any) -> list[dict]:
        return [{"current_stock": 5.0}]


class _OpeningCatalog(_Catalog):
    def __init__(self, *args: Any, has: bool, **kw: Any) -> None:
        super().__init__(*args, **kw)
        self.has = has

    async def has_opening_stock(self, **kwargs: Any) -> bool:
        return self.has


async def test_usage_over_stock_with_no_opening_stock_is_flagged_for_the_hint():
    entry = _entry(catalog=_OpeningCatalog([CEMENT, SAND], has=False), stock=_Stock())
    ready = await _prepare(entry, direction="used", quantity=20)
    assert ready.event.fields["no_opening_stock"] is True


async def test_no_hint_when_opening_stock_exists_or_usage_is_within_stock():
    has = await _prepare(_entry(catalog=_OpeningCatalog([CEMENT, SAND], has=True), stock=_Stock()), direction="used", quantity=20)
    assert "no_opening_stock" not in has.event.fields
    within = await _prepare(_entry(catalog=_OpeningCatalog([CEMENT, SAND], has=False), stock=_Stock()), direction="used", quantity=2)
    assert "no_opening_stock" not in within.event.fields


# -- units: load -> cum ------------------------------------------------------------

UNITS["loads"] = {"id": "u-load", "code": "load", "display_name": "Loads"}


async def test_a_load_of_sand_in_cum_asks_once_with_buttons():
    said = await _prepare(_entry(actor=_two_sites("ADMIN")), material_name="Sand", quantity=2, unit="loads")
    assert isinstance(said, Say) and said.status == "choose"
    assert said.question == "1 load = how many cum? (e.g. 3)"
    assert said.options == ("2", "3", "4", "Other")
    assert "Cubic Meters" not in said.text and "set_unit_conversion" in said.text


async def test_once_the_company_has_said_it_the_load_is_converted_without_a_question():
    ready = await _prepare(_entry(catalog=_Catalog([CEMENT, SAND], per=3), actor=_two_sites("ADMIN")), material_name="Sand", quantity=2, unit="loads")
    assert isinstance(ready, Ready)
    f = ready.event.fields
    assert (f["quantity"], f["unit"], f["reported_quantity"]) == (pytest.approx(0.6667, abs=1e-3), "cum", 2.0)


async def test_someone_who_may_not_set_it_is_told_the_plain_fact_without_buttons():
    said = await _prepare(_entry(actor=_two_sites("SITE_ENGINEER")), material_name="Sand", quantity=2, unit="loads")
    assert isinstance(said, Say) and said.status == "info" and not said.options


async def test_the_new_material_unit_question_offers_cft_tons_and_load():
    said = await _prepare(_entry(catalog=_Catalog([]), actor=_two_sites("ADMIN"), modules=_Create()), material_name="M sand", unit="", new_material=True)
    assert isinstance(said, Say)
    assert said.options == ("Bags", "Kg", "Nos", "Cum", "Cft", "Tons", "Litres", "Load")


class _Create:
    async def enabled_modules(self, *, organization_id: str) -> list[str]:
        return ["materials"]

    async def get(self, *, organization_id: str, key: str) -> Any:
        return ["ADMIN"]


# -- more than ten materials -------------------------------------------------------


class _Many(_Catalog):
    def __init__(self, n: int) -> None:
        super().__init__([{"id": f"m{i}", "name": f"Material {i:02d}", "default_unit_id": "u-bag", "is_active": True} for i in range(n)])

    async def find_materials(self, *, organization_id: str, name: str) -> list[dict]:
        return []

    async def closest_materials(self, *, organization_id: str, name: str, limit: int = 9):
        return self.materials[:limit], len(self.materials)


async def test_a_long_list_shows_nine_and_something_else():
    said = await _prepare(_entry(catalog=_Many(25), actor=_two_sites("SITE_ENGINEER")), material_name="plywood")
    assert isinstance(said, Say) and said.status == "choose"
    assert len(said.options) == 10 and said.options[-1] == SOMETHING_ELSE
    assert said.options[0] == "Material 00" and "type the material name" in said.text


async def test_ten_or_fewer_materials_are_all_shown_without_something_else():
    said = await _prepare(_entry(catalog=_Many(8), actor=_two_sites("SITE_ENGINEER")), material_name="plywood")
    assert isinstance(said, Say) and len(said.options) == 8 and SOMETHING_ELSE not in said.options


async def test_the_catalog_ranks_by_spelling_then_recent_use():
    from datetime import UTC, datetime

    from runtime.material_catalog_query import MaterialCatalogQueryService

    rows = [{"id": f"{i}", "name": n} for i, n in enumerate(["Cement PPC", "Steel 12mm", "Steel 8mm", "Sand", "Bricks"])]
    recent = [("2", datetime(2026, 10, 24, tzinfo=UTC)), ("1", datetime(2026, 10, 1, tzinfo=UTC))]

    class _Conn:
        async def execute(self, *_a, **_k):
            return SimpleNamespace(all=lambda: recent)

    class _Db:
        def transaction(self):
            class _Ctx:
                async def __aenter__(self):
                    return _Conn()

                async def __aexit__(self, *a):
                    return False

            return _Ctx()

    import mesiri.infrastructure.postgres.repositories.materials as repo_mod

    class _Repo:
        def __init__(self, conn): ...
        async def list_materials(self, **kw):
            return rows, len(rows)

    original = repo_mod.PostgresMaterialCatalogRepository
    repo_mod.PostgresMaterialCatalogRepository = _Repo
    try:
        service = MaterialCatalogQueryService(_Db())
        ranked, total = await service.closest_materials(organization_id="11111111-1111-4111-8111-111111111111", name="steel", limit=3)
    finally:
        repo_mod.PostgresMaterialCatalogRepository = original
    assert total == 5
    assert len(ranked) == 3
    assert [r["name"] for r in ranked][:2] == ["Steel 8mm", "Steel 12mm"]  # both match; the newer first


def test_a_transfer_gets_its_own_receipt_card():
    from datetime import UTC, datetime

    from channel.receipt.data import build_receipt_data
    from mesiri_contracts.assistant.v2.draft_action import DraftActionV2

    draft = DraftActionV2(
        draft_id="d", correlation_id="c", workflow_instance_id="w", action_type=DraftActionType.TRANSFER_MATERIAL,
        organization_id=ORG_ID, user_id=USER_ID, project_id=PRJ, site_id=SITE,
        fields={"material_name": "cement", "quantity": 10, "unit": "bags", "from_site_name": "Green Villa", "to_site_name": "Site B"},
    )
    data = build_receipt_data(
        draft, record_row_id="11111111-1111-4111-8111-111111111111", reporter_name="Ravi",
        projects=[], sites=[], confirmed_at=datetime(2026, 10, 24, 6, tzinfo=UTC),
    )
    assert data.category == "Material transfer"
    assert [(r.tag, r.text) for r in data.rows] == [("Material", "Cement"), ("From", "Green Villa"), ("To", "Site B")]


async def test_a_partial_destination_name_finds_the_site_like_every_other_site_said():
    """Live 29 Oct: "Green Villa-lekku" was refused while "Green Villa-il ninnu" matched."""
    actor = _actor("ADMIN", ((SITE_B, "Green Villa, Kakkanad", PRJ),))
    ready = await _prepare(_entry(actor=actor), direction="transfer", to_site_name="Green Villa")
    assert isinstance(ready, Ready) and ready.event.fields["to_site_name"] == "Green Villa, Kakkanad"
