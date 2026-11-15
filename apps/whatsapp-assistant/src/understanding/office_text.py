"""[307] The text of a Word (.docx) or Excel (.xlsx) file sent on WhatsApp, read by the code.

15 Nov 2026: an owner sent his BOQ as a Word file and was told "can't read documents or PDFs yet". The vision model
does not take Office files, and their words are already text inside the file, so the code reads them: no AI call, no
cost, nothing guessed. A table keeps its rows, one per line, cells joined with " | ", which is how a BOQ is read.

Standard library only (a .docx / .xlsx is a zip of XML). Bounded: at most ``MAX_UNZIPPED`` bytes are read from the
archive and at most ``MAX_CHARS`` characters returned, so a large or hostile file can never stall a reply.
"""

from __future__ import annotations

import io
import re
import zipfile
from xml.etree import ElementTree

#: The most bytes read out of one archive member (a zip bomb stops here).
MAX_UNZIPPED = 8 * 1024 * 1024
#: The most characters handed on: enough for a long BOQ, small enough for one model turn.
MAX_CHARS = 12_000
#: The most sheets of a workbook read.
MAX_SHEETS = 5

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"

WORD = "Word document"
EXCEL = "Excel sheet"


def office_kind(data: bytes) -> str | None:
    """``WORD`` or ``EXCEL`` when ``data`` is a .docx or .xlsx file (read from the archive itself, never from a
    mime type a phone may have got wrong), else None."""
    if not data.startswith(b"PK"):
        return None
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = set(archive.namelist())
    except (zipfile.BadZipFile, ValueError, OSError):
        return None
    if "word/document.xml" in names:
        return WORD
    if "xl/workbook.xml" in names:
        return EXCEL
    return None


def office_text(data: bytes) -> str:
    """The file's text (``""`` when it is not a Word or Excel file, or holds no text)."""
    kind = office_kind(data)
    if kind is None:
        return ""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            lines = _word_lines(archive) if kind == WORD else _excel_lines(archive)
    except (zipfile.BadZipFile, ElementTree.ParseError, KeyError, ValueError, OSError):
        return ""
    return _bounded(lines)


def _read(archive: zipfile.ZipFile, name: str) -> bytes:
    with archive.open(name) as member:
        data = member.read(MAX_UNZIPPED + 1)
    if len(data) > MAX_UNZIPPED:
        raise ValueError(f"{name} is larger than {MAX_UNZIPPED} bytes unzipped")
    return data


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _paragraph(p: ElementTree.Element) -> str:
    parts: list[str] = []
    for node in p.iter():
        if node.tag == f"{_W}t" and node.text:
            parts.append(node.text)
        elif node.tag in (f"{_W}tab", f"{_W}br"):
            parts.append(" ")
    return _clean("".join(parts))


def _word_lines(archive: zipfile.ZipFile) -> list[str]:
    body = ElementTree.fromstring(_read(archive, "word/document.xml")).find(f"{_W}body")
    if body is None:
        return []
    lines: list[str] = []
    for block in body:
        if block.tag == f"{_W}p":
            lines.append(_paragraph(block))
        elif block.tag == f"{_W}tbl":
            for row in block.iter(f"{_W}tr"):
                cells = [" ".join(t for t in (_paragraph(p) for p in cell.iter(f"{_W}p")) if t)
                         for cell in row.findall(f"{_W}tc")]
                if any(cells):
                    lines.append(" | ".join(cells))
    return [line for line in lines if line]


def _excel_lines(archive: zipfile.ZipFile) -> list[str]:
    names = set(archive.namelist())
    shared: list[str] = []
    if "xl/sharedStrings.xml" in names:
        for item in ElementTree.fromstring(_read(archive, "xl/sharedStrings.xml")).findall(f"{_S}si"):
            shared.append(_clean("".join(t.text or "" for t in item.iter(f"{_S}t"))))
    lines: list[str] = []
    for title, path in _sheets(archive, names)[:MAX_SHEETS]:
        lines.append(f"Sheet: {title}")
        root = ElementTree.fromstring(_read(archive, path))
        for row in root.iter(f"{_S}row"):
            cells = [_cell(c, shared) for c in row.findall(f"{_S}c")]
            if any(cells):
                lines.append(" | ".join(cells).strip(" |"))
    return [line for line in lines if line]


def _sheets(archive: zipfile.ZipFile, names: set[str]) -> list[tuple[str, str]]:
    """(title, path) of each sheet in the workbook's order."""
    workbook = ElementTree.fromstring(_read(archive, "xl/workbook.xml"))
    targets: dict[str, str] = {}
    if "xl/_rels/workbook.xml.rels" in names:
        for rel in ElementTree.fromstring(_read(archive, "xl/_rels/workbook.xml.rels")).findall(f"{_PKG_REL}Relationship"):
            target = str(rel.get("Target") or "").lstrip("/")
            targets[str(rel.get("Id"))] = target if target.startswith("xl/") else f"xl/{target}"
    out: list[tuple[str, str]] = []
    for number, sheet in enumerate(workbook.iter(f"{_S}sheet"), start=1):
        path = targets.get(str(sheet.get(f"{_REL}id")), f"xl/worksheets/sheet{number}.xml")
        if path in names:
            out.append((str(sheet.get("name") or f"Sheet{number}"), path))
    return out


def _cell(cell: ElementTree.Element, shared: list[str]) -> str:
    kind = cell.get("t")
    if kind == "inlineStr":
        return _clean("".join(t.text or "" for t in cell.iter(f"{_S}t")))
    value = cell.find(f"{_S}v")
    raw = (value.text or "") if value is not None else ""
    if kind == "s":
        try:
            return shared[int(raw)]
        except (ValueError, IndexError):
            return ""
    if kind != "str" and re.fullmatch(r"-?\d+\.\d{6,}", raw):
        return f"{float(raw):.2f}".rstrip("0").rstrip(".")  # 324.99999999999994 -> 325
    return _clean(raw)


def _bounded(lines: list[str]) -> str:
    out: list[str] = []
    size = 0
    for line in lines:
        if size + len(line) + 1 > MAX_CHARS:
            out.append(f"(… {len(lines) - len(out)} more lines not read)")
            break
        out.append(line)
        size += len(line) + 1
    return "\n".join(out)
