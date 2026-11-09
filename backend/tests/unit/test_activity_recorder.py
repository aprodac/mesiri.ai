"""ADM-01 unit tests: how the activity recorder names a change and finds its record (no database).

The guards: an action on a record is that record, not a new one named after the verb; a create is the new record
from the reply; a reply that wraps the record (``{"link": {...}, "token": ...}``) gives its id and label and never
anything else; routes that save nothing are marked so.
"""

from __future__ import annotations

from mesiri.http import activity
from mesiri.http.activity import action_words, record_from


def test_action_words():
    assert action_words("submit_ra_bill", "POST") == "Submit RA bill"
    assert action_words("create", "POST", "client_link") == "Create client link"  # a bare verb takes the kind
    assert action_words("hand_over_work", "POST", "user") == "Hand over work"
    assert action_words(None, "DELETE", "task") == "Delete task"
    assert action_words("put_contract", "PUT", "project") == "Save contract"  # HTTP words read as what was done


def test_an_action_on_a_record_is_that_record():
    bill = "11111111-1111-1111-1111-111111111111"
    assert record_from("/billing/ra-bills/{bill_id}/submit", {"bill_id": bill}, {"id": bill, "ref": "RA-02"}) == (
        "ra_bill", bill, "RA-02")
    # No id in the reply: still the bill in the path.
    assert record_from("/billing/ra-bills/{bill_id}/submit", {"bill_id": bill}, {"ok": True}) == ("ra_bill", bill, None)


def test_a_create_is_the_new_record_from_the_reply():
    project, new = "22222222-2222-2222-2222-222222222222", "33333333-3333-3333-3333-333333333333"
    assert record_from("/projects/{project_id}/ra-bills", {"project_id": project}, {"id": new, "ref": "RA-03"}) == (
        "ra_bill", new, "RA-03")
    assert record_from("/tasks", {}, {"id": new, "ref": "T-4", "title": "Tie steel"}) == ("task", new, "T-4")


def test_a_wrapped_reply_gives_its_record_and_never_a_secret():
    project, link = "22222222-2222-2222-2222-222222222222", "44444444-4444-4444-4444-444444444444"
    reply = {"link": {"id": link, "label": "Mr. Thomas"}, "token": "S3CR3T-token-value"}
    kind, rid, label = record_from("/projects/{project_id}/client-links", {"project_id": project}, reply)
    assert (kind, rid, label) == ("client_link", link, "Mr. Thomas")


def test_plural_forms():
    assert activity._singular("categories") == "category"
    assert activity._singular("addresses") == "address"
    assert activity._singular("ra-bills") == "ra_bill"
    assert activity._singular("access") == "access"


def test_routes_that_save_nothing_are_marked():
    from mesiri.domains.drawings.router import read_drawing
    from mesiri.domains.materials.router import preview_material_import
    from mesiri.domains.progress.boq_router import boq_import_preview
    from mesiri.domains.subcontracts.router import check_bill

    for route in (read_drawing, preview_material_import, boq_import_preview, check_bill):
        assert getattr(route, "saves_nothing", False), route.__name__
