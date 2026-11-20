"""Green Villa's drawings, drawn the way an architect's and a structural consultant's office issue them: walls with
their thickness, columns on a grid, doors with their swing, windows, the stair, furniture, dimension chains, grid
bubbles, a north point and a title strip; the footing layout on the same grid with every footing to scale, its
schedule and a typical section (project bible section 5, LRN-F6).

All geometry comes from ``green_villa`` (rooms, grid, footings, columns), so the plan, the footing layout, the BOQ and
the story agree. Every sheet still reads through Drawing check exactly as before (``domains/drawings``): the room's
name with its size under it and the printed area, the title strip's labels, "F1-150X150" marks with their column and
the schedule rows; nothing else on a sheet may look like one of those (no "A x B" anywhere but a room or a footing,
no "LVL" on a plan, no rotated text).

A3 sheets: the plan at 1:50 (1 cm on site is ``K`` points on paper), the footing layout at 1:75.
"""

from __future__ import annotations

import math

from reportlab.lib import colors
from reportlab.lib.pagesizes import A3, landscape

from mesiri.application.learn import green_villa as gv

K = 72 / 2.54 / 50  # points per cm at 1:50
K75 = 72 / 2.54 / 75
EXT, INT = gv.WALL_EXT, gv.WALL_INT
WIDTH, HEIGHT = landscape(A3)
STRIP = 232  # the title strip's width, down the right side
INK = colors.HexColor("#1d1d1b")
POCHE = colors.HexColor("#8c8c88")
FAINT = colors.HexColor("#9a9a96")
OUT_W = gv.CLEAR_W + 2 * EXT  # outside face to outside face
OUT_D = gv.CLEAR_D + 2 * EXT
#: Where a room's name sits, moved off its centre so furniture does not run through it (cm).
LABEL_SHIFT = {"LIVING": (110, 40), "BEDROOM-2": (0, -90), "BEDROOM-1": (-60, -60), "STAIR": (0, 40), "SIT OUT": (0, -10),
               "TOILET": (20, -35), "STORE": (-30, 10)}


class Plan:
    """A drawing in centimetres from the building's outside front-left corner, placed on the sheet at (ox, oy)."""

    def __init__(self, pdf, ox: float, oy: float, k: float = K) -> None:  # noqa: ANN001
        self.pdf, self.ox, self.oy, self.k = pdf, ox, oy, k

    def p(self, x: float, y: float) -> tuple[float, float]:
        return self.ox + x * self.k, self.oy + y * self.k

    def rect(self, x: float, y: float, w: float, d: float, *, fill=None, stroke=True, width=0.5, dash=None) -> None:  # noqa: ANN001
        pdf = self.pdf
        pdf.saveState()
        pdf.setLineWidth(width)
        if dash:
            pdf.setDash(list(dash))
        if fill is not None:
            pdf.setFillColor(fill)
        px, py = self.p(x, y)
        pdf.rect(px, py, w * self.k, d * self.k, stroke=1 if stroke else 0, fill=1 if fill is not None else 0)
        pdf.restoreState()

    def line(self, x1: float, y1: float, x2: float, y2: float, width: float = 0.4, dash=None, color=INK) -> None:  # noqa: ANN001
        pdf = self.pdf
        pdf.saveState()
        pdf.setLineWidth(width)
        pdf.setStrokeColor(color)
        if dash:
            pdf.setDash(list(dash))
        pdf.line(*self.p(x1, y1), *self.p(x2, y2))
        pdf.restoreState()

    def arc(self, cx: float, cy: float, r: float, start: float, extent: float, width: float = 0.3) -> None:
        pdf = self.pdf
        pdf.saveState()
        pdf.setLineWidth(width)
        x, y = self.p(cx, cy)
        pdf.arc(x - r * self.k, y - r * self.k, x + r * self.k, y + r * self.k, startAng=start, extent=extent)
        pdf.restoreState()

    def text(self, x: float, y: float, s: str, size: float = 7, *, bold: bool = False, align: str = "c") -> None:
        pdf = self.pdf
        pdf.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        px, py = self.p(x, y)
        {"c": pdf.drawCentredString, "l": pdf.drawString, "r": pdf.drawRightString}[align](px, py, s)


def _in(x: float, y: float) -> tuple[float, float]:
    """A room's inside coordinates (from the inside face of the front-left walls) on the outside-corner system."""
    return x + EXT, y + EXT


# --- The sheet: border, title, the title strip ------------------------------------------------------------------------

def sheet_frame(pdf, number: str, title: str, scale: str, notes: tuple[str, ...], table=None) -> None:  # noqa: ANN001
    """Border, the sheet's title with its scale, and the title strip down the right: notes, a table (a schedule) and
    the title block (Drawing check reads its labels: PROJECT, CLIENT, DWG.TITLE, DWG.NO, REV, SCALE, DATE, DRAWN BY,
    CHECKED BY; the practice's name in capitals before ARCHITECTS)."""
    pdf.setStrokeColor(INK)
    pdf.setFillColor(INK)
    pdf.setLineWidth(1.4)
    pdf.rect(24, 24, WIDTH - 48, HEIGHT - 48)
    pdf.setLineWidth(0.5)
    pdf.rect(30, 30, WIDTH - 60, HEIGHT - 60)
    sx = WIDTH - 30 - STRIP
    pdf.setLineWidth(1)
    pdf.line(sx, 30, sx, HEIGHT - 30)
    # The sheet's own title, under the drawing, with its scale.
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(52, 52, title)
    pdf.setLineWidth(0.8)
    pdf.line(52, 48, 52 + pdf.stringWidth(title, "Helvetica-Bold", 12), 48)
    pdf.setFont("Helvetica", 8)
    pdf.drawString(52, 38, f"SCALE {scale}")
    x, y = sx + 10, HEIGHT - 50
    pdf.setFont("Helvetica-Bold", 8)
    pdf.drawString(x, y, "NOTES")
    pdf.setFont("Helvetica", 6.6)
    for i, note in enumerate(notes, 1):
        for j, part in enumerate(_wrap(pdf, f"{i}. {note}", STRIP - 22, 6.6)):
            y -= 9
            pdf.drawString(x + (8 if j else 0), y, part)
        y -= 2
    if table:
        heading, header, rows, widths = table
        y -= 16
        pdf.setFont("Helvetica-Bold", 8)
        pdf.drawString(x, y, heading)
        y -= 4
        top = y
        pdf.setFont("Helvetica-Bold", 6.2)
        y -= 9
        cx = x
        for h, w in zip(header, widths, strict=True):
            pdf.drawString(cx + 2, y, h)
            cx += w
        pdf.setFont("Helvetica", 6.2)
        for row in rows:
            y -= 9
            cx = x
            for cell, w in zip(row, widths, strict=True):
                pdf.drawString(cx + 2, y, cell)
                cx += w
        pdf.setLineWidth(0.4)
        pdf.rect(x, y - 3, sum(widths), top - y + 3)
        pdf.line(x, top - 12, x + sum(widths), top - 12)
    # The title block, from the bottom of the strip.
    by = 40
    pdf.setLineWidth(0.6)
    rows = (("CHECKED BY:", "AR" if number[0] in "AEP" else "RA"), ("DRAWN BY:", "SK"), ("DATE:", "09.10.2026"),
            ("SCALE:", scale), ("REV:", "A"), ("DWG.NO:", number))
    for key, value in rows:
        pdf.setFont("Helvetica", 7.5)
        pdf.drawString(sx + 10, by + 6, key)
        pdf.setFont("Helvetica-Bold", 8)
        pdf.drawString(sx + 80, by + 6, value)
        pdf.line(sx, by, WIDTH - 30, by)
        by += 18
    pdf.line(sx, by, WIDTH - 30, by)
    for key, value in (("DWG.TITLE:", title), ("CLIENT:", gv.CLIENT["name"].upper()),
                       ("PROJECT:", "GREEN VILLA, PUTHUR ROAD, THRISSUR")):
        pdf.setFont("Helvetica", 7.5)
        pdf.drawString(sx + 10, by + 18, key)
        pdf.setFont("Helvetica-Bold", 8)
        pdf.drawString(sx + 10, by + 7, value)
        by += 30
        pdf.line(sx, by, WIDTH - 30, by)
    office = gv.ARCHITECT.split(",")[0].upper() if number[0] != "S" else gv.CONSULTANT.split(",")[0].upper()
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(sx + 10, by + 26, office)
    pdf.setFont("Helvetica", 6.6)
    pdf.drawString(sx + 10, by + 14, "MG ROAD, THRISSUR, KERALA" if number[0] != "S" else "STRUCTURAL CONSULTANT, THRISSUR")
    pdf.drawString(sx + 10, by + 4, "ALL DIMENSIONS ARE IN CM UNLESS NOTED")
    by += 40
    pdf.line(sx, by, WIDTH - 30, by)
    pdf.setFont("Helvetica", 6)
    pdf.drawString(sx + 10, by + 6, "Sample drawing for learning Mesiri. Not for construction.")


def _wrap(pdf, text: str, width: float, size: float) -> list[str]:  # noqa: ANN001
    words, lines, cur = text.split(), [], ""
    for w in words:
        nxt = f"{cur} {w}".strip()
        if pdf.stringWidth(nxt, "Helvetica", size) > width and cur:
            lines.append(cur)
            cur = w
        else:
            cur = nxt
    return [*lines, cur] if cur else lines


# --- Plan symbols -----------------------------------------------------------------------------------------------------

def _clear(pl: Plan, x: float, y: float, w: float, d: float) -> None:
    """Cut an opening through a wall: paint it white, then draw its jambs."""
    pl.rect(x, y, w, d, fill=colors.white, stroke=False)
    if w > d:  # an opening in a wall running up the sheet: jambs are horizontal
        pl.line(x, y, x + w, y, 0.6)
        pl.line(x, y + d, x + w, y + d, 0.6)
    else:
        pl.line(x, y, x, y + d, 0.6)
        pl.line(x + w, y, x + w, y + d, 0.6)


def door_h(pl: Plan, x1: float, x2: float, wall: tuple[float, float], into: int, hinge: str, mark: str) -> None:
    """A door in a wall running across the sheet (wall = its two faces' y): into +1 opens upward, -1 downward."""
    y0, y1 = wall
    pl.rect(x1, y0, x2 - x1, y1 - y0, fill=colors.white, stroke=False)
    pl.line(x1, y0, x1, y1, 0.6)
    pl.line(x2, y0, x2, y1, 0.6)
    w = x2 - x1
    face = y1 if into > 0 else y0
    hx = x1 if hinge == "l" else x2
    pl.line(hx, face, hx, face + into * w, 0.7)
    start = (0 if hinge == "l" else 90) if into > 0 else (270 if hinge == "l" else 180)
    pl.arc(hx, face, w, start, 90, 0.25)
    pl.text((x1 + x2) / 2, face + into * (w * 0.55) - 2, mark, 5.5)


def door_v(pl: Plan, y1: float, y2: float, wall: tuple[float, float], into: int, hinge: str, mark: str) -> None:
    """A door in a wall running up the sheet (wall = its two faces' x): into +1 opens to the right."""
    x0, x1 = wall
    pl.rect(x0, y1, x1 - x0, y2 - y1, fill=colors.white, stroke=False)
    pl.line(x0, y1, x1, y1, 0.6)
    pl.line(x0, y2, x1, y2, 0.6)
    w = y2 - y1
    face = x1 if into > 0 else x0
    hy = y1 if hinge == "b" else y2
    pl.line(face, hy, face + into * w, hy, 0.7)
    start = (0 if hinge == "b" else 270) if into > 0 else (90 if hinge == "b" else 180)
    pl.arc(face, hy, w, start, 90, 0.25)
    pl.text(face + into * w * 0.55, (y1 + y2) / 2 - 2, mark, 5.5)


