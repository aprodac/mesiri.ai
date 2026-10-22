"""Express a materials-catalog lookup in the shared resolution vocabulary --
Phase 3 of docs/execution/ENTITY_RESOLUTION_PLAN.md §5.

Phase 3 is the plan's own stated correctness check: materials are the one
entity whose good behaviour already existed before the entity-resolution
layer, so if the generic mechanism cannot express it *without special-casing*,
the abstraction is wrong. Migrating it produced two findings, both recorded
here rather than papered over.

## Finding 1 -- the layer splits in two, and materials need only one half

`member_resolution.py` contributes BOTH halves to USER: the matching
technique (difflib near-match scoring, because an org's user list has no
searchable structure and ഹൈസം/Hisham must still meet) and the outcome
vocabulary (Resolved/Ambiguous/Missing).

Materials need only the second. Their matching already happens in SQL and is
already right: `find_by_name_exact_active` then `find_by_name_fuzzy`'s
substring/ILIKE over a catalog the org itself curated. Substring is the
*better* technique here -- "cement" should match "OPC Cement 53 Grade", which
difflib scores at 0.35 and would discard, while difflib's strength (catching
a transliteration one character off) is not what a product catalog needs.

So this module deliberately does NOT re-implement scoring. It classifies a
list the caller already fetched. That is not a gap in the abstraction; it is
the abstraction being honest about which of its two halves each entity needs.

## Finding 2 -- there is no `EntityType.MATERIAL`, on purpose

`EntityType`'s members are the entities a *workflow* provides
(`workflow_that_provides`), and no workflow provides MATERIAL: creating a
catalog entry is a direct `create_material` write inside
`_create_material_and_resume`, not a confirmed workflow the way CREATE_USER
is. Adding a member here would make `workflow_that_provides(MATERIAL)` return
None -- a lie in a table whose entire purpose is answering that question.

The chaining half of the plan (§3's "insert a step, run the provider
workflow, resume where it left off") therefore does not apply to materials at
all, and the create-offer/resume legs in `resume.py` stay exactly as they
are. Only the gate's *vocabulary* moves.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from runtime.entity_resolution import normalize_name
from workflows.entities import Ambiguous, Candidate, Missing, ResolutionOutcome, Resolved


def classify_material_matches(
    name_hint: str, matches: Sequence[Mapping[str, Any]]
) -> ResolutionOutcome:
    """Turn `MaterialCatalogQueryService.find_materials`' rows into the shared
    Resolved/Ambiguous/Missing vocabulary.

    Pure -- the query already happened. `matches` is that call's result
    verbatim.

    **Only an exact name match resolves silently.** A lone substring
    candidate is `Ambiguous`, not `Resolved` -- it is offered as a one-row
    picker (with the "None of these" escape `render_material_picker` always
    appends) rather than assumed. This is the rule `find_by_name_fuzzy`'s own
    docstring always stated ("candidates for a WhatsApp disambiguation
    picker, never auto-accepted") and that its caller had quietly not
    honoured: reporting "50 bags of cement" against a catalog whose only
    *cement*-matching row was "Cement Paint" resolved to Cement Paint in
    silence, and the confirmation prompt that followed showed a plausible
    enough line for a busy site engineer to wave through.

    Exactness is decided here rather than trusted from the query, because
    `find_materials` flattens both probes into one list -- an exact hit is
    returned alone, but so is a single substring hit, and by this point the
    two are indistinguishable by shape. Comparing the hint against the row's
    own name (via the package's shared `normalize_name`, the same rule
    `member_resolution` uses) recovers the distinction without widening that
    service's contract.
    """
    if not matches:
        return Missing(name_hint=name_hint)

    hint = normalize_name(name_hint)
    if hint:
        for row in matches:
            if _same_name(normalize_name(str(row["name"])), hint):
                return Resolved(entity_id=str(row["id"]), display_name=str(row["name"]))

    return Ambiguous(
        candidates=tuple(
            Candidate(entity_id=str(row["id"]), display_name=str(row["name"]))
            for row in matches
        )
    )


def _same_name(name: str, hint: str) -> bool:
    """Exact, or the same word in singular and plural ("brick" / "Bricks",
    live golden set 22 Oct). Still never a different material: "cement" is
    not "Cement Paint"."""
    return name == hint or name in (hint + "s", hint + "es") or hint in (name + "s", name + "es")
