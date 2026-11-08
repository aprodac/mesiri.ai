"""DR-09: a structural set's schedules, the foundation's quantities and the checks between sheets.

Laid out like a Kerala structural consultant's GFC set (the case it was built on: a B+G+2 commercial building whose
combined footing detail names both its columns C5 while the footing plan shows C5 and C6). Customer drawings are not
kept in the repository (D-DR3): these are word lists as ``pdf_text.pages`` returns them, names made up.
"""

from __future__ import annotations

import pytest

from mesiri.domains.drawings import reader, structure
from mesiri.domains.drawings.read import read_pages


def w(text: str, x: float, top: float, size: float = 5.0) -> dict:
    return {"text": text, "x0": x, "x1": x + 0.55 * size * len(text), "top": top, "bottom": top + size,
            "size": size, "upright": True}


def row(texts: str, x: float, top: float, gap: float = 4.0) -> list[dict]:
    """Words of one line, left to right."""
    out, at = [], x
    for t in texts.split():
        out.append(w(t, at, top))
        at += 0.55 * 5 * len(t) + gap
    return out


def page(n: int, words: list[dict]) -> dict:
    return {"number": n, "width": 595, "height": 842, "words": words}


TITLE = (row("DRAWING TITLE", 180, 744) + row("PROPOSED", 330, 744) + row("ARCHITECT", 580, 744)
         + row("REMARKS", 50, 744))


def title_block(title: str, number: str) -> list[dict]:
    return (TITLE + row(title, 190, 754) + row("OFFICE BUILDING AT TIRUR", 340, 754)
            + row("NOVA", 596, 752) + [w("ARCHITECTS", 596, 758, 4)]
            + row(f"PROJECT NO : 12 / 2026 DWG NO :{number} Mob :+91 900 00 000 00", 440, 770)
            + row("OWNER : Mr. Example", 440, 780)
            + row("PREPARED : AB CHECKED : AB DRAWN : CD Calicut,Kerala", 440, 790)
            + row("3. Alignments, measurements and levels should be checked and confirmed before work.", 180, 800)
            + row("Grade of Concrete: M20", 50, 770) + row("Grade of Steel: Fe 500", 50, 790))


# Footing plan: F1 under C1 twice, F2 under C2 once, F6 (combined) under C5 and C6, and their column marks.
PLAN = page(1, [
    w("F1-250X250", 100, 100), w("C1", 112, 110), w("F1-250X250", 300, 100), w("C1", 312, 110),
    w("F2-220X220", 100, 300), w("C2", 112, 310),
    w("F6-220X350", 260, 200), w("C5", 262, 212), w("C6", 300, 214),
    *row("KEY PLAN - FOOTING & COLUMN", 200, 600, 6), *title_block("FOOTING & COLUMN DETAILS", "12/ST/01/01"),
])

SCHEDULE = page(2, [
    *row("1.CLEAR COVER", 50, 60), *row("- Footing - 50 mm, side - 75 mm", 50, 66), *row("- Column - 40 mm", 50, 72),
    *row("2) Off set for P.C.C : 10 cm (on each side)", 280, 60), *row("5) SBC is taken as 25T", 280, 70),
    *row("7) The structural design is done for B+G+2 (4 floors)", 280, 80), *row("P.C.C 1:4:8", 500, 90),
    *row("1 F1 250X250 70 20 16 nos. 16 dia bars 16 nos. 16 dia bars", 90, 200),
    *row("2 F2 220X220 60 20 12 nos. 16 dia bars 12 nos. 16 dia bars", 90, 210),
    *row("3 F9 100X100 40 15 6 nos. 12 dia bars 6 nos. 12 dia bars", 90, 220),
    # The combined footing: its plan, then its section with the columns, bars and depth.
    *row("F6 COMBINED FOOTING PLAN", 230, 400), *row("73 203 73", 200, 430), w("C5-20X60", 220, 440),
    w("C5-20X60", 330, 440), w("50", 420, 450), *row("PCC 10", 150, 470), *row("22 nos-12 dia", 260, 480),
    *row("14 nos-16 dia", 260, 488), w("350", 300, 500), *row("F6 COMBINED FOOTING SECTION X - X", 220, 520),
    *title_block("FOOTING DETAILS", "12/ST/01/02"),
])

