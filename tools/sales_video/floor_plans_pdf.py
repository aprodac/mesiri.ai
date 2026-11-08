"""A two-floor architect's plan set (A-101, A-102) for demos: walls, doors, windows, room names with sizes, a title
block. Made up (no customer's drawing): a small commercial building, rooms on a 4 m grid.

    python tools/sales_video/floor_plans_pdf.py OUT.pdf
"""

from __future__ import annotations

import sys

#: Rooms per floor: name, x, y, width, depth (cm on site). The plan is drawn at 1:100 on A3.
FLOORS = {
    "GROUND FLOOR PLAN": ("A-101", [
        ("SHOP-1", 0, 0, 450, 600), ("SHOP-2", 450, 0, 450, 600), ("SHOP-3", 900, 0, 450, 600),
        ("LOBBY", 0, 600, 300, 400), ("STAIR", 300, 600, 250, 400), ("TOILET", 550, 600, 200, 400),
        ("STORE", 750, 600, 600, 400),
    ]),
    "FIRST FLOOR PLAN": ("A-102", [
        ("OFFICE-1", 0, 0, 450, 600), ("OFFICE-2", 450, 0, 450, 600), ("CONFERENCE", 900, 0, 450, 600),
        ("RECEPTION", 0, 600, 300, 400), ("STAIR", 300, 600, 250, 400), ("TOILET", 550, 600, 200, 400),
        ("PANTRY", 750, 600, 300, 400), ("STORE", 1050, 600, 300, 400),
    ]),
}
SCALE = 0.42  # points per cm on site: 13.5 m across ~ 567 pt on an A3 landscape sheet
ORIGIN = (150, 120)


def build() -> bytes:
    from fpdf import FPDF

    pdf = FPDF(unit="pt", format="A3", orientation="L")
    for title, (number, rooms) in FLOORS.items():
        pdf.add_page()
        ox, oy = ORIGIN
        # walls: each room's outline, thick
        pdf.set_line_width(3.2)
        pdf.set_draw_color(40, 40, 40)
        for _name, x, y, w, d in rooms:
            pdf.rect(ox + x * SCALE, oy + y * SCALE, w * SCALE, d * SCALE)
        # doors (a gap and a swing) and windows on the outer wall
        pdf.set_line_width(0.8)
        for _name, x, y, w, d in rooms:
            dx, dy = ox + (x + w / 2 - 45) * SCALE, oy + (y + d) * SCALE
            pdf.set_draw_color(255, 255, 255)
            pdf.set_line_width(3.6)
            pdf.line(dx, dy, dx + 90 * SCALE, dy)
            pdf.set_draw_color(90, 90, 90)
            pdf.set_line_width(0.6)
            pdf.line(dx, dy, dx, dy - 90 * SCALE)
            if y == 0:
                wx = ox + (x + w / 2 - 75) * SCALE
                pdf.set_draw_color(70, 120, 200)
                pdf.set_line_width(1.6)
                pdf.line(wx, oy, wx + 150 * SCALE, oy)
        # stairs: treads
        pdf.set_draw_color(120, 120, 120)
        pdf.set_line_width(0.5)
        for name, x, y, w, d in rooms:
            if name == "STAIR":
                for k in range(1, 14):
                    yy = oy + (y + k * d / 14) * SCALE
                    pdf.line(ox + (x + 20) * SCALE, yy, ox + (x + w - 20) * SCALE, yy)
        # room names over their sizes, and the area below
        for name, x, y, w, d in rooms:
            cx, cy = ox + (x + w / 2) * SCALE, oy + (y + d / 2) * SCALE
            pdf.set_font("Helvetica", "B", 9)
            pdf.set_text_color(20, 20, 20)
            pdf.text(cx - pdf.get_string_width(name) / 2, cy - 4, name)
            pdf.set_font("Helvetica", size=7)
            size = f"{w} x {d}"
            pdf.text(cx - pdf.get_string_width(size) / 2, cy + 6, size)
        # dimension line across the top
        pdf.set_font("Helvetica", size=7)
        pdf.set_draw_color(150, 150, 150)
        pdf.set_line_width(0.4)
        pdf.line(ox, oy - 26, ox + 1350 * SCALE, oy - 26)
        pdf.text(ox + 1350 * SCALE / 2 - 10, oy - 30, "1350")
        # title block
        pdf.set_draw_color(40, 40, 40)
        pdf.set_line_width(1)
        bx, by = 760, 700
        pdf.rect(bx, by, 400, 120)
        pdf.set_font("Helvetica", size=6)
        rows = [("PROJECT:", "COMMERCIAL BUILDING, KONDOTTY"), ("DWG.TITLE:", title), ("DWG NO", number),
                ("SCALE:", "1:100"), ("DATE:", "02.11.2026"), ("ALL DIMENSIONS ARE IN CM", "")]
        for k, (label, value) in enumerate(rows):
            pdf.text(bx + 8, by + 16 + k * 17, label)
            pdf.set_font("Helvetica", "B" if label == "DWG.TITLE:" else "", 8 if label == "DWG.TITLE:" else 6)
            pdf.text(bx + 90, by + 16 + k * 17, value)
            pdf.set_font("Helvetica", size=6)
        pdf.text(bx + 300, by + 16, "REV")
        pdf.text(bx + 330, by + 16, "A")
        pdf.set_font("Helvetica", "B", 7)
        pdf.text(bx + 260, by + 110, "NOVA ARCHITECTS")
    return bytes(pdf.output())


if __name__ == "__main__":
    with open(sys.argv[1], "wb") as f:
        f.write(build())
