"""Unit tests for planning/preview.py -- the plan preview
(docs/execution/COMPOSITE_REQUEST_PLAN_LAYER.md §8, P3)."""

from __future__ import annotations

from mesiri_contracts.assistant.canonical_event import CanonicalEventType
from mesiri_contracts.assistant.planner_decision import WorkflowKey
from planning.plan import Plan, PlanOrigin, PlanStep, StepRef
from planning.preview import describe_step, render_plan_preview

ORG = "11111111-1111-4111-8111-111111111111"
USR = "22222222-2222-4222-8222-222222222222"


def _plan(*steps: PlanStep) -> Plan:
    return Plan(
        plan_id="plan_1",
        correlation_id="cor_1",
        user_id=USR,
        organization_id=ORG,
        origin=PlanOrigin.DECOMPOSITION,
        steps=steps,
    )


def test_describe_project_create():
    step = PlanStep(
        step_id="s1",
        workflow_key=WorkflowKey.PROJECT_CREATE,
        event_type=CanonicalEventType.PROJECT_CREATE_REQUESTED,
        fields={"name": "Paraclette"},
    )
    assert describe_step(step, _plan(step)) == "Create project Paraclette"


def test_describe_site_create_resolves_the_project_ref_to_its_name():
    """The whole point: the project is a StepRef at preview time (nothing
    has run yet), and the preview must still say "Paraclette", not a raw
    step id or "(an earlier step)"."""
    project = PlanStep(
        step_id="s1",
        workflow_key=WorkflowKey.PROJECT_CREATE,
        event_type=CanonicalEventType.PROJECT_CREATE_REQUESTED,
        fields={"name": "Paraclette"},
    )
    site = PlanStep(
        step_id="s2",
        workflow_key=WorkflowKey.SITE_CREATE,
        event_type=CanonicalEventType.SITE_CREATE_REQUESTED,
        fields={"name": "Tower B"},
        scope={"project_id": StepRef("s1", "project_id")},
    )
    plan = _plan(project, site)
    assert describe_step(site, plan) == "Create site Tower B under Paraclette"


def test_describe_site_create_with_a_literal_project_id_falls_back_honestly():
    """When the project already existed (a literal id, not a ref), there is
    no name to show -- the preview must not fabricate one."""
    site = PlanStep(
        step_id="s1",
        workflow_key=WorkflowKey.SITE_CREATE,
        event_type=CanonicalEventType.SITE_CREATE_REQUESTED,
        fields={"name": "Tower B"},
        scope={"project_id": "33333333-3333-4333-8333-333333333333"},
    )
    text = describe_step(site, _plan(site))
    assert text.startswith("Create site Tower B under ")


def test_describe_create_user_with_and_without_a_phone_number():
    with_number = PlanStep(
        step_id="s1",
        workflow_key=WorkflowKey.CREATE_USER,
        event_type=CanonicalEventType.CREATE_USER_REQUESTED,
        fields={"full_name": "Hysamm", "whatsapp_number": "9198765xxxxx"},
    )
    assert describe_step(with_number, _plan(with_number)) == (
        "Add Hysamm (9198765xxxxx) as a new user"
    )

    without_number = PlanStep(
        step_id="s1",
        workflow_key=WorkflowKey.CREATE_USER,
        event_type=CanonicalEventType.CREATE_USER_REQUESTED,
        fields={"full_name": "Hysamm"},
    )
    assert describe_step(without_number, _plan(without_number)) == "Add Hysamm as a new user"


def test_describe_add_project_member_resolves_the_created_users_exact_name():
    """member_name references CREATE_USER's full_name -- the preview must
    show "Hysamm", not the raw StepRef or a placeholder."""
    user = PlanStep(
        step_id="s1",
        workflow_key=WorkflowKey.CREATE_USER,
        event_type=CanonicalEventType.CREATE_USER_REQUESTED,
        fields={"full_name": "Hysamm"},
    )
    member = PlanStep(
        step_id="s2",
        workflow_key=WorkflowKey.ADD_PROJECT_MEMBER,
        event_type=CanonicalEventType.ADD_PROJECT_MEMBER_REQUESTED,
        fields={"member_name": StepRef("s1", "full_name"), "role": "PROJECT_MANAGER"},
        scope={"project_id": StepRef("s0", "project_id")},  # unresolved on purpose
    )
    plan = _plan(user, member)
    assert describe_step(member, plan) == "Make Hysamm PROJECT_MANAGER of (an earlier step)"


