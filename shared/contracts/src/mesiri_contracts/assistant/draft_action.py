"""DraftAction.v1 — the proposed business action a workflow produces, awaiting confirmation.

Produced by the Workflow Runtime (M6) from collected fields. A DraftAction is
the workflow→application handoff: it describes *what would be recorded* if the
user confirms, but nothing is persisted to the domain until confirmation
(architecture rule #4). It carries no domain rules and no SQL knowledge — it is
a pure data description of an intended action.

Ownership: SHARED ARCHITECTURE — part of the M0 contract surface. Version: v1.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

CONTRACT_VERSION = "v1"


class DraftActionType(str, Enum):
    """The kind of business record a draft would create."""

    RECORD_MATERIAL_RECEIPT = "record_material_receipt"
    RECORD_MATERIAL_USAGE = "record_material_usage"
    TRANSFER_MATERIAL = "transfer_material"
    RECORD_EXPENSE = "record_expense"
    MANAGE_MONEY_ACCOUNT = "manage_money_account"
    TRANSFER_MONEY = "transfer_money"
    REVERSE_TRANSACTION = "reverse_transaction"
    RECORD_LABOUR_ATTENDANCE = "record_labour_attendance"
    CREATE_ACTIVITY = "create_activity"
    ADD_PROGRESS_UPDATE = "add_progress_update"
    CORRECT_ACTIVITY_QUANTITY = "correct_activity_quantity"
    RECORD_SITE_ISSUE = "record_site_issue"
    CLOSE_SITE_ISSUE = "close_site_issue"
    CREATE_PROJECT = "create_project"
    CREATE_SITE = "create_site"
    CREATE_AUTOMATION = "create_automation"
    ADD_PROJECT_MEMBER = "add_project_member"
    CREATE_USER = "create_user"
    # Future v1 domains: record_equipment_usage


class DraftAction(BaseModel):
    """A proposed business action produced by a workflow, awaiting confirmation."""

    version: str = CONTRACT_VERSION

    # -- Provenance / linkage (correlation must survive end to end) ----------
    draft_id: str
    correlation_id: str
    causation_event_id: str | None = None
    workflow_instance_id: str

    # -- The proposed action -------------------------------------------------
    action_type: DraftActionType

    # -- Tenancy / scope ------------------------------------------------------
    organization_id: str
    user_id: str
    project_id: str | None = None
    site_id: str | None = None

    # -- The structured business payload that would be recorded --------------
    fields: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "forbid"}
