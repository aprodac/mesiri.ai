"""CC-01: a period's full cost split into cost centres (domains/costing/centres.split). Pure."""

from __future__ import annotations

from decimal import Decimal

from mesiri.domains.costing.centres import CENTRES, split


def _costs(materials="0", labour="0", hire="0", fuel="0", expenses="0") -> dict:
    total = sum(Decimal(x) for x in (materials, labour, hire, fuel, expenses))
    return {
        "total": str(total.quantize(Decimal("0.01"))),
        "materials": {"amount": materials, "deliveries": 2, "unpriced": 1},
        "labour": {"amount": labour, "man_days": "12", "priced_man_days": "10"},
        "machines": {"amount": str(Decimal(hire) + Decimal(fuel)), "hire": hire, "fuel": fuel},
    }


def _row(category, centre, amount, bill=False):
    return {"category_id": category, "category": category, "cost_centre": centre, "subcontract_bill": bill,
            "n": 1, "amount": Decimal(amount)}


def _amount(out, key):
    return Decimal(next(c["amount"] for c in out["centres"] if c["key"] == key))


def test_each_source_lands_in_its_centre_and_the_parts_add_up():
    out = split(_costs(materials="5000", labour="6400", hire="1100", fuel="900", expenses="2300"),
                [_row("Materials", "materials", "2000"), _row("Tea", None, "300")])
    assert _amount(out, "materials") == 7000 and _amount(out, "labour") == 6400
    assert _amount(out, "equipment") == 1100 and _amount(out, "fuel") == 900
    assert Decimal(out["not_set"]["amount"]) == 300
    assert sum((Decimal(c["amount"]) for c in out["centres"]), Decimal(out["not_set"]["amount"])) == Decimal(out["total"])
    assert [c["key"] for c in out["centres"]] == list(CENTRES)


def test_a_subcontract_bill_is_subcontract_whatever_its_category():
    out = split(_costs(expenses="15000"), [_row("Labour", "labour", "15000", bill=True)])
    assert _amount(out, "subcontract") == 15000 and _amount(out, "labour") == 0
    assert out["centres"][2]["parts"][0]["source"] == "Subcontract bills"


def test_unpriced_deliveries_and_unwaged_days_are_passed_on_to_be_said():
    out = split(_costs(), [])
    assert out["unpriced_deliveries"] == 1 and out["man_days"] == "12" and out["priced_man_days"] == "10"