COLUMNS = page(3, [
    *row("COLUMN - C1", 100, 50), *row("COLUMN - C2", 300, 50),
    w("40", 110, 80), w("40", 90, 100), w("1", 140, 90), w("30", 310, 80), w("50", 290, 100), w("2", 330, 90),
    *row("REINF: 4 T25+8 T20", 90, 200), *row("REINF: 10 T20", 290, 200),
    *row("TIES: T8 @ 20 CM C/C", 90, 210), *row("TIES: T8 @ 18 CM C/C", 290, 210),
    *row("COLUMN - C5", 100, 300), *row("COLUMN - C6", 300, 300),
    w("20", 110, 320), w("60", 90, 340), w("20", 310, 320), w("60", 290, 340),
    *row("REINF: 8 T20+2 T16", 90, 420), *row("REINF: 12 T16", 290, 420),
    *row("TIES: T8 @ 18 CM C/C", 90, 430), *row("TIES: T8 @ 18 CM C/C", 290, 430),
    *title_block("COLUMN DETAILS", "12/ST/01/03"),
])

SLABS = page(4, [
    *row("KEY PLAN - FIRST FLOOR", 200, 500, 6),
    *row("S1 ONE WAY 12cm 10 @ 16 cm C/C 8 @ 20 cm C/C", 100, 560),
    *row("S2 DOUBLE MESH 15cm 8 @ 22 cm C/C 8 @ 22 cm C/C", 100, 570),
    *row("BEAM Z4", 400, 200), *row("20X40", 400, 206),
    *title_block("FIRST FLOOR DETAILS", "12/ST/04/01"),
])

SET = [PLAN, SCHEDULE, COLUMNS, SLABS]


def test_title_block_of_a_structural_sheet():
    s = reader.sheet(SCHEDULE)
    assert s["number"] == "12/ST/01/02"  # never "... Mob :+91 ..."
    assert (s["title"], s["discipline"]) == ("FOOTING DETAILS", "structural")
    assert s["project"].startswith("OFFICE BUILDING")  # under PROPOSED, never "NO : 12 / 2026"
    assert (s["drawn_by"], s["checked_by"]) == ("CD", "AB")  # not the address, not the note's "checked"
    assert s["architect"] == "Nova Architects"  # the name above "ARCHITECTS", never the labels' row
    first = reader.sheet(SLABS)
    assert (first["kind"], first["level"]) == ("plan", "First floor")


def test_schedules_are_read():
    sched = structure.footing_schedule(SET)
    assert sched["F1"] == {"mark": "F1", "a": 250, "b": 250, "d": 70, "c": 20, "main": {"nos": 16, "dia": 16},
                           "dist": {"nos": 16, "dia": 16}, "page": 2}
    cols = structure.column_schedule(SET)
    assert cols["C1"]["size"] == [40, 40] and cols["C2"]["size"] == [30, 50] and cols["C6"]["size"] == [20, 60]
    assert cols["C1"]["bars"] == [{"nos": 4, "dia": 25}, {"nos": 8, "dia": 20}]
    assert cols["C2"]["ties"] == {"dia": 8, "spacing_cm": 18}
    notes = structure.notes(SET)
    assert notes == {"concrete": "M20", "steel": "Fe 500", "sbc_t_per_sqm": 25, "designed_for": "B+G+2",
                     "cover_footing_mm": 50.0, "cover_column_mm": 40.0, "pcc_offset_cm": 10.0, "pcc_mix": "1:4:8"}


