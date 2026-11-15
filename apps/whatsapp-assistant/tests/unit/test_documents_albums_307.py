"""[307] (15 Nov, live): an owner sent his BOQ as a Word file ("can't read documents or PDFs yet"), then its pages as
photos sent together (the album marker got "can't read this kind of message") and three of the four pages got
"couldn't read that photo" though the vision model had described them.

Now: a PDF, Word or Excel file is a DOCUMENT that is downloaded and read (Office files by the code, as text); the album
marker gets no answer (its photos follow one by one); a photo the model described is never "unreadable"."""

from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from channel.replies import SILENTLY_IGNORED_RAW_TYPES
from ingress.normalization import EXCEL_MIME, WORD_MIME, MessageNormalizer, readable_document
from mesiri_ai.models import VisionResult
from mesiri_contracts.assistant.enums import InputModality
from mesiri_contracts.assistant.normalized_message import (
    MediaReference,
    NormalizedMessage,
    SenderInfo,
)
from understanding.office_text import EXCEL, MAX_CHARS, WORD, office_kind, office_text

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
S = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
R = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'


def _zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, text in files.items():
            z.writestr(name, text)
    return buf.getvalue()


def _p(text: str) -> str:
    return f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"


def _row(*cells: str) -> str:
    return "<w:tr>" + "".join(f"<w:tc>{_p(c)}</w:tc>" for c in cells) + "</w:tr>"


def _docx() -> bytes:
    body = (_p("Preliminary BOQ - G+1 Commercial Supermarket, 7000 sq ft")
            + "<w:tbl>" + _row("Item", "Description", "Qty", "Unit")
            + _row("1.1", "Excavation for foundations", "450", "cum")
            + _row("1.2", "Foundation reinforcement steel", "7000", "kg") + "</w:tbl>")
    return _zip({"[Content_Types].xml": "<Types/>",
                 "word/document.xml": f"<w:document {W}><w:body>{body}</w:body></w:document>"})


def _xlsx() -> bytes:
    shared = f'<sst {S}><si><t>Item</t></si><si><t>PCC below foundations</t></si><si><t>cum</t></si></sst>'
    sheet = (f'<worksheet {S}><sheetData>'
             '<row r="1"><c r="A1" t="s"><v>0</v></c></row>'
             '<row r="2"><c r="A2" t="s"><v>1</v></c><c r="B2"><v>29.999999999999996</v></c>'
             '<c r="C2" t="s"><v>2</v></c></row></sheetData></worksheet>')
    workbook = f'<workbook {S} {R}><sheets><sheet name="BOQ" sheetId="1" r:id="rId1"/></sheets></workbook>'
    rels = ('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
    return _zip({"xl/workbook.xml": workbook, "xl/_rels/workbook.xml.rels": rels,
                 "xl/sharedStrings.xml": shared, "xl/worksheets/sheet1.xml": sheet})


def _normalize(message: dict):
    return MessageNormalizer().normalize(message, contacts=[], phone_number_id="P", display_phone_number="1")


def _wa(raw_type: str, **extra: object) -> dict:
    return {"from": "919000000000", "id": f"wamid.{raw_type}", "timestamp": "1710000000", "type": raw_type, **extra}


# -- documents ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("mime, name", [
    (WORD_MIME, "Preliminary_BOQ.docx"), (EXCEL_MIME, "BOQ.xlsx"), ("application/pdf", "BOQ.pdf"),
    ("image/jpeg", "page1.jpg"), ("application/octet-stream", "BOQ.docx")])
def test_a_readable_file_is_a_document_with_its_caption_and_name(mime: str, name: str) -> None:
    """The reported file (a .docx), and its siblings: Excel, PDF, a picture sent as a file, a phone that sends no type."""
    normalized = _normalize(_wa("document", document={"id": "d1", "mime_type": mime, "filename": name,
                                                      "caption": "understand this boq"}))
    assert normalized.modality is InputModality.DOCUMENT
    assert normalized.text == "understand this boq"
    assert normalized.metadata["filename"] == name


@pytest.mark.parametrize("mime, name", [("application/msword", "old.doc"), ("application/zip", "drawings.zip"),
                                        ("image/gif", "funny.gif")])
def test_guard_other_files_are_still_declined(mime: str, name: str) -> None:
    message = _wa("document", document={"id": "d1", "mime_type": mime, "filename": name})
    assert readable_document(message) is None
    assert _normalize(message).modality is InputModality.UNKNOWN


async def test_the_receiver_downloads_a_readable_document() -> None:
    from types import SimpleNamespace

    from ingress.receiver import WhatsAppReceiver

    asked: list[str] = []

    async def download(media_id: str):  # noqa: ANN202
        asked.append(media_id)
        return SimpleNamespace(id=media_id)

    receiver = WhatsAppReceiver.__new__(WhatsAppReceiver)
    receiver._media_downloader = SimpleNamespace(download=download)  # type: ignore[attr-defined]
    await receiver._download_media_if_required(_wa("document", document={"id": "doc-7", "mime_type": WORD_MIME}))
    assert await receiver._download_media_if_required(
        _wa("document", document={"id": "doc-8", "mime_type": "application/msword"})) is None
    assert asked == ["doc-7"]