def window_h(pl: Plan, x1: float, x2: float, wall: tuple[float, float], mark: str, out: int) -> None:
    y0, y1 = wall
    pl.rect(x1, y0, x2 - x1, y1 - y0, fill=colors.white, stroke=False)
    pl.line(x1, y0, x1, y1, 0.6)
    pl.line(x2, y0, x2, y1, 0.6)
    for f in (0, 0.4, 0.6, 1):
        pl.line(x1, y0 + (y1 - y0) * f, x2, y0 + (y1 - y0) * f, 0.35 if f in (0.4, 0.6) else 0.5)
    pl.text((x1 + x2) / 2, (y0 if out < 0 else y1) + out * 16 - 2, mark, 5.5)


def window_v(pl: Plan, y1: float, y2: float, wall: tuple[float, float], mark: str, out: int) -> None:
    x0, x1 = wall
    pl.rect(x0, y1, x1 - x0, y2 - y1, fill=colors.white, stroke=False)
    pl.line(x0, y1, x1, y1, 0.6)
    pl.line(x0, y2, x1, y2, 0.6)
    for f in (0, 0.4, 0.6, 1):
        pl.line(x0 + (x1 - x0) * f, y1, x0 + (x1 - x0) * f, y2, 0.35 if f in (0.4, 0.6) else 0.5)
    pl.text((x0 if out < 0 else x1) + out * 20, (y1 + y2) / 2 - 2, mark, 5.5)


def dim_h(pl: Plan, xs: list[float], y: float, ext_from: float) -> None:
    """A dimension chain across the sheet at height y: ticks at each x, the distance written above each span."""
    pl.line(xs[0] - 15, y, xs[-1] + 15, y, 0.3)
    for x in xs:
        pl.line(x, ext_from, x, y - 8, 0.2, color=FAINT)
        pl.line(x - 5, y - 5, x + 5, y + 5, 0.6)
    for a, b in zip(xs, xs[1:], strict=False):
        span = b - a
        label = f"{span:g}"
        pl.text((a + b) / 2, y + 5, label, 5.6 if span < 40 else 6.3)


def dim_v(pl: Plan, ys: list[float], x: float, ext_from: float, side: int) -> None:
    """A dimension chain up the sheet at x; side -1 writes the figures left of the line, +1 right of it."""
    pl.line(x, ys[0] - 15, x, ys[-1] + 15, 0.3)
    for y in ys:
        pl.line(ext_from, y, x - side * 8, y, 0.2, color=FAINT)
        pl.line(x - 5, y - 5, x + 5, y + 5, 0.6)
    for a, b in zip(ys, ys[1:], strict=False):
        span = b - a
        pl.text(x + side * 7, (a + b) / 2 - 2, f"{span:g}", 5.6 if span < 40 else 6.3, align="l" if side > 0 else "r")


def grid(pl: Plan, top: float, left: float, bottom: float, right: float, *, through: bool) -> None:
    """Grid bubbles: letters across the top, numbers down the left; the lines dash-dot to the far side."""
    for name, x in gv.GRID_X:
        pl.line(x, bottom if through else OUT_D, x, top - 22, 0.25, dash=(6, 2, 1, 2), color=FAINT)
        cx, cy = pl.p(x, top)
        pl.pdf.setLineWidth(0.6)
        pl.pdf.circle(cx, cy, 9)
        pl.pdf.setFont("Helvetica-Bold", 8)
        pl.pdf.drawCentredString(cx, cy - 3, name)
    for name, y in gv.GRID_Y:
        pl.line(left + 22, y, right if through else 0, y, 0.25, dash=(6, 2, 1, 2), color=FAINT)
        cx, cy = pl.p(left, y)
        pl.pdf.setLineWidth(0.6)
        pl.pdf.circle(cx, cy, 9)
        pl.pdf.setFont("Helvetica-Bold", 8)
        pl.pdf.drawCentredString(cx, cy - 3, name)


def north(pdf, x: float, y: float) -> None:  # noqa: ANN001
    pdf.setLineWidth(0.6)
    pdf.circle(x, y, 16)
    p = pdf.beginPath()
    p.moveTo(x, y + 14)
    p.lineTo(x - 6, y - 10)
    p.lineTo(x, y - 5)
    p.close()
    pdf.drawPath(p, fill=1, stroke=1)
    p = pdf.beginPath()
    p.moveTo(x, y + 14)
    p.lineTo(x + 6, y - 10)
    p.lineTo(x, y - 5)
    p.close()
    pdf.drawPath(p, fill=0, stroke=1)
    pdf.setFont("Helvetica-Bold", 9)
    pdf.drawCentredString(x, y + 20, "N")


# --- Furniture and fittings (outlines only, the way a plan shows them) -------------------------------------------------

def _bed(pl: Plan, x: float, y: float, w: float = 180, d: float = 200, head: str = "top") -> None:
    pl.rect(x, y, w, d, width=0.35)
    if head == "top":
        pl.rect(x + 12, y + d - 38, w / 2 - 18, 28, width=0.25)
        pl.rect(x + w / 2 + 6, y + d - 38, w / 2 - 18, 28, width=0.25)
        pl.line(x, y + d - 55, x + w, y + d - 70, 0.25)
    else:
        pl.rect(x + d - 38, y + 12, 28, w / 2 - 18, width=0.25)
        pl.line(x + d - 55, y, x + d - 70, y + w, 0.25)


def _wardrobe(pl: Plan, x: float, y: float, w: float, d: float) -> None:
    pl.rect(x, y, w, d, width=0.35)
    pl.line(x, y, x + w, y + d, 0.2)
    pl.line(x, y + d, x + w, y, 0.2)


def _chair(pl: Plan, x: float, y: float) -> None:
    pl.rect(x, y, 42, 42, width=0.3)


def _wc(pl: Plan, x: float, y: float) -> None:
    """A European closet against a wall above it: cistern, then the pan."""
    pl.rect(x - 22, y - 18, 44, 18, width=0.35)
    cx, cy = pl.p(x, y - 45)
    pl.pdf.setLineWidth(0.35)
    pl.pdf.ellipse(cx - 18 * pl.k, cy - 26 * pl.k, cx + 18 * pl.k, cy + 26 * pl.k)


def _basin(pl: Plan, x: float, y: float) -> None:
    pl.rect(x - 25, y - 40, 50, 40, width=0.35)
    cx, cy = pl.p(x, y - 20)
    pl.pdf.setLineWidth(0.3)
    pl.pdf.ellipse(cx - 18 * pl.k, cy - 13 * pl.k, cx + 18 * pl.k, cy + 13 * pl.k)


def _stair(pl: Plan, room: tuple, *, first: bool = False, walking: bool = True) -> None:  # noqa: ANN001
    """A dog-leg stair: two flights of nine treads with a landing at the far end, "UP" at the foot; on the first floor
    "DN" too (the flight that came up), and the stair goes on to the roof."""
    _label, x, y, w, d, _a = room
    X, Y = _in(x, y)
    lobby, tread, landing = 100, 25, w - 100 - 9 * 25
    fw = (d - 10) / 2
    for f in range(10):
        tx = X + lobby + f * tread
        pl.line(tx, Y, tx, Y + fw, 0.35)
        pl.line(tx, Y + fw + 10, tx, Y + d, 0.35)
    pl.rect(X + lobby, Y + fw, 9 * tread + landing, 10, width=0.35)  # the wall between the flights
    pl.line(X + lobby + 9 * tread, Y, X + lobby + 9 * tread, Y + d, 0.5)  # landing edge
    if not walking:
        return
    # The walking line: up the first flight, across the landing, back along the second, cut by the break line.
    pl.line(X + lobby + 8, Y + fw / 2, X + w - landing / 2, Y + fw / 2, 0.45)
    pl.line(X + w - landing / 2, Y + fw / 2, X + w - landing / 2, Y + fw + 10 + fw / 2, 0.45)
    pl.line(X + w - landing / 2, Y + fw + 10 + fw / 2, X + lobby + 120, Y + fw + 10 + fw / 2, 0.45)
    ax, ay = X + lobby + 120, Y + fw + 10 + fw / 2
    pl.line(ax, ay, ax + 10, ay + 6, 0.45)
    pl.line(ax, ay, ax + 10, ay - 6, 0.45)
    pl.line(X + lobby + 95, Y + d, X + lobby + 135, Y + fw + 10, 0.5)  # the break line
    cx, cy = pl.p(X + lobby + 8, Y + fw / 2)
    pl.pdf.circle(cx, cy, 2, fill=1)
    pl.text(X + lobby + 30, Y + fw / 2 - 16, "UP", 6, bold=True)
    if first:
        pl.text(X + lobby + 30, Y + fw + 10 + fw / 2 + 8, "DN", 6, bold=True)


# --- The plans: one building shell for A-101, A-102, E-101 and P-101 ------------------------------------------------

GROUND = {"rooms": gv.GROUND_FLOOR_ROOMS, "openings": gv.GROUND_OPENINGS, "doors": gv.GROUND_DOORS,
          "windows": gv.GROUND_WINDOWS, "outside": ("SIT OUT",), "columns": [c[0] for c in gv.COLUMN_SPOTS],
          "footprint": ((0, 0, OUT_W, OUT_D),)}
#: The first floor's walls: the left and middle bays whole, the right bay from the stair hall back; the terrace and
#: the balcony are outside them.
FIRST = {"rooms": gv.FIRST_FLOOR_ROOMS, "openings": gv.FIRST_OPENINGS, "doors": gv.FIRST_DOORS,
         "windows": gv.FIRST_WINDOWS, "outside": ("TERRACE", "BALCONY"),
         "columns": [c[0] for c in gv.COLUMN_SPOTS if c[0] not in gv.STOP_AT_FIRST],
         "footprint": ((0, 0, EXT + 900, OUT_D), (EXT + 890, EXT + 360, OUT_W - EXT - 890, OUT_D - EXT - 360))}


