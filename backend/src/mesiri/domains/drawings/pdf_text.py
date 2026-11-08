"""A drawing PDF's own text, with where each word sits (DR-01). The only file here that opens a PDF.

CAD programs export drawings with a text layer: every title-block field, room label, size and level is real text at
an exact position. ``pages`` returns it as plain dicts so the reader, facts and checks are pure functions that tests
feed with word lists. Scanned drawings have no text layer: their pages come back with no words, and the reader says
so instead of guessing.
"""

from __future__ import annotations

from typing import Any

#: Words drawn turned 90° read top-to-bottom or bottom-to-top depending on the CAD file; a rotated word whose
#: reversed spelling is one of these is turned the right way round ("LANIRU" is URINAL).
ROTATED_WORDS = frozenset({
    "URINAL", "TOILET", "WASH", "LIFT", "STAIR", "STAIRS", "PASSAGE", "WIDE", "ROOM", "KITCHEN", "BEDROOM", "HALL",
    "STORE", "SHOP", "OFFICE", "DINING", "LIVING", "SIT-OUT", "VERANDAH", "BALCONY", "LOBBY", "CORRIDOR", "RAMP",
    "PARKING", "PRAYER", "DUCT", "SHAFT", "UP", "DN", "FIRE", "CM", "WC",
})

#: Pages read at most (a drawing set rarely has more; a bigger PDF is refused before reading).
MAX_PAGES = 120


class NotAPdf(ValueError):
    """The file is not a PDF Mesiri can open."""


def turned(text: str) -> str:
    """A rotated word the right way round when only its reverse is a known word."""
    up, back = text.upper(), text[::-1].upper()
    return text[::-1] if back.strip(".") in ROTATED_WORDS and up.strip(".") not in ROTATED_WORDS else text


