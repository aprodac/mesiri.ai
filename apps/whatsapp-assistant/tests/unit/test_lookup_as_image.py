"""Request 144: "send today's workers list as an image". A lookup goes out as
text, PDF or image; the image is the same table as the PDF (``_query_table``)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from tests.unit.test_query_entry import _entry

from mesiri_contracts.assistant.planner_decision import WorkflowKey
from runtime.agent.tools import (
    QUERY_EXPENSES,
    QUERY_LABOUR,
    QUERY_MATERIALS,
    QUERY_WORK_LOG,
    ScopeLookup,
    to_candidate,
)
from runtime.inbound_journey.seeding import _build_query_pdf, _query_table

PNG = b"\x89PNG-fake"
MESSAGE_ = SimpleNamespace(correlation_id="c", sender=SimpleNamespace(wa_id="91"))

LABOUR = {
    "date_range_label": "Today",
    "headcount": 30,
    "total_cost": "9000",
    "rows": [
        {"occurred_date": "2026-10-29", "worker_name": f"W{i}", "trade": "mason", "headcount": 1, "daily_wage": "900"}
        for i in range(30)
    ],
}
SEEDS: dict[str, dict[str, Any]] = {
    QUERY_LABOUR: {"labour_results": LABOUR},
    QUERY_MATERIALS: {"inventory_levels": [
        {"material_name": "Cement", "received": 100, "used": 60, "current_stock": 40, "unit": "bags"}]},
    QUERY_EXPENSES: {"expense_results": {"total": "10", "count": 1, "items": [
        {"occurred_date": "2026-10-29", "amount": "10", "description": "Diesel"}]}},
    QUERY_WORK_LOG: {"activity_search_results": {"activities": [
        {"activity_date": "2026-10-29", "work_type": "slab", "narrative": "poured", "status": "done"}]}},
}


class _Renderer:
    def __init__(self, fail: bool = False) -> None:
        self.htmls: list[str] = []
        self.fail = fail

    async def render_png(self, html: str) -> bytes:
        if self.fail:
            raise RuntimeError("chromium down")
        self.htmls.append(html)
        return PNG


async def _run(tool: str, args: dict[str, Any], *, renderer: Any = None):
    images: list[tuple[bytes, str]] = []
    docs: list[tuple[str, bytes]] = []

    async def send_image(wa_id: str, png: bytes, *, caption: Any = None, filename: str = "x.png") -> bool:
        images.append((png, filename))
        return True

    async def send_document(wa_id: str, data: bytes, *, filename: str, caption: Any) -> bool:
        docs.append((filename, data))
        return True

    candidate = to_candidate(tool, args, ScopeLookup())
    entry = _entry(
        send_image=send_image, send_document=send_document,
        card_renderer=renderer if renderer is not None else _Renderer(),
    )
    from tests.unit.test_material_entry import MESSAGE, _Understanding

    ready = await entry.prepare(MESSAGE, _Understanding(candidate), candidate)
    ready.event.fields.update(SEEDS[tool])
    line = await entry.deliver(ready, MESSAGE_)
    return ready, line, images, docs, entry


def test_send_as_maps_to_output_format_and_as_pdf_still_works():
    for send_as, expected in (("image", "image"), ("pdf", "pdf")):
        assert to_candidate(QUERY_LABOUR, {"send_as": send_as}, ScopeLookup()).fields["output_format"] == expected
    assert to_candidate(QUERY_LABOUR, {"as_pdf": True}, ScopeLookup()).fields["output_format"] == "pdf"
    assert "output_format" not in to_candidate(QUERY_LABOUR, {"send_as": "text"}, ScopeLookup()).fields
    assert "output_format" not in to_candidate(QUERY_LABOUR, {}, ScopeLookup()).fields


async def test_the_workers_list_as_an_image_sends_pngs_not_a_refusal():
    _, line, images, docs, _ = await _run(QUERY_LABOUR, {"send_as": "image"})
    assert line is None and docs == []
    assert len(images) == 2 and all(png == PNG for png, _ in images)  # 30 rows -> 25 + 5


async def test_every_sibling_lookup_can_go_as_an_image():
    for tool in (QUERY_MATERIALS, QUERY_EXPENSES, QUERY_WORK_LOG):
        args = {"send_as": "image", **({"kind": "expenses"} if tool == QUERY_EXPENSES else {})}
        _, line, images, docs, _ = await _run(tool, args)
        assert line is None and len(images) == 1 and docs == [], tool


async def test_a_long_list_is_several_images_with_page_numbers():
    renderer = _Renderer()
    await _run(QUERY_LABOUR, {"send_as": "image"}, renderer=renderer)
    assert "1/2" in renderer.htmls[0] and "2/2" in renderer.htmls[1]


async def test_a_render_failure_falls_back_to_the_pdf_with_an_honest_line():
    _, line, images, docs, _ = await _run(QUERY_LABOUR, {"send_as": "image"}, renderer=_Renderer(fail=True))
    assert images == [] and len(docs) == 1 and docs[0][1].startswith(b"%PDF")
    assert line and "PDF" in line and "can't" not in line.lower()


async def test_pdf_is_unchanged_and_shares_the_image_rows():
    ready, line, images, docs, _ = await _run(QUERY_LABOUR, {"send_as": "pdf"})
    assert line is None and images == [] and len(docs) == 1 and docs[0][0] == "Labour_Attendance.pdf"
    fields = ready.event.fields
    title, _, columns, rows, _, stem = _query_table(WorkflowKey.LABOUR_QUERY, fields)
    assert len(rows) == 30 and rows[0] == ["2026-10-29", "W0", "mason", 1, "900"] and stem == "Labour_Attendance"
    assert _build_query_pdf(WorkflowKey.LABOUR_QUERY, fields)[1] == "Labour_Attendance.pdf"


async def test_a_plain_question_sends_no_image_and_no_pdf():
    _, line, images, docs, entry = await _run(QUERY_LABOUR, {})
    assert line is None and images == [] and docs == []
