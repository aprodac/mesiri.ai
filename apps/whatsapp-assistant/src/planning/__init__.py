"""Composite-request plan layer (docs/execution/COMPOSITE_REQUEST_PLAN_LAYER.md).

The shared plan structures, ordering and binding. Today's one producer is
runtime/member_create_plan.py (CREATE_USER -> ADD_PROJECT_MEMBER); the
message decomposer that also built plans went with the classic pipeline
(ARCH-06).
"""

from __future__ import annotations

from .binding import UnresolvedStepRefError, build_event, resolve_step
from .ordering import PlanCycleError, PlanUnresolvedRefError, topological_order
from .outputs import build_step_outputs
from .plan import (
    SCOPE_KEYS,
    InvalidScopeKeyError,
    Plan,
    PlanOrigin,
    PlanStep,
    StepRef,
    StepStatus,
)
from .plan_store import PlanStore

__all__ = [
    "SCOPE_KEYS",
    "InvalidScopeKeyError",
    "Plan",
    "PlanOrigin",
    "PlanStep",
    "StepRef",
    "StepStatus",
    "UnresolvedStepRefError",
    "build_event",
    "build_step_outputs",
    "resolve_step",
    "PlanCycleError",
    "PlanUnresolvedRefError",
    "topological_order",
    "PlanStore",
]