def stacked(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Upright letters drawn one under another ("T" "O" "I" "L" "E" "T" down a narrow toilet) as one vertical word,
    marked not upright: it is a label running down the page, not part of the lines across it."""
    singles = sorted((w for w in words if w["upright"] and len(w["text"]) <= 2), key=lambda w: (round(w["x0"]), w["top"]))
    used: set[int] = set()
    out = []
    for i, w in enumerate(singles):
        if id(w) in used:
            continue
        run = [w]
        for v in singles[i + 1:]:
            last = run[-1]
            if abs(v["x0"] - last["x0"]) <= 1.5 and 0 <= v["top"] - last["bottom"] <= 1.5 and id(v) not in used:
                run.append(v)
        if len(run) >= 3:
            used.update(id(x) for x in run)
            out.append({"text": "".join(x["text"] for x in run), "x0": min(x["x0"] for x in run),
                        "x1": max(x["x1"] for x in run), "top": run[0]["top"], "bottom": run[-1]["bottom"],
                        "size": max(x["size"] for x in run), "upright": False})
    return [w for w in words if id(w) not in used] + out


def _shown(rotation: int, raw_w: float, raw_h: float, box: tuple[float, float, float, float]) -> tuple[float, ...]:
    """A character box from the PDF's own (unrotated, bottom-left origin) space to the page as shown (top-left
    origin), for a page stored with /Rotate 0, 90, 180 or 270. Returns (x0, x1, top, bottom)."""
    left, bottom, right, top = box
    corners = [(left, bottom), (right, top)]
    if rotation == 90:
        pts = [(y, x) for x, y in corners]
    elif rotation == 180:
        pts = [(raw_w - x, y) for x, y in corners]
    elif rotation == 270:
        pts = [(raw_h - y, raw_w - x) for x, y in corners]
    else:
        pts = [(x, raw_h - y) for x, y in corners]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), max(xs), min(ys), max(ys)


def _words(page: Any, textpage: Any, rotation: int, raw_w: float, raw_h: float) -> list[dict[str, Any]]:
    """The page's characters joined into words, in the order the CAD file wrote them (which is reading order, also
    for text turned 90°). Generated spaces and line breaks end a word; so does a jump in position."""
    import math

    import pypdfium2.raw as raw

    words: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    last: tuple[float, float, float, float] | None = None

    def close() -> None:
        nonlocal cur
        if cur and cur["text"].strip():
            words.append(cur)
        cur = None

    for k in range(textpage.count_chars()):
        code = raw.FPDFText_GetUnicode(textpage, k)
        ch = chr(code) if code else ""
        if not ch or ch.isspace() or raw.FPDFText_IsGenerated(textpage, k) == 1:
            close()
            continue
        x0, x1, y0, y1 = _shown(rotation, raw_w, raw_h, tuple(float(v) for v in textpage.get_charbox(k)))
        # Upright as shown: the character's own angle less the page's rotation.
        upright = abs(math.sin(raw.FPDFText_GetCharAngle(textpage, k) - math.radians(rotation))) < 0.5
        size = float(raw.FPDFText_GetFontSize(textpage, k))
        h = max(y1 - y0, x1 - x0, 1.0)
        if cur is not None and last is not None and cur["upright"] == upright:
            lx0, lx1, ly0, ly1 = last
            # A dot or hyphen has a tiny box: measure the gap against the word's letters, not the mark's.
            h = max(h, (cur["bottom"] - cur["top"]) if upright else (cur["x1"] - cur["x0"]))
            if upright:
                near = (abs(y1 - ly1) < 0.5 * h or (y0 >= cur["top"] - 0.2 * h and y1 <= cur["bottom"] + 0.2 * h)) \
                    and -0.5 * h < x0 - lx1 < 0.35 * h
            else:
                near = (abs(x0 - lx0) < 0.6 * h or (x0 >= cur["x0"] - 0.2 * h and x1 <= cur["x1"] + 0.2 * h)) \
                    and min(abs(y0 - ly1), abs(ly0 - y1)) < 0.35 * h
            if not near:
                close()
        if cur is None:
            cur = {"text": "", "x0": x0, "x1": x1, "top": y0, "bottom": y1, "size": size, "upright": upright}
        cur["text"] += ch
        cur["x0"], cur["x1"] = min(cur["x0"], x0), max(cur["x1"], x1)
        cur["top"], cur["bottom"] = min(cur["top"], y0), max(cur["bottom"], y1)
        cur["size"] = max(cur["size"], size)
        last = (x0, x1, y0, y1)
    close()
    for w in words:
        if not w["upright"]:
            w["text"] = turned(w["text"])
    return words


def pages(data: bytes) -> list[dict[str, Any]]:
    """Each page as ``{"number", "width", "height", "words": [{"text", "x0", "x1", "top", "bottom", "size",
    "upright"}]}``, numbered from 1, positions in PDF points from the top-left.

    Read with pdfium (C, fast: a 9-sheet set in well under a second; pdfminer took 14 s on the vector-heavy sections)."""
    import pypdfium2 as pdfium

    try:
        doc = pdfium.PdfDocument(data)
    except Exception as exc:  # noqa: BLE001 - any open failure is "not a PDF we can read"
        raise NotAPdf(str(exc)) from exc
    try:
        if len(doc) > MAX_PAGES:
            raise NotAPdf(f"{len(doc)} pages; a drawing set of up to {MAX_PAGES} pages can be read")
        out = []
        for i in range(len(doc)):
            page = doc[i]
            rotation = page.get_rotation() % 360
            left, bottom, right, top = page.get_mediabox()
            raw_w, raw_h = float(right - left), float(top - bottom)
            width, height = (raw_h, raw_w) if rotation in (90, 270) else (raw_w, raw_h)
            textpage = page.get_textpage()
            out.append({"number": i + 1, "width": width, "height": height,
                        "words": stacked(_words(page, textpage, rotation, raw_w, raw_h))})
            textpage.close()
            page.close()
        return out
    finally:
        doc.close()
