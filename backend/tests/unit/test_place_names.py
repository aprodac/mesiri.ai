"""LP-02: places in words -> the place (domains/places/names.py), and the progress roll-up (LP-03)."""

from __future__ import annotations

import datetime
import uuid

import pytest

from mesiri.domains.places import names, progress


def _tree() -> list[names.Place]:
    out: list[names.Place] = []
    for floor in ("Basement", "Ground Floor", "First Floor", "Second Floor", "Terrace"):
        f = names.Place(uuid.uuid4(), floor, None, "Floor")
        out.append(f)
        for room in ("Room-1", "Room-2", "Kitchen", "Bedroom", "Bedroom 2", "Toilet"):
            out.append(names.Place(uuid.uuid4(), room, f.id, "Room"))
    return out


TREE = _tree()
BY_ID = {p.id: p for p in TREE}


def _said(words: str) -> str | None:
    m = names.resolve(words, TREE)
    return names.label(m.place, BY_ID) if m.place else None


@pytest.mark.parametrize("words, place", [
    ("first floor Room-2", "First Floor / Room-2"),
    ("FF R2", "First Floor / Room-2"),
    ("1st floor rm 2", "First Floor / Room-2"),
    ("floor 1 room 2", "First Floor / Room-2"),
    ("L1 room2", "First Floor / Room-2"),
    ("onnam nila kitchen", "First Floor / Kitchen"),
    ("randam nilayil bedroom 2", "Second Floor / Bedroom 2"),
    ("GF toilet", "Ground Floor / Toilet"),
    ("thazhe kitchen", "Ground Floor / Kitchen"),
    ("ground floor bedroom", "Ground Floor / Bedroom"),  # "Bedroom", not "Bedroom 2"
    ("basement room 1", "Basement / Room-1"),
    ("second floor", "Second Floor"),
    ("terrace", "Terrace"),
    ("First Floor / Room-2", "First Floor / Room-2"),
])
def test_words_name_the_place(words, place):
    assert _said(words) == place


def test_a_room_on_every_floor_asks_which():
    m = names.resolve("kitchen", TREE)
    assert m.place is None and m.reason == "several" and len(m.options) == 5


def test_a_floor_not_there_offers_the_floors():
    m = names.resolve("fifth floor", TREE)
    assert m.place is None and m.reason == "no_such_floor" and len(m.options) == 5


def test_nothing_like_a_place():
    assert names.resolve("cement 20 bags", TREE).reason == "not_found"


def test_a_room_only_on_one_floor_needs_no_floor():
    f = names.Place(uuid.uuid4(), "Ground Floor", None)
    tree = [f, names.Place(uuid.uuid4(), "Pooja Room", f.id), names.Place(uuid.uuid4(), "First Floor", None)]
    assert names.resolve("pooja room", tree).place.name == "Pooja Room"


def _w(place, kind, finished=False, day=1):
    return progress.Work(place, kind, finished, datetime.date(2026, 11, day))


def test_roll_up_floor_done_only_when_every_room_is():
    floor, r1, r2 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    places = [{"id": floor, "parent_id": None}, {"id": r1, "parent_id": floor}, {"id": r2, "parent_id": floor}]
    out = progress.roll_up(places, [_w(r1, "Plastering", True), _w(r2, "plastering", False, 2)])
    assert out["places"][floor]["cells"]["plastering"]["state"] == "in_progress"
    assert out["places"][floor]["left"] == ["Plastering"]
    out = progress.roll_up(places, [_w(r1, "Plastering", True), _w(r2, "plastering", True, 2)])
    assert out["places"][floor]["cells"]["plastering"]["state"] == "done"
    assert out["places"][floor]["cells"]["plastering"]["last"] == datetime.date(2026, 11, 2)


def test_roll_up_work_on_the_floor_itself_counts():
    floor, r1 = uuid.uuid4(), uuid.uuid4()
    places = [{"id": floor, "parent_id": None}, {"id": r1, "parent_id": floor}]
    out = progress.roll_up(places, [_w(floor, "Slab", True)])
    assert out["places"][floor]["cells"]["slab"]["state"] == "done"
    assert out["places"][r1]["cells"]["slab"]["state"] == "not_started"


@pytest.mark.parametrize("words", ["B3 footing concreted", "F1 B3 PCC done", "footing b3 kazhinju", "b-3 footing",
                                   "grid B3"])
def test_a_footing_by_its_grid(words):
    """DR-10: footings tracked from a structural drawing are places named by their grid, under Foundation."""
    root = names.Place(uuid.uuid4(), "Foundation", None)
    floor = names.Place(uuid.uuid4(), "Ground Floor", None)
    tree = [root, floor, names.Place(uuid.uuid4(), "Kitchen", floor.id)] + [
        names.Place(uuid.uuid4(), g, root.id) for g in ("A1", "A3", "B3", "B5", "D3")]
    assert names.resolve(words, tree).place.name == "B3"


def test_left_counts_only_the_work_of_its_own_floor_or_foundation():
    """Found making the sales video: "what's left on the first floor" listed footing concrete in every room."""
    ff, room, found, b3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    places = [{"id": ff, "parent_id": None}, {"id": room, "parent_id": ff},
              {"id": found, "parent_id": None}, {"id": b3, "parent_id": found}]
    out = progress.roll_up(places, [_w(room, "Brickwork"), _w(b3, "Footing concrete", True)])
    assert out["places"][room]["left"] == ["Brickwork"]  # never "Footing concrete"
    assert out["places"][found]["left"] == [] and out["places"][found]["done"] == ["Footing concrete"]


def test_rooms_from_a_drawing_are_named_as_people_write_them():
    """DR-11: a floor plan's room labels become place names; the same name twice on a floor is numbered."""
    from mesiri.domains.documents import live

    assert live.room_name("M. TOILET") == "M. Toilet" and live.room_name("ROOM-1") == "Room-1"
    assert live.room_name("Pooja room") == "Pooja room"  # already written by hand: kept as it is
    sheet = {"rooms": [{"label": "TOILET", "x": 1, "top": 1}, {"label": "KITCHEN", "x": 2, "top": 1},
                       {"label": "TOILET", "x": 3, "top": 1}]}
    assert [n for n, _ in live._sheet_rooms(sheet)] == ["Toilet", "Kitchen", "Toilet 2"]
    facts = {"sheets": [{"kind": "plan", "discipline": "architectural", "width": 1190, "rooms": sheet["rooms"]},
                        {"kind": "plan", "discipline": "structural", "width": 842, "rooms": sheet["rooms"]},
                        {"kind": "section", "discipline": "architectural", "width": 842, "rooms": sheet["rooms"]}]}
    assert len(live.floor_sheets(facts)) == 1  # a structural sheet or a section is never a floor plan of rooms
