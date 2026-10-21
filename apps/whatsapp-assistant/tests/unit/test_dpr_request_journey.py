"""Request [58]: "Send me today's report" through the real journey -- the
real dpr.request graph, the planner and the agent's preset understanding --
with only the lookup, storage and WhatsApp sender faked. Pins what the sender
is told in each state of today's report, and that a failure on the way is
said in fixed words and logged with the correlation id."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from backend.ports import ActorIdentity, ProjectSummary, SiteSummary
from context import seed
from context.identity_bridge import deterministic_canonical_uuid
from context.resolver import ContextResolver
from interactions.handler import InteractionHandler
from mesiri.infrastructure.objectstorage.fake import FakeObjectStorage
from mesiri_contracts.assistant.candidates import Candidate
from mesiri_contracts.assistant.enums import InputModality, SemanticType
from mesiri_contracts.assistant.normalized_message import NormalizedMessage, SenderInfo
from planner import Planner
from runtime.agent.journey_gateway import CaptureSink
from runtime.agent.preset_pipeline import PresetUnderstandingPipeline
from runtime.inbound_journey import process_inbound_message
from workflows import WorkflowRegistry, WorkflowRuntime
from workflows.fakes import FakeWorkflowInstanceRepository

ORG = "11111111-1111-4111-8111-111111111111"
# The project the context resolver gives this sender (seed data), with one site.
PRJ = deterministic_canonical_uuid(seed.PROJ_ALPHA)
SITE = "44444444-4444-4444-8444-444444444444"


class _Query:
    def __init__(self, result: dict[str, Any] | Exception) -> None:
        self._result = result

    async def find_report(self, **kwargs: Any) -> dict[str, Any]:
        if isinstance(self._result, Exception):
            raise self._result
        return dict(self._result)


class _Documents:
    def __init__(self, error: Exception | None = None) -> None:
        self.sent: list[tuple[str, bytes, str]] = []
        self._error = error

    async def __call__(self, wa_id: str, data: bytes, *, filename: str, caption: str | None = None):
        if self._error:
            raise self._error
        self.sent.append((wa_id, data, filename))


def _actor() -> ActorIdentity:
    return ActorIdentity(
        user_id=deterministic_canonical_uuid(seed.USER_ENGINEER),
        full_name="Engineer",
        role="site_engineer",
        organization_id=ORG,
        org_name="Acme",
        org_active=True,
        projects=[ProjectSummary(id=PRJ, name="Green Villa")],
        sites=[SiteSummary(id=SITE, name="Kakkanad", project_id=PRJ)],
    )


async def _ask(query: Any, *, documents: _Documents, storage: FakeObjectStorage):
    sink = CaptureSink()
    message = NormalizedMessage(
        message_id="wamid.dpr.1",
        correlation_id="cor_dpr_1",
        sender=SenderInfo(wa_id=seed.WA_ENGINEER, profile_name="Engineer"),
        timestamp=datetime(2026, 10, 19, 15, 41, tzinfo=UTC),
        modality=InputModality.TEXT,
        text="Send me today's report",
    )
    runtime = WorkflowRuntime(registry=WorkflowRegistry(), repo=FakeWorkflowInstanceRepository())
    actor = _actor()
    result = await process_inbound_message(
        message,
        actor_user_id=actor.user_id,
        pipeline=PresetUnderstandingPipeline(Candidate(semantic_type=SemanticType.DPR_REQUEST, fields={})),
        context_resolver=ContextResolver(seed.build_dependencies()),
        planner=Planner(),
        workflow_runtime=runtime,
        interaction_handler=InteractionHandler(workflow_runtime=runtime),
        send_text=sink.send_text,
        send_list=sink.send_list,
        send_button=sink.send_button,
        send_document=documents,
        object_storage=storage,
        actor=actor,
        dpr_request_query=query,
    )
    return result, sink


async def test_ready_report_is_sent_with_a_plain_line():
    storage = FakeObjectStorage()
    await storage.put_object("dpr/a.pdf", b"%PDF", content_type="application/pdf")
    docs = _Documents()
    result, sink = await _ask(
        _Query({"status": "ready", "object_key": "dpr/a.pdf", "code": "DPR-1"}),
        documents=docs,
        storage=storage,
    )
    assert result.workflow_run is not None, sink.replies
    assert [r.text for r in sink.replies] == ["Today's DPR (DPR-1) attached."]
    assert docs.sent == [(seed.WA_ENGINEER, b"%PDF", "DPR-1.pdf")]


async def _stored() -> FakeObjectStorage:
    storage = FakeObjectStorage()
    await storage.put_object("dpr/a.pdf", b"%PDF", content_type="application/pdf")
    return storage


async def test_a_draft_nobody_confirmed_says_so_instead_of_being_prepared():
    result, sink = await _ask(
        _Query(
            {
                "status": "pending_confirmation",
                "object_key": None,
                "code": "DPR-1",
                "confirmed": False,
                "update_count": 3,
            }
        ),
        documents=_Documents(),
        storage=await _stored(),
    )
    assert [r.text for r in sink.replies] == [
        "Kakkanad: 3 updates, not confirmed yet. The report goes out once the day is confirmed."
    ]


async def test_an_unconfirmed_pdf_is_sent_and_labelled_not_confirmed():
    docs = _Documents()
    _, sink = await _ask(
        _Query(
            {"status": "ready", "object_key": "dpr/a.pdf", "code": "DPR-1", "confirmed": False}
        ),
        documents=docs,
        storage=await _stored(),
    )
    assert [r.text for r in sink.replies] == ["Today's DPR (DPR-1) attached. Not confirmed yet."]
    assert len(docs.sent) == 1


async def test_a_confirmed_report_still_being_rendered_is_being_prepared():
    _, sink = await _ask(
        _Query({"status": "pending_render", "object_key": None, "code": "DPR-1", "confirmed": True}),
        documents=_Documents(),
        storage=await _stored(),
    )
    assert [r.text for r in sink.replies] == [
        "Today's report is being prepared. Please ask again in a few minutes."
    ]


async def test_nothing_built_yet_is_said_plainly():
    _, sink = await _ask(
        _Query({"status": "not_generated", "object_key": None, "code": None}),
        documents=_Documents(),
        storage=await _stored(),
    )
    assert sink.replies[0].text.startswith("No DPR has been generated for today yet.")


async def test_a_failed_lookup_is_fixed_words_and_logged_with_the_correlation_id(caplog):
    with caplog.at_level(logging.WARNING):
        _, sink = await _ask(
            _Query(RuntimeError("boom")), documents=_Documents(), storage=await _stored()
        )
    assert [r.text for r in sink.replies] == [
        "I can't look up today's report right now. Please try again in a minute."
    ]
    failed = [r for r in caplog.records if "dpr_request.lookup_failed" in r.getMessage()]
    assert failed and "correlation_id=cor_dpr_1" in failed[0].getMessage()
    assert failed[0].exc_info


async def test_a_missing_pdf_is_found_out_before_the_reply_says_attached(caplog):
    docs = _Documents()
    with caplog.at_level(logging.WARNING):
        _, sink = await _ask(
            _Query({"status": "ready", "object_key": "dpr/gone.pdf", "code": "DPR-1"}),
            documents=docs,
            storage=await _stored(),
        )
    assert [r.text for r in sink.replies] == [
        "Today's DPR (DPR-1) is ready, but I couldn't fetch the PDF just now. "
        "Please ask again in a minute."
    ]
    assert docs.sent == []
    assert any(
        "dpr_request.pdf_unavailable" in r.getMessage() and "cor_dpr_1" in r.getMessage()
        for r in caplog.records
    )


async def test_a_send_that_raises_is_told_and_logged(caplog):
    with caplog.at_level(logging.WARNING):
        _, sink = await _ask(
            _Query({"status": "ready", "object_key": "dpr/a.pdf", "code": "DPR-1"}),
            documents=_Documents(RuntimeError("whatsapp down")),
            storage=await _stored(),
        )
    assert sink.replies[-1].text.startswith("Sorry, the PDF didn't go through.")
    failed = [r for r in caplog.records if "dpr_request.document_send_failed" in r.getMessage()]
    assert failed and "correlation_id=cor_dpr_1" in failed[0].getMessage()


async def test_a_send_the_sender_reports_as_false_is_told_not_dropped(caplog):
    """channel/whatsapp/outbound.py's send_document returns False on a failed
    upload or send; this was ignored, so the sender saw "attached" and no PDF."""

    class _FalseDocuments(_Documents):
        async def __call__(self, *args: Any, **kwargs: Any) -> bool:
            return False

    with caplog.at_level(logging.WARNING):
        _, sink = await _ask(
            _Query({"status": "ready", "object_key": "dpr/a.pdf", "code": "DPR-1"}),
            documents=_FalseDocuments(),
            storage=await _stored(),
        )
    assert sink.replies[-1].text.startswith("Sorry, the PDF didn't go through.")
    assert any(
        "dpr_request.document_send_failed" in r.getMessage()
        and "correlation_id=cor_dpr_1" in r.getMessage()
        for r in caplog.records
    )


# -- WA-40: asked during the day, before the evening cutoff builds it ------------


class _PreviewQuery(_Query):
    def __init__(self, lines: list[str]) -> None:
        super().__init__({"status": "not_generated", "object_key": None, "code": None})
        self.lines = lines
        self.asked: dict[str, Any] = {}

    async def preview_lines(self, **kwargs: Any) -> list[str]:
        self.asked = kwargs
        return self.lines


async def test_during_the_day_the_sender_gets_the_day_so_far_marked_as_a_draft():
    query = _PreviewQuery(["• Work: 3 items", "• Labour: 16 workers", "• Materials: 2 entries"])
    docs = _Documents()
    _, sink = await _ask(query, documents=docs, storage=await _stored())
    assert sink.replies[0].text == (
        "Today's report is made this evening. So far today at Kakkanad:\n"
        "• Work: 3 items\n• Labour: 16 workers\n• Materials: 2 entries\n"
        "This is a draft: not final, and not sent to anyone."
    )
    assert query.asked["site_id"] == SITE
    assert docs.sent == []  # nothing sent: no report exists yet


async def test_a_day_with_nothing_recorded_yet_still_says_so_plainly():
    _, sink = await _ask(_PreviewQuery([]), documents=_Documents(), storage=await _stored())
    assert sink.replies[0].text.startswith("No DPR has been generated for today yet.")


async def test_after_the_cutoff_a_day_waiting_on_the_site_says_what_it_needs():
    """Round 3b: at 18:08 the day was NEEDS_DETAILS (no work done) and the reply
    was "being prepared, ask again in a few minutes", which never comes true."""
    query = _PreviewQuery(["• Labour: 16 workers", "• Materials: Cement, M sand"])
    query._result = {
        "status": "pending_confirmation",
        "object_key": None,
        "code": "DPR-1",
        "confirmed": False,
        "update_count": 0,
        "missing": ["work_done"],
    }
    docs = _Documents()
    _, sink = await _ask(query, documents=docs, storage=await _stored())
    assert sink.replies[0].text == (
        "Today's report at Kakkanad isn't confirmed yet; still needs the work done. So far:\n"
        "• Labour: 16 workers\n• Materials: Cement, M sand\n"
        "It goes out once the day is confirmed."
    )
    assert docs.sent == []
