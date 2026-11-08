"""DR-01..DR-03: the drawing reader (domains/drawings): title blocks, levels, rooms, fixtures and the checks.

Customer drawings are not kept in the repository (D-DR3): the PDF tests draw a small sheet with fpdf2 laid out like a
Kerala architect's set (the case found on the Kondotty commercial set: ROOM-1 drawn 1740 x 590 cm but labelled
1217 sq ft, which is ROOM-2's area). The rest works on word lists, the way ``pdf_text.pages`` returns them.
"""

from __future__ import annotations

import pytest

from mesiri.domains.drawings import checks, facts, pdf_text, reader
from mesiri.domains.drawings.read import read_pages


def w(text: str, x: float, top: float, size: float = 5.0, upright: bool = True) -> dict:
    """A word as pdf_text returns it: ~0.55 x size wide per letter."""
    return {"text": text, "x0": x, "x1": x + 0.55 * size * len(text), "top": top, "bottom": top + size,
            "size": size, "upright": upright}


def page(words: list[dict], n: int = 1) -> dict:
    return {"number": n, "width": 595, "height": 842, "words": words}


TITLE_BLOCK = [
    w("PROJECT:", 409, 692), w("COMMERCIAL@", 457, 705), w("KONDOTTY", 520, 705),
    w("DWG.TITLE:", 409, 715), w("KALEIDO", 284, 726), w("ARCHITECTS", 311, 726),
    w("GROUND", 469, 726, 7), w("FLOOR", 513, 726, 7), w("PLAN", 542, 726, 7),
    w("DRAWN:", 409, 740), w("CHECKED:", 479, 740), w("Ar:ABDULLAKUTY", 484, 746), w("PE", 556, 746),
    w("SUKHIL", 414, 749), w("BABU.", 445, 749), w("T", 471, 749),
    w("SCALE:", 408, 759), w("DATE:", 480, 759), w("1:100", 458, 771), w("18.05.2026", 530, 771),
    w("CLIENT:", 246, 782), w("ALL", 419, 787), w("DIMENSIONS", 436, 787), w("ARE", 487, 787), w("IN", 506, 787),
    w('CM"S', 516, 787), w("Mr.", 329, 793), w("ABDULLAKUTY", 342, 793),
]

ROOMS = [
    w("ROOM-1", 340, 296), w("1740", 338, 301.7), w("x", 349, 301.7), w("590", 353, 301.7),
    w("1217", 339, 307.2), w("Sq.ft", 350, 307.2),
    w("ROOM-2", 340, 421), w("1740", 338, 426.5), w("x", 349, 426.5), w("650", 353, 426.5),
    w("1217", 339, 432), w("Sq.ft", 350, 432),
    # Two toilets side by side: each label is its own, never "M. TOILET TOILET".
    w("M.", 230, 200), w("M.", 258, 200), w("TOILET", 225, 205), w("TOILET", 253, 205),
    w("120X150", 224, 210.5), w("120X150", 252, 210.5),
    # A urinal label drawn turned 90°, and overlapping letters that are not a room ("0 x 1").
    w("URINAL", 300, 150, upright=False), w("0", 120, 100), w("x", 123, 100), w("1", 126, 100), w("F", 121, 94),
]


def test_title_block_fields_by_label_and_shape():
    s = reader.sheet(page(TITLE_BLOCK))
    assert (s["title"], s["kind"], s["level"], s["discipline"]) == ("GROUND FLOOR PLAN", "plan", "Ground floor",
                                                                    "architectural")
    assert s["project"] == "COMMERCIAL@ KONDOTTY" and s["architect"] == "Kaleido Architects"
    # The client is under its label; the units note beside it is never the client.
    assert s["client"] == "Mr. ABDULLAKUTY"
    assert (s["drawn_by"], s["checked_by"]) == ("SUKHIL BABU. T", "Ar:ABDULLAKUTY PE")
    assert (s["scale"], s["date"], s["units"]) == ("1:100", "18.05.2026", "cm")
    assert s["number"] is None and s["revision"] is None  # not printed: None, never guessed


@pytest.mark.parametrize(("title", "kind", "level"), [
    ("BASEMENT FLOOR PLAN", "plan", "Basement"), ("FIRST FLOOR PLAN", "plan", "First floor"),
    ("TERRACE PLAN", "plan", "Terrace"), ("SECTION-A A", "section", None), ("BACK SIDE ELEVATION", "elevation", None),
    ("COLUMN SCHEDULE", "schedule", None), ("SITE PLAN", "site_plan", None), (None, None, None),
])
def test_kind_and_floor_from_the_title(title, kind, level):
    assert reader.kind_of(title) == kind and reader.level_of(title) == level


def test_levels_from_sections_and_elevations():
    words = [w("+1270", 86, 49), w("LVL", 100, 49), w("+1167.5", 86, 100), w("LVL", 104, 100), w("±0", 92, 340),
             w("LVL", 99, 340), w("-265", 88, 403), w("LVL", 100, 403), w("+1270", 600, 49), w("LVL", 614, 49),
             w("FFL", 300, 200), w("+450", 312, 200), w("+400LVL", 400, 250)]
    assert [lv["value"] for lv in facts.levels(words)] == [1270, 1167.5, 450, 400, 0, -265]


