"""InteractionHandler factory — consistent with build_context_resolver() and build_pipeline().

``build_container()`` in ``runtime/dependencies.py`` calls this rather than
constructing ``InteractionHandler`` inline, keeping the container clean and
making the dependency graph explicit.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from memory.coordinator import ConversationMemoryCoordinator
from workflows import WorkflowRuntime

from .classifier_port import InteractionClassifierPort
from .completion_photo_hint import CompletionPhotoHintStore
from .handler import InteractionHandler
from .ports import ExecutionDispatcher, ReceiptBuilder
from .slot_answer_classifier_port import SlotAnswerClassifierPort

if TYPE_CHECKING:
    from runtime.save_first import SaveFirstService


def build_interaction_handler(
    workflow_runtime: WorkflowRuntime,
    classifier: InteractionClassifierPort | None = None,
    dispatcher: ExecutionDispatcher | None = None,
    receipt_builder: ReceiptBuilder | None = None,
    memory_coordinator: ConversationMemoryCoordinator | None = None,
    completion_photo_hint_store: CompletionPhotoHintStore | None = None,
    slot_answer_classifier: SlotAnswerClassifierPort | None = None,
    save_first: SaveFirstService | None = None,
) -> InteractionHandler:
    """Construct an ``InteractionHandler`` wired to ``workflow_runtime`` and,
    once M8 is wired, an ``ExecutionDispatcher`` that executes confirmed
    Material actions synchronously in the same request, plus an optional
    ``ReceiptBuilder`` that renders the post-confirmation receipt image, an
    optional ``ConversationMemoryCoordinator`` (M19) that remembers the
    activity a confirmed CREATE_ACTIVITY/ADD_PROGRESS_UPDATE touched,
    ``completion_photo_hint_store`` (#25 AI Follow-up) needed to remember
    which Activity a proactive "want to attach a completion photo?" offer
    was about, and an optional ``slot_answer_classifier`` that resolves a
    picker reply the deterministic matcher (workflows/slots.py) couldn't.

    ``planner``/``batch_store`` (#1 Multi-Activity) params retired in Phase
    A3 (docs/execution/UNIFIED_UNDERSTANDING_PIPELINE.md) -- a multi-event
    message is now a Plan, advanced by runtime/plan_executor.py's
    advance_plan, not from inside this handler."""
    return InteractionHandler(
        workflow_runtime,
        classifier=classifier,
        dispatcher=dispatcher,
        receipt_builder=receipt_builder,
        memory_coordinator=memory_coordinator,
        completion_photo_hint_store=completion_photo_hint_store,
        slot_answer_classifier=slot_answer_classifier,
        save_first=save_first,
    )
