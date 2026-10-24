"""PlannerDecision.v1 — the routing decision between CanonicalEvent and the Workflow Registry.

Produced by the Planner from a ``CanonicalEvent``. Per the architecture's
layer-ownership table, the Planner "Reads CanonicalEvent, returns a
workflow_key" and must never own "knowledge of LangGraph, knowledge of any
specific graph." A ``PlannerDecision`` therefore carries only a routing key
(never a graph reference) plus enough scope for the Workflow Runtime to key
state on.

``reason`` is diagnostic/observability only — the ``CanonicalEventType`` value
that produced this decision. Consumers must branch on ``decision_type`` and
``workflow_key``, never on ``reason``; it is not a second routing contract.

Ownership: SHARED ARCHITECTURE — part of the M0 contract surface. Version: v1.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator

from .canonical_event import CanonicalEventType

CONTRACT_VERSION = "v1"


class PlannerDecisionType(str, Enum):
    """What the Planner decided to do with a CanonicalEvent."""

    START_WORKFLOW = "start_workflow"
    CLARIFY = "clarify"
    DIRECT_REPLY = "direct_reply"
    IGNORE = "ignore"


class PlannerPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


class WorkflowKey(str, Enum):
    """Canonical routing keys shared by the Planner (producer) and the future
    Workflow Registry (M6 consumer). Distinct from the coarser ``WorkflowKind``
    family enum in ``mesiri_contracts.context.enums``."""

    MATERIAL_RECEIPT = "material.receipt"
    MATERIAL_USAGE = "material.usage"
    # Material sent from one site to another (agent tool transfer_material).
    MATERIAL_TRANSFER = "material.transfer"
    EXPENSE_SUBMIT = "expense.submit"
    EQUIPMENT_USAGE = "equipment.usage"
    LABOUR_ATTENDANCE = "labour.attendance"
    # Triggered by the system after a confirmed labour attendance has named
    # new temporary workers -- never by AI planner intent. No SemanticType or
    # WORKFLOW_KEY_BY_EVENT mapping exists for it; inbound_journey.py creates
    # its WorkflowInstance directly after writing the attendance record.
    WORKER_PROMOTION = "labour.worker_promotion"
    SITE_UPDATE = "site.update"
    ACTIVITY_CONTINUATION = "site.activity_continuation"
    ACTIVITY_CORRECTION = "site.activity_correction"
    SITE_ISSUE_REPORT = "site.issue_report"
    SITE_ISSUE_CLOSE = "site.issue_close"
    WHO_AM_I = "who.am.i"
    MATERIAL_INVENTORY_QUERY = "material.inventory_query"
    LABOUR_QUERY = "labour.query"
    ACTIVITY_QUERY = "activity.query"
    DPR_REQUEST = "dpr.request"
    ACCOUNT_ADMIN = "finance.account_admin"
    ACCOUNT_BALANCE_QUERY = "finance.account_query"
    EXPENSE_QUERY = "expense.query"
    TRANSFER = "finance.transfer"
    PETTY_CASH = "finance.petty_cash"
    REVERSE = "finance.reverse"
    PROJECT_CREATE = "project.create"
    SITE_CREATE = "site.create"
    PROJECT_DETAIL_QUERY = "project.detail_query"
    AUTOMATION_SETUP = "automation.setup"
    ADD_PROJECT_MEMBER = "project.add_member"
    CREATE_USER = "user.create"


class PlannerDecision(BaseModel):
    """The Planner's routing decision for a single CanonicalEvent."""

    version: str = CONTRACT_VERSION

    # -- Provenance / linkage (correlation must survive end to end) ----------
    correlation_id: str
    source_message_id: str
    causation_event_id: str | None = None

    # -- The decision -----------------------------------------------------
    decision_type: PlannerDecisionType
    workflow_key: WorkflowKey | None = None
    reason: CanonicalEventType
    priority: PlannerPriority = PlannerPriority.NORMAL

    # -- Scope passthrough (the Workflow Runtime keys state on this) --------
    organization_id: str
    user_id: str
    project_id: str | None = None
    site_id: str | None = None

    # -- Consumer hints ------------------------------------------------------
    missing_fields: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _workflow_key_matches_decision_type(self) -> PlannerDecision:
        """workflow_key is set if and only if decision_type is START_WORKFLOW."""
        if self.decision_type is PlannerDecisionType.START_WORKFLOW and self.workflow_key is None:
            raise ValueError("workflow_key is required when decision_type is START_WORKFLOW")
        if (
            self.decision_type is not PlannerDecisionType.START_WORKFLOW
            and self.workflow_key is not None
        ):
            raise ValueError("workflow_key must be None unless decision_type is START_WORKFLOW")
        return self