def test_describe_site_update():
    step = PlanStep(
        step_id="s1",
        workflow_key=WorkflowKey.SITE_UPDATE,
        event_type=CanonicalEventType.GENERAL_SITE_UPDATE_REQUESTED,
        fields={"narrative": "slab work started"},
        scope={"site_id": "55555555-5555-4555-8555-555555555555"},
    )
    text = describe_step(step, _plan(step))
    assert text.startswith('Log activity "slab work started" at ')


def test_describe_falls_back_to_registry_title_for_an_unconnected_workflow_key():
    """A workflow this layer has no bespoke phrasing for (e.g. EQUIPMENT_USAGE,
    reachable in principle via a decomposed segment even though today's
    entity-linking rule never connects it to anything) still gets an honest
    line, not a crash."""
    step = PlanStep(
        step_id="s1",
        workflow_key=WorkflowKey.EQUIPMENT_USAGE,
        event_type=CanonicalEventType.EQUIPMENT_USAGE_REQUESTED,
        fields={"equipment_name": "JCB"},
    )
    text = describe_step(step, _plan(step))
    assert "JCB" in text


def test_render_plan_preview_full_paraclette_example():
    project = PlanStep(
        step_id="s1",
        workflow_key=WorkflowKey.PROJECT_CREATE,
        event_type=CanonicalEventType.PROJECT_CREATE_REQUESTED,
        fields={"name": "Paraclette"},
    )
    site = PlanStep(
        step_id="s2",
        workflow_key=WorkflowKey.SITE_CREATE,
        event_type=CanonicalEventType.SITE_CREATE_REQUESTED,
        fields={"name": "Tower B"},
        scope={"project_id": StepRef("s1", "project_id")},
    )
    user = PlanStep(
        step_id="s3",
        workflow_key=WorkflowKey.CREATE_USER,
        event_type=CanonicalEventType.CREATE_USER_REQUESTED,
        fields={"full_name": "Hysamm", "whatsapp_number": "9198765xxxxx"},
    )
    member = PlanStep(
        step_id="s4",
        workflow_key=WorkflowKey.ADD_PROJECT_MEMBER,
        event_type=CanonicalEventType.ADD_PROJECT_MEMBER_REQUESTED,
        fields={"member_name": StepRef("s3", "full_name"), "role": "PROJECT_MANAGER"},
        scope={"project_id": StepRef("s1", "project_id")},
    )
    activity = PlanStep(
        step_id="s5",
        workflow_key=WorkflowKey.SITE_UPDATE,
        event_type=CanonicalEventType.GENERAL_SITE_UPDATE_REQUESTED,
        fields={"narrative": "slab work started"},
        scope={
            "project_id": StepRef("s1", "project_id"),
            "site_id": StepRef("s2", "site_id"),
        },
    )
    plan = _plan(project, site, user, member, activity)

    preview = render_plan_preview(plan)

    assert preview == (
        "I'll do 5 things:\n"
        "1. Create project Paraclette\n"
        "2. Create site Tower B under Paraclette\n"
        "3. Add Hysamm (9198765xxxxx) as a new user\n"
        "4. Make Hysamm PROJECT_MANAGER of Paraclette\n"
        '5. Log activity "slab work started" at Tower B'
    )


def test_render_plan_preview_singular_phrasing_for_one_step():
    step = PlanStep(
        step_id="s1",
        workflow_key=WorkflowKey.PROJECT_CREATE,
        event_type=CanonicalEventType.PROJECT_CREATE_REQUESTED,
        fields={"name": "Starship"},
    )
    preview = render_plan_preview(_plan(step))
    assert preview == "I'll do this:\n1. Create project Starship"