def _shell(pl: Plan, floor: dict) -> dict:  # noqa: ANN001
    """Walls in poché with the rooms cut out, the open-air spaces outlined, openings, doors, windows and columns."""
    rooms = {r[0]: r for r in floor["rooms"]}
    for x, y, w, d in floor["footprint"]:
        pl.rect(x, y, w, d, fill=POCHE, stroke=False)
    for x, y, w, d in floor["footprint"]:
        pl.rect(x, y, w, d, width=0.9)
    for x, y, w, d in floor["footprint"]:  # where two parts of the footprint meet, no line
        pl.rect(x + 0.6, y + 0.6, w - 1.2, d - 1.2, fill=POCHE, stroke=False)
    for label, x, y, w, d, _a in floor["rooms"]:
        if label in floor["outside"]:
            continue
        X, Y = _in(x, y)
        pl.rect(X, Y, w, d, fill=colors.white, width=0.6)
    if "SIT OUT" in rooms:  # an open porch in front, its roof slab dashed, two columns, three steps down
        _l, sx, sy, sw, sd, _a = rooms["SIT OUT"]
        X, Y = _in(sx, sy)
        pl.rect(X, Y, sw, sd, width=0.6)
        pl.rect(X - 30, Y - 15, sw + 60, sd + 15, width=0.3, dash=(3, 2))
        for i in range(1, 3):
            pl.line(X + 40, Y - i * 28, X + sw - 40, Y - i * 28, 0.4)
        pl.line(X + 40, Y - 56, X + 40, Y, 0.4)
        pl.line(X + sw - 40, Y - 56, X + sw - 40, Y, 0.4)
        pl.text(X + sw / 2, Y - 50, "3 STEPS DOWN", 5.5)
    if "TERRACE" in rooms:  # the open terrace on BEDROOM-1's roof: its parapet on the two outside edges
        _l, tx, ty, tw, td, _a = rooms["TERRACE"]
        X, Y = _in(tx, ty)
        pl.rect(X - INT, 0, tw + INT + EXT, td + EXT, width=0.6)
        pl.rect(X - INT, 0, tw + INT + EXT, 15, fill=colors.HexColor("#c9c8c3"), width=0.4)
        pl.rect(OUT_W - 15, 0, 15, td + EXT, fill=colors.HexColor("#c9c8c3"), width=0.4)
        pl.text(X + tw / 2, Y + 70, "SLOPE 1 IN 100 TO RAINWATER PIPE", 5.5)
    if "BALCONY" in rooms:  # over the sit out: the slab's edge and a railing
        _l, bx, by, bw, bd, _a = rooms["BALCONY"]
        X, Y = _in(bx, by)
        pl.rect(X, Y, bw, bd, width=0.6)
        pl.rect(X + 4, Y + 4, bw - 8, bd - 4, width=0.3)
        pl.text(X + bw / 2, Y - 14, "MS RAILING 100 HIGH", 5.5)
    for x, y, w, d in floor["openings"]:
        X, Y = _in(x, y)
        _clear(pl, X, Y, w, d)
        if w > d:
            pl.line(X, Y + d / 2, X + w, Y + d / 2, 0.3, dash=(4, 2))
        else:
            pl.line(X + w / 2, Y, X + w / 2, Y + d, 0.3, dash=(4, 2))
    if floor is GROUND:  # the arch between living and dining
        X, Y = _in(40, 430)
        _clear(pl, X, Y, 440, 10)
        pl.line(X, Y + 5, X + 440, Y + 5, 0.3, dash=(4, 2))
    for kind, a, b, wall, into, hinge, mark in floor["doors"]:
        (door_h if kind == "h" else door_v)(pl, a + EXT, b + EXT, (wall[0] + EXT, wall[1] + EXT), into, hinge, mark)
    for kind, a, b, wall, mark, out in floor["windows"]:
        (window_h if kind == "h" else window_v)(pl, a + EXT, b + EXT, (wall[0] + EXT, wall[1] + EXT), mark, out)
    for mark, x, y, a, b in gv.COLUMN_SPOTS:
        if mark in floor["columns"]:
            pl.rect(x - a / 2, y - b / 2, a, b, fill=INK, width=0.3)
    return rooms


def _labels(pl: Plan, floor: dict, shift: dict, *, sizes: bool, rename: dict | None = None) -> None:  # noqa: ANN001
    """Room names; with ``sizes`` the size and the printed area under each (Drawing check reads those three lines).
    The services sheets print names only, so their rooms are not read twice."""
    pdf = pl.pdf
    for label, x, y, w, d, sqft in floor["rooms"]:
        name = (rename or {}).get(label, label)
        if not name:
            continue
        X, Y = _in(x, y)
        dx, dy = shift.get(label, (0, 0))
        px, py = pl.p(X + w / 2 + dx, Y + d / 2 + dy)
        if not sizes:  # services sheets: the name under the room's centre (the store's in its corner), clear of points
            pdf.setFont("Helvetica-Bold", 7)
            pdf.setFillColor(INK)
            if label == "STORE":
                pdf.drawString(*pl.p(X + 10, Y + d - 24), name)
            else:
                pdf.drawCentredString(*pl.p(X + w / 2, Y + d / 2 - 42), name)
            continue
        lines = [(name, "Helvetica-Bold", 7.5)]
        if sizes:
            lines.append((f"{w} X {d}", "Helvetica", 6.5))
            if sqft:
                lines.append((f"{sqft} Sq.ft", "Helvetica", 6.5))
        bw = max(pdf.stringWidth(t, f, s) for t, f, s in lines) + 8
        pdf.setFillColor(colors.white)
        pdf.rect(px - bw / 2, py + 12 - 9.5 * len(lines), bw, 9.5 * len(lines) + 1, stroke=0, fill=1)
        pdf.setFillColor(INK)
        for i, (t, f, s) in enumerate(lines):
            pdf.setFont(f, s)
            pdf.drawCentredString(px, py + 3 - i * 9, t)


def _chains(pl: Plan, ys_left: list[float], *, bottom: bool = True) -> None:
    xs = [0, EXT]
    for w in gv.BAYS_X:
        xs.append(xs[-1] + w)
        xs.append(xs[-1] + INT)
    xs[-1] = xs[-2] + EXT
    if bottom:
        dim_h(pl, xs, -322, -305)
        dim_h(pl, [0, OUT_W], -362, -330)
    dim_h(pl, xs, OUT_D + 62, OUT_D + 40)
    dim_v(pl, ys_left, -70, -40, -1)
    dim_v(pl, [0, OUT_D], -122, -80, -1)


def _section_marks(pl: Plan) -> None:
    x = EXT + 450
    for yy, up in ((-95, False), (OUT_D + 32, True)):
        pl.line(x, yy, x, yy + (25 if not up else -25), 1.6)
        px, py = pl.p(x - 30, yy + (8 if not up else -8))
        pl.pdf.setLineWidth(0.5)
        pl.pdf.circle(px, py, 7)
        pl.pdf.setFont("Helvetica-Bold", 7)
        pl.pdf.drawCentredString(px, py - 2.5, "A")


def _opening_list(floor: dict) -> tuple:
    counts: dict[str, int] = {}
    for item in (*floor["doors"], *floor["windows"]):
        mark = item[6] if len(item) == 7 else item[4]
        counts[mark] = counts.get(mark, 0) + 1
    rows = [[m, t, str(w), str(h), str(counts[m])] for m, t, w, h in gv.OPENING_TYPES if m in counts]
    return ("DOOR AND WINDOW LIST", ("MARK", "TYPE", "W", "H", "NOS"), rows, (28, 104, 24, 24, 26))


def _rev_b(pdf) -> None:  # noqa: ANN001
    sx = WIDTH - 30 - STRIP
    pdf.setFillColor(colors.white)
    pdf.rect(sx + 80, 40 + 4 * 18 + 3, 60, 13, stroke=0, fill=1)
    pdf.setFillColor(INK)
    pdf.setFont("Helvetica-Bold", 8)
    pdf.drawString(sx + 80, 40 + 4 * 18 + 6, "B")


PLAN_NOTES = ("Read with S-101, S-102 and the section A-301.",
              "External walls 23 cm solid block, partitions 10 cm brick, plastered both sides.",
              "Columns shown solid; their sizes are on S-102.",
              "Sizes in rooms are clear inside sizes; areas are carpet areas.",
              "Stair: 20 risers of 17 cm, treads 25 cm, two flights with a landing.")


# --- A-101 and A-102 ------------------------------------------------------------------------------------------------

def ground_floor(pdf, rev: str = "A") -> None:  # noqa: ANN001
    """A-101 at 1:50, one A3 sheet. ``rev`` "B" is the copy issued alone (the kit's first file)."""
    pl = Plan(pdf, 150, 282)
    rooms = _shell(pl, GROUND)
    _furnish(pl, rooms)
    _stair(pl, rooms["STAIR"])
    _labels(pl, GROUND, LABEL_SHIFT, sizes=True)
    _chains(pl, [0, EXT, EXT + 430, EXT + 440, OUT_D - EXT, OUT_D])
    grid(pl, OUT_D + 126, -180, -20, OUT_W, through=False)
    north(pdf, *pl.p(OUT_W - 60, -235))
    _section_marks(pl)
    pl.text(OUT_W - 10, -140, "PLINTH 45 ABOVE GROUND, FLOOR FINISH VITRIFIED TILE", 5.8, align="r")
    sheet_frame(pdf, "A-101", "GROUND FLOOR PLAN", "1:50", PLAN_NOTES, _opening_list(GROUND))
    if rev != "A":
        _rev_b(pdf)


FIRST_SHIFT = {"FAMILY LIVING": (110, 40), "BEDROOM-3": (60, -90), "BEDROOM-4": (0, -90), "STAIR": (0, 40),
               "STUDY": (-30, -45), "UTILITY": (-25, 35), "TOILET": (30, -40), "TERRACE": (0, 10)}


def first_floor(pdf) -> None:  # noqa: ANN001
    """A-102 at 1:50: the first floor on the ground floor's grid and walls."""
    pl = Plan(pdf, 150, 282)
    rooms = _shell(pl, FIRST)
    at = {k: (*_in(v[1], v[2]), v[3], v[4]) for k, v in rooms.items()}
    X, Y, w, d = at["FAMILY LIVING"]  # sofa on the left wall, TV unit on the right
    pl.rect(X + 10, Y + 90, 85, 210, width=0.35)
    pl.rect(X + 10, Y + 90, 20, 210, width=0.25)
    pl.rect(X + 130, Y + 170, 110, 60, width=0.3)
    pl.rect(X + w - 45, Y + 120, 35, 180, width=0.3)
    X, Y, w, d = at["BEDROOM-3"]  # bed against the back wall, wardrobe on the right
    _bed(pl, X + 60, Y + 90)
    _wardrobe(pl, X + w - 62, Y + 100, 60, 180)
    X, Y, w, d = at["BEDROOM-4"]
    _bed(pl, X + 70, Y + 150)
    _wardrobe(pl, X + 2, Y + 20, 60, 180)
    X, Y, w, d = at["STUDY"]  # a desk on the back wall, a chair, a bookshelf
    pl.rect(X + 140, Y + d - 60, 140, 60, width=0.35)
    _chair(pl, X + 190, Y + d - 110)
    pl.rect(X + w - 40, Y + 20, 35, 180, width=0.3, dash=(3, 2))
    X, Y, w, d = at["UTILITY"]  # a washing machine
    pl.rect(X + 130, Y + 85, 60, 60, width=0.35)
    cx, cy = pl.p(X + 160, Y + 115)
    pdf.setLineWidth(0.3)
    pdf.circle(cx, cy, 22 * pl.k)
    X, Y, w, d = at["TOILET"]
    _wc(pl, X + 50, Y + d)
    _basin(pl, X + 110, Y + d)
    pl.rect(X + w - 70, Y + d - 90, 70, 90, width=0.3)
    pl.line(X + w - 70, Y + d - 90, X + w, Y + d, 0.2)
    pl.line(X + w - 70, Y + d, X + w, Y + d - 90, 0.2)
    _stair(pl, rooms["STAIR"], first=True)
    _labels(pl, FIRST, FIRST_SHIFT, sizes=True)
    _chains(pl, [0, EXT, EXT + 430, EXT + 440, OUT_D - EXT, OUT_D])
    grid(pl, OUT_D + 126, -180, -20, OUT_W, through=False)
    north(pdf, *pl.p(OUT_W - 60, -235))
    _section_marks(pl)
    pl.text(OUT_W - 10, -140, "FIRST FLOOR 300 ABOVE THE GROUND FLOOR, FLOOR FINISH VITRIFIED TILE", 5.8, align="r")
    pl.text(EXT + 270, -250, "SIT OUT BELOW", 5.5)
    notes = (*PLAN_NOTES[:4], "The stair continues to the roof; the overhead tank stands on the roof over the stair.")
    sheet_frame(pdf, "A-102", "FIRST FLOOR PLAN", "1:50", notes, _opening_list(FIRST))


# --- E-101: electrical layout -----------------------------------------------------------------------------------------