def test_rooms_sizes_areas_and_fixtures():
    rooms = facts.rooms(ROOMS)
    got = [(r["label"], r["size_text"], r["area"] and r["area"]["value"]) for r in rooms]
    assert got == [("M. TOILET", "120X150", None), ("M. TOILET", "120X150", None),
                   ("ROOM-1", "1740 x 590", 1217.0), ("ROOM-2", "1740 x 650", 1217.0)]
    assert facts.fixtures(ROOMS) == {"toilet": 2, "urinal": 1, "wash": 0, "lift": 0, "stair": 0}
    assert facts.area_of(1740, 590, "cm") == {"sqm": 102.66, "sqft": 1105.0}
    assert facts.area_of(17400, 5900, "mm")["sqm"] == 102.66


def test_the_kondotty_case_is_flagged_as_a_copied_area_label():
    result = read_pages([page(TITLE_BLOCK + ROOMS, 2)])
    high = [c for c in result["checks"] if c["severity"] == "high"]
    assert len(high) == 1 and high[0]["kind"] == "area_label" and high[0]["page"] == 2
    assert high[0]["message"] == ("ROOM-1 is drawn 1740 x 590 cm (103 m², 1,105 sq ft) but labelled 1,217 sq ft. "
                                  "1,217 sq ft is ROOM-2's area: the label looks copied.")
    # ROOM-2's label is right: not flagged.
    assert not any("ROOM-2 is drawn" in c["message"] for c in result["checks"])
    assert result["floors"] == ["Ground floor"] and result["fixtures"]["toilet"] == 2


def test_levels_drawn_two_ways_typical_floors_missing_fields_and_scans():
    sec = {"page": 8, "title": "SECTION-A A", "kind": "section", "has_text": True, "levels": [{"value": 1167.5}],
           "rooms": [], "scale": "1:50", "date": "18.05.2026"}
    ele = {"page": 4, "title": "FRONT ELEVATION", "kind": "elevation", "has_text": True,
           "levels": [{"value": 1170.0}, {"value": 0.0}], "rooms": [], "scale": "1:50", "date": None}
    gf = {"page": 2, "title": "GROUND FLOOR PLAN", "kind": "plan", "level": "Ground floor", "has_text": True,
          "levels": [], "scale": "1:100", "date": "x", "rooms": [{"label": "ROOM-1", "a": 1740, "b": 590,
                                                                  "size_text": "1740 x 590"}]}
    ff = {**gf, "page": 3, "title": "FIRST FLOOR PLAN", "level": "First floor",
          "rooms": [{"label": "ROOM-1", "a": 1740, "b": 650, "size_text": "1740 x 650"}]}
    scan = {"page": 10, "has_text": False, "levels": [], "rooms": []}
    found = checks.run([gf, ff, ele, sec, scan])
    kinds = [c["kind"] for c in found]
    assert kinds.count("level") == 1 and kinds.count("typical_floor") == 1 and "no_text" in kinds
    level = next(c for c in found if c["kind"] == "level")
    assert "+1170" in level["message"] and "+1167.5" in level["message"]
    assert any(c["message"] == "No date found on page 4." for c in found)
    assert any(c["message"] == "No sheet has a drawing number." for c in found)


def test_a_pdf_drawn_like_a_cad_export_is_read_end_to_end():
    from fpdf import FPDF

    pdf = FPDF(unit="pt", format="A4")
    pdf.add_page()
    pdf.set_font("Helvetica", size=6)
    for x, y, text in [
        (340, 300, "ROOM-1"), (334, 307, "1740 x 590"), (336, 314, "1217 Sq.ft"),
        (340, 420, "ROOM-2"), (334, 427, "1740 x 650"), (336, 434, "1217 Sq.ft"),
        (409, 700, "PROJECT:"), (457, 710, "COMMERCIAL @ KONDOTTY"), (409, 722, "DWG.TITLE:"),
        (284, 734, "KALEIDO ARCHITECTS"), (469, 734, "GROUND FLOOR PLAN"), (408, 760, "SCALE:"), (480, 760, "DATE:"),
        (458, 771, "1:100"), (530, 771, "18.05.2026"), (246, 782, "CLIENT:"), (419, 787, "ALL DIMENSIONS ARE IN CM"),
        (329, 794, "Mr. ABDULLAKUTY"),
    ]:
        pdf.text(x, y, text)
    with pdf.rotation(90, x=300, y=180):
        pdf.text(300, 180, "URINAL")
    pdf.add_page()  # an empty page: no text, like a scan
    pages = pdf_text.pages(bytes(pdf.output()))
    assert [p["number"] for p in pages] == [1, 2] and pages[1]["words"] == []
    result = read_pages(pages)
    sheet = result["sheets"][0]
    assert (sheet["title"], sheet["client"], sheet["scale"], sheet["units"]) == (
        "GROUND FLOOR PLAN", "Mr. ABDULLAKUTY", "1:100", "cm")
    assert [(r["label"], r["size_text"]) for r in sheet["rooms"]] == [("ROOM-1", "1740 x 590"), ("ROOM-2", "1740 x 650")]
    assert result["fixtures"]["urinal"] == 1  # the turned label
    assert result["checks"][0]["kind"] == "area_label" and "ROOM-1 is drawn" in result["checks"][0]["message"]
    assert any(c["kind"] == "no_text" and c["page"] == 2 for c in result["checks"])


