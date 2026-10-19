"""Entity-linking: turning N independently-extracted segments into one
ordered Plan (docs/execution/COMPOSITE_REQUEST_PLAN_LAYER.md §9, §7.2).

Pure -- no I/O, no provider calls. Each segment has already been through the
SAME single-intent path every ordinary message uses
(canonicalization.build_canonical_event against the extraction call
DecompositionResult.segments[i] produced), so this module receives a plain
list of CanonicalEventV2, one per segment, in the order the sender said them.
Deliberately NOT wired into runtime/inbound_journey/process.py yet -- that
wiring, and the plan preview (§8), are separate passes.

The problem this solves: a segment described in isolation is often
incomplete on purpose. "create a site called Site A" names no project --
the sender said "then create a site... under it", and by the time this
module sees it, "it" has already been dropped by per-segment extraction
(each segment is extracted independently, exactly as if it had arrived as
its own message). Something has to notice that SITE_CREATE `requires`
PROJECT (workflows/registry.py), that this segment did not resolve one, and
that an earlier segment's PROJECT_CREATE step will produce one -- and wire a
StepRef instead of letting site_create ask "which project?" for something
the sender already answered in the same breath.

Scope, stated plainly (mirrors ENTITY_RESOLUTION_PLAN.md ADR-E3's own
"depth 1 only in V1" honesty about staying narrow rather than pretending to
be more general than it is):

- PROJECT and SITE bind automatically: if a segment's own event doesn't
  already carry a project_id/site_id and an earlier segment's workflow
  `provides` one, bind to the MOST RECENT such earlier segment. There is
  essentially always at most one project/site in play in a short composite
  message, so "the one just created" is the correct, unambiguous reading of
  "it"/"there".
- USER binds only into ADD_PROJECT_MEMBER's `member_name`, and only when
  either (a) this segment named no member at all (a bare "make him project
  manager" -- extraction returned nothing for member_name), or (b) the name
  it did extract plausibly refers to the same person an earlier CREATE_USER
  segment just created (same normalized name). A member_name that clearly
  names someone ELSE is left alone -- that person is assumed to already
  exist, and resolving them is the entity-resolution layer's job at
  execution time, not this module's.
- Any other combination -- a workflow whose `requires` this module has no
  binding rule for -- is left unbound. The segment still gets a PlanStep;
  its own workflow asks the user for whatever is missing, exactly as an
  ordinary single-message report would. A missing binding is never an
  error; it degrades to the existing, safe clarifying-question path.
"""

from __future__ import annotations

from dataclasses import dataclass

from mesiri_contracts.assistant.planner_decision import WorkflowKey
from mesiri_contracts.assistant.v2.canonical_event import CanonicalEventV2
from planner.routing import WORKFLOW_KEY_BY_EVENT

from .ordering import topological_order
from .plan import Plan, PlanOrigin, PlanStep, StepRef


def _normalize_name(name: str) -> str:
    return " ".join(name.strip().lower().split())


@dataclass(frozen=True, slots=True)
class SkippedSegment:
    """A segment that could not become a PlanStep at all -- reported so a
    future preview (§8) can tell the user honestly, the same way
    workflows/batch.py already reports a segment it couldn't start.
    Distinct from an unbound-but-planned segment: this one has no step."""

    index: int
    text: str
    reason: str
    event_type: str = ""


@dataclass(frozen=True, slots=True)
class DecomposedPlanResult:
    plan: Plan | None
    skipped: tuple[SkippedSegment, ...]


@dataclass(frozen=True, slots=True)
class _BuiltStep:
    """Bookkeeping kept alongside each already-built PlanStep so later
    segments can look up what an earlier one will produce -- the literal
    full_name a CREATE_USER step is creating, in particular, since matching
    "is this the same person" needs the name, not just the step_id."""

    step_id: str
    provides: frozenset  # frozenset[EntityType]
    full_name: str | None


def _find_provider_step(entity, built: list[_BuiltStep]) -> _BuiltStep | None:
    """The MOST RECENT earlier step that provides ``entity`` -- reversed
    search, since "it"/"him" always refers to whatever was most recently
    introduced, never an earlier one a later segment superseded."""
    for step in reversed(built):
        if entity in step.provides:
            return step
    return None