#: Points per ground floor room, at (x, y) inside the room: L light, F fan, S 5A socket, P 15A power socket, E exhaust
#: fan, T TV, SB the switch board (by the door). A point's wire runs from its room's switch board.
ELEC = {
    "LIVING": {"SB": (340, 14), "L": [(130, 320), (390, 320), (130, 110)], "F": [(260, 210)],
               "S": [(14, 330), (506, 90), (130, 14)], "T": [(506, 210)]},
    "DINING": {"SB": (506, 70), "L": [(130, 150), (390, 150)], "F": [(260, 150)], "S": [(14, 250), (506, 230)],
               "P": [(300, 286)]},
    "BEDROOM-2": {"SB": (240, 346), "L": [(180, 260), (60, 60)], "F": [(180, 170)], "S": [(14, 100), (346, 100)],
                  "P": [(100, 346)]},
    "BEDROOM-1": {"SB": (110, 346), "L": [(210, 260), (360, 60)], "F": [(250, 170)], "S": [(406, 120), (406, 300)],
                  "P": [(300, 346)]},
    "PASSAGE": {"SB": (30, 14), "L": [(180, 70)]},
    "KITCHEN": {"SB": (115, 14), "L": [(160, 120), (290, 200)], "E": [(100, 226)], "S": [(346, 60), (250, 226)],
                "P": [(346, 150), (25, 170)]},
    "STAIR": {"SB": (14, 160), "L": [(315, 105), (50, 105)]},
    "STORE": {"SB": (70, 14), "L": [(85, 90)]},
    "TOILET": {"SB": (110, 14), "L": [(120, 75)], "E": [(200, 136)], "P": [(226, 100)]},
    "SIT OUT": {"SB": (90, 226), "L": [(150, 120)], "S": [(14, 200)]},
}
SYMBOLS = (("L", "LIGHT POINT"), ("F", "CEILING FAN"), ("S", "5A SOCKET"), ("P", "15A POWER SOCKET"),
           ("E", "EXHAUST FAN"), ("T", "TV AND DATA POINT"), ("SB", "SWITCH BOARD"))
WIRE = colors.HexColor("#b03a2e")


def _symbol(pl: Plan, kind: str, x: float, y: float) -> None:
    pdf = pl.pdf
    cx, cy = pl.p(x, y)
    pdf.saveState()
    pdf.setLineWidth(0.6)
    pdf.setStrokeColor(INK)
    pdf.setFillColor(colors.white)
    if kind == "L":
        pdf.circle(cx, cy, 4.2, fill=1)
        pdf.line(cx - 3, cy - 3, cx + 3, cy + 3)
        pdf.line(cx - 3, cy + 3, cx + 3, cy - 3)
    elif kind == "F":
        pdf.circle(cx, cy, 5.5, fill=1)
        pdf.setFillColor(INK)
        pdf.circle(cx, cy, 1.4, fill=1)
        for ang in (90, 210, 330):
            r = math.radians(ang)
            pdf.line(cx, cy, cx + 5.5 * math.cos(r), cy + 5.5 * math.sin(r))
    elif kind in ("S", "P"):
        p = pdf.beginPath()
        p.moveTo(cx - 4, cy - 3)
        p.lineTo(cx + 4, cy - 3)
        p.lineTo(cx, cy + 4)
        p.close()
        pdf.setFillColor(INK if kind == "P" else colors.white)
        pdf.drawPath(p, fill=1, stroke=1)
    elif kind == "E":
        pdf.rect(cx - 5, cy - 5, 10, 10, fill=1)
        pdf.line(cx - 5, cy - 5, cx + 5, cy + 5)
        pdf.line(cx - 5, cy + 5, cx + 5, cy - 5)
    elif kind == "T":
        pdf.rect(cx - 5, cy - 3.5, 10, 7, fill=1)
        pdf.setFillColor(INK)
        pdf.setFont("Helvetica-Bold", 4.5)
        pdf.drawCentredString(cx, cy - 1.5, "TV")
    elif kind == "SB":
        pdf.setFillColor(INK)
        pdf.rect(cx - 5, cy - 2.5, 10, 5, fill=1)
    elif kind == "DB":
        pdf.setFillColor(INK)
        pdf.rect(cx - 9, cy - 4, 18, 8, fill=1)
        pdf.setFillColor(colors.white)
        pdf.setFont("Helvetica-Bold", 5)
        pdf.drawCentredString(cx, cy - 1.8, "DB")
    pdf.restoreState()


def _wire(pl: Plan, a: tuple[float, float], b: tuple[float, float], width: float = 0.45, bend: float = 0.18) -> None:
    """A conduit run drawn as a curve, the way wiring layouts show it."""
    pdf = pl.pdf
    (x1, y1), (x2, y2) = pl.p(*a), pl.p(*b)
    mx, my = (x1 + x2) / 2, (y1 + y2) / 2
    nx, ny = -(y2 - y1) * bend, (x2 - x1) * bend
    pdf.saveState()
    pdf.setStrokeColor(WIRE)
    pdf.setLineWidth(width)
    pdf.setDash([2.5, 1.5])
    p = pdf.beginPath()
    p.moveTo(x1, y1)
    p.curveTo(mx + nx, my + ny, mx + nx, my + ny, x2, y2)
    pdf.drawPath(p, stroke=1, fill=0)
    pdf.restoreState()


SERVICE_NAMES = {"TOILET": "BATH", "STAIR": ""}


def electrical(pdf) -> None:  # noqa: ANN001
    """E-101 at 1:50: the ground floor's points, switch boards and wiring runs, the board and the earth pit."""
    pl = Plan(pdf, 150, 282)
    rooms = _shell(pl, GROUND)
    _stair(pl, rooms["STAIR"], walking=False)
    counts = dict.fromkeys((k for k, _ in SYMBOLS), 0)
    db = _in(100, 14)
    for label, pts in ELEC.items():
        X, Y = _in(*rooms[label][1:3])
        sb = (X + pts["SB"][0], Y + pts["SB"][1])
        _wire(pl, db, sb, 0.7, 0.05)
        for kind, spots in pts.items():
            if kind == "SB":
                continue
            for x, y in spots:
                _wire(pl, sb, (X + x, Y + y))
        for kind, spots in pts.items():
            for x, y in ([spots] if kind == "SB" else spots):
                _symbol(pl, kind, X + x, Y + y)
                counts[kind] += 1
    _symbol(pl, "DB", *db)
    pl.text(db[0] - 8, db[1] + 26, "MAIN DB, 8 WAY", 5.5, align="l")
    meter = (OUT_W - 40, -60)
    _wire(pl, meter, db, 0.9)
    pl.rect(meter[0] - 12, meter[1] - 8, 24, 16, width=0.6)
    pl.text(meter[0], meter[1] - 3, "M", 6, bold=True)
    pl.text(meter[0] - 20, meter[1] - 3, "KSEB METER ON THE COMPOUND WALL", 5.5, align="r")
    ep = (OUT_W - 40, -200)
    cx, cy = pl.p(*ep)
    pdf.setLineWidth(0.6)
    pdf.circle(cx, cy, 6)
    for i in range(3):
        pdf.line(cx - 6 + i * 2, cy - 2 - i * 2.5, cx + 6 - i * 2, cy - 2 - i * 2.5)
    pl.text(ep[0] - 20, ep[1] - 3, "EARTH PITS, TWO, 3 M APART", 5.5, align="r")
    _wire(pl, ep, db, 0.6)
    _labels(pl, GROUND, LABEL_SHIFT, sizes=False, rename=SERVICE_NAMES)
    north(pdf, *pl.p(-120, -235))
    # The legend: each symbol with how many this floor has.
    lx, ly = pl.p(EXT + 560, -60)
    pdf.setFont("Helvetica-Bold", 7.5)
    pdf.drawString(lx - 10, ly + 14, "LEGEND")
    for i, (kind, name) in enumerate(SYMBOLS):
        col, row = divmod(i, 4)
        sx_, sy_ = lx + col * 165, ly - row * 15
        x_cm, y_cm = (sx_ - pl.ox) / pl.k, (sy_ - pl.oy) / pl.k
        _symbol(pl, kind, x_cm, y_cm)
        pdf.setFont("Helvetica", 6.3)
        pdf.drawString(sx_ + 12, sy_ - 2, f"{name}: {counts[kind]}")
    notes = ("Wiring in PVC conduits concealed in walls and slabs.",
             "Copper wire: 1.5 sq mm for lights and fans, 2.5 sq mm for 5A sockets, 4 sq mm for 15A power.",
             "Switch boards 120 above the floor; sockets 30 above the floor; kitchen sockets above the counter.",
             "Each 15A socket on its own MCB at the DB; an RCCB on the incomer.",
             "Two earth pits, connected to the DB by 8 SWG copper.",
             f"This floor: {sum(counts[k] for k in ('L', 'F', 'S', 'P', 'E', 'T'))} points.")
    sheet_frame(pdf, "E-101", "ELECTRICAL LAYOUT GROUND FLOOR", "1:50", notes)


# --- P-101: plumbing layout -------------------------------------------------------------------------------------------

WATER = colors.HexColor("#1f6fb2")
DRAIN = colors.HexColor("#8a5a2b")
RAIN = colors.HexColor("#3a7d44")


def _pipe(pl: Plan, pts: list[tuple[float, float]], color, width: float = 1.0, dash=None) -> None:  # noqa: ANN001
    pdf = pl.pdf
    pdf.saveState()
    pdf.setStrokeColor(color)
    pdf.setLineWidth(width)
    if dash:
        pdf.setDash(list(dash))
    p = pdf.beginPath()
    p.moveTo(*pl.p(*pts[0]))
    for q in pts[1:]:
        p.lineTo(*pl.p(*q))
    pdf.drawPath(p, stroke=1, fill=0)
    pdf.restoreState()


def _chamber(pl: Plan, x: float, y: float, name: str, size: float = 45) -> None:
    pl.rect(x - size / 2, y - size / 2, size, size, fill=colors.white, width=0.7)
    pl.line(x - size / 2, y - size / 2, x + size / 2, y + size / 2, 0.3)
    pl.text(x, y + size / 2 + 8, name, 5.8, bold=True)


