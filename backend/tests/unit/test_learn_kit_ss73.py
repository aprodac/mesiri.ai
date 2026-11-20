"""SS-73: the playground's starter kit is what its missions say it is (docs/plans/guided-demo-plan.md section 16.2).

Read through Mesiri's own importers, so a change to an importer or to the sample story that breaks a mission fails
here. Imported on 17 Nov into a sandbox on Postgres through the real routes: 34 lines in 9 sections, 3 without a
budget, the staircase at a loss, 6 lines with materials; 21 of 24 site works suggested a line (the three Plastering
ones ask, on purpose); the materials preview "already in Mesiri" for Cement, Malabar and Joy Tiling.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import zipfile

import pytest

from mesiri.application.organizations import sample_story
from mesiri.domains.materials.defaults import STARTER_MATERIALS
from mesiri.domains.materials.importer import read_workbook
from mesiri.domains.progress.boq_import import read_sheet

ROOT = pathlib.Path(__file__).resolve().parents[3]
KIT = ROOT / "apps" / "dashboard" / "public" / "learn" / "kit"


@pytest.fixture(scope="module")
def make_kit():
    spec = importlib.util.spec_from_file_location("make_kit", ROOT / "scripts" / "learn_kit" / "make_kit.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_checked_in_kit_is_the_scripts(make_kit) -> None:
    """The list of files is the script's (bytes can differ by library version, so contents are checked below)."""
    built = make_kit.build()
    assert built["kit.json"] == make_kit.build()["kit.json"]  # fixed: no dates, no randomness
    assert (KIT / "kit.json").read_bytes() == built["kit.json"], "stale kit: run python scripts/learn_kit/make_kit.py"
    assert sorted(p.name for p in KIT.iterdir()) == sorted(built)


def test_the_estimate_reads_with_its_catches(make_kit) -> None:
    sheet = read_sheet((KIT / make_kit.ESTIMATE).read_bytes())
    lines = [r for r in sheet.rows if not r.heading]
    headings = [r for r in sheet.rows if r.heading]
    assert len(headings) == 9 and len(lines) == 34
    no_budget = [r.work for r in lines if not r.rates.get("labour_rate") and not r.rates.get("material_rate")]
    assert no_budget == ["Vitrified tile flooring", "Bathroom wall tiling", "Granite kitchen counter"]
    loss = [r.work for r in lines if r.rates.get("labour_rate") and
            float(r.rates["labour_rate"]) + float(r.rates.get("material_rate") or 0) > float(r.rates["client_rate"])]
    assert loss == ["Staircase waist slab"]
    assert len(sheet.norms) == len(make_kit.NORMS)


def test_every_work_the_sample_site_reports_has_its_line(make_kit) -> None:
    """Green Villa's sites are the first two of the story's four; their work must count on the estimate's lines."""
    reported = {(work, unit) for site in sample_story.DEMO_WORK[:2] for work, _n, unit, _q in site}
    assert reported == set(make_kit.SITE_WORK)
    lines = {(work, unit) for _h, rows in make_kit.SECTIONS for _c, work, unit, *_ in rows}
    assert reported <= lines
    plastering = [work for work, _unit in lines if "plastering" in work.lower()]
    assert len(plastering) == 3  # the catch: the site's plastering could be any of three


def test_materials_per_unit_name_lines_and_catalogue_materials(make_kit) -> None:
    lines = {(code, work) for _h, rows in make_kit.SECTIONS for code, work, *_ in rows}
    catalogue = {m.name: m.unit_code for m in STARTER_MATERIALS}
    for code, work, material, _per, unit in make_kit.NORMS:
        assert (code, work) in lines and catalogue.get(material) == unit


