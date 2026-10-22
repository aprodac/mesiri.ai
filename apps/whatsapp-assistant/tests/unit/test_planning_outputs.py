"""Unit tests for planning/outputs.py -- what a completed step publishes for
later steps' StepRefs to resolve against
(docs/execution/COMPOSITE_REQUEST_PLAN_LAYER.md §7.2).

The gap these close: binding.py could always *resolve* a StepRef, but until
this module existed nothing generic ever *populated* the outputs it resolves
from -- so a decomposed plan's StepRef("s1", "project_id") would have raised
UnresolvedStepRefError at runtime however correct the linking was.
"""

from __future__ import annotations

from mesiri_contracts.assistant.planner_decision import WorkflowKey
from planning.outputs import build_step_outputs

ROW = "44444444-4444-4444-8444-444444444444"


def test_project_create_publishes_project_id():
    """The one that unblocks the Starship message: SITE_CREATE's
    StepRef("s1", "project_id") has something to resolve against."""
    outputs = build_step_outputs(workflow_key=WorkflowKey.PROJECT_CREATE, row_id=ROW)
    assert outputs["project_id"] == ROW


def test_site_create_publishes_site_id():
    outputs = build_step_outputs(workflow_key=WorkflowKey.SITE_CREATE, row_id=ROW)
    assert outputs["site_id"] == ROW


def test_create_user_publishes_user_id():
    outputs = build_step_outputs(workflow_key=WorkflowKey.CREATE_USER, row_id=ROW)
    assert outputs["user_id"] == ROW


def test_site_update_publishes_activity_id():
    outputs = build_step_outputs(workflow_key=WorkflowKey.SITE_UPDATE, row_id=ROW)
    assert outputs["activity_id"] == ROW


def test_the_id_key_matches_the_scope_key_a_consuming_step_uses():
    """PlanStep.scope is validated against SCOPE_KEYS ("project_id",
    "site_id"). If the published id key ever drifted from those names, every
    scope StepRef would resolve to nothing -- so assert the two agree
    rather than trusting the shared "<noun>_id" convention to hold."""
    from planning.plan import SCOPE_KEYS

    project = build_step_outputs(workflow_key=WorkflowKey.PROJECT_CREATE, row_id=ROW)
    site = build_step_outputs(workflow_key=WorkflowKey.SITE_CREATE, row_id=ROW)
    assert set(project) == {"project_id"} and "project_id" in SCOPE_KEYS
    assert set(site) == {"site_id"} and "site_id" in SCOPE_KEYS


def test_draft_scalar_fields_are_republished():
    """What makes the member-create chain work: ADD_PROJECT_MEMBER needs the
    exact name the user was created under, not the id."""
    outputs = build_step_outputs(
        workflow_key=WorkflowKey.CREATE_USER,
        row_id=ROW,
        draft_fields={"full_name": "Hisham", "whatsapp_number": "919876543210"},
    )
    assert outputs["user_id"] == ROW
    assert outputs["full_name"] == "Hisham"
    assert outputs["whatsapp_number"] == "919876543210"


def test_reproduces_the_member_create_chains_previous_hardcoded_outputs():
    """This call site used to hand-write {"user_id": ..., "full_name": ...}.
    The generic builder must produce those two keys with those two values,
    which is what lets the existing member-create tests pass unchanged."""
    outputs = build_step_outputs(
        workflow_key=WorkflowKey.CREATE_USER,
        row_id=ROW,
        draft_fields={"full_name": "Hisham"},
    )
    assert outputs["user_id"] == ROW
    assert outputs["full_name"] == "Hisham"


def test_non_scalar_draft_fields_are_skipped():
    """A labour report's `lines` array is structure no StepRef can name, and
    copying it would bloat a Redis value carried for 30 minutes."""
    outputs = build_step_outputs(
        workflow_key=WorkflowKey.CREATE_USER,
        row_id=ROW,
        draft_fields={
            "full_name": "Hisham",
            "lines": [{"worker_name": "Ravi"}],
            "nested": {"a": 1},
        },
    )
    assert "lines" not in outputs
    assert "nested" not in outputs
    assert outputs["full_name"] == "Hisham"


def test_none_valued_draft_fields_are_skipped_not_stringified():
    """An absent field must be absent, never the literal string "None"."""
    outputs = build_step_outputs(
        workflow_key=WorkflowKey.CREATE_USER,
        row_id=ROW,
        draft_fields={"full_name": "Hisham", "role": None},
    )
    assert "role" not in outputs


def test_created_by_role_is_never_republished():
    """It describes the ACTOR's authority for that one step, not the entity
    created. A later step inheriting it by reference would be carrying the
    wrong step's permission context."""
    outputs = build_step_outputs(
        workflow_key=WorkflowKey.CREATE_USER,
        row_id=ROW,
        draft_fields={"full_name": "Hisham", "created_by_role": "ADMIN"},
    )
    assert "created_by_role" not in outputs


def test_the_provided_id_wins_over_a_same_named_draft_field():
    """A draft that happens to carry its own `project_id` must not shadow
    the id of the row actually written."""
    outputs = build_step_outputs(
        workflow_key=WorkflowKey.PROJECT_CREATE,
        row_id=ROW,
        draft_fields={"project_id": "some-other-value"},
    )
    assert outputs["project_id"] == ROW


def test_no_row_id_publishes_no_id_but_still_publishes_draft_fields():
    """An informational step, or one that completed without a draft, wrote
    no row. It publishes no id -- and a StepRef naming one then fails loudly
    in binding.py rather than silently resolving to None."""
    outputs = build_step_outputs(
        workflow_key=WorkflowKey.PROJECT_CREATE,
        row_id=None,
        draft_fields={"name": "Starship"},
    )
    assert "project_id" not in outputs
    assert outputs["name"] == "Starship"


def test_a_workflow_that_provides_nothing_publishes_only_draft_fields():
    outputs = build_step_outputs(
        workflow_key=WorkflowKey.EXPENSE_SUBMIT,
        row_id=ROW,
        draft_fields={"amount": 1500},
    )
    assert outputs == {"amount": "1500"}


def test_every_registered_provider_publishes_a_resolvable_id():
    """Sweep the registry: any workflow declaring `provides` must publish a
    non-empty id key for it. Adding a new EntityType + provider wires itself
    through this path with no edit here -- this test is what guarantees that
    claim stays true."""
    from workflows.registry import iter_definitions

    for definition in iter_definitions():
        if not definition.provides:
            continue
        outputs = build_step_outputs(workflow_key=definition.key, row_id=ROW)
        for entity in definition.provides:
            key = f"{entity.value}_id"
            assert outputs.get(key) == ROW, (
                f"{definition.key.value} provides {entity.value} but did not publish {key}"
            )