def plumbing(pdf) -> None:  # noqa: ANN001
    """P-101 at 1:50: water from the sump to the overhead tank and down to each point; soil and waste to the
    inspection chambers, the septic tank and the soak pit; rainwater to the recharge pit."""
    pl = Plan(pdf, 122, 232)
    rooms = _shell(pl, GROUND)
    _stair(pl, rooms["STAIR"], walking=False)
    at = {k: _in(v[1], v[2]) for k, v in rooms.items()}
    tx, ty = at["TOILET"]
    kx, ky = at["KITCHEN"]
    _wc(pl, tx + 50, ty + 150)
    _basin(pl, tx + 130, ty + 150)
    pl.rect(tx + 160, ty + 60, 80, 90, width=0.3)
    _basin(pl, *(_in(505, 560)))  # the dining room's wash basin, on the right wall
    pl.rect(kx + 235, ky + 188, 80, 42, width=0.3)  # kitchen sink
    # Water: the down take from the overhead tank in the back wall between store and toilet, along the back wall.
    dt = (EXT + 1075, OUT_D - 30)
    _pipe(pl, [dt, (tx + 50, ty + 128)], WATER)
    _pipe(pl, [dt, (dt[0], ty + 120), (tx + 130, ty + 120)], WATER)
    _pipe(pl, [dt, (dt[0], ty + 40), (tx + 200, ty + 40), (tx + 200, ty + 105)], WATER)
    _pipe(pl, [dt, (kx + 275, dt[1]), (kx + 275, ky + 200)], WATER)
    _pipe(pl, [(kx + 275, dt[1]), (EXT + 540, dt[1]), (EXT + 540, EXT + 560 - 20)], WATER)
    _pipe(pl, [(kx + 100, dt[1]), (kx + 100, OUT_D + 30)], WATER)
    pl.text(kx + 112, OUT_D + 30, "GARDEN TAP", 5.5, align="l")
    cx, cy = pl.p(*dt)
    pdf.setFillColor(WATER)
    pdf.circle(cx, cy, 3.2, fill=1)
    pdf.setFillColor(INK)
    pl.text(dt[0], dt[1] - 22, "DOWN TAKE 32 CPVC FROM OHT", 5.5)
    # The overhead tank on the roof over the stair, and the rising main from the sump.
    sx0, sy0 = _in(900 + 120, 370 + 40)
    pl.rect(sx0, sy0, 180, 130, width=0.5, dash=(4, 2))
    ox_, oy_ = pl.p(sx0 + 90, sy0 + 64)
    pdf.setFillColor(colors.white)
    pdf.rect(ox_ - 38, oy_ - 9, 76, 21, stroke=0, fill=1)
    pdf.setFillColor(INK)
    pl.text(sx0 + 90, sy0 + 70, "OHT 2000 L", 6, bold=True)
    pl.text(sx0 + 90, sy0 + 58, "ON THE ROOF ABOVE", 5.5)
    sump = (OUT_W - 150, -190)
    pl.rect(sump[0] - 90, sump[1] - 55, 180, 110, width=0.7, fill=colors.white)
    pl.rect(sump[0] - 84, sump[1] - 49, 168, 98, width=0.3, dash=(3, 2))
    pl.text(sump[0], sump[1] + 6, "SUMP 10,000 L", 6, bold=True)
    pl.text(sump[0], sump[1] - 8, "UNDERGROUND, 1.5 M DEEP", 5.5)
    _pipe(pl, [(sump[0] - 90, sump[1] + 30), (OUT_W + 25, sump[1] + 30), (OUT_W + 25, sy0 + 60), (sx0 + 180, sy0 + 60)],
          WATER, 1.3, (5, 2))
    pl.text(OUT_W + 5, -20, "RISING MAIN 32 CPVC, PUMP 1 HP", 5.5, align="r")
    _pipe(pl, [(sump[0] + 90, sump[1]), (sump[0] + 140, sump[1])], WATER, 1.3)
    pl.text(sump[0] + 115, sump[1] + 10, "MAIN", 5.5)
    # Soil from the closet and waste from the basin and shower to IC 1 behind the toilet; kitchen waste through the
    # gully trap to IC 2; both on to the septic tank and the soak pit.
    ic1, ic2, ic3 = (tx + 60, OUT_D + 55), (kx + 275, OUT_D + 55), (EXT + 780, OUT_D + 140)
    _pipe(pl, [(tx + 50, ty + 105), (tx + 50, OUT_D), ic1], DRAIN, 1.6)
    _pipe(pl, [(tx + 130, ty + 130), (tx + 130, OUT_D + 20), (ic1[0] + 22, ic1[1])], DRAIN, 1.0)
    _pipe(pl, [(tx + 200, ty + 105), (tx + 200, OUT_D + 40), (ic1[0] + 22, ic1[1] + 10)], DRAIN, 1.0)
    _pipe(pl, [(kx + 275, ky + 210), (kx + 275, OUT_D)], DRAIN, 1.0)
    gt = (kx + 275, OUT_D + 25)
    _pipe(pl, [gt, ic2], DRAIN, 1.0)
    _pipe(pl, [(EXT + 505, EXT + 560 - 30), (EXT + 470, EXT + 560 - 30), (EXT + 470, OUT_D + 60), (ic2[0] - 22, ic2[1])],
          DRAIN, 1.0)
    septic = (EXT + 1050, OUT_D + 100, 240, 100)
    _pipe(pl, [ic1, (ic1[0], septic[1] + 50 + 0), (septic[0] + septic[2], septic[1] + 50)], DRAIN, 1.6)
    _pipe(pl, [ic2, (ic2[0], ic3[1]), ic3], DRAIN, 1.2)
    _chamber(pl, *ic1, "IC 1")
    _chamber(pl, *ic2, "IC 2")
    _chamber(pl, *ic3, "IC 3")
    pl.rect(gt[0] - 12, gt[1] - 12, 24, 24, fill=colors.white, width=0.6)
    pl.text(gt[0] + 18, gt[1] - 3, "GT", 5.8, bold=True, align="l")
    sx_, sy_, sw, sd = septic
    pl.rect(sx_, sy_, sw, sd, fill=colors.white, width=0.8)
    pl.line(sx_ + sw * 0.62, sy_, sx_ + sw * 0.62, sy_ + sd, 0.5)
    pl.text(sx_ + sw / 2, sy_ + sd / 2 + 4, "SEPTIC TANK", 6, bold=True)
    pl.text(sx_ + sw / 2, sy_ + sd / 2 - 8, "2.4 M BY 1.0 M, 1.5 M DEEP, 2 CHAMBERS", 5.2)
    soak = (EXT + 900, OUT_D + 150)
    _pipe(pl, [(sx_, sy_ + 50), (soak[0] + 50, soak[1])], DRAIN, 1.2)
    _pipe(pl, [ic3, (soak[0] - 50, soak[1])], DRAIN, 1.2)
    cx, cy = pl.p(*soak)
    pdf.setLineWidth(0.8)
    pdf.setFillColor(colors.white)
    pdf.circle(cx, cy, 50 * pl.k, fill=1)
    pdf.setFillColor(INK)
    pl.text(soak[0], soak[1] - 3, "SOAK PIT", 5.8, bold=True)
    pl.text(soak[0], soak[1] - 62, "1.2 M DIA, 2.5 M DEEP", 5.2)
    # Rainwater: a pipe at each corner of the roof to the recharge pit.
    pit = (180, OUT_D + 150)
    rwps = ((-12, OUT_D + 12), (OUT_W + 12, OUT_D + 12), (-12, -12), (EXT + 890 + 12, -12))
    for i, (x, y) in enumerate(rwps, 1):
        cx, cy = pl.p(x, y)
        pdf.setFillColor(RAIN)
        pdf.circle(cx, cy, 3.2, fill=1)
        pdf.setFillColor(INK)
        pl.text(x + (16 if x > 0 else -16), y + (10 if y > 0 else -16), f"RWP {i}", 5.2, align="l" if x > 0 else "r")
    _pipe(pl, [rwps[0], (rwps[0][0], pit[1]), (pit[0] - 60, pit[1])], RAIN, 1.0, (4, 2))
    _pipe(pl, [rwps[2], (-45, -12), (-45, pit[1] - 20), (pit[0] - 60, pit[1] - 20)], RAIN, 1.0, (4, 2))
    _pipe(pl, [rwps[1], (OUT_W + 12, OUT_D + 95), (pit[0] + 60, OUT_D + 95), (pit[0] + 60, pit[1] - 30)], RAIN, 1.0, (4, 2))
    _pipe(pl, [rwps[3], (EXT + 902, -40), (-30, -40)], RAIN, 1.0, (4, 2))
    pl.rect(pit[0] - 60, pit[1] - 45, 120, 90, fill=colors.white, width=0.7)
    pl.text(pit[0], pit[1] + 4, "RECHARGE PIT", 5.8, bold=True)
    pl.text(pit[0], pit[1] - 8, "1.2 M SQUARE", 5.2)
    _labels(pl, GROUND, LABEL_SHIFT, sizes=False, rename=SERVICE_NAMES)
    north(pdf, *pl.p(-80, -235))
    lx, ly = pl.p(EXT + 520, -110)
    pdf.setFont("Helvetica-Bold", 7.5)
    pdf.drawString(lx, ly + 16, "LEGEND")
    for i, (color, width, dash, name) in enumerate(((WATER, 1.0, None, "WATER SUPPLY, CPVC"),
                                                    (WATER, 1.3, (5, 2), "RISING MAIN FROM THE SUMP"),
                                                    (DRAIN, 1.6, None, "SOIL, 110 SWR PVC"),
                                                    (DRAIN, 1.0, None, "WASTE, 75 SWR PVC"),
                                                    (RAIN, 1.0, (4, 2), "RAINWATER, 110 PVC"))):
        y = ly - i * 13
        pdf.saveState()
        pdf.setStrokeColor(color)
        pdf.setLineWidth(width)
        if dash:
            pdf.setDash(list(dash))
        pdf.line(lx, y, lx + 30, y)
        pdf.restoreState()
        pdf.setFont("Helvetica", 6.3)
        pdf.drawString(lx + 38, y - 2, name)
    pdf.drawString(lx + 190, ly, "IC: INSPECTION CHAMBER, 45 SQUARE")
    pdf.drawString(lx + 190, ly - 13, "GT: GULLY TRAP")
    pdf.drawString(lx + 190, ly - 26, "RWP: RAINWATER PIPE, 110 PVC")
    notes = ("Water supply in CPVC: 32 down take, 25 branches, 20 to each point.",
             "Soil and waste in SWR PVC with a slope of 1 in 60; IC at every change of direction.",
             "Septic tank and soak pit at least 7.5 M from any well.",
             "Floor traps in the bath and the utility; nahani traps sunk 15 below the floor.",
             "First floor points stand over these; their down pipes run in the duct behind the toilet.")
    sheet_frame(pdf, "P-101", "PLUMBING LAYOUT GROUND FLOOR", "1:50", notes)


def _furnish(pl: Plan, rooms: dict) -> None:  # noqa: ANN001
    def at(label: str) -> tuple[float, float, float, float]:
        _l, x, y, w, d, _a = rooms[label]
        X, Y = _in(x, y)
        return X, Y, w, d

    X, Y, w, d = at("LIVING")  # sofa along the left wall, two chairs, a centre table, TV unit on the right
    pl.rect(X + 10, Y + 90, 85, 210, width=0.35)
    pl.rect(X + 10, Y + 90, 20, 210, width=0.25)
    _chair(pl, X + 140, Y + 300)
    _chair(pl, X + 200, Y + 300)
    pl.rect(X + 130, Y + 170, 110, 60, width=0.3)
    pl.rect(X + w - 45, Y + 120, 35, 180, width=0.3)
    X, Y, w, d = at("DINING")  # a table for six
    tx, ty = X + 40, Y + d / 2 - 45
    pl.rect(tx, ty, 150, 90, width=0.35)
    for i in range(3):
        _chair(pl, tx + 8 + i * 48, ty - 46)
        _chair(pl, tx + 8 + i * 48, ty + 94)
    pl.rect(X + w - 150, Y + d - 55, 140, 45, width=0.3)  # a crockery shelf
    X, Y, w, d = at("KITCHEN")  # counter along the back and the right, sink and hob, fridge
    pl.rect(X + 210, Y + d - 60, w - 210, 60, width=0.35)
    pl.rect(X + w - 60, Y, 60, d - 60, width=0.35)
    pl.rect(X + 235, Y + d - 52, 80, 42, width=0.3)  # the sink, two bowls
    pl.line(X + 275, Y + d - 52, X + 275, Y + d - 10, 0.3)
    for i in range(2):
        for j in range(2):
            cx, cy = pl.p(X + w - 42 + j * 24, Y + 50 + i * 30)
            pl.pdf.circle(cx, cy, 5)
    pl.rect(X + 10, Y + d - 80, 70, 70, width=0.3)  # the fridge
    pl.line(X + 10, Y + d - 80, X + 80, Y + d - 10, 0.2)
    X, Y, w, d = at("BEDROOM-2")  # bed against the left wall, wardrobe on the back wall
    _bed(pl, X + 70, Y + 150)
    _wardrobe(pl, X + 2, Y + 20, 60, 180)
    X, Y, w, d = at("BEDROOM-1")  # bed against the back wall, wardrobe on the left, a table under the window
    _bed(pl, X + 220, Y + 150)
    _wardrobe(pl, X + 10, Y + 20, 60, 180)
    pl.rect(X + 150, Y + 10, 100, 50, width=0.3)
    X, Y, w, d = at("TOILET")  # closet, basin, shower
    _wc(pl, X + 50, Y + d)
    _basin(pl, X + 130, Y + d)
    pl.rect(X + w - 80, Y + d - 90, 80, 90, width=0.3)
    pl.line(X + w - 80, Y + d - 90, X + w, Y + d, 0.2)
    pl.line(X + w - 80, Y + d, X + w, Y + d - 90, 0.2)
    X, Y, w, d = at("STORE")  # a shelf along the back wall
    pl.rect(X, Y + d - 30, w, 30, width=0.3, dash=(3, 2))