def test_foundation_quantities():
    t = structure.takeoff(SET, [reader.sheet(p) for p in SET])
    by = {f["mark"]: f for f in t["footings"]}
    assert (by["F1"]["count"], by["F2"]["count"], by["F6"]["count"]) == (2, 1, 1)
    # F1 under C1 (40x40): base 2.5×2.5×0.2 + frustum 0.5/3 × (6.25 + 0.36 + √(6.25×0.36)) = 2.6017 m³ each.
    assert by["F1"]["concrete_cum"] == pytest.approx(2 * 2.6017, abs=0.01)
    # Bars: 250 − 2×5 + 2×(20 − 10) = 260 cm; 16 nos each way of 16 mm (1.580 kg/m), two footings.
    assert by["F1"]["steel_kg"] == pytest.approx(2 * 2 * 16 * 2.60 * 16 * 16 / 162, abs=0.2)
    # The combined footing: 350×220×50 block; the 22 bars run the short way, the 14 the long way.
    assert (by["F6"]["depth_cm"], by["F6"]["concrete_cum"]) == (50, 3.85)
    assert by["F6"]["steel_kg"] == pytest.approx(22 * 2.10 * 144 / 162 + 14 * 3.40 * 256 / 162, abs=0.2)
    f = t["foundation"]
    assert f["footings"] == 4 and set(f["steel_by_dia"]) == {"12 mm", "16 mm"}
    assert f["pcc_cum"] == pytest.approx(2 * 0.729 + 0.576 + 0.888, abs=0.01)  # (A + 20) × (B + 20) × 10 cm
    assert f["cement_bags"] == pytest.approx(8 * f["concrete_cum"] + 3.4 * f["pcc_cum"], abs=1)
    c1 = next(c for c in t["columns"] if c["mark"] == "C1")
    assert c1["count_on_plan"] == 2 and c1["kg_per_m"] == pytest.approx(4 * 625 / 162 + 8 * 400 / 162 + 5 * 1.472 * 64 / 162, abs=0.1)  # 5 ties of 1.47 m a metre
    s1 = next(s for s in t["slabs"] if s["mark"] == "S1")
    assert (s1["floor"], s1["thickness_cm"]) == ("First floor", 12)
    assert s1["steel_kg_per_sqm"] == pytest.approx(100 / 16 * 100 / 162 + 100 / 20 * 64 / 162, abs=0.01)


def test_checks_between_the_sheets():
    t = structure.takeoff(SET, [reader.sheet(p) for p in SET])
    msgs = [c["message"] for c in t["checks"]]
    assert "F6 combined footing: the detail names its columns C5 and C5, the footing plan shows C5 and C6." in msgs
    assert "F9 in the footing schedule but not on the footing plan." in msgs
    assert not any("F6 is on the footing plan but not in the footing schedule" in m for m in msgs)  # it has a detail


def test_the_whole_read_of_a_structural_set():
    r = read_pages(SET)
    assert r["structure"]["foundation"]["footings"] == 4
    assert r["floors"] == ["First floor"]  # the footing plan is not a floor
    assert all(s["rooms"] == [] for s in r["sheets"])  # "BEAM Z4 20X40" is a beam, not a room
    assert r["checks"][0]["kind"] == "structure"  # the serious one first
    found = r["draft_boq"]["sections"][0]
    assert found["name"] == "Foundation"
    assert [ln["unit"] for ln in found["lines"]] == ["cum", "cum", "kg"]


def test_an_architectural_set_has_no_structure():
    arch = page(1, [*row("GROUND FLOOR PLAN", 200, 600, 6), *row("ROOM-1", 100, 100), *row("400 x 300", 98, 106)])
    assert read_pages([arch])["structure"] is None


def test_a_mix_ratio_is_never_a_scale():
    assert reader.sheet(SCHEDULE)["scale"] is None  # "P.C.C 1:4:8" on the sheet
    assert reader.sheet(page(9, row("SCALE : 1:100", 400, 700)))["scale"] == "1:100"
