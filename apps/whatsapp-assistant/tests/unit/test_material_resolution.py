"""runtime/entity_resolution/material_resolution.py -- Phase 3 of
ENTITY_RESOLUTION_PLAN.md: the materials catalog expressed in the shared
Resolved/Ambiguous/Missing vocabulary.

Pure function, no DB and no fakes needed -- the SQL matching happens before
this and is the catalog repository's own concern (see that module's docstring
on why materials need only half of the entity-resolution layer).

The behavioural proof that this migration changed nothing lives in
test_material_create_gate.py / test_material_unit_gates.py, which exercise
_run_material_unit_gates end-to-end and were not modified for Phase 3.
"""

from __future__ import annotations

import uuid

from runtime.entity_resolution.material_resolution import classify_material_matches
from workflows.entities import Ambiguous, Missing, Resolved

CEMENT_ID = str(uuid.uuid4())
OPC_ID = str(uuid.uuid4())
PPC_ID = str(uuid.uuid4())


def _row(material_id: str, name: str) -> dict:
    return {"id": material_id, "name": name, "is_active": True, "default_unit_id": None}


def test_no_matches_is_missing_and_carries_the_hint_back():
    outcome = classify_material_matches("Fevicol", [])
    assert isinstance(outcome, Missing)
    # ADR-E4: Missing always offers to create with the EXACT reported name,
    # never an invented one -- so the hint has to survive.
    assert outcome.name_hint == "Fevicol"


def test_an_exact_name_match_resolves():
    outcome = classify_material_matches("cement", [_row(CEMENT_ID, "Cement")])
    assert isinstance(outcome, Resolved)
    assert outcome.entity_id == CEMENT_ID
    assert outcome.display_name == "Cement"


def test_several_matches_are_ambiguous_in_order():
    outcome = classify_material_matches(
        "cement", [_row(OPC_ID, "OPC Cement"), _row(PPC_ID, "PPC Cement")]
    )
    assert isinstance(outcome, Ambiguous)
    assert [c.entity_id for c in outcome.candidates] == [OPC_ID, PPC_ID]
    assert [c.display_name for c in outcome.candidates] == ["OPC Cement", "PPC Cement"]


def test_a_lone_substring_match_asks_instead_of_auto_accepting():
    """The behaviour change this module exists to make. "cement" against a
    catalog whose only matching row is "Cement Paint" used to resolve to
    Cement Paint silently; find_by_name_fuzzy's own docstring always said
    substring candidates are "never auto-accepted", and its caller quietly
    didn't honour that.

    One row, so the picker shows a single option -- which is only safe
    because render_material_picker always appends "None of these" (see
    test_replies.py). Without that escape this would be a trap, not a
    question.
    """
    outcome = classify_material_matches("cement", [_row(OPC_ID, "Cement Paint")])
    assert isinstance(outcome, Ambiguous)
    assert [c.display_name for c in outcome.candidates] == ["Cement Paint"]


def test_an_exact_match_still_resolves_silently_even_among_others():
    """Exactness, not row count, is what earns a silent resolve -- so a
    perfect hit is never demoted to a picker just because the substring probe
    also dragged in near-misses."""
    outcome = classify_material_matches(
        "cement", [_row(OPC_ID, "OPC Cement"), _row(CEMENT_ID, "Cement")]
    )
    assert isinstance(outcome, Resolved)
    assert outcome.entity_id == CEMENT_ID


def test_exact_match_ignores_case_and_surrounding_whitespace():
    outcome = classify_material_matches("  CEMENT  ", [_row(CEMENT_ID, "Cement")])
    assert isinstance(outcome, Resolved)
    assert outcome.entity_id == CEMENT_ID


def test_a_blank_hint_never_resolves_by_accident():
    """An empty/whitespace hint must not exact-match a row whose name is
    also blank-ish -- it asks instead, since nothing was actually reported."""
    outcome = classify_material_matches("   ", [_row(CEMENT_ID, "Cement")])
    assert isinstance(outcome, Ambiguous)


def test_non_string_ids_are_normalized_to_str():
    """find_materials returns rows straight from the repository, where id is a
    uuid.UUID rather than a str -- the outcome must not leak that through to
    canonical_event.fields, which is serialized to JSON."""
    real_uuid = uuid.uuid4()
    outcome = classify_material_matches(
        "cement", [{"id": real_uuid, "name": "Cement", "is_active": True}]
    )
    assert isinstance(outcome, Resolved)
    assert outcome.entity_id == str(real_uuid)
    assert isinstance(outcome.entity_id, str)


def test_singular_and_plural_are_the_same_material_but_a_longer_name_is_not():
    """Live golden set, 22 Oct: "1500 brick" against "Bricks" asked which
    material; "cement" must still never become "Cement Paint"."""
    from runtime.entity_resolution.material_resolution import Resolved

    assert isinstance(classify_material_matches("brick", [_row(CEMENT_ID, "Bricks")]), Resolved)
    assert isinstance(classify_material_matches("tiles", [_row(CEMENT_ID, "Tile")]), Resolved)
    assert not isinstance(classify_material_matches("cement", [_row(CEMENT_ID, "Cement Paint")]), Resolved)
