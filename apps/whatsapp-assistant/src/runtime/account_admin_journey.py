"""Deterministic account-admin command journey (Finance Module Slice 6, account-admin scope).

"create account X" / "rename X to Y" / "deactivate X" bypass the AI
understanding pipeline entirely -- same principle as
handle_whoami_trigger/handle_greeting_trigger ("a plain deterministic
command costs no tokens"). Unlike those, this still needs to reach
WorkflowRuntime (every business-affecting write is confirmed before it
commits -- architecture rule #4), so it lives alongside inbound_journey.py
rather than as a synchronous InteractionHandler fast-path method, and
constructs a minimal CanonicalEventV2 + PlannerDecisionV2 directly instead
of going through canonicalization/planner.decide() -- there is nothing for
the AI understanding pipeline to extract here; the regex parser already has
every field.

As of 2026-07-26 this is no longer the only way to reach account-admin: it
remains a zero-token fast path checked first (see runtime/dependencies.py),
but any phrasing it doesn't recognize -- different wording, voice, non-
English -- now falls through to the normal AI-understood journey via
SemanticType.ACCOUNT_ADMIN (see canonicalization/mapping.py,
platform/ai's extraction prompts, and runtime/inbound_journey.py's own
_ACCOUNT_ADMIN_ROLES gate, which enforces the identical role set this
module's _ACCOUNT_ADMIN_ROLES does for that path). Both converge on the
same WorkflowKey.ACCOUNT_ADMIN graph and the same
application/finance/validation.py role check.

Execution (the actual create/rename/deactivate SQL) does NOT happen here --
once WorkflowRuntime.start() returns STARTED, the draft sits AWAITING_CONFIRMATION
exactly like an expense capture draft, and the user's "YES" reply is picked
up by the *existing* InteractionHandler.handle_fast_path -> ActionTypeRoutingDispatcher
path (see runtime/dependencies.py's execution_dispatcher wiring) -- no new
code needed there, since that routing is already generic on DraftActionType.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from channel.replies import ReplySpec
from mesiri.authorization.roles import MONEY_MANAGE_ROLES
from mesiri_contracts.assistant.canonical_event import CanonicalEventType, IntentCompleteness
from mesiri_contracts.assistant.enums import InputModality
from mesiri_contracts.assistant.planner_decision import (
    PlannerDecisionType,
    PlannerPriority,
    WorkflowKey,
)
from mesiri_contracts.assistant.v2.canonical_event import CanonicalEventV2
from mesiri_contracts.assistant.v2.planner_decision import PlannerDecisionV2
from mesiri_contracts.common.ids import new_id
from workflows import WorkflowRunResult, WorkflowRuntime

from .account_admin_parser import parse_account_admin_command

if TYPE_CHECKING:
    from backend.ports import ActorIdentity
    from mesiri_contracts.assistant.normalized_message import NormalizedMessage

# Deliberately narrower than authorization/roles.py's ORG_WIDE_ROLES (ADMIN
# only) -- FINANCE may also manage accounts, matching the permission table
# in docs/execution/FINANCE_MODULE_PLAN.md. Same normalization idiom as
# mesiri.authorization.roles.role_is_org_wide (str(role or "").strip().upper()).
# 7 Nov 2026 (SEC-03): the one rule in mesiri.authorization.roles.
_ACCOUNT_ADMIN_ROLES = MONEY_MANAGE_ROLES


@dataclass(frozen=True, slots=True)
class AccountAdminCommandResult:
    """None from try_handle() means "not a recognized command at all" --
    the caller falls through to the normal journey. This type is only ever
    returned once the text *is* recognized, so reply is always populated (a
    permission denial included).

    ``reply`` is the full ReplySpec, not a bare string -- a live report
    ("Confirm this action? Create a new user... Reply YES to confirm or NO
    to cancel", sent as plain text with no tappable buttons) turned out to
    apply here too: ACCOUNT_ADMIN's graph produces a real confirmable draft
    the same shape as CREATE_USER's, and this used to render it via
    render_workflow_run_reply (string-only) instead of render_workflow_run_
    reply_spec (the one place that decides plain text vs Yes/No buttons vs
    a tappable list for a WorkflowRunResult)."""

    reply: ReplySpec
    workflow_run: WorkflowRunResult | None = None


async def try_handle_account_admin_command(
    message: NormalizedMessage,
    actor: ActorIdentity | None,
    workflow_runtime: WorkflowRuntime,
) -> AccountAdminCommandResult | None:
    """Text/interactive only -- voice has no text until Sarvam transcribes
    it, same reasoning as handle_whoami_trigger; a spoken account-admin
    command isn't wired to this fast path and falls through to the normal
    journey, which planner.decide() has no route for (DIRECT_REPLY)."""
    if message.modality not in (InputModality.TEXT, InputModality.INTERACTIVE):
        return None
    if not message.text:
        return None

    parsed = parse_account_admin_command(message.text)
    if parsed is None:
        return None

    if actor is None or not actor.organization_id:
        return AccountAdminCommandResult(
            reply=ReplySpec(text="⛔ I couldn't identify your organization for that command.")
        )

    if str(actor.role or "").strip().upper() not in _ACCOUNT_ADMIN_ROLES:
        return AccountAdminCommandResult(
            reply=ReplySpec(text="⛔ Only an admin or finance user can manage accounts.")
        )

    event = CanonicalEventV2(
        event_id=new_id("evt"),
        correlation_id=message.correlation_id,
        source_message_id=message.message_id,
        event_type=CanonicalEventType.ACCOUNT_ADMIN_REQUESTED,
        completeness=IntentCompleteness.ACTIONABLE,
        organization_id=actor.organization_id,
        user_id=actor.user_id,
        fields=dict(parsed.fields),
    )
    decision = PlannerDecisionV2(
        correlation_id=message.correlation_id,
        source_message_id=message.message_id,
        causation_event_id=event.event_id,
        decision_type=PlannerDecisionType.START_WORKFLOW,
        workflow_key=WorkflowKey.ACCOUNT_ADMIN,
        reason=event.event_type,
        priority=PlannerPriority.NORMAL,
        organization_id=actor.organization_id,
        user_id=actor.user_id,
    )
    result = await workflow_runtime.start(decision, event)

    from runtime.inbound_journey.reply import render_workflow_run_reply_spec

    return AccountAdminCommandResult(
        reply=render_workflow_run_reply_spec(result),
        workflow_run=result,
    )
