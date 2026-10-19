"""RecordReceiptBuilder: one record -> its card; several -> one combined card."""

from __future__ import annotations

from types import SimpleNamespace

from tests.unit.receipt_samples import ORG, PRJ, SITE, USR, Named

from channel.receipt.builder import RecordReceiptBuilder
from mesiri_contracts.application.results.execution_result import ExecutionStatus
from mesiri_contracts.assistant.draft_action import DraftActionType


class _Renderer:
    def __init__(self) -> None:
        self.html: list[str] = []

    async def render_png(self, html: str) -> bytes:
        self.html.append(html)
        return b"png"


def _saved(action_type, fields, row_id):
    draft = SimpleNamespace(
        action_type=action_type,
        fields=fields,
        project_id=PRJ,
        site_id=SITE,
        organization_id=ORG,
        user_id=USR,
    )
    confirmed = SimpleNamespace(draft_action=draft, correlation_id="c", workflow_instance_id="w")
    execution = SimpleNamespace(status=ExecutionStatus.SUCCEEDED, material_row_id=row_id)
    return confirmed, execution


ACTOR = SimpleNamespace(
    full_name="Mohammed", projects=[Named(PRJ, "Riverside Tower")], sites=[Named(SITE, "Block A")]
)
MATERIAL = (DraftActionType.RECORD_MATERIAL_RECEIPT, {"material_name": "cement", "quantity": 50, "unit": "bags"})
ISSUE = (DraftActionType.RECORD_SITE_ISSUE, {"issue_type": "LEAK", "severity": "HIGH", "narrative": "Pipe burst"})


async def test_one_record_gets_its_own_card():
    renderer = _Renderer()
    png = await RecordReceiptBuilder(renderer).build(*_saved(*MATERIAL, "aaaa-1"), ACTOR)
    assert png == b"png"
    assert "50" in renderer.html[0] and "SAVED · DRAFT" in renderer.html[0]
    assert "SITE UPDATE" not in renderer.html[0].upper()


async def test_several_records_get_one_combined_card():
    renderer = _Renderer()
    png = await RecordReceiptBuilder(renderer).build_combined(
        [_saved(*MATERIAL, "aaaa-1"), _saved(*ISSUE, "bbbb-2")], ACTOR
    )
    assert png == b"png"
    assert len(renderer.html) == 1
    assert "2 SAVED · DRAFT" in renderer.html[0]
    assert "Pipe burst" in renderer.html[0] and "50 bags" in renderer.html[0]


async def test_a_failed_part_is_left_out_not_fatal():
    renderer = _Renderer()
    failed = _saved(*ISSUE, "bbbb-2")
    failed[1].status = ExecutionStatus.FAILED if hasattr(ExecutionStatus, "FAILED") else None
    png = await RecordReceiptBuilder(renderer).build_combined([_saved(*MATERIAL, "aaaa-1"), failed], ACTOR)
    assert png == b"png"
    assert "Pipe burst" not in renderer.html[0]


async def test_nothing_saved_means_no_image():
    assert await RecordReceiptBuilder(_Renderer()).build_combined([], ACTOR) is None


async def test_a_renderer_failure_degrades_to_no_image():
    class _Broken:
        async def render_png(self, html):
            raise RuntimeError("chromium died")

    assert await RecordReceiptBuilder(_Broken()).build(*_saved(*MATERIAL, "aaaa-1"), ACTOR) is None


async def test_the_handler_combines_what_a_multi_part_note_saved():
    from interactions.handler import InteractionHandler

    renderer = _Renderer()
    handler = InteractionHandler(workflow_runtime=None, receipt_builder=RecordReceiptBuilder(renderer))
    handled = [
        SimpleNamespace(result=SimpleNamespace(confirmed_action=c), execution_result=e)
        for c, e in (_saved(*MATERIAL, "aaaa-1"), _saved(*ISSUE, "bbbb-2"))
    ]
    handled.append(SimpleNamespace(result=SimpleNamespace(confirmed_action=None), execution_result=None))

    assert await handler.build_combined_receipt(handled, ACTOR) == b"png"
    assert "2 SAVED · DRAFT" in renderer.html[0]
    assert await InteractionHandler(workflow_runtime=None).build_combined_receipt(handled, ACTOR) is None


async def test_builder_stamps_the_receipt_in_the_actor_timezone(monkeypatch):
    from datetime import UTC, datetime

    import channel.receipt.builder as builder_module

    class _Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 19, 12, 35, tzinfo=UTC)

    monkeypatch.setattr(builder_module, "datetime", _Clock)
    renderer = _Renderer()
    actor = SimpleNamespace(full_name="M", projects=[], sites=[], timezone="Asia/Kolkata")
    await RecordReceiptBuilder(renderer).build(*_saved(*MATERIAL, "aaaa-1"), actor)
    assert "6:05 PM" in renderer.html[0]


ACTIVITY_40 = (
    DraftActionType.CREATE_ACTIVITY,
    {"work_type": "plastering", "location": "2nd floor", "progress_percent": 40},
)


async def test_the_work_row_is_in_the_senders_script_when_a_localizer_is_wired():
    """Request 57, B4: card text in the worker's script; amounts and names stay."""
    renderer = _Renderer()
    seen = []

    async def localize(texts, actor):
        seen.extend(texts)
        return {t: "പ്ലാസ്റ്ററിംഗ് · രണ്ടാം നില · 40%" for t in texts}

    await RecordReceiptBuilder(renderer, localize=localize).build(
        *_saved(*ACTIVITY_40, "aaaa-1"), ACTOR
    )
    assert "Plastering · 2nd floor · 40%" in seen
    assert "പ്ലാസ്റ്ററിംഗ് · രണ്ടാം നില · 40%" in renderer.html[0]
    assert "Riverside Tower" in renderer.html[0]


async def test_a_failing_localizer_leaves_the_card_in_english():
    renderer = _Renderer()

    async def boom(texts, actor):
        raise RuntimeError("model down")

    png = await RecordReceiptBuilder(renderer, localize=boom).build(
        *_saved(*ACTIVITY_40, "aaaa-1"), ACTOR
    )
    assert png == b"png"
    assert "Plastering · 2nd floor · 40%" in renderer.html[0]