def test_the_materials_workbook_reads_and_has_no_phone_or_gstin(make_kit) -> None:
    rows = read_workbook((KIT / make_kit.MATERIALS).read_bytes())
    by_sheet: dict[str, int] = {}
    for row in rows:
        by_sheet[row.sheet] = by_sheet.get(row.sheet, 0) + 1
        assert not row.values.get("Phone") and not row.values.get("GSTIN")
    assert by_sheet == {"Items": 7, "Vendors": 4, "Opening stock": 2, "Minimum stock": 2}
    assert all(r.values.get("Quantity") for r in rows if r.sheet == "Opening stock")


def test_the_contract_says_the_estimates_total(make_kit) -> None:
    total = sum(q * r for _h, rows in make_kit.SECTIONS for _c, _w, _u, q, r, *_ in rows)
    assert make_kit._rupees(total) == "Rs 82,06,050"
    assert b"%PDF" in (KIT / make_kit.CONTRACT).read_bytes()[:8]


def test_the_manifest_and_the_zip_hold_every_file(make_kit) -> None:
    manifest = json.loads((KIT / "kit.json").read_text())
    files = [f["file"] for f in manifest["files"]]
    assert all((KIT / name).exists() for name in files)
    files += [extra for f in manifest["files"] for extra in f.get("also", [])]
    assert all((KIT / name).exists() for name in files)
    with zipfile.ZipFile(KIT / manifest["zip"]) as z:
        assert sorted(pathlib.PurePath(n).name for n in z.namelist()) == sorted(files)
    assert all(f["what"] and f["goes"] and f["catch"] and f["page"].startswith("/") for f in manifest["files"])


# SS-73 part 2: each document's catch, through the rule that shows it.


def _text(path: pathlib.Path) -> str:
    from mesiri.domains.drawings.pdf_text import pages

    return " ".join(w["text"] for p in pages(path.read_bytes()) for w in p["words"])


def test_drawing_check_finds_the_copied_bedroom_label_and_nothing_else(make_kit) -> None:
    from mesiri.domains.drawings.read import read_pdf

    out = read_pdf((KIT / make_kit.PLAN).read_bytes())
    sheet = out["sheets"][0]
    assert (sheet["title"], sheet["number"], sheet["scale"], sheet["units"]) == ("GROUND FLOOR PLAN", "A-101", "1:100", "cm")
    assert len(sheet["rooms"]) == len(make_kit.ROOMS)
    assert [c["message"] for c in out["checks"]] == [
        "BEDROOM-2 is drawn 360 x 360 cm (13 m², 140 sq ft) but labelled 163 sq ft. "
        "163 sq ft is BEDROOM-1's area: the label looks copied."]


def test_the_quotes_cheapest_cement_is_not_the_cheapest_total(make_kit) -> None:
    rates = make_kit.QUOTE_RATES
    qty = [q for _i, _u, q in make_kit.RFQ_ITEMS]
    totals = {v: sum(q * r for q, r in zip(qty, rs, strict=True)) for v, rs in rates.items()}
    cheapest_cement = min(rates, key=lambda v: rates[v][0])
    cheapest_total = min(totals, key=totals.get)
    split = sum(q * min(rs[i] for rs in rates.values()) for i, q in enumerate(qty))
    assert (cheapest_cement, cheapest_total) == ("Malabar Cements Agency", "Kerala Steels")
    assert split < totals[cheapest_total]  # lowest per line beats lowest total
    for name, vendor in zip(make_kit.QUOTES, rates, strict=True):
        assert vendor.split()[0] in _text(KIT / name)


def test_the_challan_brings_less_than_ordered_and_the_bill_is_dearer(make_kit) -> None:
    from decimal import Decimal

    from mesiri.domains.vendors.matching import flags

    challan = _text(KIT / make_kit.CHALLAN)
    assert f"{make_kit.ORDERED}" in challan and f"{make_kit.DELIVERED}" in challan
    bill = _text(KIT / make_kit.BILL)
    assert f"{make_kit.BILL_RATE}" in bill
    order_rate = make_kit.QUOTE_RATES["Malabar Cements Agency"][0]  # the order is placed at Malabar's quote
    assert flags(Decimal(make_kit.DELIVERED), Decimal(make_kit.DELIVERED), Decimal(order_rate), Decimal(make_kit.BILL_RATE),
                 "bags") == ["rate ₹410 on the bill, ₹400 on site"]


