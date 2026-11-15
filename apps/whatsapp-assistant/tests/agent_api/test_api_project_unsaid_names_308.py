"""[308] (15 Nov, live): an owner sent a photo of a BOQ page with "try to understand this boq from now il work on this
project this is the 7000sq feet project". Mesiri prepared a project change with the client "Commercial Supermarket
Client", a name nobody said and the page does not show; the card line said only "Change project · Supermarket Kerala",
and one tap saved the made-up client over the project.

Now the code drops a project name, client or place that is neither in their words nor in what their photo or file
shows; an update that then changes nothing is not prepared; and the card line shows every field Save writes."""

from __future__ import annotations

from tests.agent_api.test_api_project_lines_257 import PLACES, PROJECT, _turn

from agent_api.agent import PendingWrite, project_changes, without_unsaid_names
from agent_api.receipts import slip_for
from agent_api.tools import CONFIRM_ARG

PHOTO = ("(sent a photo: try to understand this boq from now il work on this project this is the 7000sq feet project)"
         "\nWhat the photo shows: Preliminary Bill of Quantities for G+1 Commercial Supermarket Building (7000 sq ft)")
CURRENT = {"name": "Supermarket Kerala", "client": "D2D Supermarket", "location": "Kerala"}


async def test_the_reported_turn_a_made_up_client_is_never_prepared() -> None:
    turn = await _turn([("update_project", {
        "project_id": PROJECT, "name": "Supermarket Kerala", "client": "Commercial Supermarket Client",
        CONFIRM_ARG: "Update project Supermarket Kerala"})], saved=CURRENT, said=PHOTO)
    assert turn.pending == []  # nothing left to change: never a card line, never a Save
    (call,) = turn.calls
    assert call["result"]["status"] == "not prepared: nothing to change"
    assert 'client "Commercial Supermarket Client"' in call["result"]["note"]


async def test_sibling_a_client_they_said_goes_through_and_the_made_up_place_does_not() -> None:
    turn = await _turn([("update_project", {"project_id": PROJECT, "client": "Day to Day Supermarket",
                                            "location": "Kochi Bypass", CONFIRM_ARG: "x"})],
                       saved=CURRENT, said="client Day to Day Supermarket aanu")
    (entry,) = turn.pending
    assert entry.body.get("client") == "Day to Day Supermarket" and "location" not in entry.body
    assert entry.summary == "*Supermarket Kerala*: client Day to Day Supermarket"


async def test_sibling_a_name_the_photo_shows_counts_as_said() -> None:
    turn = await _turn([("update_project", {"project_id": PROJECT, "name": "G+1 Commercial Supermarket Building",
                                            CONFIRM_ARG: "x"})], saved=CURRENT, said=f"rename it to this\n{PHOTO}")
    assert turn.pending[0].body["name"] == "G+1 Commercial Supermarket Building"


async def test_guard_a_new_project_keeps_its_name_but_not_an_unsaid_client() -> None:
    turn = await _turn([("create_project", {"name": "Tower B", "client": "Acme Developers", CONFIRM_ARG: "x"})],
                       said="new project Tower B")
    (entry,) = turn.pending
    assert entry.body["name"] == "Tower B" and "client" not in entry.body


def test_names_in_another_script_are_kept_and_unchanged_fields_are_no_change() -> None:
    body = {"client": "Day to Day Supermarket"}
    assert without_unsaid_names(body, "ക്ലയന്റ് ഡേ ടു ഡേ സൂപ്പർമാർക്കറ്റ്", {}) == (body, [])
    assert not project_changes({"project_id": PROJECT, "name": "Supermarket Kerala"}, CURRENT)
    assert project_changes({"name": "D2D Mart"}, CURRENT)
    assert project_changes({"name": "Supermarket Kerala"}, {})  # the project could not be read: a change


def test_the_card_line_shows_every_field_save_writes() -> None:
    entry = PendingWrite("update_project", "PUT", f"/projects/{PROJECT}", {}, {"client": "Day to Day Supermarket"},
                         "*Supermarket Kerala*: client Day to Day Supermarket", "k")
    from tests.agent_api.test_api_receipts_132 import CTX

    (line,) = slip_for([entry], CTX, ({}, {}), targets={PROJECT: "Supermarket Kerala"}).lines
    assert line.title == "Change project"
    assert line.note == "Supermarket Kerala: client Day to Day Supermarket"
    assert PLACES.projects[0][1] in line.note