# --- S-101: the footing layout --------------------------------------------------------------------------------------

def footing_layout(pdf) -> None:  # noqa: ANN001
    """S-101 at 1:75: the grid, every footing to scale with its PCC bed, its mark ("F1-150X150") under it and its column
    ("C1") beside the column, the plinth beams; the schedule (the rows Drawing check reads) and a typical section."""
    pl = Plan(pdf, 250, 420, K75)
    grid(pl, OUT_D + 190, -215, -330, OUT_W + 110, through=True)
    for (x1, y1), (x2, y2) in gv.PLINTH_BEAMS:  # plinth beams, 23 wide, under the walls
        if y1 == y2:
            pl.rect(min(x1, x2), y1 - 11.5, abs(x2 - x1), 23, width=0.3, dash=(2, 1.5))
        else:
            pl.rect(x1 - 11.5, min(y1, y2), 23, abs(y2 - y1), width=0.3, dash=(2, 1.5))
    by_col = {c: f for f in gv.FOOTINGS for c in f[5]}
    for mark, x, y, a, b in gv.COLUMN_SPOTS:
        f = by_col[mark]
        fa, fb = f[1], f[2]
        pl.rect(x - fa / 2 - 10, y - fb / 2 - 10, fa + 20, fb + 20, width=0.3, dash=(3, 2))  # the PCC, 10 beyond
        pl.rect(x - fa / 2, y - fb / 2, fa, fb, fill=colors.white, width=0.7)
        for sx_, sy_ in ((-1, -1), (1, -1), (1, 1), (-1, 1)):  # the slope, from the edge up to the column
            pl.line(x + sx_ * fa / 2, y + sy_ * fb / 2, x + sx_ * (a / 2 + 10), y + sy_ * (b / 2 + 10), 0.25)
        pl.rect(x - a / 2 - 10, y - b / 2 - 10, a + 20, b + 20, width=0.25)
        pl.rect(x - a / 2, y - b / 2, a, b, fill=INK, width=0.3)
        label = f"{f[0]}-{fa}X{fb}"
        lx, ly = pl.p(x, y - fb / 2 - 38)
        tw = pdf.stringWidth(label, "Helvetica-Bold", 6)
        pdf.setFillColor(colors.white)
        pdf.rect(lx - tw / 2 - 2, ly - 2, tw + 4, 8, stroke=0, fill=1)
        pdf.setFillColor(INK)
        pl.text(x, y - fb / 2 - 38, label, 6, bold=True)
        pl.text(x + a / 2 + 8, y - b / 2 - 18, mark, 6, align="l")
    dim_h(pl, [x for _n, x in gv.GRID_X], OUT_D + 140, OUT_D + 120)
    dim_v(pl, [y for _n, y in gv.GRID_Y], -150, -130, -1)
    pl.text(500, -232, "C13, C14 CARRY THE SIT OUT'S ROOF", 5.6, align="l")
    notes = ("Concrete M20 for footings, columns and plinth beams; steel Fe 500.",
             "PCC 1:4:8, 10 cm thick, 10 cm beyond the footing on every side.",
             "Clear cover 50 mm to footings, 40 mm to columns.",
             "Safe bearing capacity taken as 15 t per sq m; to be confirmed on site at 150 cm depth.",
             "Footings and columns on the grid of A-101; plinth beams PB1 on every grid line.",
             "PB1: 23 wide, 45 deep, 4 bars of 12 dia (2 top, 2 bottom), stirrups 8 dia at 15 cm.",
             "Do not scale; set out every footing on site from the grid before digging.")
    sheet_frame(pdf, "S-101", "FOOTING LAYOUT AND SCHEDULE", "1:75", notes)
    _footing_schedule(pdf, 52, 250)
    _footing_section(pdf, 610, 112)


def _footing_schedule(pdf, x0: float, top: float) -> None:  # noqa: ANN001
    """The schedule, one row per type, each row's text exactly what Drawing check reads:
    "F1 150X150 45 20 8 nos. 12 dia bars 8 nos. 12 dia bars"."""
    cols = ((0, "TYPE"), (36, "A X B"), (92, "D"), (118, "C"), (146, "BOTTOM BARS, EACH WAY"), (330, "COLUMNS ON IT"))
    pdf.setFont("Helvetica-Bold", 9)
    pdf.drawString(x0, top + 16, "FOOTING SCHEDULE")
    pdf.setFont("Helvetica-Bold", 6.4)
    for dx, h in cols:
        pdf.drawString(x0 + dx, top, h)
    y = top
    for mark, a, b, d, c, cols_on, n, dia in gv.FOOTINGS:
        y -= 13
        pdf.setFont("Helvetica", 7)
        pdf.drawString(x0, y, mark)
        pdf.drawString(x0 + 36, y, f"{a}X{b}")
        pdf.drawString(x0 + 92, y, str(d))
        pdf.drawString(x0 + 118, y, str(c))
        pdf.drawString(x0 + 146, y, f"{n} nos. {dia} dia bars {n} nos. {dia} dia bars")
        pdf.drawString(x0 + 330, y, " ".join(cols_on))
    right = x0 + 450
    pdf.setLineWidth(0.4)
    pdf.rect(x0 - 5, y - 5, right - x0 + 5, top - y + 15)
    pdf.line(x0 - 5, top - 4, right, top - 4)
    for dx, _h in cols[1:]:
        pdf.line(x0 + dx - 5, y - 5, x0 + dx - 5, top + 10)
    pdf.setFont("Helvetica", 6)
    pdf.drawString(x0, y - 16, "A X B: footing size; D: depth at the column; C: depth at the edge (cm). PCC under every footing.")


def _footing_section(pdf, cx: float, base: float) -> None:  # noqa: ANN001
    """A typical footing in section (not to scale): the PCC bed, the sloped footing, its bottom bars, the column
    rising to the plinth beam; each part named at the right with a leader line."""
    s = 0.62  # points per cm in this detail
    a, d, c, col, pcc = 150, 45, 20, 23, 10
    pdf.setFont("Helvetica-Bold", 9)
    pdf.drawString(cx - 80, base + 166, "TYPICAL FOOTING SECTION")
    pdf.setFont("Helvetica", 6.4)
    pdf.drawString(cx - 80, base + 157, "NOT TO SCALE")
    left, right = cx - a / 2 * s, cx + a / 2 * s
    pdf.setLineWidth(0.6)
    pdf.setFillColor(colors.HexColor("#d9d6cf"))
    pdf.rect(left - 10 * s, base, (a + 20) * s, pcc * s, stroke=1, fill=1)
    fy = base + pcc * s
    half = (col / 2 + 10) * s
    path = pdf.beginPath()
    for i, (px, py) in enumerate(((left, fy), (right, fy), (right, fy + c * s), (cx + half, fy + d * s),
                                  (cx - half, fy + d * s), (left, fy + c * s))):
        (path.moveTo if i == 0 else path.lineTo)(px, py)
    path.close()
    pdf.setFillColor(colors.HexColor("#efede8"))
    pdf.drawPath(path, fill=1, stroke=1)
    top = fy + (d + 150) * s
    pdf.rect(cx - col / 2 * s, fy + d * s, col * s, (150 - 45) * s, stroke=1, fill=1)
    pdf.setFillColor(colors.HexColor("#efede8"))
    pdf.rect(cx - 40 * s, top - 45 * s, 80 * s, 45 * s, stroke=1, fill=1)  # the plinth beam, cut
    pdf.setFillColor(INK)
    pdf.setLineWidth(1)
    pdf.line(left + 5 * s, fy + 6 * s, right - 5 * s, fy + 6 * s)
    pdf.line(left + 5 * s, fy + 6 * s, left + 5 * s, fy + 15 * s)
    pdf.line(right - 5 * s, fy + 6 * s, right - 5 * s, fy + 15 * s)
    for i in range(1, 8):
        pdf.circle(left + i * (a / 8) * s, fy + 9 * s, 1.2, fill=1)
    for dx in (-7, 7):  # the column's bars, bent at the foot
        pdf.line(cx + dx * s, fy + 7 * s, cx + dx * s, top - 5 * s)
        pdf.line(cx + dx * s, fy + 7 * s, cx + (dx + (-14 if dx < 0 else 14)) * s, fy + 7 * s)
    ground = fy + (d + 150 - 45 - 150 + 150) * s - 45 * s  # the ground line at the plinth beam's foot
    pdf.setLineWidth(0.5)
    pdf.setDash([5, 2])
    pdf.line(left - 50, ground, right + 30, ground)
    pdf.setDash()
    # Dimension D and C at the left
    pdf.setLineWidth(0.3)
    for y1, y2, lab in ((fy, fy + d * s, "D"), (fy, fy + c * s, "C")):
        xx = left - (30 if lab == "D" else 14)
        pdf.line(xx, y1, xx, y2)
        pdf.line(xx - 3, y1 - 3, xx + 3, y1 + 3)
        pdf.line(xx - 3, y2 - 3, xx + 3, y2 + 3)
        pdf.drawRightString(xx - 4, (y1 + y2) / 2 - 2, lab)
    pdf.line(left, base - 12, right, base - 12)
    for xx in (left, right):
        pdf.line(xx - 3, base - 15, xx + 3, base - 9)
    pdf.drawCentredString(cx, base - 22, "A")
    # Names at the right, each with a leader to its part.
    tx = right + 34
    for y_part, x_part, label in ((top - 22 * s, cx + 40 * s, "PLINTH BEAM PB1"),
                                  (top - 70 * s, cx + col / 2 * s, "COLUMN, SIZE AND BARS AS S-102"),
                                  (ground, right + 30, "GROUND"),
                                  (fy + (d - 10) * s, cx + half + 10, "FOOTING, M20"),
                                  (fy + 9 * s, right - 10 * s, "BOTTOM BARS EACH WAY, AS SCHEDULE"),
                                  (base + pcc * s / 2, right + 10 * s, "PCC 1:4:8, 10 THICK")):
        pdf.line(x_part, y_part, tx - 3, y_part)
        pdf.drawString(tx, y_part - 2, label)
    pdf.drawString(tx, base - 24, "FOUNDATION 150 BELOW GROUND, FIRM SOIL")


# --- A-201 and A-301: the front elevation and the section A-A ----------------------------------------------------------

HATCH = colors.HexColor("#c9c8c3")


def _level_mark(pl: Plan, x: float, level: float, name: str, side: int = 1) -> None:
    """A level: a filled triangle on a short line, "+345 LVL" and what the level is (Drawing check reads the first)."""
    pdf = pl.pdf
    px, py = pl.p(x, level)
    pdf.setLineWidth(0.4)
    pdf.line(px - 6 * side, py, px + 40 * side, py)
    p = pdf.beginPath()
    p.moveTo(px, py)
    p.lineTo(px - 3.5, py + 5)
    p.lineTo(px + 3.5, py + 5)
    p.close()
    pdf.setFillColor(INK)
    pdf.drawPath(p, fill=1, stroke=0)
    pdf.setFont("Helvetica-Bold", 6.6)
    text = f"{'±' if level == 0 else '+'}{level:g} LVL"
    (pdf.drawString if side > 0 else pdf.drawRightString)(px + 8 * side, py + 2, text)
    pdf.setFont("Helvetica", 5.2)
    (pdf.drawString if side > 0 else pdf.drawRightString)(px + 8 * side, py - 6, name)


def _ground(pl: Plan, x1: float, x2: float) -> None:
    pl.line(x1, 0, x2, 0, 1.2)
    for i in range(int((x2 - x1) / 18)):
        x = x1 + i * 18
        pl.line(x, 0, x - 10, -10, 0.25)


