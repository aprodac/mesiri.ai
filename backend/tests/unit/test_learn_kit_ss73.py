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


def test_the_checked_in_files_are_what_the_script_makes(make_kit) -> None:
    built = make_kit.build()
    assert built == make_kit.build()  # fixed: no dates, no randomness
    for name, data in built.items():
        assert (KIT / name).read_bytes() == data, f"{name} is stale: run python scripts/learn_kit/make_kit.py"


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
    with zipfile.ZipFile(KIT / manifest["zip"]) as z:
        assert sorted(pathlib.PurePath(n).name for n in z.namelist()) == sorted(files)
    assert all(f["what"] and f["goes"] and f["catch"] and f["page"].startswith("/") for f in manifest["files"])
