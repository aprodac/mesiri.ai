"""The plan preview (docs/execution/COMPOSITE_REQUEST_PLAN_LAYER.md §8, P3).

One numbered line per step, before anything runs -- the safety net a
composite request needs that a single-workflow message doesn't: five wrong
records are a much bigger mistake than one, and a bad decomposition or a
wrong entity-link is only ever caught here, before the first write. Nothing
in this module executes anything or touches PlanStore; it only describes a
Plan that has already been built (by planning/decomposition.py or any future
producer) and not yet started.

Pure -- no I/O, no provider calls. describe_step's per-step phrasing is
bespoke for the five workflow keys the entity-linking rule
(planning/decomposition.py) actually connects today (PROJECT_CREATE,
SITE_CREATE, CREATE_USER, ADD_PROJECT_MEMBER, SITE_UPDATE); anything else
falls back to the registry's own `title` plus its first informative field,
which is honest and general rather than a guess at natural language for a
workflow this layer was never tested against.
"""

from __future__ import annotations

from typing import Any

from mesiri_contracts.assistant.planner_decision import WorkflowKey

from .plan import Plan, PlanStep, StepRef


def _resolve_display(value: Any, plan: Plan) -> str:
    """The best available human-readable value for one field/scope entry --
    the literal itself, or, for a StepRef, a best-effort look at what the
    step it names will actually produce.

    A StepRef's real value does not exist until that step executes (ADR-C2),
    so this is deliberately NOT the same resolution binding.py does -- it is
    a preview-only guess from information already available at preview time:
    the referenced step's OWN extracted fields, which were known the moment
    it was decomposed, well before it runs. Two patterns cover the two real
    producers of a StepRef today:

    - ``output_key`` matches a field name the referenced step ALREADY carries
      literally (e.g. ADD_PROJECT_MEMBER's member_name references CREATE_
      USER's full_name -- and "full_name" is also CREATE_USER's own field
      name, by construction of planning/outputs.py's echo-scalars rule).
    - A scope ref (project_id/site_id) has no such literal field of the same
      name -- the referenced step calls it "name", not "project_id" -- so
      falls back to that.
    """
    if not isinstance(value, StepRef):
        return str(value)
    referenced = plan.step(value.step_id)
    if referenced is None:
        return "(an earlier step)"
    same_key = referenced.fields.get(value.output_key)
    if same_key is not None and not isinstance(same_key, StepRef):
        return str(same_key)
    if value.output_key in ("project_id", "site_id"):
        name = referenced.fields.get("name")
        if name is not None and not isinstance(name, StepRef):
            return str(name)
    return "(an earlier step)"


def describe_step(step: PlanStep, plan: Plan) -> str:
    """One line describing what ``step`` will do, in plain language."""
    fields = {k: _resolve_display(v, plan) for k, v in step.fields.items()}
    scope = {k: _resolve_display(v, plan) for k, v in step.scope.items()}

    if step.workflow_key is WorkflowKey.PROJECT_CREATE:
        return f"Create project {fields.get('name', '(unnamed)')}"

    if step.workflow_key is WorkflowKey.SITE_CREATE:
        under = f" under {scope['project_id']}" if scope.get("project_id") else ""
        return f"Create site {fields.get('name', '(unnamed)')}{under}"

    if step.workflow_key is WorkflowKey.CREATE_USER:
        name = fields.get("full_name", "(unnamed)")
        number = fields.get("whatsapp_number")
        return f"Add {name} ({number}) as a new user" if number else f"Add {name} as a new user"

    if step.workflow_key is WorkflowKey.ADD_PROJECT_MEMBER:
        name = fields.get("member_name", "(unnamed)")
        role = fields.get("role")
        of_project = f" of {scope['project_id']}" if scope.get("project_id") else ""
        return f"Make {name} {role}{of_project}" if role else f"Add {name}{of_project}"

    if step.workflow_key is WorkflowKey.SITE_UPDATE:
        narrative = fields.get("narrative", "an update")
        at_site = f" at {scope['site_id']}" if scope.get("site_id") else ""
        return f'Log activity "{narrative}"{at_site}'

    if step.workflow_key is WorkflowKey.MATERIAL_RECEIPT and fields.get("material_name"):
        amount = " ".join(str(fields[k]) for k in ("quantity", "unit") if fields.get(k))
        what = f"{amount} {fields['material_name']}".strip()
        sender = f" from {fields['supplier']}" if fields.get("supplier") else ""
        return f"Record {what} received{sender}"

    if step.workflow_key is WorkflowKey.EXPENSE_SUBMIT and fields.get("amount") is not None:
        from workflows.readable import money  # lazy, same reason as get_definition below

        paid = money(fields["amount"], fields.get("currency"))
        for_what = f" for {fields['vendor']}" if fields.get("vendor") else ""
        return f"Record an expense of {paid}{for_what}"

    # Generic fallback -- honest rather than a guess at natural language
    # for a workflow key this layer's linking rule doesn't specifically
    # connect today (see workflows/registry.py's own title/one_liner,
    # already used everywhere else a workflow needs describing).
    from workflows.registry import get_definition

    definition = get_definition(step.workflow_key)
    title = definition.title if definition is not None else step.workflow_key.value
    first_field = next(iter(fields.values()), None)
    return f"{title}: {first_field}" if first_field is not None else title


def render_plan_preview(plan: Plan) -> str:
    """The full preview block (§8): one numbered line per step, in the
    order they will run, before anything has been started or written."""
    lines = [f"I'll do {len(plan.steps)} things:" if len(plan.steps) != 1 else "I'll do this:"]
    lines.extend(
        f"{i}. {describe_step(step, plan)}" for i, step in enumerate(plan.steps, start=1)
    )
    return "\n".join(lines)