def _window_elev(pl: Plan, x1: float, x2: float, sill: float, top: float, shutters: int, *, shade: bool = True) -> None:
    pl.rect(x1, sill, x2 - x1, top - sill, fill=colors.white, width=0.7)
    pl.rect(x1 + 5, sill + 5, x2 - x1 - 10, top - sill - 10, width=0.3)
    for i in range(1, shutters):
        x = x1 + (x2 - x1) * i / shutters
        pl.line(x, sill + 5, x, top - 5, 0.4)
    for i in range(shutters):  # glass: two light strokes a pane
        a = x1 + 5 + (x2 - x1 - 10) * i / shutters
        pl.line(a + 6, sill + 20, a + 20, sill + 40, 0.2, color=FAINT)
        pl.line(a + 10, sill + 20, a + 30, sill + 50, 0.2, color=FAINT)
    pl.rect(x1 - 5, sill - 6, x2 - x1 + 10, 6, width=0.4)  # sill
    if shade:  # the sunshade over it, 60 out
        pl.rect(x1 - 15, top, x2 - x1 + 30, 8, fill=HATCH, width=0.5)


def _door_elev(pl: Plan, x1: float, x2: float, bottom: float, top: float, leaves: int = 1) -> None:
    pl.rect(x1, bottom, x2 - x1, top - bottom, fill=colors.white, width=0.7)
    for i in range(leaves):
        a = x1 + (x2 - x1) * i / leaves
        b = x1 + (x2 - x1) * (i + 1) / leaves
        pl.rect(a + 6, bottom + 10, b - a - 12, (top - bottom) / 2 - 15, width=0.3)
        pl.rect(a + 6, bottom + (top - bottom) / 2 + 5, b - a - 12, (top - bottom) / 2 - 15, width=0.3)


def _railing(pl: Plan, x1: float, x2: float, bottom: float, height: float = 100) -> None:
    pl.line(x1, bottom + height, x2, bottom + height, 1.0)
    pl.line(x1, bottom + 10, x2, bottom + 10, 0.4)
    n = int((x2 - x1) / 12)
    for i in range(n + 1):
        x = x1 + i * (x2 - x1) / n
        pl.line(x, bottom, x, bottom + height, 0.3)


def front_elevation(pdf) -> None:  # noqa: ANN001
    """A-201 at 1:50: the road side, as the plans and the section build it; levels at the left (the roof +660: the
    section says +655, the catch)."""
    pl = Plan(pdf, 128, 215)
    lv = dict(zip(("ground", "plinth", "first", "roof", "parapet"), gv.ELEVATION_LEVELS, strict=True))
    f, roof, top = lv["first"], lv["roof"], lv["parapet"]
    ff = f - 12  # the first floor slab's soffit
    _ground(pl, -170, OUT_W + 60)
    # The right bay's first floor, set back behind the terrace: drawn first, lighter.
    pl.rect(EXT + 890, f + 100, OUT_W - EXT - 890, roof - f - 100, fill=colors.HexColor("#f4f3ef"), width=0.4)
    pl.rect(EXT + 890, roof - 15, OUT_W - EXT - 890, 30, fill=HATCH, width=0.4)
    pl.rect(EXT + 890, roof + 15, OUT_W - EXT - 890, top - roof - 15, fill=colors.white, width=0.5)
    _door_elev(pl, EXT + 905, EXT + 995, f, f + 210)
    # Plinth, ground floor, the first floor slab's edge band, the main block's first floor, roof band, parapet.
    pl.rect(0, 0, OUT_W, lv["plinth"], fill=HATCH, width=0.6)
    for i in range(1, 3):
        pl.line(0, i * 15, OUT_W, i * 15, 0.25)
    pl.rect(0, lv["plinth"], OUT_W, ff - lv["plinth"], fill=colors.white, width=0.8)
    pl.rect(0, ff, OUT_W, 30, fill=HATCH, width=0.6)
    pl.rect(EXT + 890, f + 18, OUT_W - EXT - 890, 100 - 18, fill=colors.white, width=0.7)  # terrace parapet
    pl.rect(EXT + 885, f + 100, OUT_W - EXT - 880, 6, fill=HATCH, width=0.4)
    pl.rect(0, f + 18, EXT + 900, roof - 15 - f - 18, fill=colors.white, width=0.8)
    pl.rect(-5, roof - 15, EXT + 910, 30, fill=HATCH, width=0.6)
    pl.rect(0, roof + 15, EXT + 900, top - roof - 15, fill=colors.white, width=0.8)
    pl.rect(-5, top - 6, EXT + 910, 6, fill=HATCH, width=0.4)
    pl.rect(EXT + 885, top - 6, OUT_W - EXT - 880, 6, fill=HATCH, width=0.4)
    # Ground floor openings: the living's W3, BEDROOM-2's and BEDROOM-1's W1, the main door behind the sit out.
    p, sill, head = lv["plinth"], lv["plinth"] + gv.SILL, lv["plinth"] + gv.LINTEL
    _window_elev(pl, EXT + 420, EXT + 510, sill, head, 2)
    _window_elev(pl, EXT + 635, EXT + 785, sill, head, 3)
    _window_elev(pl, EXT + 1030, EXT + 1180, sill, head, 3)
    _door_elev(pl, EXT + 200, EXT + 320, p, head, 1)
    # First floor: the balcony door, the family living's W3, BEDROOM-4's W1.
    fs, fh = f + gv.SILL, f + gv.LINTEL
    _window_elev(pl, EXT + 420, EXT + 510, fs, fh, 2)
    _window_elev(pl, EXT + 635, EXT + 785, fs, fh, 3)
    _door_elev(pl, EXT + 200, EXT + 320, f + 12, fh, 2)
    # The sit out: its columns, three steps, its roof slab (the balcony) with the railing.
    for x in (133, 410):
        pl.rect(x, p, 23, ff - p, fill=colors.white, width=0.7)
    for i in range(3):
        pl.rect(173 - i * 10, 15 * i, 220 + i * 20, 15, fill=colors.white, width=0.4)
    pl.rect(103, p - 5, 360, 5, fill=HATCH, width=0.4)
    pl.rect(103, ff, 360, 30, fill=HATCH, width=0.6)
    _railing(pl, 110, 463, f + 18)
    # Rainwater pipes: the main roof's front corner, and the terrace's.
    for x, y2 in ((-12, roof), (EXT + 902, f + 100)):
        pl.rect(x - 5, 0, 10, y2, width=0.4)
    # Levels at the left; heights between them.
    for v, name in zip(gv.ELEVATION_LEVELS, gv.LEVEL_NAMES, strict=True):
        _level_mark(pl, -40, v, name, side=-1)
    dim_v(pl, list(gv.ELEVATION_LEVELS), -150, -150, -1)
    # What the outside is finished in.
    for x, y, text in ((OUT_W - 20, top + 25, "PARAPET WITH PRECAST COPING"),
                       (OUT_W - 20, f + 112, "TERRACE PARAPET 100 HIGH"),
                       (OUT_W - 20, 22, "PLINTH IN GREY TEXTURED PLASTER")):
        pl.text(x, y, text, 5.6, align="r")
    notes = ("Walls: cement plaster 15 thick outside, exterior emulsion in two coats over primer.",
             "Plinth band: textured plaster in grey; sunshades 60 out over every window.",
             "Windows UPVC with 5 mm clear glass; sills in granite.",
             "Balcony and terrace railing in MS, primed and enamelled.",
             "Levels in cm above the finished ground at the main door.")
    sheet_frame(pdf, "A-201", "FRONT ELEVATION", "1:50", notes)


def section_aa(pdf) -> None:  # noqa: ANN001
    """A-301 at 1:50: the cut on A-101's line A-A, through the living and the dining (and above them the family
    living and BEDROOM-3), front at the left; the sit out and its columns seen beyond. The roof at +655 (the
    elevation says +660: the catch)."""
    pl = Plan(pdf, 300, 225)
    lv = dict(zip(("ground", "plinth", "first", "roof", "parapet"), gv.SECTION_LEVELS, strict=True))
    p, f, roof, top = lv["plinth"], lv["first"], lv["roof"], lv["parapet"]
    _ground(pl, -330, OUT_D + 140)
    # Below ground, as S-101 builds it: seen beyond the cut, the footings of grid line A (F1, F2, F1) on their PCC,
    # each with its column rising to the plinth beam; the plinth beams cut on the grid lines; earth filled between.
    by_col = {c: f for f in gv.FOOTINGS for c in f[5]}
    on_a = [s_ for s_ in gv.COLUMN_SPOTS if s_[1] == gv.GRID_X[0][1]]
    found = -150  # the bottom of the footings (S-101 note 4)
    for mark, _x, y, _a, b_ in sorted(on_a, key=lambda c: c[2]):
        f_ = by_col[mark]
        fa, d_, c_ = f_[1], f_[3], f_[4]
        pl.rect(y - fa / 2 - 10, found - 10, fa + 20, 10, fill=colors.HexColor("#d9d6cf"), width=0.4)  # PCC
        path = pl.pdf.beginPath()
        for i, (yy, z) in enumerate(((y - fa / 2, found), (y + fa / 2, found), (y + fa / 2, found + c_),
                                     (y + b_ / 2 + 10, found + d_), (y - b_ / 2 - 10, found + d_), (y - fa / 2, found + c_))):
            (path.moveTo if i == 0 else path.lineTo)(*pl.p(yy, z))
        path.close()
        pl.pdf.setFillColor(colors.HexColor("#e6e3dc"))
        pl.pdf.setLineWidth(0.5)
        pl.pdf.drawPath(path, fill=1, stroke=1)
        pl.pdf.setFillColor(INK)
        pl.rect(y - b_ / 2, found + d_, b_, p - 10 - 45 - found - d_, fill=colors.HexColor("#d4d1ca"), width=0.5)
        pl.text(y, found - 30, f"{f_[0]} ({mark})", 5.6)
    pl.rect(23, 0, OUT_D - 46, p - 10, fill=colors.HexColor("#efede8"), width=0.3)
    for i in range(12):
        y = 40 + i * 60
        pl.line(y, 5, y + 25, p - 15, 0.2, color=FAINT)
    for _n, y in gv.GRID_Y:  # the plinth beams, cut, at the top of the basement
        pl.rect(y - 11.5, p - 10 - 45, 23, 45, fill=colors.HexColor("#8f8c85"), width=0.6)
    pl.rect(0, p - 10, OUT_D, 10, fill=HATCH, width=0.4)  # PCC and tiles
    # Ground floor walls: the front with its W3, the back, the arch between living and dining.
    sill, head = p + gv.SILL, p + gv.LINTEL
    ff = f - 12
    pl.rect(0, p, EXT, sill - p, fill=POCHE, width=0.6)
    pl.rect(0, head, EXT, ff - head, fill=POCHE, width=0.6)
    pl.rect(0, head, EXT, 15, fill=HATCH, width=0.4)
    pl.line(EXT * 0.35, sill, EXT * 0.35, head, 0.4)
    pl.line(EXT * 0.65, sill, EXT * 0.65, head, 0.4)
    pl.rect(OUT_D - EXT, p, EXT, ff - p, fill=POCHE, width=0.6)
    pl.rect(OUT_D - EXT, head, EXT, 15, fill=HATCH, width=0.4)
    pl.rect(EXT + 430, head, 10, ff - head, fill=POCHE, width=0.5)
    # First floor slab with beams on the grid lines; the sit out's roof slab (the balcony) out in front.
    pl.rect(-255, ff, OUT_D + 255, 12, fill=INK, width=0.4)
    for _n, y in gv.GRID_Y:
        pl.rect(y - 11.5, ff - 33, 23, 33, fill=INK, width=0.4)
    pl.rect(-255, ff - 20, 20, 20, fill=INK, width=0.3)
    # First floor walls: the front with its W3, the back, the partition with BEDROOM-3's door.
    fs, fh, rs = f + gv.SILL, f + gv.LINTEL, roof - 12
    pl.rect(0, f, EXT, fs - f, fill=POCHE, width=0.6)
    pl.rect(0, fh, EXT, rs - fh, fill=POCHE, width=0.6)
    pl.line(EXT * 0.35, fs, EXT * 0.35, fh, 0.4)
    pl.line(EXT * 0.65, fs, EXT * 0.65, fh, 0.4)
    pl.rect(OUT_D - EXT, f, EXT, rs - f, fill=POCHE, width=0.6)
    pl.rect(EXT + 430, fh, 10, rs - fh, fill=POCHE, width=0.5)
    pl.rect(EXT + 430, f, 10, 0.1, width=0.3)
    # Roof slab and beams, the weathering course, the parapets with coping.
    pl.rect(0, rs, OUT_D, 12, fill=INK, width=0.4)
    for _n, y in gv.GRID_Y:
        pl.rect(y - 11.5, rs - 33, 23, 33, fill=INK, width=0.4)
    pl.rect(0, roof, OUT_D, 6, fill=HATCH, width=0.3)
    for y0 in (0, OUT_D - EXT):
        pl.rect(y0, roof, EXT, top - roof - 6, fill=POCHE, width=0.6)
        pl.rect(y0 - 5, top - 6, EXT + 10, 6, fill=HATCH, width=0.4)
    # Seen beyond the cut: the sit out's columns and steps, the balcony railing, the doors in the far walls.
    for y in (-240,):
        pl.rect(y, p, 23, ff - 20 - p, width=0.5)
    pl.rect(-240, p - 5, 240, 5, fill=HATCH, width=0.3)
    for i in range(3):
        pl.rect(-296 + i * 18, 15 * i, 18 + (2 - i) * 0 + 0, 15, width=0.3)
    _railing(pl, -150, 0, f)
    _door_elev(pl, EXT + 560, EXT + 650, p, head)
    # Names of the spaces cut, and the levels at the right.
    for y, z, name in ((215, p + 150, "LIVING"), (600, p + 150, "DINING"), (215, f + 150, "FAMILY LIVING"),
                       (600, f + 150, "BEDROOM-3"), (-120, p + 150, "SIT OUT"), (-75, f + 125, "BALCONY")):
        pl.text(y, z, name, 7, bold=True)
    for v, name in zip(gv.SECTION_LEVELS, gv.LEVEL_NAMES, strict=True):
        _level_mark(pl, OUT_D + 60, v, name)
    dim_v(pl, list(gv.SECTION_LEVELS), -330, -300, -1)
    for y, z, text in ((OUT_D / 2, roof + 25, "RCC ROOF SLAB 12 THICK, WEATHERING COURSE AND TILES ON TOP"),
                       (OUT_D / 2, f + 6, "RCC SLAB 12 THICK ON BEAMS 23 WIDE"),
                       (OUT_D / 2, -212, "FOOTINGS OF GRID LINE A SEEN BEYOND (S-101), PLINTH BEAMS PB1 CUT ON THE GRID LINES"),
                       (OUT_D / 2, 18, "EARTH FILLED AND RAMMED, PCC 1:4:8, TILES")):
        lx, ly = pl.p(y, z)
        w = pdf.stringWidth(text, "Helvetica", 5.6) + 6
        pdf.setFillColor(colors.white)
        pdf.rect(lx - w / 2, ly - 2.5, w, 8, stroke=0, fill=1)
        pdf.setFillColor(INK)
        pl.text(y, z, text, 5.6)
    notes = ("Cut on the line A-A of A-101 and A-102, looking towards the left wall.",
             "Floor to floor 300 on the ground floor; roof slab top as marked.",
             "Lintels and the lintel band at 210 above each floor, 15 deep.",
             "Parapet 110 above the roof, with a precast coping.",
             "Levels in cm above the finished ground at the main door.")
    sheet_frame(pdf, "A-301", "SECTION A-A", "1:50", notes)