def test_joy_tiling_bills_more_than_was_measured(make_kit) -> None:
    from decimal import Decimal

    from mesiri.domains.subcontracts.rules import check_bill

    rows, measured = make_kit._tiled_rows()
    assert measured == 81.94 and f"{measured:.2f}" in _text(KIT / make_kit.MEASURE)
    assert f"{make_kit.TILING_BILLED:.2f}" in _text(KIT / make_kit.SUB_BILL)
    line = {"description": "Vitrified tile flooring", "unit": "sqm", "quantity": Decimal(290), "rate": Decimal(make_kit.TILING_RATE)}
    found = check_bill({"l": line}, {"l": Decimal(str(measured))}, {}, [{"line_id": "l", "quantity": make_kit.TILING_BILLED,
                                                                        "rate": make_kit.TILING_RATE}],
                       Decimal(str(make_kit.TILING_BILLED * make_kit.TILING_RATE)))
    assert [f["code"] for f in found] == ["over_measured"] and "10.06 sqm more than measured" in found[0]["words"]


def test_the_drawing_set_reads_with_exactly_its_three_catches(make_kit) -> None:
    """LRN-F5: the eight-sheet set reads through Drawing check with the catches the kit says, and no others: the copied
    bedroom label (A-101), the roof at +660 on the elevation and +655 on the section, and the first-floor toilet drawn
    smaller than the one below it. Its footings are counted (6) for Track and the draft BOQ."""
    from mesiri.application.learn import green_villa
    from mesiri.domains.drawings.read import read_pdf

    out = read_pdf((KIT / make_kit.DRAWING_SET).read_bytes())
    assert [s["number"] for s in out["sheets"]] == [n for n, _t, _k in green_villa.DRAWINGS]
    kinds = {c["kind"]: c["message"] for c in out["checks"]}
    assert set(kinds) == {"area_label", "level", "typical_floor"}
    assert "+660" in kinds["level"] and "+655" in kinds["level"]
    assert "TOILET" in kinds["typical_floor"]
    assert out["architect"] == green_villa.ARCHITECT.split(",")[0]
    assert out["structure"]["foundation"]["footings"] == sum(len(f[5]) for f in green_villa.FOOTINGS) == 6


def test_the_papers_agree_with_the_story(make_kit) -> None:
    """The rate card is the seed's supply rates, and its catch is the seed's later M sand rate; the return comes off
    the kit's own challan; the hire bill is above the hours logged; the handover is the contract's date."""
    from mesiri.application.learn import green_villa as gv

    for material, _unit, rate in gv.RATE_CARD["rates"]:
        vendor, _size, seeded = sample_story.DEMO_SUPPLY[material]
        assert (vendor, seeded) == (gv.RATE_CARD["vendor"], rate)
    assert sample_story.DEMO_RATE_NOW[(None, "m sand")][0] > dict((m, r) for m, _u, r in gv.RATE_CARD["rates"])["m sand"]
    assert gv.RETURN["quantity"] <= make_kit.DELIVERED and gv.RETURN["against"] == "MCA/DC/2611"
    assert gv.HIRE["billed_hours"] > gv.HIRE["logged_hours"]
    assert gv.HANDOVER["date"] == "31 July 2027" and gv.CONTRACT["handover_on"] == "2027-07-31"
    files = {f["file"] for f in json.loads((KIT / "kit.json").read_text())["files"]}
    assert {make_kit.DRAWING_SET, make_kit.PERMIT, make_kit.RATE_CARD, make_kit.RETURN_NOTE, make_kit.HIRE_BILL,
            make_kit.HANDOVER} <= files