def build_plan_from_segments(
    segment_events: list[CanonicalEventV2],
    *,
    plan_id: str,
    origin: PlanOrigin = PlanOrigin.DECOMPOSITION,
) -> DecomposedPlanResult:
    """Turn per-segment CanonicalEventV2s into one ordered Plan.

    Identity (organization_id, user_id, permissions, source_message_id,
    conversation_id) is read from ``segment_events[0]`` -- every segment
    came from the same sender and the same inbound message, so they are
    identical across all of them by construction, not independently chosen
    here.

    Returns a Plan of however many segments turned out plannable (as few as
    one, if the rest were unsupported) alongside which segments were
    skipped and why. None for ``plan`` only when nothing at all was
    plannable -- the caller's existing single-message fallback applies
    unchanged in that case.
    """
    # Imported here, not at module level, to avoid a hard dependency from
    # planning/ (imported by both the entity-resolution and composite-plan
    # producers) onto workflows/registry's full graph-of-adapters import
    # chain at import time -- registry.py itself has no problem being
    # imported from planning/ (see this module's own docstring on layering),
    # this just keeps the import lazy the same way other cross-package
    # lookups in this codebase already do.
    from workflows.entities import EntityType
    from workflows.registry import get_definition

    if not segment_events:
        return DecomposedPlanResult(plan=None, skipped=())

    first = segment_events[0]
    raw_steps: list[PlanStep] = []
    built: list[_BuiltStep] = []
    skipped: list[SkippedSegment] = []

    for index, event in enumerate(segment_events):
        workflow_key = WORKFLOW_KEY_BY_EVENT.get(event.event_type)
        if workflow_key is None:
            # source_text: the part as the sender wrote it, stashed by
            # runtime/inbound_journey/decomposed_plan.py so the reply can quote
            # a question or a part it could not read back to them.
            skipped.append(
                SkippedSegment(
                    index=index,
                    text=str(
                        event.fields.get("source_text")
                        or event.fields.get("narrative")
                        or event.event_type.value
                    ),
                    reason="not_understood"
                    if event.fields.get("not_understood")
                    else "unsupported_event_type",
                    event_type=event.event_type.value,
                )
            )
            continue

        definition = get_definition(workflow_key)
        requires = definition.requires if definition is not None else frozenset()
        provides = definition.provides if definition is not None else frozenset()

        step_id = f"s{index + 1}"
        fields = dict(event.fields)
        scope: dict[str, object] = {}
        if event.project_id:
            scope["project_id"] = str(event.project_id)
        if event.site_id:
            scope["site_id"] = str(event.site_id)

        for entity in requires:
            if entity is EntityType.PROJECT and "project_id" not in scope:
                provider = _find_provider_step(EntityType.PROJECT, built)
                if provider is not None:
                    scope["project_id"] = StepRef(provider.step_id, "project_id")
            elif entity is EntityType.SITE and "site_id" not in scope:
                provider = _find_provider_step(EntityType.SITE, built)
                if provider is not None:
                    scope["site_id"] = StepRef(provider.step_id, "site_id")
            elif entity is EntityType.USER and workflow_key is WorkflowKey.ADD_PROJECT_MEMBER:
                # The only USER-requiring workflow today; a second one with
                # a different field name would need its own case here (see
                # module docstring's stated V1 narrowness).
                provider = _find_provider_step(EntityType.USER, built)
                if provider is not None:
                    existing = str(fields.get("member_name") or "").strip()
                    if not existing or (
                        provider.full_name
                        and _normalize_name(existing) == _normalize_name(provider.full_name)
                    ):
                        fields["member_name"] = StepRef(provider.step_id, "full_name")

        step = PlanStep(
            step_id=step_id,
            workflow_key=workflow_key,
            event_type=event.event_type,
            fields=fields,
            scope=scope,
        )
        raw_steps.append(step)
        built.append(
            _BuiltStep(
                step_id=step_id,
                provides=provides,
                full_name=str(event.fields.get("full_name")) if event.fields.get("full_name") else None,
            )
        )

    if not raw_steps:
        return DecomposedPlanResult(plan=None, skipped=tuple(skipped))

    ordered = topological_order(raw_steps)
    plan = Plan(
        plan_id=plan_id,
        correlation_id=first.correlation_id,
        user_id=first.user_id,
        organization_id=first.organization_id,
        origin=origin,
        source_message_id=first.source_message_id,
        conversation_id=first.conversation_id,
        permissions=tuple(first.permissions),
        steps=ordered,
    )
    return DecomposedPlanResult(plan=plan, skipped=tuple(skipped))
