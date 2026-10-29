"""System graph for the control panel — how the assistant reacts to messages.

Platform-admin only. Two capabilities:

1. GET ``/admin/system-graph`` — a structured, drill-down-ready map of the
   inbound pipeline. Nothing here is hand-drawn: the Mermaid diagram, the stage
   nodes, the workflow list, the required fields and the example messages are all
   generated on request from the live tables the runtime actually uses
   (understanding modality branches, ``canonicalization.mapping``, planner
   ``routing``, workflow ``registry``) plus each compiled LangGraph's own
   ``draw_mermaid()``, and the example copy from ``channel.replies``. Change any
   of those and this endpoint reflects it on the next refresh.

2. POST ``/admin/system-graph/simulate`` — run one message through the *real*
   pipeline (real AI providers) as a chosen org+user, capturing the reply instead
   of sending it to WhatsApp, and returning the full routing trace. Single-shot
   and side-effect-free: the material graph only builds a draft and asks for
   confirmation; nothing is persisted until a "YES" resume, which this harness
   never sends. See the ``dry_run`` marker in the response.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from mesiri.domains.shared.auth import require_platform_admin
from runtime.reply_capture import (
    CapturedReply,
    ReplyCapture,
    ReplyOption,
    UserNotFound,
    identity_refusal,
    run_captured,
    user_whatsapp_number,
)

router = APIRouter(prefix="/admin/system-graph", tags=["admin"])


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------
class StageNode(BaseModel):
    id: str
    label: str
    description: str | None = None


class PipelineStage(BaseModel):
    key: str
    title: str
    summary: str
    nodes: list[StageNode]


class WorkflowGraphInfo(BaseModel):
    workflow_key: str
    title: str
    implemented: bool
    canonical_event: str | None = None
    semantic_type: str | None = None
    required_fields: list[str] = []
    required_field_labels: list[str] = []
    node_names: list[str] = []
    example_messages: list[str] = []
    mermaid: str | None = None
    # Only set for workflows that reach a confirmation prompt with a real
    # execution dispatcher wired (today: material.receipt / material.usage).
    # Shows what happens AFTER the draft — confirm/reject/cancel/correct and
    # the resulting execution outcome — which the 2-node build graph alone
    # doesn't capture.
    lifecycle_mermaid: str | None = None


class FastPathInfo(BaseModel):
    """A deterministic, pre-AI reply path (runtime/dependencies.py's
    _on_normalized). These never touch the understanding pipeline — matched
    against static phrase lists, not model output — so they're shown
    separately from the AI-routed workflows above."""

    key: str
    title: str
    description: str
    example_messages: list[str] = []


class HardcodedReplyInfo(BaseModel):
    """A reply that is a fixed/templated string, not model output — the user
    never gets an answer generated for their specific message here, just one
    of a small set of canned texts. Distinct from fast_paths (which is about
    *when the AI is skipped*); this is about *every* canned string in the
    system, including ones the AI pipeline itself falls back to (e.g. the
    'general question' canned reply, or the post-confirmation outcome
    replies) — so a wrong-but-plausible-looking reply can be traced back to
    its exact source line."""

    key: str
    title: str
    source: str
    trigger: str
    template: str
    flag: str | None = None


class SemanticTypeInfo(BaseModel):
    """One understanding hypothesis (``SemanticType``) traced through the whole
    routing chain: semantic type -> canonical event(s) -> workflow(s) -> built?.
    Derived live from the same tables the runtime uses (canonicalization.mapping,
    planner.routing, workflows.registry), so it can't drift from what ships.

    The inverse view of ``workflows`` above: that list is keyed by workflow, this
    one by what Understanding decided the message was *about*."""

    semantic_type: str
    description: str
    # How the type gets set: AI extraction for most; a couple also/only via a
    # deterministic pre-AI shortcut.
    detection: str
    # 1 event, or 2 for MATERIAL_UPDATE (splits by direction: received / used).
    canonical_events: list[str] = []
    # Workflow(s) this routes to; empty when it's answered by a direct reply
    # (GENERAL_QUESTION / UNKNOWN never start a workflow).
    workflow_keys: list[str] = []
    # True when at least one mapped workflow is actually built (registered in
    # workflows.registry).
    implemented: bool = False
    # Short note for the types that never reach a workflow.
    routes_to_reply: str | None = None
    required_field_labels: list[str] = []
    example_messages: list[str] = []


class SystemGraphResponse(BaseModel):
    mermaid: str
    fast_paths: list[FastPathInfo]
    hardcoded_replies: list[HardcodedReplyInfo]
    stages: list[PipelineStage]
    semantic_types: list[SemanticTypeInfo]
    workflows: list[WorkflowGraphInfo]


# The captured-reply shapes live with the capture itself (shared with the
# dashboard's "Tell Mesiri", WEB-36); same fields as before.
ReplyOptionInfo = ReplyOption
StructuredReplyInfo = CapturedReply


class SimulateRequest(BaseModel):
    organization_id: uuid.UUID
    user_id: uuid.UUID
    text: str = ""
    modality: str = "text"
    interactive_reply_id: str | None = None


class ResetSimulateRequest(BaseModel):
    organization_id: uuid.UUID
    user_id: uuid.UUID


class SimulateResponse(BaseModel):
    dry_run: bool = True
    ran_as_wa_id: str
    # Which check produced the reply — mirrors runtime/dependencies.py's
    # _on_normalized order: identity_gate -> confirmation_fast_path ->
    # category_tap -> greeting_trigger -> whoami_trigger -> ai_pipeline.
    # Everything before ai_pipeline is deterministic and never touches a model.
    routed_via: str
    replies: list[str]
    structured_replies: list[StructuredReplyInfo] = []
    understanding: dict | None = None
    resolved_context: dict | None = None
    canonical_event: dict | None = None
    planner_decision: dict | None = None
    workflow_run: dict | None = None



# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def _node_id(value: str) -> str:
    """Mermaid-safe node id."""
    return value.replace(".", "_").replace("-", "_")


# Workflows whose confirmation reply reaches a real ExecutionDispatcher today
# (see MaterialExecutionDispatcher) — the only ones _confirmation_lifecycle_
# mermaid actually applies to.
_LIFECYCLE_WORKFLOWS: set[str] = {"material.receipt", "material.usage"}

def _workflow_titles() -> dict[str, str]:
    """Display title per registered workflow, read from workflows/registry.py.

    Hand-maintained until 2026-07-30, by which point it named 8 of the 26
    registered workflows and the control panel simply rendered the other 18
    untitled.
    """
    from workflows.registry import iter_definitions

    return {d.key.value: d.title for d in iter_definitions()}


_WORKFLOW_TITLES: dict[str, str] = _workflow_titles()

# Workflows that only read and reply (COMPLETED with no draft_action) — never
# reach a confirmation prompt, so they have no post-confirmation lifecycle.
_READ_ONLY_WORKFLOWS: set[str] = {"who.am.i", "material.inventory_query"}


def _example_messages_by_workflow() -> dict[str, list[str]]:
    """Example messages per workflow, read from workflows/registry.py so the
    control panel shows exactly what the assistant tells users to send.

    These used to be recovered by regex-scraping double-quoted fragments out
    of channel.replies prompt copy (a `_quoted()` helper over `_EXAMPLES` and
    `_CATEGORY_PROMPTS`), which meant the control panel's documentation
    depended on the punctuation of user-facing sentences. The registry now
    carries the examples as data and both surfaces read the same field.
    """
    from workflows.registry import iter_definitions

    return {d.key.value: list(d.examples) for d in iter_definitions() if d.examples}


def _fast_paths() -> list[FastPathInfo]:
    """The deterministic checks that run before the AI pipeline is ever
    touched, in the exact order runtime/message_journey.py's _on_normalized
    runs them. Phrase examples are imported from the same JSON-backed
    vocabulary the real classifiers use — never hand-duplicated."""
    from channel.replies import CATEGORY_ROWS
    from interactions.classifier import _PHRASE_SETS
    from mesiri_ai.greeting_classifier import _GREETING_PHRASES
    from mesiri_ai.whoami_classifier import _WHOAMI_PHRASES

    return [
        FastPathInfo(
            key="confirmation_resume",
            title="Confirmation reply",
            description=(
                "When the user has a workflow awaiting confirmation, a reply matching "
                "confirm/reject/cancel vocabulary resumes it immediately — the AI "
                "pipeline is skipped entirely."
            ),
            example_messages=(
                _PHRASE_SETS["confirm"][:2]
                + _PHRASE_SETS["reject"][:1]
                + _PHRASE_SETS["cancel"][:1]
            ),
        ),
        FastPathInfo(
            key="category_tap",
            title="Category menu tap",
            description=(
                "Tapping a row on the WhatsApp category menu (Material / Equipment / "
                "Labour / Expense) sends a deterministic prompt for that category — no AI "
                "call, the row id is matched verbatim. It also stores a semantic_hint "
                "(channel/replies.py:CATEGORY_SEMANTIC_HINT) for that user, which is "
                "popped and fed into extraction on their VERY NEXT message only — a "
                "one-shot bias, not sticky state, so this simulate endpoint (single "
                "message only) can't reproduce it end-to-end."
            ),
            example_messages=[r.title for r in CATEGORY_ROWS],
        ),
        FastPathInfo(
            key="greeting_trigger",
            title="Greeting / menu",
            description=(
                "A bare greeting or menu word opens the tappable category menu — "
                "matched against a static phrase list, never AI-classified."
            ),
            example_messages=sorted(_GREETING_PHRASES)[:6],
        ),
        FastPathInfo(
            key="whoami_trigger",
            title="Who am I",
            description=(
                "A bare identity question (matched against this English phrase list) "
                "returns the caller's name/role/org/projects/sites directly — no AI call. "
                "A non-English identity question that misses this list still gets answered "
                "correctly: Understanding re-checks after translation and routes it to the "
                "same reply via the AI pipeline (see 'Who-am-I identity summary' below)."
            ),
            example_messages=sorted(_WHOAMI_PHRASES)[:6],
        ),
    ]


def _who_am_i_sample_reply() -> str:
    """Renders the real who.am.i workflow node against a representative state,
    so the catalog shows exactly what a project-specific sub-query looks like
    (the case the pre-pipeline fast path's simpler template can't produce)."""
    from workflows.state import WorkflowGraphState
    from workflows.who_am_i.nodes import generate_identity_reply

    state: WorkflowGraphState = {
        "collected_fields": {
            "actor_profile": {
                "full_name": "Jane Doe",
                "role": "project_manager",
                "org_name": "Acme Construction",
                "projects": [
                    {"name": "Green Valley", "location": "East Zone", "status": "at_risk"},
                    {"name": "Metro Heights", "location": "South Zone", "status": "on_track"},
                ],
                "sites": [{"name": "East Zone Site"}],
                "query_text": "which project am i on",
            }
        }
    }
    return generate_identity_reply(state).get("pending_prompt", "")


def _inventory_query_sample_reply() -> str:
    """Renders the real material.inventory_query workflow node against a
    representative stock snapshot."""
    from workflows.material_inventory_query.nodes import generate_inventory_reply
    from workflows.state import WorkflowGraphState

    state: WorkflowGraphState = {
        "collected_fields": {
            "material_name": "cement",
            "inventory_levels": [
                {
                    "material_name": "Cement",
                    "unit": "bags",
                    "current_stock": 30,
                    "received": 50,
                    "used": 20,
                }
            ],
        }
    }
    return generate_inventory_reply(state).get("pending_prompt", "")


def _confirmation_lifecycle_mermaid() -> str:
    """What happens after a workflow's draft/confirmation prompt, generated
    from the real enums that drive it (interactions.intent.InteractionIntent,
    workflows.runtime.WorkflowResumeStatus, and the execution outcome from
    mesiri_contracts.application.results.execution_result.ExecutionStatus).
    Only reachable for workflows with a real ExecutionDispatcher wired —
    today, that's the material dispatcher only, so this is attached to
    material.receipt / material.usage."""
    from interactions.intent import InteractionIntent
    from mesiri_contracts.application.results.execution_result import ExecutionStatus
    from workflows.runtime import WorkflowResumeStatus

    return "\n".join(
        [
            "flowchart TD",
            '  draft["Draft built — confirmation prompt sent"]',
            f'  draft -->|"{InteractionIntent.CONFIRM.value}"| confirmed["{WorkflowResumeStatus.CONFIRMED.value}"]',
            f'  draft -->|"{InteractionIntent.REJECT.value}"| rejected["{WorkflowResumeStatus.REJECTED.value}"]',
            f'  draft -->|"{InteractionIntent.CANCEL.value}"| cancelled["{WorkflowResumeStatus.CANCELLED.value}"]',
            f'  draft -->|"{InteractionIntent.CORRECTION.value} (LLM-classified)"| corrected["Draft fields updated"]',
            "  corrected --> draft",
            f'  draft -->|"{InteractionIntent.AMBIGUOUS.value}"| reprompt["Ask user to restate"]',
            "  reprompt --> draft",
            f'  draft -->|"{InteractionIntent.UNRELATED.value}"| newmsg["Treated as a fresh message"]',
            '  confirmed --> dispatch["Material dispatcher executes the domain write"]',
            f'  dispatch -->|success| succeeded["{ExecutionStatus.SUCCEEDED.value}"]',
            f'  dispatch -->|"duplicate delivery"| already["{ExecutionStatus.ALREADY_EXECUTED.value}"]',
            f'  dispatch -->|failure| failed["{ExecutionStatus.FAILED.value}"]',
            '  rejected --> doneReply["Reply: cancelled"]',
            "  cancelled --> doneReply",
        ]
    )


def _hardcoded_replies() -> list[HardcodedReplyInfo]:
    """Catalog of every fixed/templated reply in the system, rendered from the
    real source functions/constants wherever construction is cheap (so this
    can never drift from what actually ships) — never hand-retyped strings.
    `flag` calls out entries that are misleading or leftover dev scaffolding,
    found by reading the source: the general-question canned reply never
    actually answers the question asked, and render_execution_reply's FAILED
    case claims an automatic retry that no code anywhere implements."""
    from backend.ports import ActorIdentity, ProjectSummary, SiteSummary
    from channel.replies import (
        render_category_prompt,
        render_direct_reply,
        render_greeting_menu,
        render_understanding_failed_reply,
        render_unsupported_reply,
    )
    from context.live_identity import (
        NO_ORG_MESSAGE,
        ORG_SUSPENDED_MESSAGE,
        UNREGISTERED_MESSAGE,
        whoami_reply,
    )

    def _category_prompt_text(row_id: str) -> str:
        prompt = render_category_prompt(row_id)
        return prompt.text if prompt is not None else ""
    from interactions.response_handler import render_execution_reply, render_resume_reply
    from mesiri_contracts.application.results.execution_result import (
        ExecutionResult,
        ExecutionStatus,
    )
    from mesiri_contracts.assistant.canonical_event import CanonicalEventType
    from mesiri_contracts.assistant.planner_decision import PlannerDecisionType
    from mesiri_contracts.assistant.v2.planner_decision import PlannerDecisionV2
    from workflows.runtime import WorkflowResumeResult, WorkflowResumeStatus

    def _decision(reason: CanonicalEventType) -> PlannerDecisionV2:
        return PlannerDecisionV2(
            correlation_id="sample",
            source_message_id="sample",
            decision_type=PlannerDecisionType.DIRECT_REPLY,
            reason=reason,
            organization_id="00000000-0000-0000-0000-000000000000",
            user_id="00000000-0000-0000-0000-000000000000",
        )

    def _resume(status: WorkflowResumeStatus) -> WorkflowResumeResult:
        return WorkflowResumeResult(
            status=status, workflow_instance_id="sample", correlation_id="sample"
        )

    def _execution(status: ExecutionStatus, **kw: object) -> ExecutionResult:
        return ExecutionResult(status=status, idempotency_key="sample", **kw)

    sample_actor = ActorIdentity(
        user_id="sample",
        full_name="Jane Doe",
        role="project_manager",
        organization_id="sample",
        org_name="Acme Construction",
        org_active=True,
        projects=[
            ProjectSummary(
                id="p1",
                name="Green Valley",
                location="East Zone",
                code="GV-01",
                status="at_risk",
                progress=42,
                open_issues=1,
            )
        ],
        sites=[SiteSummary(id="s1", name="East Zone Site")],
    )

    entries: list[HardcodedReplyInfo] = [
        # --- Identity gate (context/live_identity.py) ---
        HardcodedReplyInfo(
            key="unregistered_number",
            title="Unregistered WhatsApp number",
            source="context/live_identity.py:UNREGISTERED_MESSAGE",
            trigger="Sender's WhatsApp number has no matching user record.",
            template=UNREGISTERED_MESSAGE,
        ),
        HardcodedReplyInfo(
            key="no_organization",
            title="User has no organization",
            source="context/live_identity.py:NO_ORG_MESSAGE",
            trigger="User exists but isn't attached to any organization.",
            template=NO_ORG_MESSAGE.format(name="{name}"),
        ),
        HardcodedReplyInfo(
            key="org_suspended",
            title="Organization suspended",
            source="context/live_identity.py:ORG_SUSPENDED_MESSAGE",
            trigger="User's organization is not Active.",
            template=ORG_SUSPENDED_MESSAGE,
        ),
        HardcodedReplyInfo(
            key="whoami_reply_fast_path",
            title="Who-am-I — pre-pipeline fast path (English text)",
            source="context/live_identity.py:whoami_reply()",
            trigger=(
                'A bare "who am i"/"my profile"/etc, matched by '
                "interactions/handler.py:handle_whoami_trigger BEFORE Understanding runs "
                "(see the whoami_trigger fast path above). Always the full profile — no "
                "project/site drill-down."
            ),
            template=whoami_reply(sample_actor),
        ),
        HardcodedReplyInfo(
            key="whoami_reply_workflow",
            title="Who-am-I — workflow (voice / non-English text)",
            source="workflows/who_am_i/nodes.py:generate_identity_reply()",
            trigger=(
                "The who.am.i LangGraph workflow (SemanticType.WHOAMI_QUESTION -> "
                "CanonicalEventType.IDENTITY_LOOKUP_REQUESTED -> START_WORKFLOW). "
                "Supports project-specific and site-specific sub-queries."
            ),
            template=_who_am_i_sample_reply(),
            flag=(
                "For plain-English text this workflow is effectively unreachable: "
                "handle_whoami_trigger above matches the exact same phrase list "
                "(whoami_phrases.json) and always intercepts first, before Understanding "
                "ever runs — so English 'which project am I on'-style sub-queries never "
                "reach this richer, project/site-aware template. Only voice and "
                "non-English text (which the fast path can't check pre-translation) "
                "actually get here."
            ),
        ),
        HardcodedReplyInfo(
            key="inventory_query_reply",
            title="Material inventory snapshot",
            source="workflows/material_inventory_query/nodes.py:generate_inventory_reply()",
            trigger=(
                "SemanticType.INVENTORY_QUERY -> CanonicalEventType.INVENTORY_QUERY_ASKED "
                "-> START_WORKFLOW. Stock levels are queried read-only in "
                "runtime/inbound_journey.py before the graph runs (the workflow itself "
                "never touches the database) and injected as inventory_levels."
            ),
            template=_inventory_query_sample_reply(),
        ),
        # --- Direct / fallback replies (channel/replies.py) ---
        HardcodedReplyInfo(
            key="greeting_returning_user",
            title="Greeting — returning user",
            source="channel/replies.py:render_greeting_menu()",
            trigger='A bare "hi"/"menu"/etc, or anything UNRECOGNIZED that reaches the planner as DIRECT_REPLY.',
            template=render_greeting_menu(is_first_message=False).text,
        ),
        HardcodedReplyInfo(
            key="greeting_first_message",
            title="Greeting — first-ever message",
            source="channel/replies.py:render_greeting_menu(is_first_message=True)",
            trigger="Same as above, for a sender's very first message (is_first_message isn't wired anywhere yet — always False today).",
            template=render_greeting_menu(is_first_message=True).text,
        ),
        HardcodedReplyInfo(
            key="general_question_canned",
            title="General question — canned answer",
            source="channel/replies.py:render_direct_reply() GENERAL_QUESTION_ASKED case",
            trigger='semantic_type=general_question (e.g. "what can you do", or any question the model has no other bucket for).',
            template=render_direct_reply(_decision(CanonicalEventType.GENERAL_QUESTION_ASKED)).text,
            flag="Always the same text regardless of what was actually asked — it doesn't answer the question, it describes what Mesiri records.",
        ),
        HardcodedReplyInfo(
            key="category_prompt_material",
            title="Category prompt — Material",
            source="channel/replies.py:render_category_prompt('cat_material')",
            trigger='Tapping "Material" on the category menu (asks Arrived/Used via buttons).',
            template=_category_prompt_text("cat_material"),
        ),
        HardcodedReplyInfo(
            key="category_prompt_equipment",
            title="Category prompt — Equipment",
            source="channel/replies.py:render_category_prompt('cat_equipment')",
            trigger='Tapping "Equipment & Machinery" on the category menu.',
            template=_category_prompt_text("cat_equipment"),
        ),
        HardcodedReplyInfo(
            key="category_prompt_labour",
            title="Category prompt — Labour",
            source="channel/replies.py:render_category_prompt('cat_labour')",
            trigger='Tapping "Labour" on the category menu.',
            template=_category_prompt_text("cat_labour"),
        ),
        HardcodedReplyInfo(
            key="category_prompt_expense",
            title="Category prompt — Expense",
            source="channel/replies.py:render_category_prompt('cat_expense')",
            trigger='Tapping "Expense" on the category menu.',
            template=_category_prompt_text("cat_expense"),
        ),
        HardcodedReplyInfo(
            key="understanding_failed",
            title="Understanding failed",
            source="channel/replies.py:render_understanding_failed_reply()",
            trigger="Extraction/speech/vision confidence came back UNUSABLE — the AI couldn't make sense of the message at all.",
            template=render_understanding_failed_reply(),
        ),
        HardcodedReplyInfo(
            key="unsupported_workflow",
            title="Understood, but not supported",
            source="channel/replies.py:render_unsupported_reply()",
            trigger="A real intent was understood (expense/equipment/labour/site-update) but that workflow isn't built yet — see Workflows above.",
            template=render_unsupported_reply(),
        ),
        # --- Post-confirmation outcome replies (interactions/response_handler.py) ---
        HardcodedReplyInfo(
            key="resume_rejected",
            title="Confirmation — rejected",
            source="interactions/response_handler.py:render_resume_reply()",
            trigger='User replied "no" and no ExecutionDispatcher is wired for that workflow (M7-only path).',
            template=render_resume_reply(_resume(WorkflowResumeStatus.REJECTED)),
        ),
        HardcodedReplyInfo(
            key="resume_cancelled",
            title="Confirmation — cancelled",
            source="interactions/response_handler.py:render_resume_reply()",
            trigger='User replied "cancel"/"stop".',
            template=render_resume_reply(_resume(WorkflowResumeStatus.CANCELLED)),
        ),
        HardcodedReplyInfo(
            key="resume_already_handled",
            title="Confirmation — already handled",
            source="interactions/response_handler.py:render_resume_reply()",
            trigger="Duplicate WhatsApp delivery / double reply to an already-resolved confirmation.",
            template=render_resume_reply(_resume(WorkflowResumeStatus.ALREADY_RESOLVED)),
        ),
        HardcodedReplyInfo(
            key="execution_succeeded",
            title="Execution — succeeded",
            source="interactions/response_handler.py:render_execution_reply()",
            trigger="User confirmed and the material dispatcher's domain write succeeded (also the CONFIRMED text for any workflow without a dispatcher).",
            template=render_execution_reply(
                _execution(ExecutionStatus.SUCCEEDED, material_row_id="sample")
            ),
        ),
        HardcodedReplyInfo(
            key="execution_rejected",
            title="Execution — rejected",
            source="interactions/response_handler.py:render_execution_reply()",
            trigger="The domain layer rejected the confirmed action (a business rule failed).",
            template=render_execution_reply(
                _execution(
                    ExecutionStatus.REJECTED, rejection_reasons=["<reason from the domain layer>"]
                )
            ),
        ),
        HardcodedReplyInfo(
            key="execution_failed",
            title="Execution — failed",
            source="interactions/response_handler.py:render_execution_reply()",
            trigger="The dispatcher caught an unhandled exception during the domain write (mesiri.application.materials.dispatcher).",
            template=render_execution_reply(_execution(ExecutionStatus.FAILED)),
        ),
    ]
    return entries


def _workflow_node_names(graph: object | None) -> list[str]:
    """Node ids of a compiled LangGraph, minus the synthetic start/end."""
    if graph is None:
        return []
    try:
        nodes = graph.get_graph().nodes  # type: ignore[attr-defined]
        return [n for n in nodes if n not in ("__start__", "__end__")]
    except Exception:  # noqa: BLE001
        return []


# ---------------------------------------------------------------------------
# Pipeline map (structured)
# ---------------------------------------------------------------------------
def _build_stages() -> list[PipelineStage]:
    """The four pipeline stages as structured, clickable nodes."""
    from canonicalization.mapping import REQUIRED_FIELDS
    from mesiri_contracts.assistant.canonical_event import CanonicalEventType
    from mesiri_contracts.assistant.planner_decision import PlannerDecisionType

    understanding = PipelineStage(
        key="understanding",
        title="1 · Understanding",
        summary="Turns any message into text + structured fields. The path depends on modality.",
        nodes=[
            StageNode(id="text", label="Text / interactive", description="Straight to extraction."),
            StageNode(
                id="voice",
                label="Voice",
                description="Speech-to-text + translation, then extraction.",
            ),
            StageNode(
                id="media",
                label="Image / document",
                description="Vision (OCR / description), then extraction.",
            ),
            StageNode(
                id="extraction",
                label="Structured extraction",
                description="LLM pulls fields (material, quantity, amount…) and a semantic type.",
            ),
        ],
    )
    canonicalization = PipelineStage(
        key="canonicalization",
        title="2 · Canonicalization",
        summary="Maps the understood message to one canonical business event and checks required fields.",
        nodes=[
            StageNode(
                id=event.value,
                label=event.value,
                description=("needs: " + ", ".join(REQUIRED_FIELDS.get(event, ())))
                if REQUIRED_FIELDS.get(event)
                else "no required fields",
            )
            for event in CanonicalEventType
        ],
    )
    planner = PipelineStage(
        key="planner",
        title="3 · Planner",
        summary="Decides what to do with the event.",
        nodes=[
            StageNode(id=d.value, label=d.value, description=_PLANNER_DECISION_DOC.get(d.value, ""))
            for d in PlannerDecisionType
        ],
    )
    workflows = PipelineStage(
        key="workflows",
        title="4 · Workflows",
        summary="START_WORKFLOW events run a LangGraph that drafts a record and asks the user to confirm.",
        nodes=[
            StageNode(id=key, label=title, description="")
            for key, title in _WORKFLOW_TITLES.items()
        ],
    )
    return [understanding, canonicalization, planner, workflows]


_PLANNER_DECISION_DOC: dict[str, str] = {
    "start_workflow": "Run the matching workflow (only material is built today).",
    "clarify": "Ask the user for the missing required fields.",
    "direct_reply": "Answer directly — greetings, questions, unrecognized.",
    "ignore": "Do nothing (rare — e.g. system noise).",
}


def _build_pipeline_mermaid() -> str:
    """The end-to-end inbound journey, derived from live routing tables."""
    from canonicalization.mapping import (
        _MATERIAL_DIRECTION_EVENT_TYPE,
        _SIMPLE_EVENT_TYPE,
    )
    from mesiri_contracts.assistant.canonical_event import CanonicalEventType
    from mesiri_contracts.assistant.enums import SemanticType
    from planner.routing import WORKFLOW_KEY_BY_EVENT
    from workflows.registry import is_implemented

    lines: list[str] = ["flowchart LR"]

    lines += [
        '  subgraph Understanding["1 · Understanding"]',
        "    msg([WhatsApp message])",
        '    text{{"text / interactive"}}',
        '    voice{{"voice"}}',
        '    media{{"image / document"}}',
        '    speech["Speech: STT + translation"]',
        '    vision["Vision: OCR / description"]',
        '    extraction["Structured extraction (LLM)"]',
        "    msg --> text & voice & media",
        "    text --> extraction",
        "    voice --> speech --> extraction",
        "    media --> vision --> extraction",
        "  end",
    ]

    lines.append('  subgraph Canonicalization["2 · Canonicalization"]')
    for event in CanonicalEventType:
        lines.append(f'    {_node_id(event.name)}(["{event.value}"])')
    lines.append("  end")

    for semantic, event in _SIMPLE_EVENT_TYPE.items():
        lines.append(f'  extraction -- "{semantic.value}" --> {_node_id(event.name)}')
    for direction, event in _MATERIAL_DIRECTION_EVENT_TYPE.items():
        lines.append(
            f'  extraction -- "{SemanticType.MATERIAL_UPDATE.value} · {direction}" '
            f"--> {_node_id(event.name)}"
        )
    lines.append(
        f'  extraction -- "unknown / low confidence" --> {_node_id(CanonicalEventType.UNRECOGNIZED.name)}'
    )

    lines += [
        '  subgraph Planner["3 · Planner"]',
        '    direct["DIRECT_REPLY"]',
        '    clarify["CLARIFY"]',
        "  end",
        f"  {_node_id(CanonicalEventType.GENERAL_QUESTION_ASKED.name)} --> direct",
        f"  {_node_id(CanonicalEventType.UNRECOGNIZED.name)} --> direct",
        f"  {_node_id(CanonicalEventType.CLARIFICATION_REQUIRED.name)} --> clarify",
        '  direct --> reply(["Reply on WhatsApp"])',
        "  clarify --> reply",
    ]

    lines.append('  subgraph Workflows["4 · Workflows (LangGraph)"]')
    for key in sorted({k for k in WORKFLOW_KEY_BY_EVENT.values()}, key=lambda k: k.value):
        implemented = is_implemented(key)
        label = key.value if implemented else f"{key.value} · not built yet"
        shape = f'[["{label}"]]' if implemented else f'["{label}"]'
        lines.append(f"    wf_{_node_id(key.value)}{shape}")
    lines.append("  end")

    for event, key in WORKFLOW_KEY_BY_EVENT.items():
        lines.append(f"  {_node_id(event.name)} --> wf_{_node_id(key.value)}")

    for key in WORKFLOW_KEY_BY_EVENT.values():
        target = "reply" if is_implemented(key) else "unsupported"
        lines.append(f"  wf_{_node_id(key.value)} --> {target}")
    lines.append("  unsupported([\"'Not supported yet' reply\"])")

    return "\n".join(lines)


# One-line, human descriptions per semantic type. Kept here (not on the enum)
# because the enum's docstring is class-level, not per-member — this is the
# display copy for the control panel.
_SEMANTIC_TYPE_DOC: dict[str, str] = {
    "expense": "An expense to record (an amount spent).",
    "equipment_usage": "An equipment / machinery usage report.",
    "material_update": "Material received or used — the one type that splits by direction.",
    "labour_update": "A labour attendance / headcount update.",
    "general_site_update": "A free-form site progress update.",
    "general_question": "A question with no other bucket — gets a canned capability reply.",
    "whoami_question": "A 'who am I' / 'my profile' question — answered with the caller's own identity.",
    "inventory_query": "A read-only stock / movement question (never an update).",
    "unknown": "Not understood — falls back to the greeting / menu.",
}

# How each type is set. Default is plain AI extraction; a couple have a
# deterministic pre-AI path too (see understanding/pipeline.py
# _apply_deterministic_shortcut and interactions/handler.py's fast paths).
_SEMANTIC_TYPE_DETECTION: dict[str, str] = {
    "whoami_question": (
        "AI extraction, plus a deterministic pre-AI fast path — English identity "
        "phrases are intercepted before Understanding even runs."
    ),
    "unknown": "The fallback when nothing else matches, or a deterministic greeting shortcut.",
}

# Short note for the semantic types that never start a workflow.
_SEMANTIC_TYPE_REPLY_NOTE: dict[str, str] = {
    "general_question": "Direct canned reply (describes what Mesiri records).",
    "unknown": "Direct reply — opens the greeting / category menu.",
}


def _semantic_type_infos() -> list[SemanticTypeInfo]:
    """Every SemanticType traced through the live routing chain. The inverse of
    _workflow_infos(): keyed by understanding hypothesis, walking
    canonicalization.mapping -> planner.routing -> workflows.registry."""
    from canonicalization.mapping import (
        _MATERIAL_DIRECTION_EVENT_TYPE,
        _SIMPLE_EVENT_TYPE,
        REQUIRED_FIELDS,
    )
    from channel.replies import _FIELD_LABELS
    from mesiri_contracts.assistant.canonical_event import CanonicalEventType
    from mesiri_contracts.assistant.enums import SemanticType
    from planner.routing import WORKFLOW_KEY_BY_EVENT
    from workflows.registry import is_implemented

    examples = _example_messages_by_workflow()

    def _labels(events: list[CanonicalEventType]) -> list[str]:
        """Union of required-field labels across the given event(s), order-stable."""
        seen: list[str] = []
        for event in events:
            for field in REQUIRED_FIELDS.get(event, ()):
                label = _FIELD_LABELS.get(field, field.replace("_", " "))
                if label not in seen:
                    seen.append(label)
        return seen

    infos: list[SemanticTypeInfo] = []
    for semantic in SemanticType:
        # Resolve the canonical event(s) this semantic type maps to.
        if semantic is SemanticType.MATERIAL_UPDATE:
            events = list(_MATERIAL_DIRECTION_EVENT_TYPE.values())
        elif semantic in _SIMPLE_EVENT_TYPE:
            events = [_SIMPLE_EVENT_TYPE[semantic]]
        else:  # UNKNOWN — no mapping, routes to UNRECOGNIZED
            events = [CanonicalEventType.UNRECOGNIZED]

        # Event(s) -> workflow key(s), preserving order and dropping duplicates.
        workflow_keys: list[str] = []
        implemented = False
        for event in events:
            key = WORKFLOW_KEY_BY_EVENT.get(event)
            if key is not None and key.value not in workflow_keys:
                workflow_keys.append(key.value)
                if is_implemented(key):
                    implemented = True

        # Example messages: gathered from the mapped workflows (verbatim copy).
        example_messages: list[str] = []
        for key_value in workflow_keys:
            for msg in examples.get(key_value, []):
                if msg not in example_messages:
                    example_messages.append(msg)

        infos.append(
            SemanticTypeInfo(
                semantic_type=semantic.value,
                description=_SEMANTIC_TYPE_DOC.get(semantic.value, ""),
                detection=_SEMANTIC_TYPE_DETECTION.get(semantic.value, "AI extraction."),
                canonical_events=[e.value for e in events],
                workflow_keys=workflow_keys,
                implemented=implemented,
                routes_to_reply=_SEMANTIC_TYPE_REPLY_NOTE.get(semantic.value),
                required_field_labels=_labels(events),
                example_messages=example_messages,
            )
        )
    return infos


def _workflow_infos() -> list[WorkflowGraphInfo]:
    """Structured, drill-down info per workflow key."""
    from canonicalization.mapping import (
        _MATERIAL_DIRECTION_EVENT_TYPE,
        _SIMPLE_EVENT_TYPE,
        REQUIRED_FIELDS,
    )
    from channel.replies import _FIELD_LABELS
    from mesiri_contracts.assistant.canonical_event import CanonicalEventType
    from mesiri_contracts.assistant.enums import SemanticType
    from mesiri_contracts.assistant.planner_decision import WorkflowKey
    from planner.routing import WORKFLOW_KEY_BY_EVENT
    from workflows.registry import WorkflowRegistry, is_implemented

    # Reverse the routing table: workflow key -> canonical event.
    event_by_key = {key: event for event, key in WORKFLOW_KEY_BY_EVENT.items()}
    # Canonical event -> semantic type (best-effort, for display only).
    semantic_by_event: dict[CanonicalEventType, SemanticType] = {
        e: s for s, e in _SIMPLE_EVENT_TYPE.items()
    }
    for e in _MATERIAL_DIRECTION_EVENT_TYPE.values():
        semantic_by_event[e] = SemanticType.MATERIAL_UPDATE

    examples = _example_messages_by_workflow()
    registry = WorkflowRegistry()

    infos: list[WorkflowGraphInfo] = []
    for key in WorkflowKey:
        implemented = is_implemented(key)
        event = event_by_key.get(key)
        semantic = semantic_by_event.get(event) if event else None
        req = list(REQUIRED_FIELDS.get(event, ())) if event else []

        mermaid: str | None = None
        graph = None
        try:
            graph = registry.get_graph(key)
            if graph is not None:
                mermaid = graph.get_graph().draw_mermaid()
        except Exception:  # noqa: BLE001 — langgraph optional; degrade to status-only
            pass

        infos.append(
            WorkflowGraphInfo(
                workflow_key=key.value,
                title=_WORKFLOW_TITLES.get(key.value, key.value),
                implemented=implemented,
                canonical_event=event.value if event else None,
                semantic_type=semantic.value if semantic else None,
                required_fields=req,
                required_field_labels=[_FIELD_LABELS.get(f, f.replace("_", " ")) for f in req],
                node_names=_workflow_node_names(graph),
                example_messages=examples.get(key.value, []),
                mermaid=mermaid,
                lifecycle_mermaid=_confirmation_lifecycle_mermaid()
                if key.value in _LIFECYCLE_WORKFLOWS
                else None,
            )
        )
    return infos


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@router.get("", response_model=SystemGraphResponse)
async def get_system_graph(_admin: dict = Depends(require_platform_admin)):
    return SystemGraphResponse(
        mermaid=_build_pipeline_mermaid(),
        fast_paths=_fast_paths(),
        hardcoded_replies=_hardcoded_replies(),
        stages=_build_stages(),
        semantic_types=_semantic_type_infos(),
        workflows=_workflow_infos(),
    )


async def _lookup_user_wa_id(org_id: uuid.UUID, user_id: uuid.UUID) -> str:
    """Resolve the chosen user's registered WhatsApp number (the pipeline keys
    identity off it). Raises HTTPException if the user is missing or unregistered."""
    try:
        number = await user_whatsapp_number(org_id, user_id)
    except UserNotFound:
        raise HTTPException(status_code=404, detail="User not found in that organization") from None
    if not number:
        raise HTTPException(
            status_code=400,
            detail="That user has no WhatsApp number on file, so a message can't be simulated as them.",
        )
    return number


@router.post("/simulate/reset")
async def reset_simulation_session(
    body: ResetSimulateRequest,
    request: Request,
    _admin: dict = Depends(require_platform_admin),
):
    """Clear any pending workflow confirmation or held gate report for the given user."""
    from runtime.dependencies import get_container
    from workflows.ports import ResumeAction

    wa_id = await _lookup_user_wa_id(body.organization_id, body.user_id)
    container = get_container(request)
    user_id = str(body.user_id)

    loaded = await container.workflow_runtime.get_awaiting_confirmation(user_id)
    if loaded is not None:
        await container.workflow_runtime.resume(loaded, ResumeAction.CANCEL)


    if hasattr(container, "category_hint_store") and container.category_hint_store:
        await container.category_hint_store.pop_hint(user_id=user_id)

    return {"status": "ok", "user_id": user_id, "wa_id": wa_id}


@router.post("/simulate", response_model=SimulateResponse)
async def simulate_message(
    body: SimulateRequest,
    request: Request,
    _admin: dict = Depends(require_platform_admin),
):
    """Run one message exactly as a real inbound WhatsApp message would,
    capturing replies instead of sending them: the production message handler
    (runtime/message_journey.py) with a capturing sender, so buttons, YES/NO
    and the agent behave as on WhatsApp, including multi-turn workflows."""
    from mesiri_contracts.assistant.enums import InputModality
    from mesiri_contracts.assistant.normalized_message import NormalizedMessage, SenderInfo
    from mesiri_contracts.common.ids import new_id
    from runtime.dependencies import get_container

    try:
        modality = InputModality(body.modality)
    except ValueError:
        raise HTTPException(
            status_code=400, detail=f"Unsupported modality: {body.modality}"
        ) from None
    if modality not in (InputModality.TEXT, InputModality.INTERACTIVE):
        raise HTTPException(
            status_code=400,
            detail="Only text and interactive simulation are supported for now.",
        )

    wa_id = await _lookup_user_wa_id(body.organization_id, body.user_id)
    container = get_container(request)

    capture = ReplyCapture()

    def _build_response(routed_via: str, result_obj: object | None = None) -> SimulateResponse:
        def _dump(obj) -> dict | None:
            return obj.model_dump(mode="json") if obj is not None else None

        und = _dump(getattr(result_obj, "understanding", None))
        ctx_dump = _dump(getattr(result_obj, "resolved_context", None))
        canon = _dump(getattr(result_obj, "canonical_event", None))
        planner_dec = _dump(getattr(result_obj, "planner_decision", None))
        wf_run = None
        run_obj = getattr(result_obj, "workflow_run", None)
        if run_obj is not None:
            wf_run = {
                "status": run_obj.status.value,
                "workflow_key": run_obj.workflow_key.value,
                "workflow_instance_id": run_obj.workflow_instance_id,
            }

        return SimulateResponse(
            dry_run=True,
            ran_as_wa_id=wa_id,
            routed_via=routed_via,
            replies=capture.texts,
            structured_replies=capture.replies,
            understanding=und,
            resolved_context=ctx_dump,
            canonical_event=canon,
            planner_decision=planner_dec,
            workflow_run=wf_run,
        )

    # --- Identity gate (M4) — same check the real webhook path runs first. ---
    refusal = await identity_refusal(container, wa_id)
    if refusal is not None:
        capture.text(refusal)
        return _build_response("identity_gate")

    metadata: dict[str, object] = {"simulated": True}
    if body.interactive_reply_id:
        metadata["interactive_reply_id"] = body.interactive_reply_id

    message = NormalizedMessage(
        message_id=new_id("sim"),
        sender=SenderInfo(wa_id=wa_id, phone_number=wa_id),
        timestamp=datetime.now(UTC),
        modality=modality,
        text=body.text or body.interactive_reply_id or "",
        metadata=metadata,
    )

    # ARCH-06: the very handler a real WhatsApp message runs (taps, YES/NO,
    # menu, the agent), with a sender that captures its replies.
    if container.simulate_handler is None:
        raise HTTPException(status_code=503, detail="The simulator is not wired.")

    await run_captured(container, message, capture)
    return _build_response("message_journey")

