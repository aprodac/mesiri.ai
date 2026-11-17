"""Drawing check reads numbers and labels with narrow characters whole, in every common font (found 17 Nov, SS-73).

A "1" has little ink in a wide box; measuring the gap between characters by their ink split "1100 x 450" into "1"
"100" and "ROOM-11" into "ROOM-1" "1" in Arial-like fonts (Helvetica here), so a room's size and name were misread.
The gap is now measured between the characters' full widths. Guard: separate words placed apart stay apart."""

from __future__ import annotations

import io

import pytest

from mesiri.domains.drawings.pdf_text import pages


@pytest.mark.parametrize("font", ["Helvetica", "Helvetica-Bold", "Courier", "Times-Roman"])
def test_narrow_characters_stay_in_their_word(font: str) -> None:
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, invariant=1)
    pdf.setFont(font, 9)
    pdf.drawString(100, 700, "1100 x 450")
    pdf.drawString(100, 650, "DATE: 11.11.2026")
    pdf.drawString(100, 600, "ROOM-11 ilil")
    pdf.drawString(100, 550, "LIVING")  # the guard: two strings placed apart are two words
    pdf.drawString(160, 550, "520")
    pdf.save()
    words = [w["text"] for w in pages(buffer.getvalue())[0]["words"]]
    assert words == ["1100", "x", "450", "DATE:", "11.11.2026", "ROOM-11", "ilil", "LIVING", "520"]