# --- S-102: the column schedule ----------------------------------------------------------------------------------------

K15 = 72 / 2.54 / 15


def column_schedule(pdf) -> None:  # noqa: ANN001
    """S-102: one panel a column ("COLUMN - C1", its section at 1:15 with the bars and the tie, its size, "REINF:" and
    "TIES:", which Drawing check reads), a beam schedule and a typical column elevation."""
    by_col = {c: f[0] for f in gv.FOOTINGS for c in f[5]}
    grid_x = dict((round(x, 1), n) for n, x in gv.GRID_X)
    grid_y = dict((round(y, 1), n) for n, y in gv.GRID_Y)
    pw, ph = 125, 140
    for i, (mark, a, b, main, ties) in enumerate(gv.COLUMNS):
        row, col = divmod(i, 7)
        x0, top = 52 + col * pw, 795 - row * (ph + 10)
        spot = next(s for s in gv.COLUMN_SPOTS if s[0] == mark)
        where = (f"{grid_x.get(round(spot[1], 1), '')}{grid_y.get(round(spot[2], 1), '')}" or "SIT OUT")
        pdf.setLineWidth(0.5)
        pdf.rect(x0, top - ph, pw - 6, ph)
        pdf.setFont("Helvetica-Bold", 8)
        pdf.drawString(x0 + 6, top - 12, f"COLUMN - {mark}")
        pdf.setFont("Helvetica", 5.8)
        pdf.drawString(x0 + 6, top - 22, f"GRID {where}  ON FOOTING {by_col[mark]}")
        # The section: concrete, the tie inside the cover, the bars.
        w, d = a * K15, b * K15
        cx, cy = x0 + 50, top - 30 - d / 2 - 4
        pdf.setFillColor(colors.HexColor("#efede8"))
        pdf.rect(cx - w / 2, cy - d / 2, w, d, fill=1)
        pdf.setFillColor(INK)
        c = 4 * K15
        pdf.setLineWidth(0.6)
        pdf.roundRect(cx - w / 2 + c, cy - d / 2 + c, w - 2 * c, d - 2 * c, 2)
        n = int(main.split("-")[0])
        dia = int(main.split("T")[1])
        r = dia / 20 * K15
        spots = [(-1, -1), (1, -1), (1, 1), (-1, 1)] + ([(-1, 0), (1, 0)] if n == 6 else [])
        for sx_, sy_ in spots:
            pdf.circle(cx + sx_ * (w / 2 - c - r), cy + sy_ * (d / 2 - c - r), r, fill=1)
        pdf.setFont("Helvetica", 6)
        pdf.setLineWidth(0.3)
        pdf.line(cx - w / 2, cy - d / 2 - 6, cx + w / 2, cy - d / 2 - 6)
        pdf.drawCentredString(cx, cy - d / 2 - 14, str(a))
        pdf.line(cx + w / 2 + 6, cy - d / 2, cx + w / 2 + 6, cy + d / 2)
        pdf.drawString(cx + w / 2 + 9, cy - 2, str(b))
        y = top - ph + 22
        pdf.setFont("Helvetica-Bold", 6.2)
        pdf.drawString(x0 + 6, y, f"REINF: {main.replace('-', ' ')}")
        pdf.setFont("Helvetica", 6.2)
        pdf.drawString(x0 + 6, y - 9, f"TIES: {ties} C/C")
        pdf.setFont("Helvetica", 5.4)
        pdf.drawString(x0 + 6, y - 19, "FOOTING TO FIRST FLOOR" if mark in gv.STOP_AT_FIRST else "FOOTING TO ROOF")
    # The beam schedule.
    x0, top = 52, 470
    pdf.setFont("Helvetica-Bold", 9)
    pdf.drawString(x0, top + 14, "BEAM SCHEDULE")
    heads = (("MARK", 0), ("WHERE", 40), ("WIDTH", 190), ("DEPTH", 225), ("TOP BARS", 262), ("BOTTOM BARS", 322),
             ("STIRRUPS", 392))
    rows = (("PB1", "PLINTH, ALL GRID LINES", "23", "45", "2 T12", "2 T12", "T8 @ 15 CM"),
            ("B1", "FIRST FLOOR, GRID LINES", "23", "45", "2 T12", "3 T16", "T8 @ 15 CM"),
            ("B2", "ROOF, GRID LINES", "23", "45", "2 T12", "3 T12", "T8 @ 15 CM"),
            ("L1", "LINTELS AND LINTEL BAND", "23", "15", "2 T10", "2 T10", "T6 @ 15 CM"))
    pdf.setFont("Helvetica-Bold", 6.4)
    for h, dx in heads:
        pdf.drawString(x0 + dx, top, h)
    pdf.setFont("Helvetica", 6.8)
    y = top
    for r in rows:
        y -= 12
        for (_h, dx), cell in zip(heads, r, strict=True):
            pdf.drawString(x0 + dx, y, cell)
    pdf.setLineWidth(0.4)
    pdf.rect(x0 - 5, y - 5, 460, top - y + 15)
    pdf.line(x0 - 5, top - 4, x0 + 455, top - 4)
    pdf.setFont("Helvetica", 6)
    pdf.drawString(x0, y - 16, "Widths and depths in cm. Beams of the grid lines carry the walls and the slabs.")
    # A typical column, footing to roof: where it meets each beam, where bars are lapped.
    cx, base, s = 700, 110, 0.48
    levels = ((0, "PLINTH BEAM PB1"), (345, "FIRST FLOOR BEAM B1"), (655, "ROOF BEAM B2"))
    pdf.setFont("Helvetica-Bold", 8.5)
    pdf.drawString(cx - 60, 480, "TYPICAL COLUMN ELEVATION")
    pdf.setLineWidth(0.6)
    pdf.setFillColor(colors.HexColor("#efede8"))
    pdf.rect(cx - 90 * s, base - 55 * s, 180 * s, 45 * s, fill=1)  # footing
    pdf.rect(cx - 11.5 * s * 2, base - 10 * s, 23 * s * 2, (655 + 10) * s, fill=1)
    pdf.setFillColor(INK)
    for z, name in levels:
        pdf.setFillColor(colors.HexColor("#bdbab3"))
        pdf.rect(cx - 70 * s, base + (z - 45) * s, 140 * s, 45 * s, fill=1)
        pdf.setFillColor(INK)
        pdf.setFont("Helvetica", 6)
        pdf.drawString(cx + 80 * s, base + (z - 25) * s, name)
    pdf.setLineWidth(0.9)
    for dx in (-6, 6):
        pdf.line(cx + dx, base - 50 * s, cx + dx, base + 650 * s)
    for z in (150, 470):
        pdf.setLineWidth(0.3)
        pdf.line(cx - 30, base + z * s, cx - 14, base + z * s)
        pdf.line(cx - 30, base + (z + 80) * s, cx - 14, base + (z + 80) * s)
        pdf.line(cx - 24, base + z * s, cx - 24, base + (z + 80) * s)
        pdf.setFont("Helvetica", 5.6)
        pdf.drawRightString(cx - 32, base + (z + 35) * s, "LAP 50 DIA")
    pdf.setFont("Helvetica", 6)
    pdf.drawString(cx + 80 * s, base - 40 * s, "FOOTING, AS S-101")
    # Figures in the notes keep their units on them ("40mm"): a bare number near a panel would read as its size.
    notes = ("Concrete M20, steel Fe 500; cover 40mm to columns, 25mm to beams.",
             "Laps of fifty bar diameters, in the middle half of the height; not more than half the bars at one level.",
             "Ties with 135-degree hooks, closer (10cm) for 60cm above and below every beam.",
             "Columns cast in lifts of not more than 1.5 m.",
             "Read with S-101 for where each column stands.")
    sheet_frame(pdf, "S-102", "COLUMN SCHEDULE", "1:15", notes)
