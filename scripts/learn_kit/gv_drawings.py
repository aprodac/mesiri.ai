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


def _stair(pl: Plan, room: tuple) -> None:  # noqa: ANN001
    """A dog-leg stair: two flights of nine treads with a landing at the far end, "UP" at the foot."""
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


# --- A-101: the ground floor plan --------------------------------------------------------------------------------------

def ground_floor(pdf, rev: str = "A") -> None:  # noqa: ANN001
    """A-101 at 1:50, one A3 sheet. ``rev`` "B" is the copy issued alone (the kit's first file)."""
    ox, oy = 150, 282
    pl = Plan(pdf, ox, oy)
    rooms = {r[0]: r for r in gv.GROUND_FLOOR_ROOMS}
    # 1. Walls: the whole footprint in poché, the rooms cut out of it.
    pl.rect(0, 0, OUT_W, OUT_D, fill=POCHE, width=0.9)
    for label, x, y, w, d, _a in gv.GROUND_FLOOR_ROOMS:
        if label == "SIT OUT":
            continue
        X, Y = _in(x, y)
        pl.rect(X, Y, w, d, fill=colors.white, width=0.6)
    # The sit out: an open porch in front, its roof slab dashed, two columns, three steps down.
    _l, sx, sy, sw, sd, _a = rooms["SIT OUT"]
    X, Y = _in(sx, sy)
    pl.rect(X, Y, sw, sd, width=0.6)
    pl.rect(X - 30, Y - 15, sw + 60, sd + 15, width=0.3, dash=(3, 2))  # roof slab over the sit out
    for i in range(1, 3):
        pl.line(X + 40, Y - i * 28, X + sw - 40, Y - i * 28, 0.4)
    pl.line(X + 40, Y - 56, X + 40, Y, 0.4)
    pl.line(X + sw - 40, Y - 56, X + sw - 40, Y, 0.4)
    pl.text(X + sw / 2, Y - 50, "3 STEPS DOWN", 5.5)
    # 2. Openings without doors: the arch between living and dining, living to passage, passage to the stair lobby.
    for x, y, w, d in gv.GROUND_OPENINGS:
        X, Y = _in(x, y)
        _clear(pl, X, Y, w, d)
        if w > d:
            pl.line(X, Y + d / 2, X + w, Y + d / 2, 0.3, dash=(4, 2))
        else:
            pl.line(X + w / 2, Y, X + w / 2, Y + d, 0.3, dash=(4, 2))
    # 3. Doors and windows.
    for kind, a, b, wall, into, hinge, mark in gv.GROUND_DOORS:
        if kind == "h":
            door_h(pl, a + EXT, b + EXT, (wall[0] + EXT, wall[1] + EXT), into, hinge, mark)
        else:
            door_v(pl, a + EXT, b + EXT, (wall[0] + EXT, wall[1] + EXT), into, hinge, mark)
    for kind, a, b, wall, mark, out in gv.GROUND_WINDOWS:
        if kind == "h":
            window_h(pl, a + EXT, b + EXT, (wall[0] + EXT, wall[1] + EXT), mark, out)
        else:
            window_v(pl, a + EXT, b + EXT, (wall[0] + EXT, wall[1] + EXT), mark, out)
    # 4. Columns on the grid (solid), and the porch's.
    for _mark, x, y, a, b in gv.COLUMN_SPOTS:
        pl.rect(x - a / 2, y - b / 2, a, b, fill=INK, width=0.3)
    # 5. Furniture and fittings.
    _furnish(pl, rooms)
    _stair(pl, rooms["STAIR"])
    # 6. Room names, sizes and the area printed (Drawing check reads these three lines).
    for label, x, y, w, d, sqft in gv.GROUND_FLOOR_ROOMS:
        X, Y = _in(x, y)
        dx, dy = LABEL_SHIFT.get(label, (0, 0))
        cx, cy = X + w / 2 + dx, Y + d / 2 + dy
        bw = max(pdf.stringWidth(label, "Helvetica-Bold", 7.5), 46) + 6
        pdf.setFillColor(colors.white)
        px, py = pl.p(cx, cy)
        pdf.rect(px - bw / 2, py - 19, bw, 30, stroke=0, fill=1)
        pdf.setFillColor(INK)
        pdf.setFont("Helvetica-Bold", 7.5)
        pdf.drawCentredString(px, py + 3, label)
        pdf.setFont("Helvetica", 6.5)
        pdf.drawCentredString(px, py - 6, f"{w} X {d}")
        pdf.drawCentredString(px, py - 15, f"{sqft} Sq.ft")
    # 7. Dimension chains: outside the walls, room by room, then overall.
    xs = [0, EXT]
    for w in gv.BAYS_X:
        xs.append(xs[-1] + w)
        xs.append(xs[-1] + INT)
    xs[-1] = xs[-2] + EXT
    dim_h(pl, xs, -322, -305)
    dim_h(pl, [0, OUT_W], -362, -330)
    dim_h(pl, xs, OUT_D + 62, OUT_D + 40)
    ys_left = [0, EXT, EXT + 430, EXT + 440, OUT_D - EXT, OUT_D]
    dim_v(pl, ys_left, -70, -40, -1)
    dim_v(pl, [0, OUT_D], -122, -80, -1)
    # 8. Grid bubbles, north point, the section line A-A through the living and the dining.
    grid(pl, OUT_D + 126, -180, -20, OUT_W, through=False)
    north(pdf, *pl.p(OUT_W - 60, -235))
    sx_ = EXT + 450
    for yy, up in ((-95, False), (OUT_D + 32, True)):
        pl.line(sx_, yy, sx_, yy + (25 if not up else -25), 1.6)
        px, py = pl.p(sx_ - 30, yy + (8 if not up else -8))
        pdf.setLineWidth(0.5)
        pdf.circle(px, py, 7)
        pdf.setFont("Helvetica-Bold", 7)
        pdf.drawCentredString(px, py - 2.5, "A")
    # The plinth, said in words (a plan carries no level marks here: the section and the elevation do).
    pl.text(OUT_W - 10, -140, "PLINTH 45 ABOVE GROUND, FLOOR FINISH VITRIFIED TILE", 5.8, align="r")
    notes = ("Read with S-101, S-102 and the section A-301.",
             "External walls 23 cm solid block, partitions 10 cm brick, plastered both sides.",
             "Columns shown solid; their sizes are on S-102.",
             "Sizes in rooms are clear inside sizes; areas are carpet areas.",
             "Stair: 20 risers of 17 cm, treads 25 cm, two flights with a landing.")
    rows = [list(r) for r in gv.OPENING_SCHEDULE]
    sheet_frame(pdf, "A-101", "GROUND FLOOR PLAN", "1:50", notes,
                ("DOOR AND WINDOW LIST", ("MARK", "TYPE", "W", "H", "NOS"), rows, (28, 104, 24, 24, 26)))
    if rev != "A":
        sx = WIDTH - 30 - STRIP
        pdf.setFillColor(colors.white)
        pdf.rect(sx + 80, 40 + 4 * 18 + 3, 60, 13, stroke=0, fill=1)
        pdf.setFillColor(INK)
        pdf.setFont("Helvetica-Bold", 8)
        pdf.drawString(sx + 80, 40 + 4 * 18 + 6, rev)


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
