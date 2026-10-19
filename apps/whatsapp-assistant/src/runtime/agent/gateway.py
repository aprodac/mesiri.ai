"""The port between the agent and the existing assistant pipeline.

The toolbox never imports the journey: it asks a `WorkflowGateway` to run an
understanding through the classic pipeline and gets back what that pipeline
would have said, captured instead of sent. `message_journey` supplies the real
gateway (journey_gateway.py); tests supply a fake or the journey over the seed
company.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from channel.replies import ReplySpec
from mesiri_contracts.assistant.candidates import Candidate


@dataclass(slots=True)
class StepResult:
    """What one workflow run produced.

    ``status``:
      - ``saved``: the record is written (draft or confirmed); ``text`` says what.
      - ``needs_confirmation``: a draft waits on Yes/No (confirm-first flows such
        as expenses and transfers); ``reply`` is that prompt.
      - ``needs_answer``: the pipeline needs the user to pick/answer something
        first (which site? which material?); ``reply`` is its question.
      - ``answer``: a query finished; ``text`` is its answer.
      - ``info``: a plain reply that is neither of the above (module switched
        off, not allowed, nothing to undo, not understood).
      - ``error``: nothing was done.
    """

    status: str
    text: str = ""
    reply: ReplySpec | None = None
    workflow_key: str | None = None
    #: Replies the pipeline produced beyond ``reply`` (documents are sent by the
    #: pipeline itself and are not captured).
    extra: list[ReplySpec] = field(default_factory=list)


class WorkflowGateway(Protocol):
    async def run(self, candidate: Candidate, *, text: str) -> StepResult:
        """Run ``candidate`` (what the user's message means) through the
        existing pipeline for the current sender. ``text`` is their message."""
        ...

    async def undo_latest_draft(self) -> StepResult:
        """Remove the sender's latest saved-as-draft update (the classic UNDO)."""
        ...

    async def finish(self) -> None:
        """After the reply is sent: the follow-ups the classic path runs after
        a save (worker promotion question, team-photo offer, ...)."""
        ...
