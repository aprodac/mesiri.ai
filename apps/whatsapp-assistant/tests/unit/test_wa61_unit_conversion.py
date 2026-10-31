"""WA-61: "1 load" of holobricks became 0.333 nos (live 23 Oct). The bot asked
"how many loads make 1 nos?", which nobody can answer, and the number was saved
upside down for the company. Now the question is asked the way people know it,
the code divides the two amounts they said, and a conversion that turns whole
things into a fraction is asked again, never saved."""

from __future__ import annotations

from decimal import Decimal

from mesiri.domains.materials.unit_conversion import to_stock_quantity
from runtime.agent.toolbox import per_stock_unit
from runtime.material_units import UnitFit, ask_amount_text, fit_stock_unit

NOS = {"id": "u-nos", "code": "nos", "display_name": "Numbers"}
LOAD = {"id": "u-load", "code": "load", "display_name": "Load"}
CUM = {"id": "u-cum", "code": "cum", "display_name": "m³"}
BAGS = {"id": "u-bags", "code": "bags", "display_name": "Bags"}
BRICKS = {"id": "m-1", "name": "Holobricks", "default_unit_id": "u-nos"}
SAND = {"id": "m-2", "name": "Sand", "default_unit_id": "u-cum"}


class _Catalog:
    def __init__(self, per):  # noqa: ANN001
        self.per = per

    async def resolve_unit(self, text):  # noqa: ANN001, ANN201
        return {"load": LOAD, "bags": BAGS, "nos": NOS}.get(text)

    async def get_unit(self, unit_id):  # noqa: ANN001, ANN201
        return {u["id"]: u for u in (NOS, LOAD, CUM, BAGS)}.get(unit_id)

    async def find_conversion(self, **_kw):  # noqa: ANN003, ANN201
        return self.per


def test_the_two_amounts_become_the_stored_number_either_way_round():
    assert to_stock_quantity(1, per_stock_unit({"unit_amount": 1, "stock_amount": 300})) == 300
    assert to_stock_quantity(2, per_stock_unit({"unit_amount": 1, "stock_amount": 300})) == 600
    assert per_stock_unit({"unit_amount": 28, "stock_amount": 1}) == 28
    assert to_stock_quantity(1, per_stock_unit({"stock_amount": 300})) == 300  # "1" left out
    assert per_stock_unit({"unit_amount": 1, "stock_amount": 0}) is None
    assert per_stock_unit({"unit_amount": 1}) is None


async def test_one_load_of_300_bricks_is_300_nos():
    fields = {"quantity": 1, "unit": "load"}
    fit = await fit_stock_unit(
        fields, BRICKS, catalog_query=_Catalog(per_stock_unit({"unit_amount": 1, "stock_amount": 300})),
        organization_id="org-1",
    )
    assert fit.kind == "ok"
    assert fields["quantity"] == 300 and fields["reported_quantity"] == 1


async def test_a_conversion_that_makes_a_fraction_of_bricks_is_asked_not_saved():
    fields = {"quantity": 1, "unit": "load"}
    fit = await fit_stock_unit(fields, BRICKS, catalog_query=_Catalog(Decimal(3)), organization_id="org-1")
    assert fit.kind == "mismatch" and fit.doubtful == Decimal("0.333")
    assert fields == {"quantity": 1, "unit": "load"}
    text = ask_amount_text(BRICKS, fields, fit, role="ADMIN")
    assert "can't be right" in text
    assert "How many nos is 1 load of Holobricks" in text


async def test_fractions_of_a_measured_unit_are_fine():
    fields = {"quantity": 10, "unit": "bags"}
    fit = await fit_stock_unit(fields, SAND, catalog_query=_Catalog(Decimal(28)), organization_id="org-1")
    assert fit.kind == "ok" and fields["quantity"] == 0.357


def test_the_question_is_asked_the_way_people_know_it():
    fit = UnitFit("mismatch", stock_unit=NOS, reported_unit=LOAD)
    text = ask_amount_text(BRICKS, {"quantity": 1, "unit": "load"}, fit, role="ADMIN")
    assert "How many nos is 1 load of Holobricks (or how many load make 1 nos)?" in text


# Request 178: "1 load" must be asked about before Save, never stored as "1 load".
TMT_NO_UNIT = {"id": "m-3", "name": "TMT Steel Bars", "default_unit_id": None}
TMT_IN_LOAD = {"id": "m-3", "name": "TMT Steel Bars", "default_unit_id": "u-load"}


async def test_a_load_of_a_material_with_no_stock_unit_is_asked_not_saved():
    for word in ("load", "loads", "vandi", "lorry", "trip", "pickup"):
        fit = await fit_stock_unit({"quantity": 1, "unit": word}, TMT_NO_UNIT, catalog_query=_Catalog(None), organization_id="o")
        assert fit.kind == "vague", word


async def test_a_material_the_company_counts_in_loads_takes_loads_as_they_are():
    fit = await fit_stock_unit({"quantity": 1, "unit": "load"}, TMT_IN_LOAD, catalog_query=_Catalog(None), organization_id="o")
    assert fit.kind == "ok"


async def test_measures_never_trigger_it():
    for word in ("bags", "kg", "tons", "nos", "cum"):
        fields = {"quantity": 5, "unit": word}
        fit = await fit_stock_unit(fields, TMT_NO_UNIT, catalog_query=_Catalog(None), organization_id="o")
        assert fit.kind == "ok", word


async def test_a_load_with_a_saved_size_still_converts_and_without_asks_the_old_way():
    sand = dict(SAND)
    fields = {"quantity": 5, "unit": "load"}
    fit = await fit_stock_unit(fields, sand, catalog_query=_Catalog(Decimal("0.5")), organization_id="o")
    assert fit.kind == "ok" and fields["quantity"] == 10
    fit = await fit_stock_unit({"quantity": 5, "unit": "load"}, sand, catalog_query=_Catalog(None), organization_id="o")
    assert fit.kind == "mismatch"
