"""The port between the agent and the existing assistant pipeline.

The toolbox never imports the journey: it asks a `WorkflowGateway` to run an
understanding through the classic pipeline and gets back what that pipeline
would have said, captured instead of sent. `message_journey` supplies the real
gateway (journey_gateway.py); tests supply a fake or the journey over the seed
company.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

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
    #: ``saved`` only: what was saved in a few words, from the saved data
    #: ("16 workers (6 mason, 10 helper)").
    summary: str | None = None
    #: Request 104: several lines for one step (issues to close, one per issue).
    summaries: list[str] = field(default_factory=list)
    #: Replies the pipeline produced beyond ``reply`` (documents are sent by the
    #: pipeline itself and are not captured).
    extra: list[ReplySpec] = field(default_factory=list)
    #: ``choose`` only: what the answer fills in ("site", "material"...).
    awaiting: str = ""
    #: ``drafted`` with a question on the card (request 127): how to take an
    #: answer they type instead of tapping (the entry's own instruction).
    hint: str = ""
    #: ``drafted`` only: the line is a correction (of a line of the card, or of a
    #: saved entry). It is a change they have not saved yet (request 129).
    changed: bool = False
    #: ``answer`` only (request 143): documents sent with it (the report's PDFs).
    documents: int = 0
    #: Request 143: a line of the code's (``wording`` key and its values): the toolbox
    #: words it in the turn's language; ``text`` stays the English for the model and logs.
    line_key: str = ""
    line_values: dict[str, Any] = field(default_factory=dict)


class WorkflowGateway(Protocol):
    async def run(self, candidate: Candidate, *, text: str) -> StepResult:
        """Run ``candidate`` (what the user's message means) through the
        existing pipeline for the current sender. ``text`` is their message."""
        ...

    async def undo_latest_draft(self) -> StepResult:
        """Remove the sender's latest saved-as-draft update (the classic UNDO)."""
        ...

    async def undo_card(self, refs: list[str]) -> StepResult:
        """Request 88: remove the entries of the sender's latest card (all of
        them, or the ones ``refs`` name). Only ids the code offered are taken;
        several entries and no ``refs`` is a pick list. Optional: a gateway
        without cards falls back to ``undo_latest_draft``."""
        ...

    async def set_unit_conversion(self, *, material: str, unit: str, count: float) -> StepResult:
        """WA-41: remember how many ``unit`` make one stock unit of ``material``,
        company-wide (admins and project managers only)."""
        ...

    async def set_work_site(self, *, project_id: str | None, site_id: str) -> str:
        """WA-45: the sender works at ``site_id`` for the rest of today. Returns
        how to name it to them ("Site B (Project B)")."""
        ...

    async def finish(self) -> None:
        """After the reply is sent: the follow-ups the classic path runs after
        a save (worker promotion question, team-photo offer, ...)."""
        ...