def test_not_a_pdf_and_page_rotation():
    with pytest.raises(pdf_text.NotAPdf):
        pdf_text.pages(b"not a pdf")
    # A character at the PDF's bottom-left on a page stored turned 90°: shown at the top-left.
    assert pdf_text._shown(90, 842, 595, (0, 0, 10, 5)) == (0, 5, 0, 10)
    assert pdf_text._shown(0, 595, 842, (10, 832, 20, 842)) == (10, 20, 0, 10)
    assert pdf_text.turned("LANIRU") == "URINAL" and pdf_text.turned("URINAL") == "URINAL"


# -- DR-05 / DR-06: drafts --------------------------------------------------------------------------------------------

def _read_like_kondotty() -> dict:
    room = lambda label, a, b: {"label": label, "a": a, "b": b, "size_text": f"{a} x {b}"}  # noqa: E731
    plan = lambda page, level, rooms, fx: {"page": page, "kind": "plan", "level": level, "title": f"{level} plan",  # noqa: E731
                                           "rooms": rooms, "fixtures": fx}
    return {
        "units": "cm",
        "floors": ["Basement", "Ground floor", "First floor"],
        "levels": [{"value": v} for v in (1270, 1167.5, 855, 805, 450, 400, 45, 0, -5, -265)],
        "sheets": [
            plan(2, "Ground floor", [room("ROOM-1", 1740, 590), room("LIFT", 180, 240)],
                 {"toilet": 4, "urinal": 0, "wash": 0}),
            plan(1, "Basement", [room("M. TOILET", 120, 150)], {"toilet": 4, "urinal": 3, "wash": 1}),
        ],
    }


def test_draft_schedule_goes_up_floor_by_floor_then_finishes():
    from mesiri.domains.drawings import drafts

    acts = [a["name"] for a in drafts.schedule(_read_like_kondotty())]
    assert acts[:3] == ["Site clearing and setting out", "Excavation", "Basement retaining wall"]
    assert acts.index("Basement: slab and beams") < acts.index("Ground floor: columns") < acts.index(
        "First floor: slab and beams") < acts.index("Basement: masonry")
    assert acts[-1] == "Handover" and drafts.schedule({"floors": []})[2]["name"] == "Footings and columns up to plinth"


def test_draft_boq_from_rooms_with_the_clear_height_from_the_levels():
    from mesiri.domains.drawings import drafts

    b = drafts.boq(_read_like_kondotty())
    assert b["clear_height_m"] == 3.9 and "4.05 m" in b["height_note"]  # -5 to +400, less a 15 cm slab
    assert [s["name"] for s in b["sections"]] == ["Basement", "Ground floor"]
    ground = {ln["work"]: ln for ln in b["sections"][1]["lines"]}
    assert ground["Flooring (vitrified tiles)"]["quantity"] == 102.66  # ROOM-1 only: the lift gets no flooring
    assert ground["Skirting"]["quantity"] == 46.6  # 2 × (17.40 + 5.90)
    assert ground["Wall plaster 12 mm (inside)"]["quantity"] == round(46.6 * 3.9, 2)
    assert ground["WC with fittings"]["quantity"] == 4 and "Urinal with fittings" not in ground
    assert drafts.clear_height_m({"levels": [], "units": "cm"})[0] == drafts.DEFAULT_CLEAR_M


def test_a_note_mentioning_a_toilet_is_not_a_toilet_but_labels_side_by_side_count():
    note = [w("Toilet", 10, 400), w("sinking", 32, 400), w("5", 55, 400), w("cm's", 60, 400)]
    labels = [w("TOILET", 10, 200), w("TOILET", 38, 200), w("FIRE", 80, 200), w("STAIR", 95, 200)]
    assert facts.fixtures(note) == {"toilet": 0, "urinal": 0, "wash": 0, "lift": 0, "stair": 0}
    assert facts.fixtures(labels)["toilet"] == 2 and facts.fixtures(labels)["stair"] == 1


def test_a_floor_whose_big_areas_have_no_size_is_warned_not_guessed():
    from mesiri.domains.drawings import drafts

    b = drafts.boq(_read_like_kondotty())
    basement, ground = b["sections"]
    assert basement["area_sqm"] == 1.8 and "not included" in basement["warning"]
    assert ground["warning"] is None
