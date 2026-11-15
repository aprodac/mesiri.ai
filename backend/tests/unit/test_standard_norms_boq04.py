"""BOQ-04: the usual materials per unit offered for common BOQ work, in the company's own materials and units."""

from __future__ import annotations

from decimal import Decimal as D

from mesiri.domains.progress.standard_norms import standard_for, suggest

CATALOGUE = [
    {"id": "cem", "name": "Cement", "unit": "bags"},
    {"id": "msand", "name": "M Sand", "unit": "cum"},
    {"id": "psand", "name": "P Sand", "unit": "cft"},
    {"id": "agg20", "name": "Aggregate 20mm", "unit": "cum"},
    {"id": "agg40", "name": "Aggregate 40mm", "unit": "cum"},
    {"id": "brick", "name": "Bricks", "unit": "nos"},
    {"id": "steel", "name": "TMT steel bars", "unit": "mt"},
    {"id": "wire", "name": "Binding Wire", "unit": "kg"},
]


def _by(out):
    return {n["material_id"]: n["quantity_per_unit"] for n in out["norms"]}


def test_m20_per_cum_is_the_nominal_mix():
    out = suggest("M20 RCC for first floor slab", "cum", CATALOGUE)
    assert out["standard"].startswith("M20")
    assert _by(out) == {"cem": D("8.06"), "msand": D("0.42"), "agg20": D("0.84")}
    assert all(n["note"].startswith("Standard: ") for n in out["norms"])


def test_the_mix_written_as_a_ratio_and_pcc():
    assert standard_for("PCC 1:4:8 below footing", "cum").name.startswith("PCC 1:4:8")
    assert standard_for("Concrete 1:2:4", "cum").name.startswith("M15")


def test_plaster_in_sqft_uses_plaster_sand_in_its_own_unit():
    out = suggest("Internal plastering 12 mm thick in CM 1:4", "sqft", CATALOGUE)
    q = _by(out)
    assert q["cem"] == D("0.0084")  # 0.09 bags a m², per sqft
    assert "psand" in q and q["psand"] == D("0.0410")  # 0.0125 m³ a m² -> cft a sqft
    assert "msand" not in q


def test_brickwork_and_steel():
    bricks = _by(suggest("Brick masonry in CM 1:6", "cum", CATALOGUE))
    assert bricks["brick"] == D("500") and bricks["cem"] == D("1.32")
    steel = _by(suggest("Reinforcement steel Fe500", "kg", CATALOGUE))
    assert steel["steel"] == D("0.0010") and steel["wire"] == D("0.0080")  # 1 kg a kg in tonnes; 8 kg wire a tonne


def test_never_a_guess_plain_rcc_a_high_grade_another_unit_or_unknown_work():
    assert standard_for("RCC slab", "cum") is None
    assert standard_for("M30 concrete", "cum") is None
    assert standard_for("M20 concrete", "sqft") is None
    assert standard_for("Anti termite treatment", "sqm") is None


def test_a_material_the_company_lacks_or_buys_in_another_unit_is_said_missing():
    out = suggest("M20 concrete", "cum", [{"id": "cem", "name": "Cement", "unit": "bags"},
                                           {"id": "s", "name": "Sand", "unit": "load"}])
    assert [n["material_id"] for n in out["norms"]] == ["cem"]
    assert set(out["missing"]) == {"sand", "aggregate 20"}