def test_a_word_file_is_read_as_text_with_its_table_rows() -> None:
    data = _docx()
    assert office_kind(data) == WORD
    text = office_text(data)
    assert text.splitlines()[0] == "Preliminary BOQ - G+1 Commercial Supermarket, 7000 sq ft"
    assert "1.1 | Excavation for foundations | 450 | cum" in text
    assert "1.2 | Foundation reinforcement steel | 7000 | kg" in text


def test_an_excel_file_is_read_sheet_by_sheet() -> None:
    data = _xlsx()
    assert office_kind(data) == EXCEL
    assert office_text(data).splitlines() == ["Sheet: BOQ", "Item", "PCC below foundations | 30 | cum"]


def test_guard_not_an_office_file_and_a_long_file_is_bounded() -> None:
    assert office_kind(b"%PDF-1.7 ...") is None and office_text(b"not a zip") == ""
    assert office_kind(_zip({"other.txt": "x"})) is None
    long = _zip({"word/document.xml": f"<w:document {W}><w:body>"
                 + "".join(_p(f"Line {n} " + "x" * 90) for n in range(400)) + "</w:body></w:document>"})
    text = office_text(long)
    assert len(text) <= MAX_CHARS + 40 and text.endswith("more lines not read)")


# -- what the agent reads ------------------------------------------------------------------------------------------


class _Vision:
    def __init__(self, result: VisionResult) -> None:
        self.result, self.mimes = result, []

    async def analyze_image(self, image, *, mime_type=None, hint=None, correlation_id=None):
        self.mimes.append(mime_type)
        return self.result


async def _describe(data: bytes, vision: _Vision, *, modality=InputModality.DOCUMENT, mime="application/octet-stream"):
    from understanding.pipeline import UnderstandingPipeline

    storage = AsyncMock()
    storage.get_object.return_value = type("Obj", (), {"data": data})()
    pipeline = UnderstandingPipeline(voice_extraction=AsyncMock(), vision=vision, object_storage=storage)
    message = NormalizedMessage(
        message_id="m1", correlation_id="cor_1", sender=SenderInfo(wa_id="919000000000"),
        timestamp=datetime(2026, 11, 15, 15, 0, tzinfo=UTC), modality=modality,
        media=MediaReference(object_key="media/x", mime_type=mime))
    return await pipeline.describe_media(message, None)


async def test_a_word_file_reaches_the_agent_as_its_text_with_no_vision_call() -> None:
    vision = _Vision(VisionResult(document_classification="unknown", description="", raw_fields={}))
    shown = await _describe(_docx(), vision, mime=WORD_MIME)
    assert shown is not None and shown.startswith("Word document:\n")
    assert "Excavation for foundations | 450 | cum" in shown
    assert vision.mimes == []  # read by the code: no AI call, no cost


async def test_a_pdf_goes_to_the_vision_model_as_a_pdf() -> None:
    vision = _Vision(VisionResult(document_classification="boq", description="A BOQ", raw_fields={}))
    assert await _describe(b"%PDF-1.7 rest", vision) == "A BOQ"
    assert vision.mimes == ["application/pdf"]


async def test_a_page_the_model_described_is_never_unreadable() -> None:
    """The reported photos: "unknown", no fields, but a description of what is on the page."""
    vision = _Vision(VisionResult(document_classification="unknown",
                                  description="Printed table: bill of quantities, items 2.1 to 2.9", raw_fields={}))
    shown = await _describe(b"\xff\xd8 jpeg", vision, modality=InputModality.IMAGE, mime="image/jpeg")
    assert shown == "Printed table: bill of quantities, items 2.1 to 2.9"


async def test_guard_an_empty_read_is_still_unreadable() -> None:
    vision = _Vision(VisionResult(document_classification="unknown", description="  ", raw_fields={}))
    assert await _describe(b"\xff\xd8", vision, modality=InputModality.IMAGE, mime="image/jpeg") is None


# -- the album marker ----------------------------------------------------------------------------------------------


def test_the_album_marker_is_answered_with_nothing() -> None:
    marker = _wa("unsupported", unsupported={"type": "album", "raw_type": "album"},
                 errors=[{"code": 131051, "title": "Message type unknown"}])
    normalized = _normalize(marker)
    assert normalized.modality is InputModality.UNKNOWN
    assert normalized.metadata["raw_type"] == "album"
    assert "album" in SILENTLY_IGNORED_RAW_TYPES


def test_guard_another_unsupported_kind_is_still_declined() -> None:
    normalized = _normalize(_wa("unsupported", unsupported={"type": "poll"}))
    assert normalized.metadata["raw_type"] == "poll" and "poll" not in SILENTLY_IGNORED_RAW_TYPES
    assert _normalize(_wa("unsupported"))  # no inner type: still normalises, declined as "this kind of message"
