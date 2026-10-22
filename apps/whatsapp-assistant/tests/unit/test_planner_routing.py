"""Every event type the routing table names starts a workflow that exists."""

from __future__ import annotations

from mesiri_contracts.assistant.planner_decision import WorkflowKey
from planner.routing import WORKFLOW_KEY_BY_EVENT

#: Routed but genuinely never built yet (draft_action.py's DraftActionType
#: docstring: "Future v1 domains: record_equipment_usage") -- not a
#: regression, a known-open scope gap. Keep this set to exactly the keys
#: that are deliberately incomplete; anything else missing from the
#: registry below is a bug, not a backlog item.
_KNOWN_UNIMPLEMENTED_WORKFLOW_KEYS = frozenset({WorkflowKey.EQUIPMENT_USAGE})


def test_every_routed_workflow_key_has_a_registered_graph() -> None:
    """Regression guard: WORKFLOW_KEY_BY_EVENT once pointed
    ACTIVITY_CONTINUATION_REQUESTED at WorkflowKey.ACTIVITY_CONTINUATION
    after that key's registry entry was retired (the workflows merged into
    WorkflowKey.SITE_UPDATE, see docs/execution/ACTIVITY_RESOLUTION_AND_
    CORRECTION_PLAN.md) -- silently degrading every material-usage-linked
    activity segment to workflows/runtime.py's "no_graph" outcome, with
    nothing in this table's own tests to catch it. Every CanonicalEventType
    this table routes must resolve to a WorkflowKey workflows.registry
    actually has a compiled graph for, except the deliberately-open gaps
    listed above."""
    from workflows.registry import is_implemented

    unimplemented = {
        event_type.value: workflow_key.value
        for event_type, workflow_key in WORKFLOW_KEY_BY_EVENT.items()
        if not is_implemented(workflow_key)
        and workflow_key not in _KNOWN_UNIMPLEMENTED_WORKFLOW_KEYS
    }
    assert unimplemented == {}
